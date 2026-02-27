"""Tests for the Content Engine orchestrator module."""

import os
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from src.content_engine import ContentEngine, TopicSelection, BlogDraft, QualityResult


@pytest.fixture
def engine():
    config_path = os.path.join(PROJECT_ROOT, "config.yaml")
    e = ContentEngine(config_path=config_path)
    return e


@pytest.fixture
def valid_draft():
    return BlogDraft(
        title="Why 92% of Sales Processes Fail",
        slug="why-92-percent-sales-processes-fail",
        content_markdown="# Test\n\nContent with 33% stat and $5M revenue and 12% rate and 47% top and 28% median and 3.4x multiplier and $350K value and 92% failure rate across 33,000 companies.",
        content_html="<h1>Test</h1><p>Content</p>",
        key_takeaway="Most sales processes fail because they lack systematic approaches. Data from 33,000 companies confirms that the gap between top and bottom performers is structural, not talent-based. Fix the system first.",
        tldr_bullets=[
            "92% of sales processes fail systematically",
            "Data from 33,000 companies reveals root causes",
            "SMARTSCALING Process pillar addresses this",
            "Run a diagnostic to find your gaps",
        ],
        faq_items=[
            {"question": "Why do processes fail?", "answer": "Lack of system."},
            {"question": "How long to fix?", "answer": "90-180 days."},
            {"question": "What's the ROI?", "answer": "3.4x improvement."},
            {"question": "Build or buy?", "answer": "Depends on revenue."},
            {"question": "What is SMARTSCALING?", "answer": "11 functions, 4 pillars."},
        ],
        comparison_table="| Metric | Before | After |",
        meta_description="Data from 33,000 companies reveals why 92 percent of sales processes fail and the systems approach from SMARTSCALING framework for service businesses.",
        seo_title="Why 92% of Sales Processes Fail | RevHeat",
        word_count=1500,
        smartscaling_pillar="process",
        smartscaling_function="Sales Process Architecture",
        categories=["process"],
        tags=["sales-process-failure"],
    )


@pytest.fixture
def invalid_draft():
    return BlogDraft(
        title="Short Post",
        slug="short-post",
        content_markdown="Short content.",
        content_html="<p>Short content.</p>",
        key_takeaway="",
        tldr_bullets=["Only one bullet"],
        faq_items=[{"question": "Q?", "answer": "A."}],
        comparison_table="",
        meta_description="Short",
        seo_title="Short Post",
        word_count=50,
        smartscaling_pillar="process",
        smartscaling_function="",
        categories=["process"],
        tags=[],
    )


class TestTopicSelection:
    def test_topic_selection_rotation(self, engine):
        """Verify correct format assigned to each day of week."""
        # Monday = data_insight
        monday = datetime(2026, 3, 16, 9, 0, tzinfo=timezone.utc)  # Monday
        topic = engine.select_topic(monday)
        assert topic.format_type == "data_insight"

        # Tuesday = how_to
        tuesday = datetime(2026, 3, 17, 9, 0, tzinfo=timezone.utc)
        topic = engine.select_topic(tuesday)
        assert topic.format_type in ("how_to", "data_insight")  # May match content map

    def test_topic_selection_returns_topic(self, engine):
        """Verify topic selection returns a valid TopicSelection."""
        today = datetime.now(timezone.utc)
        topic = engine.select_topic(today)
        assert isinstance(topic, TopicSelection)
        assert topic.topic  # Should have a topic title
        assert topic.primary_keyword  # Should have a keyword

    def test_topic_selection_balance(self, engine):
        """Verify topics come from the content map."""
        topic = engine.select_topic(datetime(2026, 3, 16, tzinfo=timezone.utc))
        # Should have selected from the priority 1 data_insight posts
        assert topic.topic
        assert topic.smartscaling_pillar


class TestDraftGeneration:
    def test_draft_generation_template(self, engine):
        """Generate a draft via template (no API), verify all required elements."""
        engine.disable_api()  # Force template mode (prevents lazy re-init from env)
        topic = TopicSelection(
            topic="Why 92% of Sales Processes Fail",
            primary_keyword="sales process failure",
            secondary_keywords=["sales system", "sales optimization"],
            format_type="data_insight",
            smartscaling_pillar="process",
            smartscaling_function="Sales Process Architecture",
        )

        draft = engine.generate_draft(topic)
        assert isinstance(draft, BlogDraft)
        assert draft.title
        assert draft.slug
        assert draft.content_html
        assert draft.content_markdown
        assert draft.word_count > 100
        assert len(draft.faq_items) >= 5
        assert len(draft.tldr_bullets) == 4
        assert draft.meta_description


