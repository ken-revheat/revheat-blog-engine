#!/usr/bin/env python3
"""Republish a WordPress post from a Cowork draft file.

Processes the draft through the full pipeline (FAQ fix, CSS classes,
images, schema, internal links, CTA normalization, Reddit strip) and
updates an existing WP post by ID — replacing the template-generated
placeholder content with the real Cowork draft.

Usage:
    python scripts/republish_post.py <draft_file> <wp_post_id>

Example:
    python scripts/republish_post.py \
        ~/Dropbox/SEO-Machine/04-Blog-Drafts/Week-01/day-05-five-stages-revenue-growth.md \
        9765
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.content_engine import ContentEngine
from src.utils.logger import setup_logging


def republish(draft_path: str, post_id: int):
    """Process a Cowork draft and update an existing WP post."""
    setup_logging()
    log = logging.getLogger("republish")

    draft_file = Path(draft_path)
    if not draft_file.exists():
        log.error(f"Draft file not found: {draft_file}")
        sys.exit(1)

    log.info(f"=== REPUBLISH: {draft_file.name} -> WP post #{post_id} ===")

    # 1. Initialize engine
    engine = ContentEngine(config_path="config.yaml")
    today = datetime.now(timezone.utc)

    # 2. Ingest the draft file through DraftIngester
    topic, draft = engine.draft_ingester.build_draft_from_file(
        draft_file, engine._parse_draft
    )
    log.info(
        f"Ingested: {draft.title} | slug={draft.slug} | "
        f"{draft.word_count} words | {len(draft.faq_items)} FAQs"
    )

    # 3. Quality check (warn only — Cowork drafts are trusted)
    quality = engine.quality_check(draft, topic=topic)
    if quality.failures:
        log.warning(f"Quality failures (proceeding anyway): {quality.failures}")
    if quality.warnings:
        log.info(f"Quality warnings: {quality.warnings}")

    # 4. Generate images (Pexels featured image + data charts)
    images = engine.image_pipeline.full_pipeline(draft)
    log.info(f"Generated {len(images)} images")

    # 5. Build Schema (same logic as _publish_one)
    reading_minutes = max(1, round(draft.word_count / 238)) if draft.word_count else 5
    reading_time_iso = f"PT{reading_minutes}M"
    speakable_selectors = [".key-takeaway", ".tldr", "h1"]
    speakable_text = []
    if draft.meta_description:
        speakable_text.append(draft.meta_description)

    pillar_sections = {
        "people": "Sales People",
        "performance": "Sales Performance",
        "process": "Sales Process",
        "strategy": "Sales Strategy",
    }
    article_section = pillar_sections.get(
        (draft.smartscaling_pillar or "").lower(), "Sales Optimization"
    )

    schema = engine.schema_builder.build_full_graph({
        "post_url": f"https://revheat.com/{draft.slug}/",
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
        "article_section": article_section,
        "time_required": reading_time_iso,
        "speakable_text": speakable_text,
        "speakable_selectors": speakable_selectors,
    })

    # 6. Content cleanup pipeline
    content_clean = engine.normalize_ctas(draft.content_html)
    content_clean = engine.strip_reddit_section(content_clean)
    content_with_schema = engine.schema_builder.inject_into_html(content_clean, schema)
    content_with_planned = engine.inject_planned_links(
        content_with_schema, draft.planned_internal_links
    )
    content_final = engine.build_internal_links(
        content_with_planned, engine.wp.get_all_posts()
    )

    # 7. Upload images to WordPress
    media_ids = []
    for img in images:
        media_id = engine.wp.upload_image(img.path, img.alt_text)
        media_ids.append(media_id)

    # 8. UPDATE the existing post (not create new)
    post = engine.wp.update_post(
        post_id=post_id,
        title=draft.title,
        content_html=content_final,
        slug=draft.slug,  # Update slug from wordy auto-generated to Cowork's clean slug
        meta={
            "rank_math_title": draft.seo_title,
            "rank_math_description": draft.meta_description,
            "rank_math_focus_keyword": topic.primary_keyword,
        },
    )
    log.info(f"Updated post #{post_id} with new content")

    # 9. Set featured image
    if media_ids:
        engine.wp.set_featured_image(post_id, media_ids[0])
        log.info(f"Set featured image: media_id={media_ids[0]}")

    # 10. Assign categories and tags
    category_ids = [engine.wp.get_category_id(s) for s in draft.categories]
    tag_ids = [engine.wp.get_tag_id(s) for s in draft.tags]
    engine.wp.assign_taxonomy(post_id, category_ids, tag_ids)

    # 11. Set SEO meta
    engine.wp.set_seo_meta(
        post_id,
        seo_title=draft.seo_title,
        meta_desc=draft.meta_description,
        focus_keyword=topic.primary_keyword,
        secondary_keywords=topic.secondary_keywords,
    )

    # 12. Set social meta + canonical
    post_url = f"https://revheat.com/{draft.slug}/"
    featured_url = ""
    if media_ids:
        try:
            media_resp = engine.wp._request(
                "GET", f"{engine.wp.api_base}/media/{media_ids[0]}"
            )
            if media_resp.status_code == 200:
                featured_url = media_resp.json().get("source_url", "")
        except Exception:
            pass

    engine.wp.set_social_meta(
        post_id,
        title=draft.seo_title or draft.title,
        description=draft.meta_description,
        image_url=featured_url,
    )
    engine.wp.set_canonical_url(post_id, post_url)

    # 13. Record in state tracker
    engine.state.record_publish(
        slug=draft.slug,
        title=draft.title,
        post_id=post_id,
        pillar=draft.smartscaling_pillar,
        function=draft.smartscaling_function,
    )

    log.info(f"=== REPUBLISH COMPLETE ===")
    log.info(f"Post: {draft.title}")
    log.info(f"URL: {post_url}")
    log.info(f"Edit: https://revheat.com/wp-admin/post.php?post={post_id}&action=edit")
    log.info(f"Slug updated: {draft.slug}")
    log.info(f"Images: {len(media_ids)}")
    log.info(f"FAQs: {len(draft.faq_items)}")
    log.info(f"Words: {draft.word_count}")

    print(f"\n✅ Republished: {draft.title}")
    print(f"   URL: {post_url}")
    print(f"   Edit: https://revheat.com/wp-admin/post.php?post={post_id}&action=edit")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    draft_path = sys.argv[1]
    try:
        wp_post_id = int(sys.argv[2])
    except ValueError:
        print(f"Error: post_id must be an integer, got: {sys.argv[2]}")
        sys.exit(1)

    republish(draft_path, wp_post_id)
