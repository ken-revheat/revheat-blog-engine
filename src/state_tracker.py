"""State Tracker — persists published topic history to prevent duplicate content."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import yaml

log = logging.getLogger(__name__)


class StateTracker:
    """Tracks which topics have been published to prevent repeats."""

    def __init__(self, state_path="data/published_state.yaml"):
        self.state_path = state_path
        self.state = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                return yaml.safe_load(f) or {}
        return {"published": [], "last_run": None}

    def _save(self):
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        with open(self.state_path, "w") as f:
            yaml.dump(self.state, f, default_flow_style=False, sort_keys=False)

    def is_published(self, slug: str) -> bool:
        """Check if a topic slug has already been published."""
        published_slugs = {
            entry["slug"]
            for entry in self.state.get("published", [])
            if isinstance(entry, dict) and "slug" in entry
        }
        return slug in published_slugs

    def get_published_slugs(self) -> set[str]:
        """Return all published slugs."""
        return {
            entry["slug"]
            for entry in self.state.get("published", [])
            if isinstance(entry, dict) and "slug" in entry
        }

    def record_publish(self, slug: str, title: str, post_id: int, pillar: str = "", function: str = ""):
        """Record a newly published topic."""
        if "published" not in self.state:
            self.state["published"] = []

        self.state["published"].append({
            "slug": slug,
            "title": title,
            "post_id": post_id,
            "pillar": pillar,
            "function": function,
            "published_at": datetime.now(timezone.utc).isoformat(),
        })
        self.state["last_run"] = datetime.now(timezone.utc).isoformat()
        self._save()
        log.info(f"Recorded publish: {slug} (post #{post_id})")

    def record_run(self):
        """Record that the daily engine ran (even if no post was created)."""
        self.state["last_run"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def get_last_run(self) -> str | None:
        """Return ISO timestamp of last run, or None."""
        return self.state.get("last_run")

    def get_pillar_counts(self) -> dict[str, int]:
        """Return count of published posts per pillar for balance tracking."""
        counts: dict[str, int] = {}
        for entry in self.state.get("published", []):
            if isinstance(entry, dict):
                pillar = entry.get("pillar", "unknown")
                counts[pillar] = counts.get(pillar, 0) + 1
        return counts
