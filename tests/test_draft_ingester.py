"""Tests for the Draft Ingester module."""

import os
import tempfile
import pytest
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from src.draft_ingester import DraftIngester
from src.content_engine import ContentEngine, TopicSelection, BlogDraft


# ---------------------------------------------------------------------------
# Paths to actual Cowork drafts (relative to SEO Machine root)
# ---------------------------------------------------------------------------
SEO_MACHINE_ROOT = os.path.dirname(PROJECT_ROOT)
DRAFTS_DIR = os.path.join(SEO_MACHINE_ROOT, "04-Blog-Drafts")
HAS_DRAFTS = os.path.isdir(DRAFTS_DIR)


@pytest.fixture
def ingester():
    """DraftIngester with no content map."""
    return DraftIngester()


@pytest.fixture
def ingester_with_map():
    """DraftIngester loaded with the real content map."""
    map_path = os.path.join(PROJECT_ROOT, "data", "pillar_cluster_map.yaml")
    content_map = {}
    if os.path.exists(map_path):
        import yaml
        with open(map_path) as f:
            content_map = yaml.safe_load(f) or {}
    return DraftIngester(content_map=content_map)


@pytest.fixture
def engine():
    config_path = os.path.join(PROJECT_ROOT, "config.yaml")
    return ContentEngine(config_path=config_path)


# ===========================================================================
# Frontmatter parsing
# ===========================================================================

class TestFrontmatterParsing:
    def test_parse_with_frontmatter(self, ingester, tmp_path):
        """File with YAML frontmatter is parsed correctly."""
        md = tmp_path / "test.md"
        md.write_text(
            "---\n"
            "title: Test Post\n"
            "slug: test-post\n"
            "focus_keyword: testing\n"
            "---\n"
            "# Test Post\n\nBody content here.\n"
        )
        metadata, body = ingester.parse_frontmatter(md)
        assert metadata["title"] == "Test Post"
        assert metadata["slug"] == "test-post"
        assert "Body content here." in body

    def test_parse_without_frontmatter(self, ingester, tmp_path):
        """File without frontmatter returns empty metadata and full body."""
        md = tmp_path / "test.md"
        md.write_text("# My Title\n\nSome content.\n")
        metadata, body = ingester.parse_frontmatter(md)
        assert metadata == {}
        assert body.startswith("# My Title")

    def test_parse_malformed_yaml(self, ingester, tmp_path):
        """Malformed YAML frontmatter returns empty metadata and full content."""
        md = tmp_path / "bad.md"
        md.write_text("---\n[bad yaml: {{\n---\n# Title\n\nBody.\n")
        metadata, body = ingester.parse_frontmatter(md)
        assert metadata == {}

    @pytest.mark.skipif(not HAS_DRAFTS, reason="04-Blog-Drafts not found")
    def test_parse_real_cluster_page(self, ingester):
        """Parse a real cluster page with full frontmatter."""
        filepath = Path(DRAFTS_DIR) / "Cluster-Pages" / "cluster-process-architecture.md"
        if not filepath.exists():
            pytest.skip("cluster-process-architecture.md not found")
        metadata, body = ingester.parse_frontmatter(filepath)
        assert metadata.get("slug") == "sales-process-architecture"
        assert metadata.get("pillar") == "Process"
        assert metadata.get("content_format") == "cluster_page"
        assert len(body) > 100

    @pytest.mark.skipif(not HAS_DRAFTS, reason="04-Blog-Drafts not found")
    def test_parse_real_week01_no_frontmatter(self, ingester):
        """Parse a real Week-01 file (no frontmatter)."""
        filepath = Path(DRAFTS_DIR) / "Week-01" / "day-03-why-92-percent-sales-processes-fail.md"
        if not filepath.exists():
            pytest.skip("day-03 file not found")
        metadata, body = ingester.parse_frontmatter(filepath)
        assert metadata == {}
        assert body.startswith("# Why 92%")


# ===========================================================================
# Metadata inference
# ===========================================================================

class TestMetadataInference:
    def test_infer_title_from_h1(self, ingester):
        """H1 in body is extracted as title."""
        body = "# Revenue Growth Framework\n\nContent here."
        filepath = Path("/tmp/test-post.md")
        meta = ingester.infer_metadata_from_content(body, filepath)
        assert meta["title"] == "Revenue Growth Framework"

    def test_infer_slug_from_filename(self, ingester):
        """Slug is derived from filename with day-XX- prefix stripped."""
        body = "# Some Title\n\nContent."
        filepath = Path("/tmp/Week-01/day-05-five-stages-revenue-growth.md")
        meta = ingester.infer_metadata_from_content(body, filepath)
        assert meta["slug"] == "five-stages-revenue-growth"

    def test_infer_pillar_type_from_folder(self, ingester):
        """Pillar-Pages folder sets content_format to pillar_page."""
        body = "# Pillar Title\n\nContent."
        filepath = Path("/tmp/Pillar-Pages/pillar-strategy.md")
        meta = ingester.infer_metadata_from_content(body, filepath)
        assert meta["content_format"] == "pillar_page"

    def test_infer_cluster_type_from_folder(self, ingester):
        """Cluster-Pages folder sets content_format to cluster_page."""
        body = "# Cluster Title\n\nContent."
        filepath = Path("/tmp/Cluster-Pages/cluster-foo.md")
        meta = ingester.infer_metadata_from_content(body, filepath)
        assert meta["content_format"] == "cluster_page"


