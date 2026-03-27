from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, TypeVar

T = TypeVar("T")


@dataclass
class BatchPlan:
    items: List[T]
    batch_size: int

    def batches(self) -> Iterable[Sequence[T]]:
        for i in range(0, len(self.items), self.batch_size):
            yield self.items[i : i + self.batch_size]


def build_batch_plan(items: List[T], batch_size: int) -> BatchPlan:
    safe_size = max(1, int(batch_size or 1))
    return BatchPlan(items=items, batch_size=safe_size)
