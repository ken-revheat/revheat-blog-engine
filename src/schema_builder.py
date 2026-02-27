"""Schema Builder — generates and validates JSON-LD structured data for blog posts."""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

log = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SchemaBuilder:
    """Generates and validates JSON-LD structured data for every blog post."""

    def __init__(self, templates_dir="templates/", pillar_map_path="data/pillar_cluster_map.yaml"):
        self.templates_dir = templates_dir
        self.env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=False,
        )

        # Load pillar-cluster mapping for breadcrumbs
        self.pillar_map = {}
        if os.path.exists(pillar_map_path):
            with open(pillar_map_path) as f:
                self.pillar_map = yaml.safe_load(f) or {}

        log.info("SchemaBuilder initialized")

    def build_article_schema(self, post_data: dict) -> dict:
        """Build Article JSON-LD from post data."""
        template = self.env.get_template("article-template.json")

        defaults = {
            "primary_topic": post_data.get("smartscaling_pillar", "Sales Optimization"),
            "topic_description": "",
            "article_section": "",
            "time_required": "",
            "speakable_text": [],
            "speakable_selectors": [],
        }
        merged = {**defaults, **post_data}

        rendered = template.render(**merged)
        return json.loads(rendered)

    def build_faq_schema(self, faq_items: list[dict], post_url: str = "") -> dict:
        """Build FAQPage JSON-LD from FAQ items."""
        template = self.env.get_template("faqpage-template.json")
        rendered = template.render(faq_items=faq_items, post_url=post_url)
        return json.loads(rendered)

    def build_howto_schema(self, howto_data: dict) -> dict:
        """Build HowTo JSON-LD from step data."""
        if not howto_data or not howto_data.get("steps"):
            return {}

        template = self.env.get_template("howto-template.json")
        rendered = template.render(**howto_data)
        return json.loads(rendered)

    def build_breadcrumb_schema(self, pillar: str, cluster: str, post_title: str, post_url: str) -> dict:
        """Build BreadcrumbList JSON-LD using pillar/cluster mapping."""
        pillar_name, pillar_slug = self._resolve_pillar(pillar)
        cluster_name, cluster_slug = self._resolve_cluster(pillar, cluster)

        template = self.env.get_template("breadcrumb-template.json")
        rendered = template.render(
            post_url=post_url,
            pillar_name=pillar_name,
            pillar_slug=pillar_slug,
            cluster_name=cluster_name,
            cluster_slug=cluster_slug,
            post_title=post_title,
        )
        return json.loads(rendered)

    def _resolve_pillar(self, pillar: str) -> tuple[str, str]:
        """Map pillar name to display name and slug."""
        pillar_key = pillar.lower().strip()
        pillar_data = self.pillar_map.get(pillar_key, {})
        if pillar_data and "pillar_page" in pillar_data:
            pp = pillar_data["pillar_page"]
            return pp.get("title", pillar.title()), pp.get("slug", pillar_key)
        return pillar.title(), pillar_key

    def _resolve_cluster(self, pillar: str, cluster: str) -> tuple[str, str]:
        """Map cluster name to display name and slug."""
        pillar_key = pillar.lower().strip()
        pillar_data = self.pillar_map.get(pillar_key, {})
        clusters = pillar_data.get("clusters", {})

        # Try direct key match
        cluster_key = cluster.lower().replace(" ", "_").replace("-", "_")
        if cluster_key in clusters:
            cp = clusters[cluster_key].get("cluster_page", {})
            return cp.get("title", cluster), cp.get("slug", cluster_key)

        # Fuzzy match by iterating
        for key, data in clusters.items():
            cp = data.get("cluster_page", {})
            if cluster.lower() in cp.get("title", "").lower():
                return cp.get("title", cluster), cp.get("slug", key)

        # Fallback
        slug = re.sub(r"[^a-z0-9]+", "-", cluster.lower()).strip("-")
        return cluster, slug

    def build_full_graph(self, post_data: dict) -> dict:
        """Build complete @graph with Article, BreadcrumbList, and optional FAQ/HowTo."""
        graph = []

        # Always include Article
        article = self.build_article_schema(post_data)
        graph.append(article)

        # Always include BreadcrumbList
        breadcrumb = self.build_breadcrumb_schema(
            pillar=post_data.get("smartscaling_pillar", ""),
            cluster=post_data.get("smartscaling_function", post_data.get("smartscaling_pillar", "")),
            post_title=post_data.get("post_title", ""),
            post_url=post_data.get("post_url", ""),
        )
        graph.append(breadcrumb)

        # Optional FAQPage
        faq_items = post_data.get("faq_items", [])
        if faq_items:
            faq = self.build_faq_schema(faq_items, post_data.get("post_url", ""))
            graph.append(faq)

        # Optional HowTo
        howto_steps = post_data.get("howto_steps")
        if howto_steps:
            howto_data = {
                "title": post_data.get("post_title", ""),
                "description": post_data.get("meta_description", ""),
                "estimated_time": post_data.get("estimated_time", ""),
                "steps": howto_steps,
                "post_url": post_data.get("post_url", ""),
            }
            howto = self.build_howto_schema(howto_data)
            if howto:
                graph.append(howto)

        return {
            "@context": "https://schema.org",
            "@graph": graph,
        }

    def validate_schema(self, json_ld: dict) -> ValidationResult:
        """Validate a JSON-LD schema dict for correctness."""
        errors = []
        warnings = []

        graph = json_ld.get("@graph", [json_ld])

        for item in graph:
            schema_type = item.get("@type", "")

            if schema_type == "Article":
                self._validate_article(item, errors, warnings)
            elif schema_type == "FAQPage":
                self._validate_faq(item, errors, warnings)
            elif schema_type == "HowTo":
                self._validate_howto(item, errors, warnings)
            elif schema_type == "BreadcrumbList":
                self._validate_breadcrumb(item, errors, warnings)

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _validate_article(self, article: dict, errors: list, warnings: list):
        required = ["headline", "datePublished", "author", "description"]
        for field_name in required:
            if not article.get(field_name):
                errors.append(f"Article missing required field: {field_name}")

        # Validate date format
        for date_field in ["datePublished", "dateModified"]:
            val = article.get(date_field, "")
            if val and not self._is_valid_iso_date(val):
                errors.append(f"Article {date_field} is not valid ISO 8601: {val}")

        # Validate word count
        wc = article.get("wordCount")
        if wc is not None and not isinstance(wc, int):
            errors.append(f"Article wordCount must be int, got {type(wc).__name__}")

        # Check for empty values
        if not article.get("image", {}).get("url"):
            warnings.append("Article missing featured image URL")

    def _validate_faq(self, faq: dict, errors: list, warnings: list):
        entities = faq.get("mainEntity", [])
        if not entities:
            errors.append("FAQPage has no questions")
        for i, q in enumerate(entities):
            if not q.get("name"):
                errors.append(f"FAQ question {i+1} missing 'name'")
            answer = q.get("acceptedAnswer", {})
            if not answer.get("text"):
                errors.append(f"FAQ question {i+1} missing answer text")

    def _validate_howto(self, howto: dict, errors: list, warnings: list):
        if not howto.get("name"):
            errors.append("HowTo missing 'name'")
        steps = howto.get("step", [])
        if not steps:
            errors.append("HowTo has no steps")
        for i, step in enumerate(steps):
            if not step.get("name"):
                errors.append(f"HowTo step {i+1} missing 'name'")
            if not step.get("text"):
                errors.append(f"HowTo step {i+1} missing 'text'")

    def _validate_breadcrumb(self, bc: dict, errors: list, warnings: list):
        items = bc.get("itemListElement", [])
        if not items:
            errors.append("BreadcrumbList has no items")
        for i, item in enumerate(items):
            if not item.get("name"):
                errors.append(f"Breadcrumb item {i+1} missing 'name'")
            if not item.get("item"):
                warnings.append(f"Breadcrumb item {i+1} missing 'item' URL")

    def _is_valid_iso_date(self, date_str: str) -> bool:
        iso_pattern = r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?"
        return bool(re.match(iso_pattern, date_str))

    def inject_into_html(self, html_content: str, json_ld: dict) -> str:
        """Inject JSON-LD schema into HTML content."""
        script_tag = (
            '<script type="application/ld+json">'
            + json.dumps(json_ld, separators=(",", ":"))
            + "</script>"
        )

        # Insert before </body> if present, else append
        if "</body>" in html_content:
            return html_content.replace("</body>", f"{script_tag}\n</body>")
        return html_content + "\n" + script_tag

    def deploy_site_schemas(self) -> str:
        """Generate PHP snippet for site-wide Organization/Person/WebSite schemas.

        NOTE: Rank Math already outputs basic Organization + WebSite + Person schemas.
        This enhanced version enriches them with sameAs, contactPoint, and detailed
        Person data that Rank Math doesn't include. Install via Rank Math > General
        Settings > Edit Robot.txt or via theme functions.php.
        """
        return """<?php
// Add to functions.php or Rank Math > General Settings > Code (Head) section
// This enriches the Organization + Person schemas beyond what Rank Math auto-generates.
add_action('wp_head', function() {
    $schema = [
        '@context' => 'https://schema.org',
        '@graph' => [
            [
                '@type' => 'Organization',
                '@id' => 'https://revheat.com/#organization',
                'name' => 'RevHeat',
                'url' => 'https://revheat.com',
                'description' => 'Sales consulting firm helping mid-market companies ($3M-$150M) build predictable sales systems using data from 33,000+ companies and the proprietary SMARTSCALING Framework.',
                'logo' => [
                    '@type' => 'ImageObject',
                    '@id' => 'https://revheat.com/#logo',
                    'url' => 'https://revheat.com/wp-content/uploads/2025/09/image-removebg-preview-2.png',
                    'contentUrl' => 'https://revheat.com/wp-content/uploads/2025/09/image-removebg-preview-2.png',
                    'caption' => 'RevHeat',
                    'width' => '250',
                    'height' => '250'
                ],
                'sameAs' => [
                    'https://www.linkedin.com/company/revheat'
                ],
                'contactPoint' => [
                    '@type' => 'ContactPoint',
                    'contactType' => 'sales',
                    'url' => 'https://revheat.com/#Calendar'
                ],
                'knowsAbout' => [
                    'Sales Process Architecture',
                    'Sales Performance Management',
                    'Sales Talent Assessment',
                    'Sales Strategy',
                    'SMARTSCALING Framework'
                ]
            ],
            [
                '@type' => 'Person',
                '@id' => 'https://revheat.com/#person',
                'name' => 'Ken Lundin',
                'jobTitle' => 'Founder & CEO',
                'worksFor' => ['@id' => 'https://revheat.com/#organization'],
                'url' => 'https://revheat.com/about/',
                'description' => 'Founder of RevHeat and creator of the SMARTSCALING Framework. Sales systems expert with data from 33,000+ companies.',
                'knowsAbout' => [
                    'Sales Leadership',
                    'Revenue Operations',
                    'SMARTSCALING',
                    'Sales Process Optimization',
                    'Sales Talent Assessment'
                ],
                'sameAs' => [
                    'https://www.linkedin.com/in/kenlundin/'
                ]
            ]
        ]
    ];
    echo '<script type=\"application/ld+json\">' . wp_json_encode($schema) . '</script>';
});
?>"""
