#!/usr/bin/env python3
"""Daily execution entry point for RevHeat Blog Engine."""

import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.content_engine import ContentEngine
from src.utils.logger import setup_logging


def write_last_run(project_root: Path, success: bool, message: str = ""):
    """Write a last_run.txt for health check monitoring."""
    last_run_path = project_root / "logs" / "last_run.txt"
    last_run_path.parent.mkdir(parents=True, exist_ok=True)
    status = "SUCCESS" if success else "FAILURE"
    timestamp = datetime.now(timezone.utc).isoformat()
    last_run_path.write_text(f"{status}\n{timestamp}\n{message}\n")


def main():
    setup_logging()

    try:
        engine = ContentEngine(config_path="config.yaml")
        result = engine.run_daily()

        # Handle burst mode (list of results) or single result
        if isinstance(result, list):
            titles = []
            for r in result:
                print(f"Draft created: {r.draft.title}")
                print(f"   Edit: https://revheat.com/wp-admin/post.php?post={r.post_id}&action=edit")
                titles.append(f"Post #{r.post_id}: {r.draft.title}")
            message = f"Burst: {len(result)} posts published\n" + "\n".join(titles)
            write_last_run(PROJECT_ROOT, success=True, message=message)
        else:
            print(f"Draft created: {result.draft.title}")
            print(f"   Edit: https://revheat.com/wp-admin/post.php?post={result.post_id}&action=edit")
            write_last_run(PROJECT_ROOT, success=True, message=f"Post #{result.post_id}: {result.draft.title}")
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        write_last_run(PROJECT_ROOT, success=False, message=str(e))
        raise


if __name__ == "__main__":
    main()