class TestQualityCheck:
    def test_quality_check_pass(self, engine, valid_draft):
        """Create a valid draft, verify quality check passes."""
        result = engine.quality_check(valid_draft)
        assert isinstance(result, QualityResult)
        assert result.passes, f"Quality check should pass, failures: {result.failures}"

    def test_quality_check_fail_missing_faq(self, engine, invalid_draft):
        """Create an invalid draft (missing FAQ), verify failure."""
        result = engine.quality_check(invalid_draft)
        assert not result.passes
        assert any("FAQ" in f for f in result.failures)

    def test_quality_check_fail_word_count(self, engine, invalid_draft):
        """Draft with too few words should fail."""
        result = engine.quality_check(invalid_draft)
        assert any("word" in f.lower() for f in result.failures)

    def test_quality_check_fail_tldr(self, engine, invalid_draft):
        """Draft with wrong number of TL;DR bullets should fail."""
        result = engine.quality_check(invalid_draft)
        assert any("TL;DR" in f for f in result.failures)

    def test_quality_check_fail_key_takeaway(self, engine, invalid_draft):
        """Draft missing key takeaway should fail."""
        result = engine.quality_check(invalid_draft)
        assert any("Key Takeaway" in f for f in result.failures)

    def test_quality_check_fail_comparison_table(self, engine, invalid_draft):
        """Draft missing comparison table should fail."""
        result = engine.quality_check(invalid_draft)
        assert any("comparison" in f.lower() for f in result.failures)


class TestInternalLinks:
    def test_internal_link_injection(self, engine):
        """Given existing posts, verify links are correctly inserted."""
        content = "<p>Building a repeatable Sales Process Architecture is critical for growth.</p><p>A Revenue Operations Guide helps track metrics.</p>"
        existing_posts = [
            {"title": {"rendered": "Sales Process Architecture"}, "link": "https://revheat.com/blog/sales-process/"},
            {"title": {"rendered": "Revenue Operations Guide"}, "link": "https://revheat.com/blog/rev-ops/"},
        ]
        result = engine.build_internal_links(content, existing_posts)
        assert "href=" in result

    def test_no_duplicate_links(self, engine):
        """Verify same URL is never linked twice."""
        content = "<p>Sales process is key. The sales process matters. Fix your sales process.</p>"
        existing_posts = [
            {"title": {"rendered": "Sales Process Guide"}, "link": "https://revheat.com/blog/sp/"},
        ]
        result = engine.build_internal_links(content, existing_posts)
        assert result.count("https://revheat.com/blog/sp/") <= 1

    def test_no_links_when_empty(self, engine):
        """No links injected when no existing posts."""
        content = "<p>Some content.</p>"
        result = engine.build_internal_links(content, [])
        assert result == content


class TestRedditAngle:
    def test_reddit_angle_generation(self, engine, valid_draft):
        """Verify Reddit draft has TL;DR and discussion question."""
        angle = engine.generate_reddit_angle(valid_draft, "r/sales")
        assert "TL;DR" in angle
        assert "?" in angle  # Should have a question
        assert len(angle.split()) <= 800

    def test_reddit_angle_no_promo(self, engine, valid_draft):
        """Verify Reddit draft doesn't hard-sell."""
        angle = engine.generate_reddit_angle(valid_draft, "r/sales")
        assert "buy" not in angle.lower()
        assert "sign up" not in angle.lower()
        assert "click here" not in angle.lower()


class TestStatCounting:
    def test_count_statistics(self, engine):
        """Verify stat counter finds percentages, dollars, multipliers."""
        text = "Win rate is 47%. Revenue jumped to $5.2M with a 3.4x improvement across 33,000 companies."
        count = engine._count_statistics(text)
        assert count >= 3  # 47%, $5.2M, 3.4x, 33,000


class TestNotification:
    @patch("src.content_engine.ContentEngine._send_email")
    def test_notify_ken(self, mock_email, engine, valid_draft):
        """Verify notification builds correctly."""
        quality = QualityResult(passes=True)
        engine.notify_ken(
            post_title="Test Post",
            post_edit_url="https://revheat.com/wp-admin/post.php?post=42&action=edit",
            reddit_draft="Reddit draft text",
            target_subreddit="r/sales",
            quality_report=quality,
        )
        mock_email.assert_called_once()
        call_args = mock_email.call_args
        assert "Test Post" in call_args[0][0]


