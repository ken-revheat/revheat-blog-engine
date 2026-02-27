"""Content Engine — main orchestrator for the RevHeat Blog Engine."""

from __future__ import annotations

import logging
import os
import re
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote as url_quote

import markdown as md_lib
import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from slugify import slugify

from src.image_pipeline import ImagePipeline
from src.schema_builder import SchemaBuilder
from src.state_tracker import StateTracker
from src.wp_publisher import WordPressPublisher

load_dotenv(override=True)

log = logging.getLogger(__name__)


@dataclass
class TopicSelection:
    topic: str
    primary_keyword: str
    secondary_keywords: list[str] = field(default_factory=list)
    format_type: str = "data_insight"
    smartscaling_pillar: str = ""
    smartscaling_function: str = ""
    growth_stage: str = ""
    target_subreddit: str = "r/sales"
    competitor_gap: str = ""
    data_points: list[str] = field(default_factory=list)
    internal_links: list[dict] = field(default_factory=list)


@dataclass
class BlogDraft:
    title: str
    slug: str
    content_markdown: str
    content_html: str
    key_takeaway: str = ""
    tldr_bullets: list[str] = field(default_factory=list)
    faq_items: list[dict] = field(default_factory=list)
    howto_steps: list[dict] = field(default_factory=list)
    comparison_table: str = ""
    meta_description: str = ""
    seo_title: str = ""
    word_count: int = 0
    smartscaling_pillar: str = ""
    smartscaling_function: str = ""
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    planned_internal_links: list[dict] = field(default_factory=list)  # From frontmatter


@dataclass
class QualityResult:
    passes: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class DailyResult:
    post_id: int
    topic: TopicSelection
    draft: BlogDraft


