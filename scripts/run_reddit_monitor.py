#!/usr/bin/env python3
"""Reddit monitor execution entry point."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reddit_monitor import RedditMonitor
from src.utils.logger import setup_logging


def main():
    setup_logging()
    monitor = RedditMonitor(config_path="data/reddit_config.yaml")
    opportunities = monitor.run()
    print(f"Reddit monitor complete: {len(opportunities)} opportunities found")

    for opp in sorted(opportunities, key=lambda o: o.priority_score, reverse=True)[:5]:
        print(f"  [{opp.urgency.upper()}] {opp.priority_score:.0f}/100 - {opp.thread.title}")


if __name__ == "__main__":
    main()
