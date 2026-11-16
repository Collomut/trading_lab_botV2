"""Cycle scheduling helpers."""
from __future__ import annotations

from datetime import datetime, timezone


class TradingScheduler:
    def __init__(self, interval_seconds: int = 60):
        self.interval_seconds = max(1, int(interval_seconds))

    def next_cycle_time(self, now: datetime | None = None) -> datetime:
        now = now or datetime.now(timezone.utc)
        return now

    def should_run(self, last_cycle: datetime | None, now: datetime | None = None) -> bool:
        if last_cycle is None:
            return True
        now = now or datetime.now(timezone.utc)
        return (now - last_cycle).total_seconds() >= self.interval_seconds
