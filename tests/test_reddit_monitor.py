"""Tests for the Reddit Monitor module."""

import os
import time
import pytest
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "data", "reddit_config.yaml")

from src.reddit_monitor import RedditMonitor, RedditThread, ScoredOpportunity


@pytest.fixture
def monitor():
    m = RedditMonitor(config_path=CONFIG_PATH)
    return m


@pytest.fixture
def sample_thread():
    return RedditThread(
        id="abc123",
        subreddit="sales",
        title="How do I fix my broken sales process?",
        body="We're a $5M service company and our sales process is a mess. Win rate is terrible.",
        url="https://reddit.com/r/sales/comments/abc123/",
        score=15,
        num_comments=3,
        created_utc=time.time() - 3600,  # 1 hour old
        author="frustrated_founder",
        matched_keywords=["sales process"],
        flair="Advice",
    )


@pytest.fixture
def low_score_thread():
    return RedditThread(
        id="xyz789",
        subreddit="consulting",
        title="What's a good CRM for small teams?",
        body="Looking for CRM recommendations.",
        url="https://reddit.com/r/consulting/comments/xyz789/",
        score=2,
        num_comments=25,
        created_utc=time.time() - 72000,  # 20 hours old
        author="crm_seeker",
        matched_keywords=["CRM"],
    )


class TestSubredditScan:
    @patch.object(RedditMonitor, "_scan_via_rss")
    def test_subreddit_scan(self, mock_rss, monitor, sample_thread):
        """Scan r/sales for keyword matches, verify threads returned."""
        mock_rss.return_value = [sample_thread]
        monitor.reddit = None  # Force RSS fallback

        threads = monitor.scan_subreddits(["sales"], ["sales process"])
        assert len(threads) == 1
        assert threads[0].subreddit == "sales"
        assert "sales process" in threads[0].matched_keywords


class TestOpportunityScoring:
    def test_opportunity_scoring_high(self, monitor, sample_thread):
        """Score a high-quality thread, verify high score."""
        opp = monitor.score_opportunity(sample_thread)
        assert isinstance(opp, ScoredOpportunity)
        assert opp.priority_score > 50
        assert opp.urgency in ("high", "medium")
        assert opp.response_type == "question_answer"

    def test_opportunity_scoring_low(self, monitor, low_score_thread):
        """Score a low-quality thread, verify lower score."""
        opp = monitor.score_opportunity(low_score_thread)
        assert opp.priority_score < 70
        # Old thread with many comments should score lower

    def test_freshness_scoring(self, monitor):
        """Verify fresher threads score higher."""
        fresh = RedditThread(
            id="1", subreddit="sales", title="sales process help",
            body="need help", url="", score=5, num_comments=2,
            created_utc=time.time() - 1800,  # 30 min old
            author="test",
            matched_keywords=["sales process"],
        )
        old = RedditThread(
            id="2", subreddit="sales", title="sales process help",
            body="need help", url="", score=5, num_comments=2,
            created_utc=time.time() - 82800,  # 23 hours old
            author="test",
            matched_keywords=["sales process"],
        )
        fresh_score = monitor.score_opportunity(fresh).priority_score
        old_score = monitor.score_opportunity(old).priority_score
        assert fresh_score > old_score


class TestSMARTSCALINGMapping:
    def test_smartscaling_mapping_process(self, monitor, sample_thread):
        """Map 'sales process' keywords to correct SMARTSCALING pillar/function."""
        pillar, function = monitor.map_to_smartscaling(sample_thread)
        assert pillar == "Process"
        assert function == "Sales Process Architecture"

    def test_smartscaling_mapping_people(self, monitor):
        """Map hiring keywords to People pillar."""
        thread = RedditThread(
            id="1", subreddit="sales",
            title="How do I hire my first salesperson?",
            body="We need to make our first sales hire.",
            url="", score=5, num_comments=2,
            created_utc=time.time(), author="test",
            matched_keywords=["sales hire"],
        )
        pillar, function = monitor.map_to_smartscaling(thread)
        assert pillar == "People"
        assert "Talent" in function or "Assessment" in function

    def test_smartscaling_mapping_compensation(self, monitor):
        """Map compensation keywords to Performance pillar."""
        thread = RedditThread(
            id="1", subreddit="sales",
            title="What's a fair commission structure?",
            body="Trying to set up a good compensation plan.",
            url="", score=5, num_comments=2,
            created_utc=time.time(), author="test",
            matched_keywords=["compensation"],
        )
        pillar, function = monitor.map_to_smartscaling(thread)
        assert pillar == "Performance"

    def test_no_match_returns_empty(self, monitor):
        """Thread with no SMARTSCALING keywords returns empty."""
        thread = RedditThread(
            id="1", subreddit="sales",
            title="What laptop do you use?",
            body="Looking for laptop recommendations for traveling salespeople.",
            url="", score=5, num_comments=2,
            created_utc=time.time(), author="test",
            matched_keywords=[],
        )
        pillar, function = monitor.map_to_smartscaling(thread)
        assert pillar == ""
        assert function == ""


