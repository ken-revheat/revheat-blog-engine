"""Tests for the Schema Builder module."""

import json
import os
import pytest

# Resolve paths relative to project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
PILLAR_MAP = os.path.join(PROJECT_ROOT, "data", "pillar_cluster_map.yaml")

from src.schema_builder import SchemaBuilder, ValidationResult


@pytest.fixture
def builder():
    return SchemaBuilder(templates_dir=TEMPLATES_DIR, pillar_map_path=PILLAR_MAP)


@pytest.fixture
def sample_post_data():
    return {
        "post_url": "https://revheat.com/blog/why-92-percent-sales-processes-fail/",
        "post_title": "Why 92% of Sales Processes Fail",
        "meta_description": "Data from 33,000 companies reveals why most sales processes break down.",
        "publish_date_iso": "2026-03-15T09:00:00-05:00",
        "modified_date_iso": "2026-03-15T09:00:00-05:00",
        "featured_image_url": "https://revheat.com/wp-content/uploads/sales-process-fail.webp",
        "word_count": 1650,
        "smartscaling_pillar": "process",
        "smartscaling_function": "Sales Process Architecture",
        "keywords": "sales process failure, sales system, sales optimization",
        "primary_topic": "Sales Process Optimization",
        "topic_description": "Why most sales processes fail and the systems approach that works",
    }


@pytest.fixture
def sample_faq_items():
    return [
        {"question": "Why do most sales processes fail?", "answer": "Based on data from 33,000 companies, the #1 reason is lack of adherence."},
        {"question": "How long does it take to fix a broken sales process?", "answer": "Typically 90-180 days for meaningful improvement."},
        {"question": "What metrics predict sales process health?", "answer": "Conversion rates, cycle time, and win rate are the top three."},
        {"question": "Should I hire a consultant to fix my sales process?", "answer": "If revenue exceeds $3M and you lack internal expertise, yes."},
        {"question": "What is the SMARTSCALING framework?", "answer": "A data-backed system covering 11 sales functions across 4 pillars."},
    ]


class TestArticleSchema:
    def test_article_schema_valid(self, builder, sample_post_data):
        """Build article schema, validate all required fields present."""
        schema = builder.build_article_schema(sample_post_data)
        assert schema["@type"] == "Article"
        assert schema["headline"] == "Why 92% of Sales Processes Fail"
        assert schema["wordCount"] == 1650
        assert schema["datePublished"] == "2026-03-15T09:00:00-05:00"
        assert "author" in schema
        assert schema["author"]["name"] == "Ken Lundin"

    def test_article_schema_is_valid_json(self, builder, sample_post_data):
        """Verify output is valid parseable JSON."""
        schema = builder.build_article_schema(sample_post_data)
        json_str = json.dumps(schema)
        reparsed = json.loads(json_str)
        assert reparsed["@type"] == "Article"


class TestFAQSchema:
    def test_faq_schema_with_5_items(self, builder, sample_faq_items):
        """Build FAQ with 5 questions, verify structure."""
        schema = builder.build_faq_schema(
            sample_faq_items,
            post_url="https://revheat.com/blog/test/",
        )
        assert schema["@type"] == "FAQPage"
        assert len(schema["mainEntity"]) == 5
        assert schema["mainEntity"][0]["@type"] == "Question"
        assert schema["mainEntity"][0]["acceptedAnswer"]["@type"] == "Answer"


class TestHowToSchema:
    def test_howto_schema_with_steps(self, builder):
        """Build HowTo with 3 steps, verify structure."""
        howto_data = {
            "title": "How to Evaluate Your Sales Team in 45 Minutes",
            "description": "A step-by-step diagnostic for sales leaders.",
            "estimated_time": "PT45M",
            "post_url": "https://revheat.com/blog/evaluate-sales-team/",
            "steps": [
                {"title": "Assess pipeline health", "description": "Review the last 90 days of pipeline data."},
                {"title": "Evaluate process adherence", "description": "Check CRM compliance rates."},
                {"title": "Score talent gaps", "description": "Use the 11-function audit framework."},
            ],
        }
        schema = builder.build_howto_schema(howto_data)
        assert schema["@type"] == "HowTo"
        assert len(schema["step"]) == 3
        assert schema["step"][0]["position"] == 1
        assert schema["step"][2]["name"] == "Score talent gaps"

    def test_howto_empty_returns_empty(self, builder):
        """HowTo with no steps returns empty dict."""
        result = builder.build_howto_schema({})
        assert result == {}
        result2 = builder.build_howto_schema({"title": "Test", "steps": []})
        assert result2 == {}