class ContentEngine:
    """The main orchestrator. Selects topics, generates drafts, builds schema, publishes."""

    # Day-of-week format rotation
    DAILY_ROTATION = {
        0: "data_insight",   # Monday
        1: "how_to",         # Tuesday
        2: "myth_buster",    # Wednesday
        3: "comparison",     # Thursday
        4: "case_study",     # Friday
        5: None,             # Saturday
        6: None,             # Sunday
    }

    def __init__(self, config_path="config.yaml"):
        self.config = self._load_config(config_path)
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Load content map
        pillar_map_path = os.path.join(self.project_root, "data", "pillar_cluster_map.yaml")
        self.content_map = {}
        if os.path.exists(pillar_map_path):
            with open(pillar_map_path) as f:
                self.content_map = yaml.safe_load(f) or {}

        # Load content calendar
        calendar_path = os.path.join(self.project_root, "data", "content_calendar.yaml")
        self.calendar = {}
        if os.path.exists(calendar_path):
            with open(calendar_path) as f:
                self.calendar = yaml.safe_load(f) or {}

        # State tracker — knows what's been published
        state_path = os.path.join(self.project_root, "data", "published_state.yaml")
        self.state = StateTracker(state_path=state_path)

        # Draft ingester — reads pre-written Cowork drafts (lazy import to avoid circular)
        from src.draft_ingester import DraftIngester
        self.draft_ingester = DraftIngester(content_map=self.content_map)

        # Resolve drafts directory (relative to project root or absolute)
        drafts_dir_cfg = self.config.get("content", {}).get("drafts_dir", "")
        if drafts_dir_cfg:
            if os.path.isabs(drafts_dir_cfg):
                self.drafts_dir = drafts_dir_cfg
            else:
                self.drafts_dir = os.path.normpath(os.path.join(self.project_root, drafts_dir_cfg))
        else:
            self.drafts_dir = ""

        # Initialize sub-modules (lazy — only when needed)
        self._wp = None
        self._schema_builder = None
        self._image_pipeline = None
        self._anthropic_client = None

        log.info("ContentEngine initialized")

    def _load_config(self, path: str) -> dict:
        if os.path.exists(path):
            with open(path) as f:
                return yaml.safe_load(f) or {}
        return {}

    @property
    def wp(self) -> WordPressPublisher:
        if self._wp is None:
            self._wp = WordPressPublisher()
        return self._wp

    @property
    def schema_builder(self) -> SchemaBuilder:
        if self._schema_builder is None:
            templates_dir = os.path.join(self.project_root, "templates")
            pillar_map = os.path.join(self.project_root, "data", "pillar_cluster_map.yaml")
            self._schema_builder = SchemaBuilder(templates_dir=templates_dir, pillar_map_path=pillar_map)
        return self._schema_builder

    @property
    def image_pipeline(self) -> ImagePipeline:
        if self._image_pipeline is None:
            brand_path = os.path.join(self.project_root, "assets", "brand", "colors.yaml")
            self._image_pipeline = ImagePipeline(brand_config_path=brand_path)
        return self._image_pipeline

    _DISABLED = object()  # Sentinel to distinguish "not set" from "explicitly disabled"

    @property
    def anthropic_client(self):
        if self._anthropic_client is self._DISABLED:
            return None
        if self._anthropic_client is None:
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            if api_key:
                try:
                    import anthropic
                    self._anthropic_client = anthropic.Anthropic(api_key=api_key)
                except ImportError:
                    log.warning("anthropic package not installed")
        return self._anthropic_client

    def disable_api(self):
        """Disable the Claude API client (for testing)."""
        self._anthropic_client = self._DISABLED

    def select_topic(self, date: datetime) -> TopicSelection:
        """Select today's topic based on rotation, calendar, and content gaps."""
        # 1. Check day-of-week rotation
        format_type = self.DAILY_ROTATION.get(date.weekday())
        if format_type is None:
            log.info(f"No content scheduled for {date.strftime('%A')}")
            format_type = "data_insight"

        # 2. Check pre-planned calendar
        date_str = date.strftime("%Y-%m-%d")
        scheduled = self.calendar.get("scheduled", [])
        if isinstance(scheduled, list):
            for entry in scheduled:
                if isinstance(entry, dict) and entry.get("date") == date_str:
                    return TopicSelection(
                        topic=entry.get("topic", ""),
                        primary_keyword=entry.get("primary_keyword", ""),
                        secondary_keywords=entry.get("secondary_keywords", []),
                        format_type=entry.get("format_type", format_type),
                        smartscaling_pillar=entry.get("smartscaling_pillar", ""),
                        smartscaling_function=entry.get("smartscaling_function", ""),
                    )

        # 3. Auto-select from content map based on gaps
        topic = self._select_from_content_map(format_type)
        return topic

    def _select_from_content_map(self, format_type: str) -> TopicSelection:
        """Select a topic from the content map, prioritizing under-covered clusters."""
        all_posts = []
        pillar_names = ["strategy", "people", "process", "performance"]

        for pillar_name in pillar_names:
            pillar_data = self.content_map.get(pillar_name, {})
            clusters = pillar_data.get("clusters", {})
            for cluster_name, cluster_data in clusters.items():
                posts = cluster_data.get("posts", [])
                for post in posts:
                    if isinstance(post, dict):
                        post["_pillar"] = pillar_name
                        post["_cluster"] = cluster_name
                        all_posts.append(post)

        # Also include cross-pillar content
        cross = self.content_map.get("cross_pillar", {}).get("posts", [])
        for post in cross:
            if isinstance(post, dict):
                post["_pillar"] = "cross_pillar"
                post["_cluster"] = "cross_pillar"
                all_posts.append(post)

        # Filter out already-published topics
        published_slugs = self.state.get_published_slugs()
        unpublished = [p for p in all_posts if p.get("slug", "") not in published_slugs]
        if not unpublished:
            log.warning("All topics in content map have been published — resetting to full list")
            unpublished = all_posts

        # Filter by format if possible
        format_matches = [p for p in unpublished if p.get("format") == format_type]
        candidates = format_matches if format_matches else unpublished

        # Sort by priority (lower = higher priority), then balance across pillars
        pillar_counts = self.state.get_pillar_counts()
        candidates.sort(key=lambda p: (p.get("priority", 99), pillar_counts.get(p.get("_pillar", ""), 0)))

        if not candidates:
            return TopicSelection(
                topic="SMARTSCALING Framework Overview",
                primary_keyword="sales optimization",
                format_type=format_type,
            )

        selected = candidates[0]
        pillar_name = selected.get("_pillar", "")
        cluster_name = selected.get("_cluster", "")

        # Look up cluster info for function name
        function_name = ""
        if pillar_name in self.content_map:
            clusters = self.content_map[pillar_name].get("clusters", {})
            if cluster_name in clusters:
                cp = clusters[cluster_name].get("cluster_page", {})
                function_name = cp.get("title", cluster_name)

        return TopicSelection(
            topic=selected.get("title", ""),
            primary_keyword=selected.get("keyword", ""),
            secondary_keywords=[],
            format_type=selected.get("format", format_type),
            smartscaling_pillar=pillar_name,
            smartscaling_function=function_name,
            growth_stage=selected.get("stage", ""),
            target_subreddit=self._best_subreddit(pillar_name),
        )

    def _best_subreddit(self, pillar: str) -> str:
        """Select best subreddit based on pillar."""
        mapping = {
            "strategy": "r/entrepreneur",
            "people": "r/sales",
            "process": "r/sales",
            "performance": "r/sales",
        }
        return mapping.get(pillar, "r/sales")

    def generate_draft(self, topic: TopicSelection, feedback: list[str] = None) -> BlogDraft:
        """Generate a blog post draft using Claude API."""
        if not self.anthropic_client:
            return self._generate_draft_template(topic)

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(topic, feedback)

        try:
            response = self.anthropic_client.messages.create(
                model=self.config.get("claude", {}).get("model", "claude-sonnet-4-5-20250929"),
                max_tokens=self.config.get("claude", {}).get("max_tokens", 4000),
                temperature=self.config.get("claude", {}).get("temperature", 0.7),
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw_content = response.content[0].text
            return self._parse_draft(raw_content, topic)
        except Exception as e:
            log.error(f"Claude API error: {e}")
            return self._generate_draft_template(topic)

    def _build_system_prompt(self) -> str:
        """Load the full system prompt from file, falling back to inline version."""
        # Try loading the rich prompt from the SEO Machine prompts directory
        prompt_paths = [
            os.path.join(self.project_root, "prompts", "system-prompt-blog-engine.md"),
            os.path.join(self.project_root, "..", "03-Content-Prompts", "system-prompt-blog-engine.md"),
        ]
        for path in prompt_paths:
            if os.path.exists(path):
                with open(path) as f:
                    content = f.read()
                # Extract the system prompt between the ``` delimiters
                import re as _re
                match = _re.search(r"## SYSTEM PROMPT\s*\n```\n(.*?)```", content, _re.DOTALL)
                if match:
                    log.info(f"Loaded system prompt from {path} ({len(match.group(1))} chars)")
                    return match.group(1).strip()
                # If no delimiters, use the whole file
                log.info(f"Loaded system prompt from {path} ({len(content)} chars)")
                return content.strip()

        log.warning("Rich system prompt file not found, using inline fallback")
        return """You are writing as Ken Lundin, founder of RevHeat, a sales consulting firm.
You have data from 33,000+ companies and the SMARTSCALING framework (11 sales functions across 4 pillars: Strategy, People, Process, Performance).

Voice: Direct, data-driven, practitioner perspective. No fluff. Use specific numbers.
Audience: Founders and sales leaders at $3M-$150M service/technical companies.

Every blog post MUST include:
1. A KEY TAKEAWAY block (40-60 words, boxed)
2. TL;DR with exactly 4 bullet points at the top
3. At least 5 FAQ items in a dedicated section
4. Data/statistics every 150-200 words
5. A comparison table where relevant
6. Word count: 1200-2000 words
7. SEO title (50-60 chars) and meta description (150-160 chars)

Format the output as markdown with clear section headers."""

    def _build_user_prompt(self, topic: TopicSelection, feedback: list[str] = None) -> str:
        # Build internal link suggestions from content map
        internal_links = self._suggest_internal_links(topic)

        prompt = f"""Write a blog post for RevHeat. Include the COMPLETE YAML frontmatter block AND all 15 content sections.

**Topic:** {topic.topic}
**Primary Keyword:** {topic.primary_keyword}
**Secondary Keywords:** {', '.join(topic.secondary_keywords) if topic.secondary_keywords else 'N/A'}
**Content Format:** {topic.format_type}
**SMARTSCALING Pillar:** {topic.smartscaling_pillar}
**SMARTSCALING Function:** {topic.smartscaling_function}
**Growth Stage Focus:** {topic.growth_stage or 'all'}
**Target Subreddit for Cross-Post:** {topic.target_subreddit}

**Required Data Points to Include:**
- Data from 33,000+ companies and 2.5 million sellers
- Only 6% of salespeople possess the complete skill set for elite performance
- Top 10% vs bottom 10% gap ranges from 18% to 600% depending on the skill
- System-dependent skills show 3-5x larger gaps than relationship skills

**Internal Links to Include (minimum 3):**
{internal_links}

**Competitor Gap This Addresses:**
{topic.competitor_gap or 'Sandler, RAIN Group, and Alexander Group lack data-backed frameworks with 33K company research.'}

Follow the V2 LLM-Optimized Template exactly. Every required element must be present. Output the YAML frontmatter first, then the full post."""

        if feedback:
            prompt += f"\n\n**Previous draft had these issues — please fix:**\n"
            for f in feedback:
                prompt += f"- {f}\n"

        return prompt

    def _suggest_internal_links(self, topic: TopicSelection) -> str:
        """Build internal link suggestions from the content map."""
        lines = []
        pillar = topic.smartscaling_pillar.lower() if topic.smartscaling_pillar else ""

        # Pillar page link
        pillar_data = self.content_map.get(pillar, {})
        if pillar_data and "pillar_page" in pillar_data:
            pp = pillar_data["pillar_page"]
            lines.append(f"- Pillar link: /{pp.get('slug', pillar)}/")

        # Sibling cluster link — pick a post from the same pillar
        clusters = pillar_data.get("clusters", {})
        for cluster_name, cluster_data in clusters.items():
            posts = cluster_data.get("posts", [])
            for post in posts:
                if isinstance(post, dict) and post.get("slug") != getattr(topic, "slug", ""):
                    lines.append(f"- Sibling link: /{pillar}/{cluster_name}/{post['slug']}/")
                    break
            if len(lines) >= 2:
                break

        # Cross-pillar link — pick from a different pillar
        other_pillars = [p for p in ["strategy", "people", "process", "performance"] if p != pillar]
        for other in other_pillars:
            other_data = self.content_map.get(other, {})
            for cn, cd in other_data.get("clusters", {}).items():
                posts = cd.get("posts", [])
                if posts and isinstance(posts[0], dict):
                    lines.append(f"- Cross-pillar link: /{other}/{cn}/{posts[0]['slug']}/")
                    break
            if len(lines) >= 3:
                break

        return "\n".join(lines) if lines else "- Use relevant pillar and cluster page links"

    def _parse_draft(self, raw: str, topic: TopicSelection) -> BlogDraft:
        """Parse Claude's raw output into a structured BlogDraft."""
        # Convert markdown to HTML
        content_html = md_lib.markdown(raw, extensions=["tables", "fenced_code"])

        # Extract title (first H1 or H2)
        title_match = re.search(r"^#\s+(.+)$|^##\s+(.+)$", raw, re.MULTILINE)
        title = (title_match.group(1) or title_match.group(2)) if title_match else topic.topic

        # Extract TL;DR bullets
        tldr_section = re.search(r"(?:TL;DR|TLDR).*?\n((?:[-*]\s+.+\n){1,6})", raw, re.IGNORECASE)
        tldr_bullets = []
        if tldr_section:
            tldr_bullets = [
                line.strip().lstrip("-*").strip()
                for line in tldr_section.group(1).strip().split("\n")
                if line.strip()
            ]

        # Extract Key Takeaway
        key_match = re.search(r"(?:KEY TAKEAWAY|Key Takeaway).*?\n(.+?)(?:\n\n|\n#)", raw, re.DOTALL | re.IGNORECASE)
        key_takeaway = key_match.group(1).strip() if key_match else ""

        # Extract FAQ items
        faq_items = self._extract_faqs(raw)

        # Extract comparison table
        table_match = re.search(r"(\|.+\|[\s\S]*?\|.+\|)", raw)
        comparison_table = table_match.group(1) if table_match else ""

        # Word count
        word_count = len(raw.split())

        # Generate slug and SEO fields
        slug = slugify(title, max_length=60)
        seo_title = title[:57] + "..." if len(title) > 60 else title
        meta_desc = self._extract_meta_description(raw, topic)

        return BlogDraft(
            title=title,
            slug=slug,
            content_markdown=raw,
            content_html=content_html,
            key_takeaway=key_takeaway,
            tldr_bullets=tldr_bullets,
            faq_items=faq_items,
            howto_steps=self._extract_howto_steps(raw) if topic.format_type == "how_to" else [],
            comparison_table=comparison_table,
            meta_description=meta_desc,
            seo_title=seo_title,
            word_count=word_count,
            smartscaling_pillar=topic.smartscaling_pillar,
            smartscaling_function=topic.smartscaling_function,
            categories=[topic.smartscaling_pillar] if topic.smartscaling_pillar else ["general"],
            tags=[topic.primary_keyword.replace(" ", "-")] + [
                kw.replace(" ", "-") for kw in topic.secondary_keywords[:3]
            ],
        )

    def _extract_faqs(self, text: str) -> list[dict]:
        """Extract FAQ question-answer pairs from markdown."""
        faq_section = re.search(r"(?:## FAQ|## Frequently Asked).*?\n([\s\S]+?)(?=\n## |\Z)", text, re.IGNORECASE)
        if not faq_section:
            return []

        items = []
        faq_text = faq_section.group(1)
        # Pattern: **Q: ...** or ### Q: ... followed by answer
        q_pattern = re.findall(
            r"(?:\*\*|###?\s*)(?:Q:\s*)?(.+?)(?:\*\*|$)\s*\n\s*(?:A:\s*)?(.+?)(?=\n\s*(?:\*\*|###?\s*)|$)",
            faq_text, re.MULTILINE,
        )
        for q, a in q_pattern:
            items.append({"question": q.strip(), "answer": a.strip()})

        # Fallback: numbered list pattern
        if not items:
            numbered = re.findall(
                r"\d+\.\s*\*\*(.+?)\*\*\s*\n\s*(.+?)(?=\n\d+\.|\n\n|\Z)",
                faq_text, re.DOTALL,
            )
            for q, a in numbered:
                items.append({"question": q.strip(), "answer": a.strip()})

        return items

    def _extract_howto_steps(self, text: str) -> list[dict]:
        """Extract step-by-step instructions from markdown."""
        steps = []
        step_pattern = re.findall(
            r"(?:Step\s+\d+|###\s+\d+)[.:]\s*(.+?)\n\s*(.+?)(?=\n(?:Step|###\s+\d)|\Z)",
            text, re.DOTALL,
        )
        for title, desc in step_pattern:
            steps.append({"title": title.strip(), "description": desc.strip()})
        return steps

    def _extract_meta_description(self, text: str, topic: TopicSelection) -> str:
        """Generate a 150-160 char meta description."""
        # Try to find an explicit meta description
        meta_match = re.search(r"meta.?description.*?:\s*(.+)", text, re.IGNORECASE)
        if meta_match:
            desc = meta_match.group(1).strip()
            if 140 <= len(desc) <= 170:
                return desc

        # Generate from topic
        desc = f"Data from 33,000 companies reveals {topic.topic.lower()}. {topic.primary_keyword.title()} insights from the SMARTSCALING framework."
        if len(desc) > 160:
            desc = desc[:157] + "..."
        return desc

    def _generate_draft_template(self, topic: TopicSelection) -> BlogDraft:
        """Generate a template draft when Claude API is unavailable."""
        title = topic.topic
        slug = slugify(title, max_length=60)

        content_md = f"""# {title}

## TL;DR
- Key insight 1 about {topic.primary_keyword}
- Data point from 33,000 companies
- SMARTSCALING {topic.smartscaling_pillar} pillar finding
- Action step for founders and sales leaders

## KEY TAKEAWAY
{topic.topic} is a critical challenge for service businesses scaling from $3M to $150M. Data from 33,000 companies shows that companies addressing this systematically see measurable improvement within 90-180 days.

## The Problem

Most companies get {topic.primary_keyword} wrong. Our data from 33,000 companies reveals that 92% of organizations struggle with this fundamental challenge.

## The Data

According to SMARTSCALING research across 33,000 companies:
- Bottom 25% of companies: 12% effectiveness
- Median companies: 28% effectiveness
- Top 10% performers: 47% effectiveness

The gap between median and top performers is staggering — and it's not about talent.

## The Solution: A Systems Approach

The SMARTSCALING framework addresses this through the {topic.smartscaling_pillar} pillar, specifically the {topic.smartscaling_function} function.

### Step 1: Diagnose
Assess your current state using the 11-function audit.

### Step 2: Design
Build a system tailored to your company's growth stage ({topic.growth_stage or 'scaling'}).

### Step 3: Implement
Deploy changes with accountability loops and 90-day milestones.

## Comparison Table

| Metric | Bottom 25% | Median | Top 10% |
|--------|-----------|--------|---------|
| Win Rate | 12% | 28% | 47% |
| Cycle Time | 9 months | 6 months | 3 months |
| Revenue/Rep | $350K | $650K | $1.2M |

## FAQ

**Why do most companies fail at {topic.primary_keyword}?**
Based on data from 33,000 companies, the primary reason is lack of a systematic approach.

**How long does improvement take?**
Typically 90-180 days for measurable results with the right framework.

**What's the ROI of fixing this?**
Top 10% performers generate 3.4x more revenue per rep than the median.

**Should I hire externally or build internally?**
Companies above $5M revenue typically benefit from external expertise to accelerate the process.

**What is the SMARTSCALING framework?**
A data-backed system covering 11 sales functions across 4 pillars: Strategy, People, Process, Performance.

## What to Do Next

Run a quick diagnostic on your {topic.smartscaling_function.lower() if topic.smartscaling_function else 'sales system'}. If you score below median on 3+ functions, you have a systems problem, not a people problem.
"""

        content_html = md_lib.markdown(content_md, extensions=["tables", "fenced_code"])

        return BlogDraft(
            title=title,
            slug=slug,
            content_markdown=content_md,
            content_html=content_html,
            key_takeaway=f"{topic.topic} is a critical challenge for service businesses. Data from 33,000 companies shows systematic approaches work within 90-180 days.",
            tldr_bullets=[
                f"Key insight about {topic.primary_keyword}",
                "Data from 33,000 companies supports systematic approach",
                f"SMARTSCALING {topic.smartscaling_pillar} pillar addresses this directly",
                "Action: Run a diagnostic on your sales system",
            ],
            faq_items=[
                {"question": f"Why do most companies fail at {topic.primary_keyword}?", "answer": "Lack of systematic approach based on 33K company data."},
                {"question": "How long does improvement take?", "answer": "90-180 days for measurable results."},
                {"question": "What's the ROI?", "answer": "Top 10% generate 3.4x more revenue per rep."},
                {"question": "Build internally or hire externally?", "answer": "Companies above $5M benefit from external expertise."},
                {"question": "What is SMARTSCALING?", "answer": "Data-backed system covering 11 functions across 4 pillars."},
            ],
            comparison_table="| Metric | Bottom 25% | Median | Top 10% |",
            meta_description=f"Data from 33,000 companies reveals insights about {topic.primary_keyword}. SMARTSCALING framework analysis.",
            seo_title=title[:60],
            word_count=len(content_md.split()),
            smartscaling_pillar=topic.smartscaling_pillar,
            smartscaling_function=topic.smartscaling_function,
            categories=[topic.smartscaling_pillar] if topic.smartscaling_pillar else ["general"],
            tags=[topic.primary_keyword.replace(" ", "-")],
        )

    def quality_check(self, draft: BlogDraft, topic: "TopicSelection | None" = None) -> QualityResult:
        """Check draft against V2 template requirements.

        Validates: content structure, stat density, keyword placement,
        heading hierarchy, internal link minimum, and SEO meta fields.
        """
        failures = []
        warnings = []
        md = draft.content_markdown

        # --- Existing checks ---

        # Key Takeaway
        if not draft.key_takeaway:
            failures.append("Missing Key Takeaway block")
        elif draft.key_takeaway:
            kt_words = len(draft.key_takeaway.split())
            if kt_words < 40 or kt_words > 60:
                warnings.append(f"Key Takeaway is {kt_words} words (target: 40-60)")

        # FAQ items
        if len(draft.faq_items) < 5:
            failures.append(f"Only {len(draft.faq_items)} FAQ items (minimum 5)")

        # Comparison table
        if not draft.comparison_table:
            failures.append("Missing comparison table")

        # Word count
        if draft.word_count < 1200:
            failures.append(f"Only {draft.word_count} words (minimum 1200)")
        if draft.word_count > 2000:
            warnings.append(f"{draft.word_count} words (target max 2000)")

        # Stat density
        stat_count = self._count_statistics(md)
        expected_stats = draft.word_count // 175
        if stat_count < expected_stats:
            failures.append(f"Only {stat_count} stats found (expected ~{expected_stats})")

        # TL;DR
        if len(draft.tldr_bullets) != 4:
            failures.append(f"TL;DR has {len(draft.tldr_bullets)} bullets (need exactly 4)")

        # Meta description length
        if draft.meta_description:
            md_len = len(draft.meta_description)
            if md_len < 140:
                warnings.append(f"Meta description short: {md_len} chars (target 150-160)")
            elif md_len > 170:
                warnings.append(f"Meta description long: {md_len} chars (target 150-160)")

        # --- NEW: Heading hierarchy validation ---
        h1_count = len(re.findall(r"^# [^#]", md, re.MULTILINE))
        h2_count = len(re.findall(r"^## [^#]", md, re.MULTILINE))
        h3_count = len(re.findall(r"^### [^#]", md, re.MULTILINE))

        if h1_count == 0:
            failures.append("Missing H1 heading")
        elif h1_count > 1:
            warnings.append(f"Found {h1_count} H1 headings (should be exactly 1)")

        if h2_count < 5:
            warnings.append(f"Only {h2_count} H2 headings (target: 5-8 for scannability)")
        elif h2_count > 10:
            warnings.append(f"{h2_count} H2 headings (target max: 8)")

        # Check for level-skipping: H1 → H3 without H2
        heading_levels = re.findall(r"^(#{1,6})\s", md, re.MULTILINE)
        for i in range(1, len(heading_levels)):
            prev_level = len(heading_levels[i - 1])
            curr_level = len(heading_levels[i])
            if curr_level > prev_level + 1:
                warnings.append(
                    f"Heading level skip: H{prev_level} → H{curr_level} "
                    f"(heading #{i+1})"
                )
                break  # Report only first occurrence

        # --- NEW: Keyword density validation ---
        if topic and topic.primary_keyword:
            kw = topic.primary_keyword.lower()
            text_lower = md.lower()
            kw_count = text_lower.count(kw)
            if draft.word_count > 0:
                density = (kw_count * len(kw.split())) / draft.word_count * 100
                if density < 0.5:
                    warnings.append(
                        f"Focus keyword '{kw}' appears {kw_count}x "
                        f"(~{density:.1f}% density, target: 0.8-1.5%)"
                    )
                elif density > 2.0:
                    warnings.append(
                        f"Focus keyword '{kw}' may be over-used: {kw_count}x "
                        f"(~{density:.1f}% density, target: 0.8-1.5%)"
                    )

            # Keyword placement checks (warnings, not failures — Cowork drafts are trusted)
            placements_missing = []
            # First 100 words
            first_100 = " ".join(md.split()[:100]).lower()
            if kw not in first_100:
                placements_missing.append("first 100 words")
            # At least one H2
            h2_texts = re.findall(r"^## (.+)$", md, re.MULTILINE)
            if not any(kw in h.lower() for h in h2_texts):
                placements_missing.append("H2 heading")
            # Meta description
            if draft.meta_description and kw not in draft.meta_description.lower():
                placements_missing.append("meta description")
            # At least one FAQ
            if draft.faq_items:
                faq_text = " ".join(
                    q.get("question", "").lower() for q in draft.faq_items
                )
                if kw not in faq_text:
                    placements_missing.append("FAQ question")

            if placements_missing:
                warnings.append(
                    f"Focus keyword missing from: {', '.join(placements_missing)}"
                )

        # --- NEW: SEO title validation ---
        if draft.seo_title:
            st_len = len(draft.seo_title)
            if st_len > 65:
                warnings.append(f"SEO title is {st_len} chars (target: 50-60, may truncate in SERPs)")
            elif st_len < 30:
                warnings.append(f"SEO title is only {st_len} chars (target: 50-60)")

        # --- NEW: Internal link minimum ---
        link_count = len(re.findall(r'<a\s+href=', draft.content_html))
        planned_count = len(draft.planned_internal_links)
        min_links = self.config.get("content", {}).get("min_internal_links", 3)
        total_links = link_count + planned_count
        if total_links < min_links:
            warnings.append(
                f"Only {total_links} internal links (minimum: {min_links}). "
                f"Reactive linking will attempt to supplement."
            )

        return QualityResult(
            passes=len(failures) == 0,
            failures=failures,
            warnings=warnings,
        )

    def _count_statistics(self, text: str) -> int:
        """Count numeric statistics in text."""
        # Match percentages, dollar amounts, and large numbers
        patterns = [
            r"\d+%",               # Percentages
            r"\$[\d,.]+[MBK]?",    # Dollar amounts
            r"\d{1,3}(?:,\d{3})+", # Large numbers with commas
            r"\d+x\b",             # Multipliers
        ]
        count = 0
        for pattern in patterns:
            count += len(re.findall(pattern, text))
        return count

    def generate_reddit_angle(self, draft: BlogDraft, subreddit: str) -> str:
        """Condense blog into Reddit-appropriate format."""
        tldr = "\n".join(f"- {b}" for b in draft.tldr_bullets)

        reddit_text = f"""TL;DR:
{tldr}

---

{draft.key_takeaway}

Based on data from 33,000 companies, here's what we found about {draft.title.lower()}:

Key findings:
- The gap between top and bottom performers is 3-4x
- Most companies have a systems problem, not a people problem
- Improvement is measurable within 90 days with the right framework

The most common mistake: treating this as a training problem when it's actually a structural problem.

---

What's your experience with this? Has your company tried a systematic approach or are you still relying on individual heroics?"""

        # Ensure under 800 words
        words = reddit_text.split()
        if len(words) > 800:
            reddit_text = " ".join(words[:800]) + "..."

        return reddit_text

    def build_internal_links(self, content_html: str, existing_posts: list[dict]) -> str:
        """Inject internal links into HTML content."""
        if not existing_posts:
            return content_html

        soup = BeautifulSoup(content_html, "html.parser")
        links_added = 0
        linked_urls = set()
        max_links = self.config.get("content", {}).get("max_internal_links", 5)

        for post in existing_posts:
            if links_added >= max_links:
                break

            post_title = post.get("title", {})
            if isinstance(post_title, dict):
                post_title = post_title.get("rendered", "")
            post_url = post.get("link", "")

            if not post_url or post_url in linked_urls:
                continue

            # Find relevant text nodes to link
            keywords = self._extract_link_keywords(post_title)
            for keyword in keywords:
                if links_added >= max_links:
                    break

                for text_node in soup.find_all(string=re.compile(re.escape(keyword), re.IGNORECASE)):
                    # Don't link inside existing links or headings
                    parent = text_node.parent
                    if parent.name in ("a", "h1", "h2", "h3", "h4", "script"):
                        continue

                    # Replace first occurrence
                    new_html = text_node.replace(
                        keyword,
                        f'<a href="{post_url}">{keyword}</a>',
                        1,
                    )
                    if new_html != str(text_node):
                        text_node.replace_with(BeautifulSoup(new_html, "html.parser"))
                        linked_urls.add(post_url)
                        links_added += 1
                        break

        return str(soup)

    # ------------------------------------------------------------------
    # CTA normalisation & content cleanup
    # ------------------------------------------------------------------

    CTA_URL = "https://revheat.com/#Calendar"
    CTA_TEXT = "Talk to the RevHeat Team"

    # Patterns that identify CTA links to rewrite
    _CTA_HREF_PATTERNS = [
        "sales-alpha-roadmap", "#cta", "link-to-cta", "/roadmap",
        "founder-call", "link)", "(link",
    ]
    _CTA_ANCHOR_PATTERNS = [
        "sales alpha roadmap", "get the roadmap", "get your",
        "book a consultation", "book a 20-minute", "schedule a",
        "get started", "free diagnostic", "cta:",
    ]

    def normalize_ctas(self, content_html: str) -> str:
        """Rewrite all call-to-action links and text to a single consistent CTA.

        Replaces various CTA link texts and placeholder URLs with:
          <a href="https://revheat.com/#Calendar">Talk to the RevHeat Team</a>
        """
        soup = BeautifulSoup(content_html, "html.parser")
        rewritten = 0

        # 1. Fix existing <a> tags that are CTA links
        for a_tag in soup.find_all("a"):
            href = (a_tag.get("href") or "").lower()
            text = (a_tag.get_text() or "").lower()

            is_cta = (
                any(p in href for p in self._CTA_HREF_PATTERNS)
                or any(p in text for p in self._CTA_ANCHOR_PATTERNS)
            )
            if is_cta:
                a_tag["href"] = self.CTA_URL
                a_tag.string = self.CTA_TEXT
                rewritten += 1

        # 2. Strip the "[CTA: ...]" raw text markers
        html_str = str(soup)
        html_str = re.sub(
            r'\[CTA:[^\]]*\]',
            f'<a href="{self.CTA_URL}">{self.CTA_TEXT}</a>',
            html_str,
        )

        if rewritten:
            log.info(f"Normalized {rewritten} CTA links to '{self.CTA_TEXT}'")
        return html_str

    def strip_reddit_section(self, content_html: str) -> str:
        """Remove the Reddit Cross-Post section from published HTML.

        This section is for internal use (email notification / Reddit bot)
        and should not appear on the WordPress post.
        """
        soup = BeautifulSoup(content_html, "html.parser")

        # Find any heading containing "Reddit" (h2, h3, etc.)
        for heading in soup.find_all(re.compile(r'^h[2-4]$')):
            heading_text = heading.get_text().lower()
            if "reddit" in heading_text and ("cross-post" in heading_text or "cross post" in heading_text):
                # Remove everything from this heading to the next same-level heading or end
                elements_to_remove = [heading]
                for sibling in heading.find_next_siblings():
                    if sibling.name and sibling.name == heading.name:
                        break  # Stop at the next same-level heading
                    elements_to_remove.append(sibling)
                for el in elements_to_remove:
                    el.decompose()
                log.info("Stripped Reddit cross-post section from published HTML")
                break

        return str(soup)

    def inject_planned_links(self, content_html: str, planned_links: list[dict]) -> str:
        """Inject pre-planned internal links from frontmatter into HTML.

        These take priority over the reactive build_internal_links() system.
        Returns (modified_html, set_of_linked_urls) so reactive linking can
        avoid duplicates.
        """
        if not planned_links:
            return content_html

        site_url = self.config.get("site", {}).get("url", "https://revheat.com")
        soup = BeautifulSoup(content_html, "html.parser")
        injected = 0

        for link in planned_links:
            anchor_text = link["anchor"]
            target = link["target"]

            # Build full URL if relative path
            if target.startswith("/"):
                full_url = f"{site_url}{target}"
            else:
                full_url = target

            # Find anchor text in content and wrap in link
            pattern = re.compile(re.escape(anchor_text), re.IGNORECASE)
            for text_node in soup.find_all(string=pattern):
                parent = text_node.parent
                if parent.name in ("a", "h1", "h2", "h3", "h4", "script"):
                    continue

                new_html = pattern.sub(
                    f'<a href="{full_url}">{anchor_text}</a>',
                    str(text_node),
                    count=1,
                )
                if new_html != str(text_node):
                    text_node.replace_with(BeautifulSoup(new_html, "html.parser"))
                    injected += 1
                    break  # One link per anchor

        if injected:
            log.info(f"Injected {injected} planned internal links from frontmatter")
        return str(soup)

    def _extract_link_keywords(self, title: str) -> list[str]:
        """Extract linkable keyword phrases from a post title."""
        # Remove common words and return 2-3 word phrases
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "how", "why", "what", "your", "you"}
        words = [w for w in title.split() if w.lower() not in stop_words]
        phrases = []
        # Try 3-word, then 2-word phrases
        for n in (3, 2):
            for i in range(len(words) - n + 1):
                phrase = " ".join(words[i:i+n])
                if len(phrase) > 8:
                    phrases.append(phrase)
        return phrases[:3]

    def notify_ken(self, post_title, post_edit_url, reddit_draft, target_subreddit, quality_report):
        """Send daily review notification via email."""
        subject = f"Blog Draft Ready: {post_title}"

        body = f"""Hi Ken,

Your daily blog draft is ready for review.

POST: {post_title}
EDIT: {post_edit_url}

QUALITY CHECK: {'PASSED' if quality_report.passes else 'NEEDS ATTENTION'}
"""
        if quality_report.failures:
            body += "\nIssues:\n"
            for f in quality_report.failures:
                body += f"  - {f}\n"
        if quality_report.warnings:
            body += "\nWarnings:\n"
            for w in quality_report.warnings:
                body += f"  - {w}\n"

        body += f"""
REDDIT DRAFT (for {target_subreddit}):
{'-' * 40}
{reddit_draft}
{'-' * 40}

Estimated review time: 25-30 minutes

— RevHeat Blog Engine
"""

        self._send_email(subject, body)

    def _send_email(self, subject: str, body: str):
        """Send email or save to file as fallback."""
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_pass = os.getenv("SMTP_PASSWORD", "")
        to_email = os.getenv("NOTIFICATION_EMAIL", "kglundin@gmail.com")

        if not smtp_user or not smtp_pass:
            os.makedirs("output", exist_ok=True)
            with open("output/notification.txt", "w") as f:
                f.write(f"Subject: {subject}\n\n{body}")
            log.info("Notification saved to output/notification.txt")
            return

        try:
            msg = MIMEMultipart()
            msg["From"] = smtp_user
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "587"))) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            log.info(f"Notification sent to {to_email}")
        except Exception as e:
            log.error(f"Email failed: {e}")

    def _publish_one(self, topic: TopicSelection, draft: BlogDraft,
                     quality: QualityResult, today: datetime) -> DailyResult:
        """Push a single topic+draft through the full publishing pipeline.

        Handles: images → schema → internal links → WP draft → SEO meta →
        social meta → canonical → Reddit angle → email notification → state.
        """
        # 4. Generate images
        images = self.image_pipeline.full_pipeline(draft)
        log.info(f"Generated {len(images)} images")

        # 5. Build Schema
        schema = self.schema_builder.build_full_graph({
            "post_url": f"https://revheat.com/blog/{draft.slug}/",
            "post_title": draft.title,
            "meta_description": draft.meta_description,
            "publish_date_iso": today.isoformat(),
            "modified_date_iso": today.isoformat(),
            "featured_image_url": images[0].path if images else "",
            "word_count": draft.word_count,
            "smartscaling_pillar": draft.smartscaling_pillar,
            "keywords": ", ".join([topic.primary_keyword] + topic.secondary_keywords),
            "faq_items": draft.faq_items,
            "howto_steps": draft.howto_steps if draft.howto_steps else None,
        })

        # 6a. Normalize CTAs to "Talk to the RevHeat Team" → /#Calendar
        content_clean = self.normalize_ctas(draft.content_html)

        # 6b. Strip Reddit cross-post section (internal use only)
        content_clean = self.strip_reddit_section(content_clean)

        # 6c. Inject Schema into HTML
        content_with_schema = self.schema_builder.inject_into_html(content_clean, schema)

        # 7a. Inject planned internal links from frontmatter (priority)
        content_with_planned = self.inject_planned_links(
            content_with_schema, draft.planned_internal_links
        )

        # 7b. Supplement with reactive internal links from existing posts
        content_with_links = self.build_internal_links(content_with_planned, self.wp.get_all_posts())

        # 8. Upload images to WordPress
        media_ids = []
        for img in images:
            media_id = self.wp.upload_image(img.path, img.alt_text)
            media_ids.append(media_id)

        # 9. Create WordPress draft (with slug for duplicate protection)
        post = self.wp.create_draft(
            title=draft.title,
            content_html=content_with_links,
            slug=draft.slug,
            meta={
                "rank_math_title": draft.seo_title,
                "rank_math_description": draft.meta_description,
                "rank_math_focus_keyword": topic.primary_keyword,
            },
        )

        # 10. Set featured image
        if media_ids:
            self.wp.set_featured_image(post["id"], media_ids[0])

        # 11. Assign categories and tags
        category_ids = [self.wp.get_category_id(s) for s in draft.categories]
        tag_ids = [self.wp.get_tag_id(s) for s in draft.tags]
        self.wp.assign_taxonomy(post["id"], category_ids, tag_ids)

        # 11b. Set SEO meta (with secondary keywords + robots)
        self.wp.set_seo_meta(
            post["id"],
            seo_title=draft.seo_title,
            meta_desc=draft.meta_description,
            focus_keyword=topic.primary_keyword,
            secondary_keywords=topic.secondary_keywords,
        )

        # 11c. Set OpenGraph + Twitter Card + Canonical
        post_url = f"https://revheat.com/blog/{draft.slug}/"
        featured_url = ""
        if images:
            try:
                media_resp = self.wp._request("GET", f"{self.wp.api_base}/media/{media_ids[0]}")
                if media_resp.status_code == 200:
                    featured_url = media_resp.json().get("source_url", "")
            except Exception:
                pass

        self.wp.set_social_meta(
            post["id"],
            title=draft.seo_title or draft.title,
            description=draft.meta_description,
            image_url=featured_url,
        )
        self.wp.set_canonical_url(post["id"], post_url)

        # 12. Generate Reddit angle
        reddit_draft = self.generate_reddit_angle(draft, topic.target_subreddit)

        # 13. Notify Ken
        self.notify_ken(
            post_title=draft.title,
            post_edit_url=f"https://revheat.com/wp-admin/post.php?post={post['id']}&action=edit",
            reddit_draft=reddit_draft,
            target_subreddit=topic.target_subreddit,
            quality_report=quality,
        )

        # 14. Record in state tracker
        self.state.record_publish(
            slug=draft.slug,
            title=draft.title,
            post_id=post["id"],
            pillar=draft.smartscaling_pillar,
            function=draft.smartscaling_function,
        )

        log.info(f"Published: Draft #{post['id']} — {draft.title}")
        return DailyResult(post_id=post["id"], topic=topic, draft=draft)

    def run_daily(self) -> DailyResult | list[DailyResult]:
        """The main daily execution flow.

        Checks for pre-written Cowork drafts first. If the backlog has
        unprocessed files, the next draft is ingested and pushed through
        the publishing pipeline. When the backlog is exhausted the engine
        falls back to Claude API generation.

        **Burst mode:** When enabled in config, publishes multiple pillar/cluster
        pages per run to build the site foundation quickly. Once all burst-eligible
        folders are exhausted, falls back to 1 post/day.
        """
        today = datetime.now(timezone.utc)
        log.info(f"Starting daily content engine for {today.date()}")

        prefer_drafts = self.config.get("content", {}).get("prefer_existing_drafts", True)
        scheduling = self.config.get("scheduling", {})
        burst_mode = scheduling.get("burst_mode", False)
        burst_count = scheduling.get("burst_posts_per_day", 4)
        burst_folders = set(scheduling.get("burst_folders", ["Pillar-Pages", "Cluster-Pages"]))

        # --- Build ingestion queue ---
        queue = []
        if prefer_drafts and self.drafts_dir and os.path.isdir(self.drafts_dir):
            published_slugs = self.state.get_published_slugs()
            queue = self.draft_ingester.get_ingestion_queue(self.drafts_dir, published_slugs)

        # --- Burst mode: publish multiple pillar/cluster pages at once ---
        if burst_mode and queue:
            burst_queue = [f for f in queue if f.parent.name in burst_folders]
            if burst_queue:
                batch = burst_queue[:burst_count]
                log.info(
                    f"BURST MODE: Publishing {len(batch)} of {len(burst_queue)} "
                    f"remaining pillar/cluster pages"
                )
                results = []
                for filepath in batch:
                    topic, draft = self.draft_ingester.build_draft_from_file(
                        filepath, self._parse_draft
                    )
                    quality = self.quality_check(draft, topic=topic)
                    if not quality.passes:
                        log.warning(f"Quality warnings on {filepath.name}: {quality.failures}")
                    result = self._publish_one(topic, draft, quality, today)
                    results.append(result)

                log.info(f"Burst complete: {len(results)} posts published.")
                return results if len(results) > 1 else results[0]

        # --- Standard mode: 1 post per day ---
        ingested = False

        if queue:
            next_file = queue[0]
            log.info(f"Backlog: {len(queue)} drafts remaining — ingesting {next_file.name}")
            topic, draft = self.draft_ingester.build_draft_from_file(
                next_file, self._parse_draft
            )
            ingested = True
        elif prefer_drafts and self.drafts_dir:
            log.info("Backlog exhausted — switching to API generation")

        if not ingested:
            # 1. Select topic
            topic = self.select_topic(today)
            log.info(f"Topic selected: {topic.topic}")

            # 2. Generate blog draft
            draft = self.generate_draft(topic)
            log.info(f"Draft generated: {draft.title} ({draft.word_count} words)")

        # 3. Quality check (pass topic for keyword validation)
        quality = self.quality_check(draft, topic=topic)
        if not quality.passes:
            if ingested:
                log.warning(f"Quality check warnings on ingested draft: {quality.failures}")
            else:
                log.warning(f"Quality check failed: {quality.failures}")
                draft = self.generate_draft(topic, feedback=quality.failures)
                quality = self.quality_check(draft, topic=topic)

        result = self._publish_one(topic, draft, quality, today)
        log.info(f"Daily engine complete. Draft #{result.post_id} ready for review.")
        return result