class TestResponseDraft:
    def test_response_draft_generation_fallback(self, monitor, sample_thread):
        """Generate a draft response via template (no API), verify output."""
        monitor.anthropic_client = None
        opp = monitor.score_opportunity(sample_thread)
        draft = monitor.generate_response_draft(opp)
        assert len(draft) > 50
        assert "draft" in draft.lower() or "angle" in draft.lower()
        assert "33,000" in draft or "SMARTSCALING" in draft

    @patch("src.reddit_monitor.RedditMonitor._init_anthropic")
    def test_response_type_classification(self, mock_init, monitor):
        """Verify response types are classified correctly."""
        question_thread = RedditThread(
            id="1", subreddit="sales", title="How do I improve win rates?",
            body="", url="", score=5, num_comments=2,
            created_utc=time.time(), author="test", matched_keywords=[],
        )
        assert monitor._classify_response_type(question_thread) == "question_answer"

        framework_thread = RedditThread(
            id="2", subreddit="sales", title="Best sales methodology for services",
            body="", url="", score=5, num_comments=2,
            created_utc=time.time(), author="test", matched_keywords=[],
        )
        assert monitor._classify_response_type(framework_thread) == "framework_share"

        data_thread = RedditThread(
            id="3", subreddit="sales", title="Sales benchmark data for 2026",
            body="", url="", score=5, num_comments=2,
            created_utc=time.time(), author="test", matched_keywords=[],
        )
        assert monitor._classify_response_type(data_thread) == "data_insight"


class TestDailyBrief:
    def test_daily_brief_format(self, monitor, sample_thread, tmp_path):
        """Generate brief, verify output."""
        monitor.anthropic_client = None

        # Override output dir
        with patch.dict(os.environ, {"SMTP_USER": "", "SMTP_PASSWORD": ""}):
            opp = monitor.score_opportunity(sample_thread)
            with patch("src.reddit_monitor.os.makedirs"):
                with patch("builtins.open", create=True) as mock_open:
                    mock_open.return_value.__enter__ = lambda s: s
                    mock_open.return_value.__exit__ = MagicMock(return_value=False)
                    mock_open.return_value.write = MagicMock()
                    result = monitor.send_daily_brief([opp])
                    assert result is True


class TestRSSFallback:
    @patch("requests.get")
    def test_rss_fallback(self, mock_get, monitor):
        """Test RSS scanning when API is unavailable."""
        monitor.reddit = None

        # Mock RSS feed response
        mock_resp = MagicMock()
        mock_resp.text = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
            <entry>
                <title>Help with sales process design</title>
                <id>t3_test123</id>
                <link href="https://reddit.com/r/sales/comments/test123/"/>
                <summary>We need to redesign our sales process for our service company.</summary>
                <author><name>testuser</name></author>
            </entry>
        </feed>"""
        mock_get.return_value = mock_resp

        threads = monitor.scan_subreddits(["sales"], ["sales process"])
        assert len(threads) >= 1


class TestKeywordMatching:
    def test_primary_keyword_matching(self, monitor):
        """Verify primary keywords match correctly."""
        thread = RedditThread(
            id="1", subreddit="sales",
            title="Building a sales system from scratch",
            body="Need help with B2B sales team structure.",
            url="", score=5, num_comments=2,
            created_utc=time.time(), author="test",
            matched_keywords=["sales system", "sales team"],
        )
        opp = monitor.score_opportunity(thread)
        # Two primary keyword matches should contribute to score
        assert opp.priority_score > 30

    def test_competitor_keyword_detection(self, monitor):
        """Verify competitor keywords are in the config."""
        assert "Sandler" in monitor.competitor_keywords
        assert "MEDDIC" in monitor.competitor_keywords
        assert "Challenger Sale" in monitor.competitor_keywords
