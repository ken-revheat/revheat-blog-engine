"""Tests for the WordPress Publisher module using mocked HTTP responses."""

import json
import pytest
import responses
from unittest.mock import patch

from src.wp_publisher import WordPressPublisher, AuthenticationError


BASE_URL = "https://test.revheat.com"
API_BASE = f"{BASE_URL}/wp-json/wp/v2"


@responses.activate
def _make_publisher():
    """Helper: create a publisher with mocked connection verification."""
    responses.add(
        responses.GET,
        f"{API_BASE}/",
        json={"name": "RevHeat", "namespaces": ["wp/v2"]},
        status=200,
    )
    return WordPressPublisher(
        base_url=BASE_URL,
        username="testuser",
        app_password="test-pass",
    )


class TestConnection:
    @responses.activate
    def test_connection_success(self):
        """Verify WP REST API is reachable and authenticated."""
        responses.add(
            responses.GET, f"{API_BASE}/",
            json={"name": "RevHeat"}, status=200,
        )
        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        assert wp.base_url == BASE_URL

    @responses.activate
    def test_connection_failure(self):
        """Verify ConnectionError raised when WP is unreachable."""
        responses.add(
            responses.GET, f"{API_BASE}/",
            json={"error": "not found"}, status=500,
        )
        # After retries it should raise
        with pytest.raises(Exception):
            WordPressPublisher(BASE_URL, "testuser", "test-pass")


