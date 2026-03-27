from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ReviewPolicy:
    name: str
    url: str
    description: str = ""


class ReviewSource:
    """Single source of truth for lab review policy/SOP."""

    def get_policy(self) -> Optional[ReviewPolicy]:
        raise NotImplementedError()


class ConfigReviewSource(ReviewSource):
    def __init__(self, config: dict) -> None:
        self.config = config or {}

    def get_policy(self) -> Optional[ReviewPolicy]:
        review_cfg = self.config.get("review", {}) if isinstance(self.config, dict) else {}
        root_url = (review_cfg.get("root_url") or "").strip()
        if not root_url:
            return None
        return ReviewPolicy(
            name=(review_cfg.get("name") or "Lab SOP").strip(),
            url=root_url,
            description=(review_cfg.get("description") or "").strip(),
        )