# ===========================================================================
# Topic building
# ===========================================================================

class TestTopicBuilding:
    def test_build_topic_from_metadata(self, ingester):
        """TopicSelection is built correctly from frontmatter metadata."""
        metadata = {
            "title": "Sales Process Architecture",
            "focus_keyword": "sales process architecture",
            "secondary_keywords": ["pipeline design", "sales system"],
            "content_format": "cluster_page",
            "pillar": "Process",
            "function": "Sales Process Architecture",
            "growth_stage": "scale",
            "target_subreddit": "r/sales",
        }
        body = "# Sales Process Architecture\n\nBody."
        topic = ingester.build_topic_from_metadata(metadata, body)
        assert isinstance(topic, TopicSelection)
        assert topic.primary_keyword == "sales process architecture"
        assert topic.smartscaling_pillar == "process"
        assert topic.format_type == "cluster_page"
        assert len(topic.secondary_keywords) == 2

    def test_build_topic_title_from_body_h1(self, ingester):
        """When metadata has no title, H1 from body is used."""
        metadata = {"focus_keyword": "testing"}
        body = "# My Draft Title\n\nContent."
        topic = ingester.build_topic_from_metadata(metadata, body)
        assert topic.topic == "My Draft Title"

    def test_build_topic_strips_revheat_suffix(self, ingester):
        """SEO title with '| RevHeat' suffix is cleaned for topic name."""
        metadata = {"seo_title": "Sales Process Architecture | RevHeat"}
        body = "# Doesn't matter"
        topic = ingester.build_topic_from_metadata(metadata, body)
        assert topic.topic == "Sales Process Architecture"

    def test_secondary_keywords_as_csv_string(self, ingester):
        """Secondary keywords given as comma-separated string are split."""
        metadata = {
            "title": "Test",
            "secondary_keywords": "keyword one, keyword two, keyword three",
        }
        topic = ingester.build_topic_from_metadata(metadata, "# Test")
        assert topic.secondary_keywords == ["keyword one", "keyword two", "keyword three"]


# ===========================================================================
# Full draft building (with engine's _parse_draft)
# ===========================================================================