class TestCreateDraft:
    @responses.activate
    def test_create_and_delete_draft(self):
        """Create a test draft, verify it exists, then delete it."""
        # Connection verify
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        # Create draft
        responses.add(
            responses.POST, f"{API_BASE}/posts",
            json={"id": 42, "title": {"rendered": "Test Post"}, "status": "draft", "link": f"{BASE_URL}/?p=42"},
            status=201,
        )
        # Delete
        responses.add(
            responses.DELETE, f"{API_BASE}/posts/42?force=true",
            json={"id": 42, "deleted": True}, status=200,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        post = wp.create_draft("Test Post", "<p>Test content</p>")
        assert post["id"] == 42
        assert post["status"] == "draft"

        result = wp.delete_post(42)
        assert result is True

    @responses.activate
    def test_create_draft_with_meta(self):
        """Create draft with SEO meta fields."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        responses.add(
            responses.POST, f"{API_BASE}/posts",
            json={"id": 43, "title": {"rendered": "SEO Post"}, "status": "draft", "link": f"{BASE_URL}/?p=43"},
            status=201,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        meta = {
            "rank_math_title": "SEO Title | RevHeat",
            "rank_math_description": "Meta description here",
            "rank_math_focus_keyword": "test keyword",
        }
        post = wp.create_draft("SEO Post", "<p>Content</p>", meta=meta)
        assert post["id"] == 43

        # Verify meta was sent in the request body
        request_body = json.loads(responses.calls[1].request.body)
        assert request_body["meta"]["rank_math_title"] == "SEO Title | RevHeat"


class TestUploadImage:
    @responses.activate
    def test_upload_image(self, tmp_path):
        """Upload a test image, verify media ID returned, then delete."""
        # Connection verify
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        # Upload
        responses.add(
            responses.POST, f"{API_BASE}/media",
            json={"id": 101, "source_url": f"{BASE_URL}/wp-content/uploads/test.png"},
            status=201,
        )
        # Set alt text
        responses.add(
            responses.POST, f"{API_BASE}/media/101",
            json={"id": 101, "alt_text": "Test image"}, status=200,
        )
        # Delete
        responses.add(
            responses.DELETE, f"{API_BASE}/media/101?force=true",
            json={"id": 101, "deleted": True}, status=200,
        )

        # Create a test image large enough to pass the 1KB minimum check
        test_image = tmp_path / "test.png"
        import random
        from PIL import Image as PILImage
        pil_img = PILImage.new("RGB", (200, 200))
        pixels = [(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)) for _ in range(200*200)]
        pil_img.putdata(pixels)
        pil_img.save(str(test_image), "PNG")

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        media_id = wp.upload_image(str(test_image), "Test image alt text")
        assert media_id == 101

        result = wp.delete_media(101)
        assert result is True


class TestFeaturedImage:
    @responses.activate
    def test_set_featured_image(self):
        """Create draft, set featured image, verify."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        responses.add(
            responses.POST, f"{API_BASE}/posts",
            json={"id": 44, "status": "draft"}, status=201,
        )
        responses.add(
            responses.POST, f"{API_BASE}/posts/44",
            json={"id": 44, "featured_media": 101}, status=200,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        post = wp.create_draft("Featured Test", "<p>Content</p>")
        result = wp.set_featured_image(44, 101)
        assert result is True


class TestTaxonomy:
    @responses.activate
    def test_category_lookup(self):
        """Look up category by slug, verify correct ID."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        responses.add(
            responses.GET, f"{API_BASE}/categories?slug=sales-process",
            json=[{"id": 12, "slug": "sales-process", "name": "Sales Process"}],
            status=200,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        cat_id = wp.get_category_id("sales-process")
        assert cat_id == 12

        # Second call should use cache
        cat_id2 = wp.get_category_id("sales-process")
        assert cat_id2 == 12
        # Only 2 HTTP calls total (verify + first lookup)
        assert len(responses.calls) == 2

    @responses.activate
    def test_tag_creation(self):
        """Create a new tag via API, verify it exists."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        # Tag doesn't exist yet
        responses.add(
            responses.GET, f"{API_BASE}/tags?slug=new-tag",
            json=[], status=200,
        )
        # Create it
        responses.add(
            responses.POST, f"{API_BASE}/tags",
            json={"id": 99, "slug": "new-tag", "name": "new-tag"},
            status=201,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        tag_id = wp.get_tag_id("new-tag")
        assert tag_id == 99


class TestSEOMeta:
    @responses.activate
    def test_seo_meta(self):
        """Set Rank Math meta fields, verify request payload."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        responses.add(
            responses.POST, f"{API_BASE}/posts/44",
            json={"id": 44}, status=200,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        result = wp.set_seo_meta(
            44,
            "SEO Title | RevHeat",
            "Meta description for SEO",
            "primary keyword",
        )
        assert result is True

        request_body = json.loads(responses.calls[1].request.body)
        assert request_body["meta"]["rank_math_title"] == "SEO Title | RevHeat"
        assert request_body["meta"]["rank_math_focus_keyword"] == "primary keyword"


class TestScheduling:
    @responses.activate
    def test_schedule_post(self):
        """Schedule a post for future, verify status=future in request."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        responses.add(
            responses.POST, f"{API_BASE}/posts/44",
            json={"id": 44, "status": "future"}, status=200,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        from datetime import datetime
        future_date = datetime(2026, 6, 15, 9, 0, 0)
        result = wp.schedule_post(44, future_date)
        assert result is True

        request_body = json.loads(responses.calls[1].request.body)
        assert request_body["status"] == "future"


class TestFullPipeline:
    @responses.activate
    def test_full_pipeline(self, tmp_path):
        """End-to-end: create draft -> set SEO meta -> assign categories -> schedule -> verify."""
        # Connection
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        # Create draft
        responses.add(
            responses.POST, f"{API_BASE}/posts",
            json={"id": 50, "title": {"rendered": "Pipeline Test"}, "status": "draft", "link": f"{BASE_URL}/?p=50"},
            status=201,
        )
        # Set SEO meta
        responses.add(
            responses.POST, f"{API_BASE}/posts/50",
            json={"id": 50}, status=200,
        )
        # Category lookup
        responses.add(
            responses.GET, f"{API_BASE}/categories?slug=process",
            json=[{"id": 5, "slug": "process"}], status=200,
        )
        # Assign taxonomy
        responses.add(
            responses.POST, f"{API_BASE}/posts/50",
            json={"id": 50}, status=200,
        )
        # Schedule
        responses.add(
            responses.POST, f"{API_BASE}/posts/50",
            json={"id": 50, "status": "future"}, status=200,
        )
        # Delete cleanup
        responses.add(
            responses.DELETE, f"{API_BASE}/posts/50?force=true",
            json={"id": 50, "deleted": True}, status=200,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")

        # 1. Create draft
        post = wp.create_draft("Pipeline Test", "<p>Full pipeline content</p>")
        assert post["id"] == 50

        # 2. Set SEO meta
        assert wp.set_seo_meta(50, "SEO Title", "Meta desc", "keyword")

        # 3. Assign categories
        cat_id = wp.get_category_id("process")
        assert cat_id == 5
        assert wp.assign_taxonomy(50, [cat_id], [])

        # 4. Schedule
        from datetime import datetime
        assert wp.schedule_post(50, datetime(2026, 6, 15, 9, 0))

        # Cleanup
        assert wp.delete_post(50)


class TestDraftQueue:
    @responses.activate
    def test_get_draft_queue(self):
        """Verify draft queue returns correct structure."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        responses.add(
            responses.GET,
            f"{API_BASE}/posts?status=draft&per_page=20&orderby=date",
            json=[
                {"id": 1, "title": {"rendered": "Draft 1"}, "date": "2026-03-01", "link": f"{BASE_URL}/?p=1"},
                {"id": 2, "title": {"rendered": "Draft 2"}, "date": "2026-03-02", "link": f"{BASE_URL}/?p=2"},
            ],
            status=200,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        drafts = wp.get_draft_queue()
        assert len(drafts) == 2
        assert drafts[0]["title"] == "Draft 1"
        assert drafts[1]["id"] == 2


class TestSocialMeta:
    @responses.activate
    def test_set_social_meta(self):
        """Set OpenGraph + Twitter Card meta, verify request payload."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        responses.add(
            responses.POST, f"{API_BASE}/posts/44",
            json={"id": 44}, status=200,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        result = wp.set_social_meta(
            44,
            title="OG Title | RevHeat",
            description="Social description for sharing",
            image_url="https://revheat.com/wp-content/uploads/featured.jpg",
            author_twitter="@RevHeat",
        )
        assert result is True

        request_body = json.loads(responses.calls[1].request.body)
        meta = request_body["meta"]
        assert meta["rank_math_facebook_title"] == "OG Title | RevHeat"
        assert meta["rank_math_facebook_description"] == "Social description for sharing"
        assert meta["rank_math_twitter_card_type"] == "summary_large_image"
        assert meta["rank_math_twitter_creator"] == "@RevHeat"
        assert meta["rank_math_facebook_image"] == "https://revheat.com/wp-content/uploads/featured.jpg"
        assert meta["rank_math_twitter_image"] == "https://revheat.com/wp-content/uploads/featured.jpg"

    @responses.activate
    def test_set_social_meta_no_image(self):
        """Social meta without image omits image fields."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        responses.add(
            responses.POST, f"{API_BASE}/posts/44",
            json={"id": 44}, status=200,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        result = wp.set_social_meta(44, title="Title", description="Desc")
        assert result is True

        request_body = json.loads(responses.calls[1].request.body)
        meta = request_body["meta"]
        assert "rank_math_facebook_image" not in meta
        assert "rank_math_twitter_image" not in meta


class TestCanonicalUrl:
    @responses.activate
    def test_set_canonical_url(self):
        """Set canonical URL via Rank Math field."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        responses.add(
            responses.POST, f"{API_BASE}/posts/44",
            json={"id": 44}, status=200,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        result = wp.set_canonical_url(44, "https://revheat.com/blog/my-post/")
        assert result is True

        request_body = json.loads(responses.calls[1].request.body)
        assert request_body["meta"]["rank_math_canonical_url"] == "https://revheat.com/blog/my-post/"


class TestSEOMetaSecondaryKeywords:
    @responses.activate
    def test_seo_meta_with_secondary_keywords(self):
        """Set SEO meta with secondary keywords joined into focus keyword field."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        responses.add(
            responses.POST, f"{API_BASE}/posts/44",
            json={"id": 44}, status=200,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        result = wp.set_seo_meta(
            44,
            "SEO Title | RevHeat",
            "Meta description here",
            "primary keyword",
            secondary_keywords=["secondary one", "secondary two"],
        )
        assert result is True

        request_body = json.loads(responses.calls[1].request.body)
        focus_kw = request_body["meta"]["rank_math_focus_keyword"]
        assert "primary keyword" in focus_kw
        assert "secondary one" in focus_kw
        assert "secondary two" in focus_kw

    @responses.activate
    def test_seo_meta_with_robots(self):
        """Set SEO meta with custom robots directive."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        responses.add(
            responses.POST, f"{API_BASE}/posts/44",
            json={"id": 44}, status=200,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        result = wp.set_seo_meta(
            44, "Title", "Desc", "keyword",
            robots="noindex,nofollow",
        )
        assert result is True

        request_body = json.loads(responses.calls[1].request.body)
        assert request_body["meta"]["rank_math_robots"] == "noindex,nofollow"


class TestStatusCodeHandling:
    @responses.activate
    def test_201_treated_as_success(self):
        """HTTP 201 is treated as success (not just 200)."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        responses.add(
            responses.POST, f"{API_BASE}/posts/44",
            json={"id": 44, "featured_media": 101}, status=201,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        result = wp.set_featured_image(44, 101)
        assert result is True

    @responses.activate
    def test_assign_taxonomy_201(self):
        """Assign taxonomy returns True on 201."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        responses.add(
            responses.POST, f"{API_BASE}/posts/44",
            json={"id": 44}, status=201,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        result = wp.assign_taxonomy(44, [5], [10])
        assert result is True


class TestDuplicateProtection:
    @responses.activate
    def test_create_draft_skips_existing(self):
        """Create draft returns existing post when slug already exists."""
        responses.add(responses.GET, f"{API_BASE}/", json={"name": "RevHeat"}, status=200)
        # Post exists check - return existing
        responses.add(
            responses.GET, f"{API_BASE}/posts?slug=existing-post&status=publish",
            json=[{"id": 99, "title": {"rendered": "Existing"}, "status": "publish"}],
            status=200,
        )

        wp = WordPressPublisher(BASE_URL, "testuser", "test-pass")
        post = wp.create_draft("Existing", "<p>Content</p>", slug="existing-post")
        assert post["id"] == 99  # Returns existing, doesn't create new


class TestErrorHandling:
    @responses.activate
    def test_authentication_error(self):
        """Verify AuthenticationError raised on 401."""
        responses.add(
            responses.GET, f"{API_BASE}/",
            json={"code": "rest_cannot_access"}, status=401,
        )
        with pytest.raises(AuthenticationError):
            WordPressPublisher(BASE_URL, "testuser", "bad-pass")