class TestBreadcrumbSchema:
    def test_breadcrumb_pillar_mapping(self, builder):
        """Verify breadcrumbs correctly map pillar -> cluster -> post."""
        schema = builder.build_breadcrumb_schema(
            pillar="process",
            cluster="process_architecture",
            post_title="Why 92% of Sales Processes Fail",
            post_url="https://revheat.com/blog/why-92-percent-sales-processes-fail/",
        )
        assert schema["@type"] == "BreadcrumbList"
        items = schema["itemListElement"]
        assert len(items) == 4
        assert items[0]["name"] == "Home"
        assert items[1]["position"] == 2
        # Pillar should map to process slug
        assert "process" in items[1]["item"].lower() or "sales-process" in items[1]["item"].lower()
        assert items[3]["name"] == "Why 92% of Sales Processes Fail"


class TestFullGraph:
    def test_full_graph_assembly(self, builder, sample_post_data, sample_faq_items):
        """Build complete graph with all schema types, verify @graph structure."""
        sample_post_data["faq_items"] = sample_faq_items
        sample_post_data["howto_steps"] = [
            {"title": "Step 1", "description": "Do the first thing."},
            {"title": "Step 2", "description": "Do the second thing."},
        ]

        graph = builder.build_full_graph(sample_post_data)
        assert graph["@context"] == "https://schema.org"
        assert "@graph" in graph

        types = [item["@type"] for item in graph["@graph"]]
        assert "Article" in types
        assert "BreadcrumbList" in types
        assert "FAQPage" in types
        assert "HowTo" in types

    def test_full_graph_without_howto(self, builder, sample_post_data, sample_faq_items):
        """Graph for non-how-to post should omit HowTo schema."""
        sample_post_data["faq_items"] = sample_faq_items
        # No howto_steps

        graph = builder.build_full_graph(sample_post_data)
        types = [item["@type"] for item in graph["@graph"]]
        assert "Article" in types
        assert "BreadcrumbList" in types
        assert "FAQPage" in types
        assert "HowTo" not in types

    def test_full_graph_without_faq(self, builder, sample_post_data):
        """Graph without FAQ items should omit FAQPage."""
        graph = builder.build_full_graph(sample_post_data)
        types = [item["@type"] for item in graph["@graph"]]
        assert "Article" in types
        assert "FAQPage" not in types


class TestValidation:
    def test_validation_catches_missing_fields(self, builder, sample_post_data):
        """Submit schema with missing headline, verify error caught."""
        schema = builder.build_article_schema(sample_post_data)
        schema["headline"] = ""  # Remove headline
        wrapped = {"@context": "https://schema.org", "@graph": [schema]}

        result = builder.validate_schema(wrapped)
        assert not result.valid
        assert any("headline" in e.lower() for e in result.errors)

    def test_validation_catches_bad_dates(self, builder, sample_post_data):
        """Submit schema with invalid date format, verify error."""
        schema = builder.build_article_schema(sample_post_data)
        schema["datePublished"] = "March 15, 2026"
        wrapped = {"@context": "https://schema.org", "@graph": [schema]}

        result = builder.validate_schema(wrapped)
        assert not result.valid
        assert any("date" in e.lower() for e in result.errors)

    def test_valid_schema_passes(self, builder, sample_post_data, sample_faq_items):
        """Complete valid schema should pass validation."""
        sample_post_data["faq_items"] = sample_faq_items
        graph = builder.build_full_graph(sample_post_data)
        result = builder.validate_schema(graph)
        assert result.valid, f"Validation errors: {result.errors}"


class TestInjectHTML:
    def test_inject_into_html(self, builder, sample_post_data):
        """Inject schema into HTML, verify script tag present."""
        html = "<html><body><p>Hello</p></body></html>"
        schema = builder.build_article_schema(sample_post_data)
        result = builder.inject_into_html(html, schema)

        assert '<script type="application/ld+json">' in result
        assert "</script>" in result
        # Should be before </body>
        script_pos = result.index("application/ld+json")
        body_pos = result.index("</body>")
        assert script_pos < body_pos

    def test_inject_without_body_tag(self, builder, sample_post_data):
        """Inject into HTML without body tag appends to end."""
        html = "<p>Just some content</p>"
        schema = builder.build_article_schema(sample_post_data)
        result = builder.inject_into_html(html, schema)
        assert '<script type="application/ld+json">' in result

    def test_json_ld_is_valid_json(self, builder, sample_post_data):
        """Verify injected JSON-LD is valid parseable JSON."""
        html = "<html><body><p>Test</p></body></html>"
        schema = {"@context": "https://schema.org", "@type": "Article", "headline": "Test"}
        result = builder.inject_into_html(html, schema)

        # Extract JSON from script tag
        start = result.index('application/ld+json">') + len('application/ld+json">')
        end = result.index("</script>")
        json_str = result[start:end]
        parsed = json.loads(json_str)
        assert parsed["@type"] == "Article"