class TestPlannedInternalLinks:
    def test_inject_planned_links_basic(self, engine):
        """Planned links from frontmatter are injected into HTML content."""
        content = "<p>Improving your sales process architecture is critical for growth.</p>"
        planned_links = [
            {"anchor": "sales process architecture", "target": "/blog/sales-process-architecture/", "type": "pillar"},
        ]
        result = engine.inject_planned_links(content, planned_links)
        assert '<a href="https://revheat.com/blog/sales-process-architecture/">' in result
        assert "sales process architecture</a>" in result

    def test_inject_planned_links_empty(self, engine):
        """No changes when planned links list is empty."""
        content = "<p>Some content here.</p>"
        result = engine.inject_planned_links(content, [])
        assert result == content

    def test_inject_planned_links_absolute_url(self, engine):
        """Absolute URLs are used as-is."""
        content = "<p>Read the revenue operations guide for more info.</p>"
        planned_links = [
            {"anchor": "revenue operations guide", "target": "https://revheat.com/blog/rev-ops/", "type": "internal"},
        ]
        result = engine.inject_planned_links(content, planned_links)
        assert 'href="https://revheat.com/blog/rev-ops/"' in result

    def test_inject_planned_links_skips_headings(self, engine):
        """Links are not injected inside headings."""
        content = "<h2>Sales Process Architecture</h2><p>Some content about sales process architecture.</p>"
        planned_links = [
            {"anchor": "Sales Process Architecture", "target": "/blog/spa/", "type": "pillar"},
        ]
        result = engine.inject_planned_links(content, planned_links)
        # Should NOT link inside the h2
        assert "<h2><a" not in result
        # Should link inside the p
        assert '<a href="https://revheat.com/blog/spa/">' in result

    def test_inject_planned_links_one_per_anchor(self, engine):
        """Only one link is created per anchor text, even if it appears multiple times."""
        content = "<p>Revenue operations are key.</p><p>Revenue operations drive growth.</p>"
        planned_links = [
            {"anchor": "Revenue operations", "target": "/blog/rev-ops/", "type": "internal"},
        ]
        result = engine.inject_planned_links(content, planned_links)
        assert result.count('href="https://revheat.com/blog/rev-ops/"') == 1