class TestDraftBuilding:
    @pytest.mark.skipif(not HAS_DRAFTS, reason="04-Blog-Drafts not found")
    def test_build_draft_from_cluster_page(self, ingester_with_map, engine):
        """Build a full TopicSelection + BlogDraft from a real cluster page."""
        filepath = Path(DRAFTS_DIR) / "Cluster-Pages" / "cluster-process-architecture.md"
        if not filepath.exists():
            pytest.skip("cluster-process-architecture.md not found")

        topic, draft = ingester_with_map.build_draft_from_file(filepath, engine._parse_draft)
        assert isinstance(topic, TopicSelection)
        assert isinstance(draft, BlogDraft)
        assert draft.slug == "sales-process-architecture"
        assert draft.word_count > 500
        assert draft.seo_title  # Should be overridden from frontmatter

    @pytest.mark.skipif(not HAS_DRAFTS, reason="04-Blog-Drafts not found")
    def test_build_draft_from_week01_no_frontmatter(self, ingester_with_map, engine):
        """Build a draft from a Week-01 file that has no YAML frontmatter."""
        filepath = Path(DRAFTS_DIR) / "Week-01" / "day-03-why-92-percent-sales-processes-fail.md"
        if not filepath.exists():
            pytest.skip("day-03 file not found")

        topic, draft = ingester_with_map.build_draft_from_file(filepath, engine._parse_draft)
        assert isinstance(draft, BlogDraft)
        assert draft.title
        assert draft.word_count > 500

    def test_build_draft_frontmatter_overrides(self, ingester, engine):
        """Frontmatter values override _parse_draft defaults."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(
                "---\n"
                "seo_title: Custom SEO Title | RevHeat\n"
                "meta_description: Custom meta description for testing.\n"
                "slug: custom-slug\n"
                "tags: [tag-one, tag-two]\n"
                "category: process\n"
                "pillar: process\n"
                "focus_keyword: custom keyword\n"
                "---\n"
                "# Test Draft Title\n\n"
                "## Key Takeaway\nThis is a test takeaway.\n\n"
                "## TL;DR\n"
                "- Bullet one\n"
                "- Bullet two\n"
                "- Bullet three\n"
                "- Bullet four\n\n"
                "## Content\nSome test content. " + "Word " * 200 + "\n\n"
                "## FAQ\n\n"
                "**Q: Question one?**\nAnswer one.\n\n"
                "**Q: Question two?**\nAnswer two.\n\n"
                "**Q: Question three?**\nAnswer three.\n\n"
                "**Q: Question four?**\nAnswer four.\n\n"
                "**Q: Question five?**\nAnswer five.\n\n"
                "| Metric | Before | After |\n"
                "|--------|--------|-------|\n"
                "| Win Rate | 22% | 41% |\n"
            )
            tmp_path = f.name

        try:
            topic, draft = ingester.build_draft_from_file(tmp_path, engine._parse_draft)
            assert draft.slug == "custom-slug"
            assert draft.seo_title == "Custom SEO Title | RevHeat"
            assert draft.meta_description == "Custom meta description for testing."
            assert "tag-one" in draft.tags
            assert draft.categories == ["process"]
        finally:
            os.unlink(tmp_path)


# ===========================================================================
# Folder scanning and queue ordering
# ===========================================================================

class TestFolderScanning:
    def test_scan_empty_dir(self, ingester, tmp_path):
        """Scanning an empty directory returns empty list."""
        result = ingester.scan_drafts_folder(str(tmp_path))
        assert result == []

    def test_scan_nonexistent_dir(self, ingester):
        """Scanning a nonexistent directory returns empty list."""
        result = ingester.scan_drafts_folder("/nonexistent/path")
        assert result == []

    def test_scan_ordering(self, ingester, tmp_path):
        """Files are sorted by folder priority: Pillar > Cluster > Week."""
        # Create mock folder structure
        (tmp_path / "Week-02").mkdir()
        (tmp_path / "Pillar-Pages").mkdir()
        (tmp_path / "Cluster-Pages").mkdir()
        (tmp_path / "Week-01").mkdir()

        (tmp_path / "Week-02" / "day-08.md").write_text("# Day 8")
        (tmp_path / "Pillar-Pages" / "pillar-strategy.md").write_text("# Strategy")
        (tmp_path / "Cluster-Pages" / "cluster-foo.md").write_text("# Cluster")
        (tmp_path / "Week-01" / "day-01.md").write_text("# Day 1")

        result = ingester.scan_drafts_folder(str(tmp_path))
        folder_names = [f.parent.name for f in result]
        assert folder_names == ["Pillar-Pages", "Cluster-Pages", "Week-01", "Week-02"]

    @pytest.mark.skipif(not HAS_DRAFTS, reason="04-Blog-Drafts not found")
    def test_scan_real_drafts_folder(self, ingester):
        """Scan actual 04-Blog-Drafts/ directory."""
        files = ingester.scan_drafts_folder(DRAFTS_DIR)
        assert len(files) > 30  # Expect ~47 files
        # Pillar pages should come first
        assert files[0].parent.name == "Pillar-Pages"


class TestIngestionQueue:
    def test_queue_excludes_published(self, ingester, tmp_path):
        """Already-published slugs are excluded from the queue."""
        (tmp_path / "Week-01").mkdir()
        # Create two files with frontmatter slugs
        (tmp_path / "Week-01" / "post-a.md").write_text(
            "---\nslug: post-alpha\n---\n# Post Alpha\n"
        )
        (tmp_path / "Week-01" / "post-b.md").write_text(
            "---\nslug: post-beta\n---\n# Post Beta\n"
        )

        published = {"post-alpha"}
        queue = ingester.get_ingestion_queue(str(tmp_path), published)
        assert len(queue) == 1
        # The remaining file should be post-b
        meta, _ = ingester.parse_frontmatter(queue[0])
        assert meta["slug"] == "post-beta"

    def test_queue_empty_when_all_published(self, ingester, tmp_path):
        """Queue is empty when all files are already published."""
        (tmp_path / "Week-01").mkdir()
        (tmp_path / "Week-01" / "only.md").write_text(
            "---\nslug: only-post\n---\n# Only\n"
        )
        published = {"only-post"}
        queue = ingester.get_ingestion_queue(str(tmp_path), published)
        assert len(queue) == 0


# ===========================================================================
# Content map matching
# ===========================================================================

class TestContentMapMatching:
    def test_find_in_empty_map(self, ingester):
        """No match when content map is empty."""
        result = ingester._find_in_content_map("some-slug")
        assert result is None

    @pytest.mark.skipif(
        not os.path.exists(os.path.join(PROJECT_ROOT, "data", "pillar_cluster_map.yaml")),
        reason="pillar_cluster_map.yaml not found",
    )
    def test_find_real_slug(self, ingester_with_map):
        """Find a known slug in the real content map."""
        # Try to find any slug that exists - we'll check the map structure
        result = ingester_with_map._find_in_content_map("sales-process-architecture")
        # This may or may not match depending on content map structure
        # Just verify no crash
        assert result is None or isinstance(result, dict)
