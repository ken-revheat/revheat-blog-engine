"""WordPress REST API publisher for the RevHeat Blog Engine."""

import base64
import logging
import mimetypes
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

log = logging.getLogger(__name__)

# Custom exceptions
class AuthenticationError(Exception):
    pass

class PermissionError_(Exception):
    pass


class WordPressPublisher:
    """Handles all WordPress REST API interactions."""

    def __init__(self, base_url=None, username=None, app_password=None):
        self.base_url = (base_url or os.getenv("WP_URL", "")).rstrip("/")
        self.username = username or os.getenv("WP_USERNAME", "")
        self.app_password = app_password or os.getenv("WP_APP_PASSWORD", "")
        self.api_base = f"{self.base_url}/wp-json/wp/v2"

        # Build auth header
        credentials = f"{self.username}:{self.app_password}"
        token = base64.b64encode(credentials.encode()).decode()
        self.headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }

        # Caches
        self._category_cache: dict[str, int] = {}
        self._tag_cache: dict[str, int] = {}

        # Verify connection
        self._verify_connection()

    def _verify_connection(self):
        """Verify WP REST API is reachable and authenticated."""
        try:
            resp = self._request("GET", f"{self.base_url}/wp-json/wp/v2/")
            if resp.status_code != 200:
                raise ConnectionError(
                    f"WordPress API returned status {resp.status_code}"
                )
            log.info("WordPress connection verified", extra={"endpoint": "/wp-json/wp/v2/"})
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(f"Cannot reach WordPress at {self.base_url}: {e}")

    def _request(self, method, url, retries=3, timeout=30, **kwargs):
        """Make an HTTP request with retry logic and error handling."""
        last_exception = None
        for attempt in range(retries):
            try:
                start = time.time()
                resp = requests.request(
                    method, url, headers=self.headers, timeout=timeout, **kwargs
                )
                elapsed = time.time() - start

                log.info(
                    f"{method} {url} -> {resp.status_code}",
                    extra={
                        "endpoint": url,
                        "method": method,
                        "status_code": resp.status_code,
                        "response_time": round(elapsed, 3),
                    },
                )

                # Handle specific error codes
                if resp.status_code == 401:
                    raise AuthenticationError(
                        f"Authentication failed: {resp.text}"
                    )
                if resp.status_code == 403:
                    raise PermissionError_(
                        f"Insufficient permissions: {resp.text}"
                    )
                if resp.status_code == 404:
                    log.warning(f"Not found: {url}")
                    return resp
                if resp.status_code == 429:
                    # Rate limited — exponential backoff
                    wait = 2 ** attempt
                    log.warning(f"Rate limited, waiting {wait}s")
                    time.sleep(wait)
                    continue
                if resp.status_code >= 500:
                    wait = 2 ** attempt
                    log.warning(
                        f"Server error {resp.status_code}, retry {attempt+1}/{retries}"
                    )
                    time.sleep(wait)
                    last_exception = Exception(
                        f"Server error {resp.status_code}: {resp.text}"
                    )
                    continue

                return resp

            except requests.exceptions.Timeout:
                wait = 2 ** attempt
                log.warning(f"Timeout on {url}, retry {attempt+1}/{retries}")
                time.sleep(wait)
                last_exception = requests.exceptions.Timeout(f"Timeout: {url}")
            except (AuthenticationError, PermissionError_):
                raise
            except requests.exceptions.ConnectionError as e:
                wait = 2 ** attempt
                log.warning(f"Connection error, retry {attempt+1}/{retries}")
                time.sleep(wait)
                last_exception = e

        raise last_exception or Exception(f"Request failed after {retries} retries")

    def post_exists(self, slug: str) -> dict | None:
        """Check if a post with this slug already exists (any status)."""
        for status in ("publish", "draft", "future", "pending"):
            resp = self._request(
                "GET",
                f"{self.api_base}/posts?slug={slug}&status={status}",
            )
            if resp.status_code == 200:
                posts = resp.json()
                if posts:
                    return posts[0]
        return None

    def create_draft(self, title, content_html, slug=None, meta=None) -> dict:
        """Create a new WordPress draft post. Rejects duplicates by slug."""
        if slug:
            existing = self.post_exists(slug)
            if existing:
                log.warning(
                    f"Post with slug '{slug}' already exists (ID: {existing['id']}). Skipping creation."
                )
                return existing

        payload = {
            "title": title,
            "content": content_html,
            "status": "draft",
        }
        if slug:
            payload["slug"] = slug
        if meta:
            payload["meta"] = meta

        resp = self._request("POST", f"{self.api_base}/posts", json=payload)
        resp.raise_for_status()
        post = resp.json()
        log.info(f"Created draft: {post['id']} - {title}")
        return post

    def upload_image(self, image_path, alt_text, caption="") -> int:
        """Upload an image to WordPress media library and return media_id."""
        path = Path(image_path)

        # Determine MIME type — add webp explicitly since mimetypes may not know it
        mime_type = mimetypes.guess_type(str(path))[0]
        if mime_type is None:
            ext = path.suffix.lower()
            mime_map = {".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}
            mime_type = mime_map.get(ext, "image/png")

        # Validate: file must be a real image (> 1 KB)
        file_size = path.stat().st_size
        if file_size < 1024:
            raise ValueError(f"Image file too small ({file_size} bytes), likely corrupt: {path}")

        log.info(f"Uploading image: {path.name} ({file_size:,} bytes, {mime_type})")

        # Read file data once, then use _request for retry/rate-limit handling
        with open(path, "rb") as f:
            file_data = f.read()

        # Temporarily swap headers for binary upload
        original_headers = self.headers.copy()
        self.headers["Content-Type"] = mime_type
        self.headers["Content-Disposition"] = f'attachment; filename="{path.name}"'

        try:
            resp = self._request(
                "POST",
                f"{self.api_base}/media",
                data=file_data,
                timeout=60,
            )
        finally:
            # Restore original headers
            self.headers = original_headers

        resp.raise_for_status()
        media = resp.json()
        media_id = media["id"]

        # Set alt text via PATCH
        if alt_text:
            self._request(
                "POST",
                f"{self.api_base}/media/{media_id}",
                json={"alt_text": alt_text, "caption": caption},
            )

        log.info(f"Uploaded image: {media_id} - {path.name}")
        return media_id

    def set_featured_image(self, post_id, media_id) -> bool:
        """Set the featured image for a post."""
        resp = self._request(
            "POST",
            f"{self.api_base}/posts/{post_id}",
            json={"featured_media": media_id},
        )
        return 200 <= resp.status_code < 300

    def assign_taxonomy(self, post_id, category_ids, tag_ids) -> bool:
        """Assign categories and tags to a post."""
        # Filter out invalid IDs (0 means lookup failed)
        valid_categories = [cid for cid in (category_ids or []) if cid and cid > 0]
        valid_tags = [tid for tid in (tag_ids or []) if tid and tid > 0]

        if not valid_categories and not valid_tags:
            log.warning("No valid taxonomy IDs to assign")
            return True  # Nothing to do, not an error

        payload = {}
        if valid_categories:
            payload["categories"] = valid_categories
        if valid_tags:
            payload["tags"] = valid_tags

        resp = self._request(
            "POST", f"{self.api_base}/posts/{post_id}", json=payload
        )
        return 200 <= resp.status_code < 300

    def get_category_id(self, slug) -> int:
        """Look up category ID by slug, using cache."""
        if slug in self._category_cache:
            return self._category_cache[slug]

        resp = self._request("GET", f"{self.api_base}/categories?slug={slug}")
        data = resp.json()
        if data:
            cat_id = data[0]["id"]
            self._category_cache[slug] = cat_id
            return cat_id

        log.warning(f"Category not found: {slug}")
        return 0

    def get_tag_id(self, slug) -> int:
        """Look up tag ID by slug; create tag if it doesn't exist."""
        if slug in self._tag_cache:
            return self._tag_cache[slug]

        resp = self._request("GET", f"{self.api_base}/tags?slug={slug}")
        data = resp.json()
        if data:
            tag_id = data[0]["id"]
            self._tag_cache[slug] = tag_id
            return tag_id

        # Create tag if it doesn't exist
        resp = self._request(
            "POST", f"{self.api_base}/tags", json={"name": slug, "slug": slug}
        )
        if resp.status_code in (200, 201):
            tag_id = resp.json()["id"]
            self._tag_cache[slug] = tag_id
            log.info(f"Created tag: {slug} -> {tag_id}")
            return tag_id

        log.warning(f"Failed to create tag: {slug}")
        return 0

    def set_seo_meta(self, post_id, seo_title, meta_desc, focus_keyword,
                     secondary_keywords=None, robots="index,follow") -> bool:
        """Set Rank Math SEO meta fields on a post."""
        meta = {
            "rank_math_title": seo_title,
            "rank_math_description": meta_desc,
            "rank_math_focus_keyword": focus_keyword,
            "rank_math_robots": robots,
        }

        # Secondary keywords for Rank Math scoring
        if secondary_keywords:
            if isinstance(secondary_keywords, list):
                meta["rank_math_focus_keyword"] = ",".join(
                    [focus_keyword] + secondary_keywords[:4]
                )

        resp = self._request(
            "POST",
            f"{self.api_base}/posts/{post_id}",
            json={"meta": meta},
        )
        return 200 <= resp.status_code < 300

    def set_social_meta(self, post_id, title, description, image_url="",
                        author_twitter="@RevHeat") -> bool:
        """Set OpenGraph + Twitter Card meta via Rank Math custom fields.

        Rank Math stores OG/Twitter meta as post meta fields. When present,
        it renders the corresponding <meta> tags in the HTML head.
        """
        meta = {
            # OpenGraph
            "rank_math_facebook_title": title,
            "rank_math_facebook_description": description,
            # Twitter Card
            "rank_math_twitter_use_facebook": "on",  # Mirror OG fields
            "rank_math_twitter_card_type": "summary_large_image",
            "rank_math_twitter_title": title,
            "rank_math_twitter_description": description,
            "rank_math_twitter_creator": author_twitter,
        }

        if image_url:
            meta["rank_math_facebook_image"] = image_url
            meta["rank_math_twitter_image"] = image_url

        resp = self._request(
            "POST",
            f"{self.api_base}/posts/{post_id}",
            json={"meta": meta},
        )
        if resp.status_code == 200:
            log.info(f"Set OG/Twitter meta for post {post_id}")
        return 200 <= resp.status_code < 300

    def set_canonical_url(self, post_id, canonical_url) -> bool:
        """Set canonical URL via Rank Math meta field."""
        resp = self._request(
            "POST",
            f"{self.api_base}/posts/{post_id}",
            json={
                "meta": {
                    "rank_math_canonical_url": canonical_url,
                }
            },
        )
        return 200 <= resp.status_code < 300

    def schedule_post(self, post_id, publish_datetime) -> bool:
        """Schedule a post for future publication."""
        import random
        # Add random offset (0-180 min) to avoid pattern detection
        offset_minutes = random.randint(0, 180)
        from datetime import timedelta
        adjusted = publish_datetime + timedelta(minutes=offset_minutes)

        resp = self._request(
            "POST",
            f"{self.api_base}/posts/{post_id}",
            json={"status": "future", "date": adjusted.isoformat()},
        )
        log.info(f"Scheduled post {post_id} for {adjusted.isoformat()}")
        return 200 <= resp.status_code < 300

    def publish_now(self, post_id) -> bool:
        """Publish a post immediately."""
        resp = self._request(
            "POST",
            f"{self.api_base}/posts/{post_id}",
            json={"status": "publish"},
        )
        return 200 <= resp.status_code < 300

    def get_draft_queue(self) -> list[dict]:
        """Get list of draft posts, ordered by date."""
        resp = self._request(
            "GET",
            f"{self.api_base}/posts?status=draft&per_page=20&orderby=date",
        )
        posts = resp.json()
        return [
            {
                "id": p["id"],
                "title": p["title"]["rendered"],
                "date": p["date"],
                "link": p["link"],
            }
            for p in posts
        ]

    def get_all_posts(self, per_page=100) -> list[dict]:
        """Get all published posts, paginating through all pages."""
        all_posts = []
        page = 1
        while True:
            resp = self._request(
                "GET",
                f"{self.api_base}/posts?per_page={per_page}&page={page}&status=publish",
            )
            if resp.status_code == 400:
                # No more pages
                break
            posts = resp.json()
            if not posts:
                break
            all_posts.extend(posts)
            page += 1
        return all_posts

    def delete_post(self, post_id, force=True) -> bool:
        """Delete a post (used in testing cleanup)."""
        resp = self._request(
            "DELETE",
            f"{self.api_base}/posts/{post_id}?force={'true' if force else 'false'}",
        )
        return 200 <= resp.status_code < 300

    def delete_media(self, media_id, force=True) -> bool:
        """Delete a media item (used in testing cleanup)."""
        resp = self._request(
            "DELETE",
            f"{self.api_base}/media/{media_id}?force={'true' if force else 'false'}",
        )
        return 200 <= resp.status_code < 300

    def ping_indexing(self, post_url) -> bool:
        """Notify Google Indexing API about a new/updated URL."""
        service_account_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not service_account_path or not os.path.exists(service_account_path):
            log.warning("Google service account not configured, skipping indexing ping")
            return False

        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request as GoogleRequest

            credentials = service_account.Credentials.from_service_account_file(
                service_account_path,
                scopes=["https://www.googleapis.com/auth/indexing"],
            )
            credentials.refresh(GoogleRequest())

            resp = requests.post(
                "https://indexing.googleapis.com/v3/urlNotifications:publish",
                headers={
                    "Authorization": f"Bearer {credentials.token}",
                    "Content-Type": "application/json",
                },
                json={"url": post_url, "type": "URL_UPDATED"},
                timeout=15,
            )
            log.info(f"Indexing ping for {post_url}: {resp.status_code}")
            return 200 <= resp.status_code < 300
        except ImportError:
            log.warning("google-auth not installed, skipping indexing ping")
            return False
        except Exception as e:
            log.error(f"Indexing ping failed: {e}")
            return False