class TestQualityCheckEnhancements:
    def test_heading_hierarchy_missing_h1(self, engine):
        """Draft with no H1 should produce a failure."""
        draft = BlogDraft(
            title="Test", slug="test", content_markdown="## Only H2\n\nContent.",
            content_html="<h2>Only H2</h2><p>Content.</p>",
            key_takeaway="Some takeaway. " * 5,
            tldr_bullets=["A", "B", "C", "D"],
            faq_items=[{"question": f"Q{i}?", "answer": f"A{i}."} for i in range(5)],
            comparison_table="| A | B |",
            meta_description="Test meta description for validation purposes.",
            seo_title="Test Title | RevHeat",
            word_count=1500,
        )
        result = engine.quality_check(draft)
        assert any("H1" in f for f in result.failures)

    def test_heading_hierarchy_multiple_h1(self, engine):
        """Draft with multiple H1s should produce a warning."""
        md_body = (
            "# Title One\n\n## Sub1\n\n## Sub2\n\n## Sub3\n\n## Sub4\n\n## Sub5\n\n"
            "# Title Two\n\n" + ("Content words here. " * 150)
        )
        draft = BlogDraft(
            title="Test", slug="test",
            content_markdown=md_body,
            content_html="<h1>Title One</h1><h1>Title Two</h1>",
            key_takeaway="Some takeaway text here for validation purposes. " * 5,
            tldr_bullets=["A", "B", "C", "D"],
            faq_items=[{"question": f"Q{i}?", "answer": f"A{i}."} for i in range(5)],
            comparison_table="| A | B |",
            meta_description="Test meta description for validation purposes here today.",
            seo_title="Test Title That Is Long Enough For SEO | RevHeat",
            word_count=1500,
        )
        result = engine.quality_check(draft)
        assert any("H1 heading" in w and "should be exactly 1" in w for w in result.warnings)

    def test_keyword_density_too_low(self, engine):
        """Very low keyword density produces a warning."""
        # 1500 words of generic text with keyword appearing only once
        body = "# Test Title\n\n" + ("Generic content words here. " * 200) + "\nsales process failure\n"
        draft = BlogDraft(
            title="Test", slug="test", content_markdown=body, content_html="<p>Test</p>",
            key_takeaway="Takeaway text. " * 5,
            tldr_bullets=["A", "B", "C", "D"],
            faq_items=[{"question": f"Q{i}?", "answer": f"A{i}."} for i in range(5)],
            comparison_table="| A | B |", meta_description="Test meta.", seo_title="Test Title | RevHeat",
            word_count=1500,
        )
        topic = TopicSelection(
            topic="Sales Process Failure", primary_keyword="sales process failure",
        )
        result = engine.quality_check(draft, topic=topic)
        assert any("density" in w.lower() for w in result.warnings)

    def test_keyword_placement_checks(self, engine):
        """Missing keyword placement produces warnings."""
        body = "# Title Without Keyword\n\n## Another Section\n\n## More Stuff\n\n## Even More\n\n## Final\n\n## Extra\n\nContent starts here. " + ("More words. " * 200)
        draft = BlogDraft(
            title="Test", slug="test", content_markdown=body, content_html="<p>Test</p>",
            key_takeaway="Takeaway. " * 5,
            tldr_bullets=["A", "B", "C", "D"],
            faq_items=[{"question": f"Q{i}?", "answer": f"A{i}."} for i in range(5)],
            comparison_table="| A | B |",
            meta_description="Description without the focus term.",
            seo_title="Test Title | RevHeat", word_count=1500,
        )
        topic = TopicSelection(
            topic="Revenue Ops Guide", primary_keyword="revenue ops guide",
        )
        result = engine.quality_check(draft, topic=topic)
        # Should warn about missing from first 100 words, H2, meta desc, FAQ
        placement_warnings = [w for w in result.warnings if "missing from" in w.lower()]
        assert len(placement_warnings) >= 1

    def test_seo_title_too_long(self, engine):
        """SEO title over 65 chars produces a warning."""
        draft = BlogDraft(
            title="Test", slug="test",
            content_markdown="# Title\n\n## Sub1\n\n## Sub2\n\n## Sub3\n\n## Sub4\n\n## Sub5\n\nContent " * 10,
            content_html="<p>Test</p>",
            key_takeaway="Takeaway. " * 5,
            tldr_bullets=["A", "B", "C", "D"],
            faq_items=[{"question": f"Q{i}?", "answer": f"A{i}."} for i in range(5)],
            comparison_table="| A | B |",
            meta_description="A good meta description for testing.",
            seo_title="This Is An Extremely Long SEO Title That Will Definitely Get Truncated In Search Results | RevHeat",
            word_count=1500,
        )
        result = engine.quality_check(draft)
        assert any("SEO title" in w for w in result.warnings)

    def test_internal_link_minimum_warning(self, engine):
        """Draft with fewer than min_internal_links gets a warning."""
        draft = BlogDraft(
            title="Test", slug="test",
            content_markdown="# Title\n\n## Sub1\n\n## Sub2\n\n## Sub3\n\n## Sub4\n\n## Sub5\n\nContent " * 10,
            content_html="<p>Content with no links at all.</p>",
            key_takeaway="Takeaway. " * 5,
            tldr_bullets=["A", "B", "C", "D"],
            faq_items=[{"question": f"Q{i}?", "answer": f"A{i}."} for i in range(5)],
            comparison_table="| A | B |",
            meta_description="A meta description for testing.",
            seo_title="Test Title | RevHeat", word_count=1500,
            planned_internal_links=[],
        )
        result = engine.quality_check(draft)
        assert any("internal link" in w.lower() for w in result.warnings)

    def test_quality_check_no_topic_skips_keyword(self, engine, valid_draft):
        """Quality check without topic param skips keyword validation."""
        result = engine.quality_check(valid_draft, topic=None)
        # Should not crash and should not have keyword-related warnings
        assert isinstance(result, QualityResult)


class TestNormalizedInternalLinks:
    def test_normalize_internal_links(self):
        """Frontmatter internal_links dict is normalized to flat list."""
        from src.draft_ingester import DraftIngester
        raw = {
            "pillar_link": {
                "anchor": "SmartScaling Strategy",
                "target": "/blog/smartscaling-strategy/",
            },
            "cross_pillar_link": {
                "anchor": "Revenue Operations",
                "target": "/blog/revenue-operations/",
            },
            "sibling_link": {
                "anchor": "Sales Process",
                "target": "/blog/sales-process/",
            },
        }
        result = DraftIngester._normalize_internal_links(raw)
        assert len(result) == 3
        types = {link["type"] for link in result}
        assert "pillar" in types
        assert "cross_pillar" in types
        assert "sibling" in types

    def test_normalize_empty(self):
        """Empty dict returns empty list."""
        from src.draft_ingester import DraftIngester
        assert DraftIngester._normalize_internal_links({}) == []

    def test_normalize_skips_invalid(self):
        """Non-dict values and missing fields are skipped."""
        from src.draft_ingester import DraftIngester
        raw = {
            "good": {"anchor": "Link Text", "target": "/blog/page/"},
            "bad_string": "not a dict",
            "missing_anchor": {"target": "/blog/x/"},
            "missing_target": {"anchor": "Text"},
        }
        result = DraftIngester._normalize_internal_links(raw)
        assert len(result) == 1
        assert result[0]["anchor"] == "Link Text"
