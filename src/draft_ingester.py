"""Draft Ingester — reads pre-written markdown drafts and prepares them for publishing."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import yaml
from slugify import slugify

from src.content_engine import BlogDraft, TopicSelection

log = logging.getLogger(__name__)


class DraftIngester:
    """Reads markdown files from the drafts folder, parses frontmatter and body,
    and produces TopicSelection + BlogDraft objects ready for the publishing pipeline."""

    # Publishing order: pillar pages first, then clusters, then weekly posts
    FOLDER_PRIORITY = {
        "Pillar-Pages": 0,
        "Cluster-Pages": 1,
        "Week-01": 2,
        "Week-02": 3,
        "Week-03": 4,
        "Week-04": 5,
        "Week-05": 6,
        "Week-06": 7,
        "Week-07": 8,
        "Week-08": 9,
    }

    # Map bare pillar names to WP category slugs.  Frontmatter category
    # values (e.g. "Sales Process Architecture") pass through directly —
    # wp_publisher.get_category_id() slugifies them to match WP slugs.
    PILLAR_TO_CATEGORY = {
        "people": "sales-people",
        "performance": "sales-performance",
        "process": "sales-process",
        "strategy": "sales-strategy",
    }

    def __init__(self, content_map: dict = None):
        self.content_map = content_map or {}

    def scan_drafts_folder(self, drafts_dir: str) -> list[Path]:
        """Find all markdown files in the drafts directory, sorted by publish priority."""
        drafts_path = Path(drafts_dir)
        if not drafts_path.exists():
            log.warning(f"Drafts directory not found: {drafts_dir}")
            return []

        all_files = sorted(drafts_path.rglob("*.md"))

        # Sort by folder priority, then filename
        def sort_key(filepath: Path):
            parent = filepath.parent.name
            folder_priority = self.FOLDER_PRIORITY.get(parent, 99)
            return (folder_priority, filepath.name)

        all_files.sort(key=sort_key)
        log.info(f"Found {len(all_files)} draft files in {drafts_dir}")
        return all_files

    def parse_frontmatter(self, filepath: str | Path) -> tuple[dict, str]:
        """Parse YAML frontmatter and markdown body from a file.

        Handles files with and without frontmatter. Returns (metadata, body).
        """
        with open(filepath, encoding="utf-8") as f:
            content = f.read()

        # Check for YAML frontmatter (starts with ---)
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                yaml_text = parts[1].strip()
                body = parts[2].strip()
                try:
                    metadata = yaml.safe_load(yaml_text) or {}
                    return metadata, body
                except yaml.YAMLError as e:
                    log.warning(f"Failed to parse frontmatter in {filepath}: {e}")
                    return {}, content.strip()

        # No frontmatter — return empty metadata and full content
        return {}, content.strip()

    def infer_metadata_from_content(self, body: str, filepath: Path) -> dict:
        """Infer metadata from content and filename when no frontmatter exists."""
        metadata = {}

        # Extract title from first H1
        title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        if title_match:
            metadata["title"] = title_match.group(1).strip()

        # Infer slug from filename
        filename = filepath.stem  # e.g., "day-05-five-stages-revenue-growth"
        # Strip day-XX- prefix
        slug_from_file = re.sub(r"^day-\d+-", "", filename)
        # Strip pillar-/cluster- prefix
        slug_from_file = re.sub(r"^(pillar|cluster)-", "", slug_from_file)

        # Try to match slug against content map
        map_entry = self._find_in_content_map(slug_from_file)
        if map_entry:
            metadata["slug"] = map_entry.get("slug", slug_from_file)
            metadata["focus_keyword"] = map_entry.get("keyword", "")
            metadata["content_format"] = map_entry.get("format", "data_insight")
            metadata["growth_stage"] = map_entry.get("stage", "all")
            metadata["pillar"] = map_entry.get("_pillar", "")
            metadata["function"] = map_entry.get("_function", "")
        else:
            metadata["slug"] = slug_from_file

        # Infer content type from folder
        parent = filepath.parent.name
        if parent == "Pillar-Pages":
            metadata["content_format"] = metadata.get("content_format", "pillar_page")
        elif parent == "Cluster-Pages":
            metadata["content_format"] = metadata.get("content_format", "cluster_page")

        return metadata

    def _find_in_content_map(self, slug_hint: str) -> dict | None:
        """Search the content map for a post matching the slug hint."""
        slug_hint_clean = slug_hint.lower().replace("_", "-")

        for pillar_name in ["strategy", "people", "process", "performance"]:
            pillar_data = self.content_map.get(pillar_name, {})

            # Check pillar page
            pillar_page = pillar_data.get("pillar_page", {})
            pillar_slug = pillar_page.get("slug", "").lower()
            if pillar_slug and (pillar_slug in slug_hint_clean or slug_hint_clean in pillar_slug):
                return {
                    "slug": pillar_page.get("slug"),
                    "keyword": pillar_page.get("target_keyword", ""),
                    "format": "pillar_page",
                    "_pillar": pillar_name,
                    "_function": "",
                }

            # Check cluster pages and posts
            clusters = pillar_data.get("clusters", {})
            for cluster_name, cluster_data in clusters.items():
                # Check cluster page
                cluster_page = cluster_data.get("cluster_page", {})
                cluster_slug = cluster_page.get("slug", "").lower()
                if cluster_slug and cluster_slug == slug_hint_clean:
                    return {
                        "slug": cluster_page.get("slug", slug_hint_clean),
                        "keyword": cluster_page.get("target_keyword", ""),
                        "format": "cluster_page",
                        "_pillar": pillar_name,
                        "_function": cluster_page.get("title", cluster_name),
                    }

                # Check posts
                for post in cluster_data.get("posts", []):
                    if isinstance(post, dict):
                        post_slug = post.get("slug", "")
                        # Match if slug matches or hint is contained
                        if post_slug and (post_slug == slug_hint_clean or slug_hint_clean in post_slug or post_slug in slug_hint_clean):
                            return {
                                **post,
                                "_pillar": pillar_name,
                                "_function": cluster_page.get("title", cluster_name),
                            }

        # Check cross-pillar
        cross = self.content_map.get("cross_pillar", {})
        for post in cross.get("posts", []):
            if isinstance(post, dict) and post.get("slug") and post["slug"] == slug_hint_clean:
                return {**post, "_pillar": "cross_pillar", "_function": ""}

        return None

    def build_topic_from_metadata(self, metadata: dict, body: str) -> TopicSelection:
        """Build a TopicSelection from frontmatter metadata."""
        # Extract title from body if not in metadata
        title = metadata.get("title", "")
        if not title:
            title = metadata.get("seo_title", "")
        if not title:
            title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else "Untitled Draft"

        # Clean SEO title (remove "| RevHeat" suffix for topic name)
        topic_name = re.sub(r"\s*\|\s*RevHeat\s*$", "", title).strip()

        pillar = metadata.get("pillar", "").lower().strip()
        secondary = metadata.get("secondary_keywords", [])
        if isinstance(secondary, str):
            secondary = [s.strip() for s in secondary.split(",")]

        return TopicSelection(
            topic=topic_name,
            primary_keyword=metadata.get("focus_keyword", ""),
            secondary_keywords=secondary,
            format_type=metadata.get("content_format", "data_insight"),
            smartscaling_pillar=pillar,
            smartscaling_function=metadata.get("function", ""),
            growth_stage=metadata.get("growth_stage", "all"),
            target_subreddit=metadata.get("target_subreddit", "r/sales"),
        )

    def build_draft_from_file(self, filepath: str | Path, parse_draft_fn) -> tuple[TopicSelection, BlogDraft]:
        """Read a markdown file and produce a TopicSelection + BlogDraft.

        Args:
            filepath: Path to the markdown file.
            parse_draft_fn: The ContentEngine._parse_draft method for reuse.

        Returns:
            (TopicSelection, BlogDraft) ready for the publishing pipeline.
        """
        filepath = Path(filepath)
        log.info(f"Ingesting draft: {filepath.name}")

        # 1. Parse frontmatter and body
        metadata, body = self.parse_frontmatter(filepath)

        # 2. If no frontmatter, infer metadata from content + filename
        if not metadata:
            metadata = self.infer_metadata_from_content(body, filepath)

        # 3. Build TopicSelection
        topic = self.build_topic_from_metadata(metadata, body)

        # 4. Use existing _parse_draft to extract structured elements
        draft = parse_draft_fn(body, topic)

        # 5. Override with richer frontmatter data where available
        if metadata.get("seo_title"):
            draft.seo_title = metadata["seo_title"]
        if metadata.get("meta_description"):
            draft.meta_description = metadata["meta_description"]
        if metadata.get("slug"):
            draft.slug = metadata["slug"]
        if metadata.get("tags"):
            tags = metadata["tags"]
            if isinstance(tags, list):
                draft.tags = [t.replace(" ", "-") if isinstance(t, str) else t for t in tags]
        if metadata.get("category"):
            # Pass through as-is — wp_publisher slugifies to match WP slugs
            draft.categories = [metadata["category"]]
        elif topic.smartscaling_pillar:
            # Bare pillar names need mapping (e.g. "people" → "sales-people")
            pillar = topic.smartscaling_pillar.lower()
            draft.categories = [self.PILLAR_TO_CATEGORY.get(pillar, pillar)]

        # Pass planned internal links from frontmatter
        raw_links = metadata.get("internal_links", {})
        if raw_links and isinstance(raw_links, dict):
            draft.planned_internal_links = self._normalize_internal_links(raw_links)

        log.info(
            f"Ingested: {draft.title} | slug={draft.slug} | "
            f"pillar={draft.smartscaling_pillar} | {draft.word_count} words | "
            f"{len(draft.faq_items)} FAQs"
        )
        return topic, draft

    @staticmethod
    def _normalize_internal_links(raw_links: dict) -> list[dict]:
        """Convert frontmatter internal_links dict into a flat list of {anchor, target, type}."""
        normalized = []
        for link_key, link_data in raw_links.items():
            if not isinstance(link_data, dict):
                continue
            anchor = link_data.get("anchor", "")
            target = link_data.get("target", "")
            if anchor and target:
                # Classify by key name: pillar_link, sibling_link, cross_pillar, etc.
                link_type = "internal"
                key_lower = link_key.lower()
                if "pillar" in key_lower and "cross" not in key_lower:
                    link_type = "pillar"
                elif "cross" in key_lower:
                    link_type = "cross_pillar"
                elif "sibling" in key_lower or "sister" in key_lower:
                    link_type = "sibling"
                elif "cluster" in key_lower:
                    link_type = "cluster"
                elif "post" in key_lower:
                    link_type = "post"
                normalized.append({
                    "anchor": anchor.strip(),
                    "target": target.strip(),
                    "type": link_type,
                })
        return normalized

    def get_ingestion_queue(self, drafts_dir: str, published_slugs: set[str]) -> list[Path]:
        """Get ordered list of draft files that haven't been published yet."""
        all_files = self.scan_drafts_folder(drafts_dir)
        queue = []

        for filepath in all_files:
            metadata, body = self.parse_frontmatter(filepath)
            if not metadata:
                metadata = self.infer_metadata_from_content(body, filepath)

            slug = metadata.get("slug", "")
            if not slug:
                slug = slugify(filepath.stem, max_length=60)

            if slug not in published_slugs:
                queue.append(filepath)
            else:
                log.debug(f"Skipping already-published: {slug} ({filepath.name})")

        log.info(f"Ingestion queue: {len(queue)} files remaining ({len(all_files) - len(queue)} already published)")
        return queue
