"""Tests for the Image Pipeline module."""

import os
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND_CONFIG = os.path.join(PROJECT_ROOT, "assets", "brand", "colors.yaml")

from src.image_pipeline import ImagePipeline, ImageResult


@pytest.fixture
def pipeline(tmp_path):
    p = ImagePipeline(brand_config_path=BRAND_CONFIG)
    p.output_dir = str(tmp_path)
    return p


@pytest.fixture
def sample_chart_data():
    return {
        "labels": ["Bottom 25%", "Median", "Top 10%"],
        "values": [12, 28, 47],
        "unit": "%",
        "highlight_index": 2,
    }


class TestBarChart:
    def test_bar_chart_generation(self, pipeline, sample_chart_data):
        """Generate a bar chart, verify image file created with correct dimensions."""
        result = pipeline.generate_data_chart(
            data=sample_chart_data,
            chart_type="bar",
            title="Sales Win Rates by Tier",
            subtitle="RevHeat Research",
        )
        assert isinstance(result, ImageResult)
        assert os.path.exists(result.path)
        assert result.width > 0
        assert result.height > 0
        assert result.format == "png"

    def test_comparison_bar_chart(self, pipeline, sample_chart_data):
        """Generate comparison bars, verify brand colors applied."""
        result = pipeline.generate_data_chart(
            data=sample_chart_data,
            chart_type="comparison_bar",
            title="Performance Comparison",
        )
        assert isinstance(result, ImageResult)
        assert os.path.exists(result.path)
        assert result.alt_text  # Should have alt text


class TestQuoteCard:
    def test_quote_card_generation(self, pipeline):
        """Generate quote card, verify dimensions and alt text."""
        result = pipeline.generate_quote_card(
            "The best sales teams don't have the best salespeople — they have the best systems.",
            author="Ken Lundin",
        )
        assert isinstance(result, ImageResult)
        assert os.path.exists(result.path)
        # Square format for social
        assert result.width == result.height
        assert "Ken Lundin" in result.alt_text
        assert result.format == "png"


class TestComparisonGraphic:
    def test_comparison_graphic(self, pipeline):
        """Generate before/after graphic, verify both sections present."""
        before = {"revenue": "$3.2M", "win_rate": "18%", "cycle": "9 months"}
        after = {"revenue": "$16.1M", "win_rate": "34%", "cycle": "4.5 months"}
        result = pipeline.generate_comparison_graphic(before, after, "18 Months with SMARTSCALING")
        assert isinstance(result, ImageResult)
        assert os.path.exists(result.path)
        assert result.width > 0


class TestFrameworkDiagram:
    def test_framework_diagram(self, pipeline):
        """Generate framework diagram with 4 pillars."""
        framework = {
            "title": "The SMARTSCALING 4-Pillar Framework",
            "elements": [
                {"name": "Strategy", "sub": ["Business Trajectory", "Go-to-Market"]},
                {"name": "People", "sub": ["Talent", "Leadership", "Org Design"]},
                {"name": "Process", "sub": ["Architecture", "Enablement", "RevOps"]},
                {"name": "Performance", "sub": ["Metrics", "Comp", "Improvement"]},
            ],
        }
        result = pipeline.generate_framework_diagram(framework)
        assert isinstance(result, ImageResult)
        assert os.path.exists(result.path)


class TestBrandTemplate:
    def test_brand_template_application(self, pipeline, tmp_path):
        """Apply brand template, verify output file created."""
        # Create a simple test image
        from PIL import Image
        test_img = Image.new("RGB", (800, 500), (255, 255, 255))
        test_path = str(tmp_path / "test-input.png")
        test_img.save(test_path)

        result_path = pipeline.apply_brand_template(test_path, "chart")
        assert os.path.exists(result_path)
        assert "-branded" in result_path


class TestCompression:
    def test_compression_fallback(self, pipeline, tmp_path):
        """Compress with Pillow when API unavailable."""
        from PIL import Image
        test_img = Image.new("RGB", (800, 500), (200, 100, 50))
        test_path = str(tmp_path / "compress-test.png")
        test_img.save(test_path)

        pipeline.shortpixel_key = ""  # Force fallback
        result = pipeline.compress_image(test_path)
        assert result.endswith(".webp")
        assert os.path.exists(result)

    @patch("src.image_pipeline.requests.post")
    def test_compression_shortpixel(self, mock_post, pipeline, tmp_path):
        """Compress image via API, verify file size reduction."""
        from PIL import Image
        test_img = Image.new("RGB", (800, 500), (200, 100, 50))
        test_path = str(tmp_path / "sp-test.png")
        test_img.save(test_path)

        # Mock ShortPixel response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"\x00" * 100  # Fake compressed content
        mock_post.return_value = mock_resp

        pipeline.shortpixel_key = "test-key"
        result = pipeline.compress_image(test_path)
        assert result.endswith(".webp")


class TestAltText:
    def test_alt_text_generation(self, pipeline):
        """Generate alt text, verify length <= 125 chars and includes data."""
        context = {
            "chart_title": "Sales Win Rates by Performance Tier",
            "data_summary": "Bottom 25% at 12%, Median 28%, Top 10% at 47%",
            "post_topic": "Why 92% of Sales Processes Fail",
            "source": "RevHeat Research — 33,000+ companies",
        }
        alt = pipeline.generate_alt_text(context)
        assert len(alt) <= 125
        assert "Win Rates" in alt


class TestWebPConversion:
    def test_webp_conversion(self, pipeline, tmp_path):
        """Verify WebP format output."""
        from PIL import Image
        test_img = Image.new("RGB", (400, 300), (100, 150, 200))
        test_path = str(tmp_path / "webp-test.png")
        test_img.save(test_path)

        result = pipeline._compress_pillow(test_path)
        assert result.endswith(".webp")
        # Verify it's a valid WebP
        webp_img = Image.open(result)
        assert webp_img.format == "WEBP"


class TestFullPipeline:
    def test_full_pipeline(self, pipeline):
        """Run full pipeline on a mock draft, verify 1-3 images returned."""
        @dataclass
        class MockDraft:
            title: str = "Test Blog Post"
            key_takeaway: str = "Great insight about sales"
            comparison_table: str = ""

        draft = MockDraft()
        results = pipeline.full_pipeline(draft)
        assert len(results) >= 1
        assert len(results) <= 3
        for r in results:
            assert isinstance(r, ImageResult)
