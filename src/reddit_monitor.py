"""Reddit Monitor — scans subreddits for keyword matches and generates response drafts."""

import logging
import os
import re
import smtplib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import yaml
from dotenv import load_dotenv

load_dotenv(override=True)

log = logging.getLogger(__name__)


@dataclass
class RedditThread:
    id: str
    subreddit: str
    title: str
    body: str
    url: str
    score: int
    num_comments: int
    created_utc: float
    author: str
    matched_keywords: list[str] = field(default_factory=list)
    flair: str = ""


@dataclass
class ScoredOpportunity:
    thread: RedditThread
    priority_score: float
    smartscaling_pillar: str
    smartscaling_function: str
    suggested_angle: str
    response_type: str  # "question_answer" | "framework_share" | "data_insight" | "hot_take"
    urgency: str  # "high" | "medium" | "low"


@dataclass
class EngagementResult:
    thread_id: str
    upvotes: int
    replies: int
    trend: str  # "up" | "down" | "stable"


class RedditMonitor:
    """Monitors target subreddits for keyword matches and scores opportunities."""

    # Subreddit audience size scoring
    SUB_SIZES = {
        "sales": 15,
        "entrepreneur": 15,
        "startups": 12,
        "smallbusiness": 10,
        "consulting": 8,
    }

    def __init__(self, config_path="data/reddit_config.yaml"):
        self.config = self._load_config(config_path)
        self.primary_keywords = self.config.get("primary_keywords", [])
        self.secondary_keywords = self.config.get("secondary_keywords", [])
        self.competitor_keywords = self.config.get("competitor_keywords", [])
        self.subreddits = self.config.get("subreddits", [])
        self.keyword_mapping = self.config.get("keyword_mapping", {})

        # Reddit API client
        self.reddit = self._init_reddit()

        # Claude API client (for response drafting)
        self.anthropic_client = self._init_anthropic()

        log.info("RedditMonitor initialized")

    def _load_config(self, path: str) -> dict:
        if os.path.exists(path):
            with open(path) as f:
                return yaml.safe_load(f) or {}
        return {}

    def _init_reddit(self):
        """Initialize PRAW Reddit client, or return None for RSS fallback."""
        client_id = os.getenv("REDDIT_CLIENT_ID", "")
        client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
        username = os.getenv("REDDIT_USERNAME", "")
        password = os.getenv("REDDIT_PASSWORD", "")
        user_agent = os.getenv("REDDIT_USER_AGENT", "revheat-monitor/1.0")

        if client_id and client_secret:
            try:
                import praw
                return praw.Reddit(
                    client_id=client_id,
                    client_secret=client_secret,
                    username=username,
                    password=password,
                    user_agent=user_agent,
                )
            except ImportError:
                log.warning("praw not installed, using RSS fallback")
            except Exception as e:
                log.warning(f"Reddit API init failed: {e}, using RSS fallback")
        return None

    def _init_anthropic(self):
        """Initialize Anthropic client for response drafting."""
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if api_key:
            try:
                import anthropic
                return anthropic.Anthropic(api_key=api_key)
            except ImportError:
                log.warning("anthropic package not installed")
            except Exception as e:
                log.warning(f"Anthropic client init failed: {e}")
        return None

    def scan_subreddits(self, subreddit_list=None, keywords=None) -> list[RedditThread]:
        """Scan subreddits for keyword matches in the last 24 hours."""
        if subreddit_list is None:
            subreddit_list = [s["name"] for s in self.subreddits]
        if keywords is None:
            keywords = self.primary_keywords + self.secondary_keywords

        keywords_lower = [kw.lower() for kw in keywords]
        threads = []
        cutoff = time.time() - 86400  # 24 hours ago

        if self.reddit:
            threads = self._scan_via_api(subreddit_list, keywords_lower, cutoff)
        else:
            threads = self._scan_via_rss(subreddit_list, keywords_lower, cutoff)

        log.info(f"Scanned {len(subreddit_list)} subreddits, found {len(threads)} matching threads")
        return threads

    def _scan_via_api(self, subreddit_list, keywords_lower, cutoff) -> list[RedditThread]:
        """Scan using PRAW Reddit API."""
        threads = []
        sub_config = {s["name"]: s for s in self.subreddits}

        for sub_name in subreddit_list:
            config = sub_config.get(sub_name, {})
            limit = config.get("scan_limit", 50)
            min_score = config.get("min_score", 2)

            try:
                subreddit = self.reddit.subreddit(sub_name)
                for submission in subreddit.new(limit=limit):
                    if submission.created_utc < cutoff:
                        continue
                    if submission.score < min_score:
                        continue
                    if submission.locked or submission.over_18 or submission.removed_by_category:
                        continue

                    title_lower = submission.title.lower()
                    body_lower = (submission.selftext or "").lower()
                    matched = [
                        kw for kw in keywords_lower
                        if kw in title_lower or kw in body_lower
                    ]

                    if matched:
                        threads.append(RedditThread(
                            id=submission.id,
                            subreddit=sub_name,
                            title=submission.title,
                            body=submission.selftext or "",
                            url=f"https://reddit.com{submission.permalink}",
                            score=submission.score,
                            num_comments=submission.num_comments,
                            created_utc=submission.created_utc,
                            author=str(submission.author) if submission.author else "[deleted]",
                            matched_keywords=matched,
                            flair=submission.link_flair_text or "",
                        ))
            except Exception as e:
                log.error(f"Error scanning r/{sub_name}: {e}")

        return threads

    def _scan_via_rss(self, subreddit_list, keywords_lower, cutoff) -> list[RedditThread]:
        """Scan using Reddit RSS feeds as fallback."""
        threads = []
        try:
            import feedparser
        except ImportError:
            log.error("feedparser not installed, cannot use RSS fallback")
            return threads

        import requests

        for sub_name in subreddit_list:
            try:
                feed_url = f"https://www.reddit.com/r/{sub_name}/new/.rss"
                resp = requests.get(feed_url, headers={"User-Agent": "revheat-monitor/1.0"}, timeout=15)
                feed = feedparser.parse(resp.text)

                for entry in feed.entries:
                    title_lower = entry.title.lower()
                    summary_lower = entry.get("summary", "").lower()

                    matched = [
                        kw for kw in keywords_lower
                        if kw in title_lower or kw in summary_lower
                    ]

                    if matched:
                        threads.append(RedditThread(
                            id=entry.get("id", ""),
                            subreddit=sub_name,
                            title=entry.title,
                            body=entry.get("summary", ""),
                            url=entry.link,
                            score=0,  # Not available via RSS
                            num_comments=0,
                            created_utc=time.time(),
                            author=entry.get("author", "unknown"),
                            matched_keywords=matched,
                        ))
            except Exception as e:
                log.error(f"RSS scan error for r/{sub_name}: {e}")

        return threads

    def score_opportunity(self, thread: RedditThread) -> ScoredOpportunity:
        """Score a thread for engagement opportunity (0-100)."""
        score = 0

        # Keyword match strength (0-25)
        primary_matches = sum(
            1 for kw in self.primary_keywords
            if kw.lower() in thread.title.lower() or kw.lower() in thread.body.lower()
        )
        score += min(primary_matches * 10, 25)

        # Thread freshness (0-20)
        hours_old = (time.time() - thread.created_utc) / 3600
        if hours_old < 2:
            score += 20
        elif hours_old < 6:
            score += 15
        elif hours_old < 12:
            score += 10
        elif hours_old < 24:
            score += 5

        # Engagement level (0-20) — low comments = opportunity
        if thread.num_comments < 5:
            score += 20
        elif thread.num_comments < 15:
            score += 15
        elif thread.num_comments < 30:
            score += 10

        # Subreddit size (0-15)
        score += self.SUB_SIZES.get(thread.subreddit, 5)

        # SMARTSCALING relevance (0-20)
        pillar, function = self.map_to_smartscaling(thread)
        if pillar:
            score += 20
        elif function:
            score += 10

        urgency = "high" if score > 70 else "medium" if score > 40 else "low"

        return ScoredOpportunity(
            thread=thread,
            priority_score=score,
            smartscaling_pillar=pillar,
            smartscaling_function=function,
            suggested_angle=self._suggest_angle(thread, pillar, function),
            response_type=self._classify_response_type(thread),
            urgency=urgency,
        )

    def map_to_smartscaling(self, thread: RedditThread) -> tuple[str, str]:
        """Map thread keywords to SMARTSCALING pillar and function."""
        text = f"{thread.title} {thread.body}".lower()

        for category, mappings in self.keyword_mapping.items():
            if isinstance(mappings, dict):
                for pattern, target in mappings.items():
                    keywords = pattern.split("|")
                    if any(kw.strip().lower() in text for kw in keywords):
                        if isinstance(target, dict):
                            return target.get("pillar", ""), target.get("function", "")
                        elif isinstance(target, list) and len(target) >= 2:
                            return target[0], target[1]

        return "", ""

    def _suggest_angle(self, thread: RedditThread, pillar: str, function: str) -> str:
        """Generate a brief suggestion for how to respond."""
        if pillar and function:
            return f"Share {function} insights from SMARTSCALING {pillar} pillar. Use data from 33K companies."
        if thread.matched_keywords:
            return f"Address {', '.join(thread.matched_keywords[:2])} with practical data-backed advice."
        return "Share relevant experience and data-backed insights."

    def _classify_response_type(self, thread: RedditThread) -> str:
        """Classify the best response type based on thread content."""
        title_lower = thread.title.lower()

        if any(w in title_lower for w in ["how do", "how to", "how can", "what should", "?"]):
            return "question_answer"
        if any(w in title_lower for w in ["framework", "system", "process", "methodology"]):
            return "framework_share"
        if any(w in title_lower for w in ["data", "metric", "benchmark", "stat", "number"]):
            return "data_insight"
        return "hot_take"

    def generate_response_draft(self, opportunity: ScoredOpportunity) -> str:
        """Generate a draft Reddit response using Claude API."""
        if not self.anthropic_client:
            return self._generate_response_template(opportunity)

        thread = opportunity.thread
        prompt = f"""You are drafting a Reddit comment for Ken Lundin, founder of RevHeat, a sales consulting firm.
He has data from 33,000+ companies and the SMARTSCALING framework (11 sales functions across 4 pillars).

Thread: "{thread.title}"
Subreddit: r/{thread.subreddit}
Body: {thread.body[:500]}

SMARTSCALING angle: {opportunity.smartscaling_pillar} > {opportunity.smartscaling_function}
Response type: {opportunity.response_type}

Rules:
- 90% value, 10% subtle positioning (no hard sell)
- Include 1-2 specific data points from 33K company research
- Sound like a practitioner, not a marketer
- Keep under 300 words
- End with a question to drive discussion
- Do NOT include links to RevHeat
"""

        try:
            response = self.anthropic_client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            log.error(f"Claude API error: {e}")
            return self._generate_response_template(opportunity)

    def _generate_response_template(self, opportunity: ScoredOpportunity) -> str:
        """Fallback template when Claude API is unavailable."""
        thread = opportunity.thread
        return f"""[Draft response for: "{thread.title}"]

Angle: {opportunity.smartscaling_pillar} > {opportunity.smartscaling_function}
Type: {opportunity.response_type}

Key points to cover:
- Reference data from 33,000 companies
- Share {opportunity.smartscaling_function} insight
- End with discussion question

[Ken: Edit this draft before posting]"""

    def send_daily_brief(self, opportunities: list[ScoredOpportunity]) -> bool:
        """Send daily brief email with top opportunities."""
        if not opportunities:
            log.info("No opportunities to report")
            return True

        # Sort by priority
        sorted_opps = sorted(opportunities, key=lambda o: o.priority_score, reverse=True)
        top = sorted_opps[:5]

        # Build email
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        subject = f"Reddit Opportunities — {today}"

        body = f"Hi Ken,\n\nHere are today's top Reddit conversations where your expertise would add value:\n\n"
        body += "=" * 60 + "\n\n"

        for i, opp in enumerate(top, 1):
            t = opp.thread
            hours_old = (time.time() - t.created_utc) / 3600

            priority_label = "HIGH PRIORITY" if opp.urgency == "high" else "MEDIUM PRIORITY" if opp.urgency == "medium" else "LOW PRIORITY"
            body += f"{priority_label}\n\n"
            body += f'{i}. "{t.title}" (r/{t.subreddit})\n'
            body += f"   Score: {opp.priority_score:.0f}/100 | {t.num_comments} comments | {hours_old:.0f}h old\n"
            body += f"   Angle: {opp.smartscaling_pillar} > {opp.smartscaling_function}\n"
            body += f"   Link: {t.url}\n"

            if opp.priority_score > 50:
                draft = self.generate_response_draft(opp)
                body += f"\n   Suggested response:\n   {draft}\n"

            body += "\n" + "-" * 40 + "\n\n"

        body += f"Total time estimate: ~15 minutes for 2 responses\n\n"
        body += "Reply to this email or post directly on Reddit.\n"

        return self._send_email(subject, body)

    def _send_email(self, subject: str, body: str) -> bool:
        """Send email via SMTP."""
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_pass = os.getenv("SMTP_PASSWORD", "")
        to_email = os.getenv("NOTIFICATION_EMAIL", "kglundin@gmail.com")

        if not smtp_user or not smtp_pass:
            log.warning("SMTP credentials not configured, saving brief to file")
            brief_path = "output/daily_brief.txt"
            os.makedirs("output", exist_ok=True)
            with open(brief_path, "w") as f:
                f.write(f"Subject: {subject}\n\n{body}")
            log.info(f"Brief saved to {brief_path}")
            return True

        try:
            msg = MIMEMultipart()
            msg["From"] = smtp_user
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)

            log.info(f"Daily brief sent to {to_email}")
            return True
        except Exception as e:
            log.error(f"Failed to send email: {e}")
            return False

    def track_engagement(self, posted_responses: list[dict]) -> list[EngagementResult]:
        """Track engagement on Ken's Reddit posts."""
        results = []
        if not self.reddit:
            log.warning("Reddit API not available for engagement tracking")
            return results

        for response in posted_responses:
            try:
                comment_id = response.get("comment_id", "")
                if not comment_id:
                    continue
                comment = self.reddit.comment(comment_id)
                comment.refresh()

                prev_score = response.get("last_score", 0)
                current_score = comment.score
                if current_score > prev_score + 2:
                    trend = "up"
                elif current_score < prev_score - 2:
                    trend = "down"
                else:
                    trend = "stable"

                results.append(EngagementResult(
                    thread_id=comment_id,
                    upvotes=current_score,
                    replies=len(comment.replies),
                    trend=trend,
                ))
            except Exception as e:
                log.error(f"Error tracking engagement for {response}: {e}")

        return results

    def run(self) -> list[ScoredOpportunity]:
        """Main execution: scan, score, draft, and send brief."""
        log.info("Starting Reddit monitor run")

        # 1. Scan all configured subreddits
        threads = self.scan_subreddits()

        # 2. Score each thread
        opportunities = [self.score_opportunity(t) for t in threads]

        # 3. Send daily brief
        self.send_daily_brief(opportunities)

        log.info(f"Reddit monitor complete: {len(opportunities)} opportunities scored")
        return opportunities
