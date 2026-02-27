#!/usr/bin/env python3
"""Verify WordPress API connection and permissions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.logger import setup_logging


def main():
    setup_logging()
    print("Verifying WordPress connection...")

    try:
        from src.wp_publisher import WordPressPublisher
        wp = WordPressPublisher()
        print(f"  Connected to: {wp.base_url}")

        # Test creating and deleting a draft
        print("  Creating test draft...")
        post = wp.create_draft(
            "[TEST] RevHeat Blog Engine Verification",
            "<p>This is an automated test post. It will be deleted immediately.</p>",
        )
        print(f"  Draft created: #{post['id']}")

        print("  Deleting test draft...")
        wp.delete_post(post["id"])
        print("  Test draft deleted")

        print("\nWordPress connection verified successfully!")
        return 0

    except Exception as e:
        print(f"\nConnection FAILED: {e}")
        print("\nPlease check:")
        print("  1. WP_URL is correct in .env")
        print("  2. WP_USERNAME is correct in .env")
        print("  3. WP_APP_PASSWORD is a valid WordPress Application Password")
        print("  4. The REST API is accessible at {WP_URL}/wp-json/wp/v2/")
        return 1


if __name__ == "__main__":
    sys.exit(main())
