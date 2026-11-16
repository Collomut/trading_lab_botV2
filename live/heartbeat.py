"""Process health / heartbeat."""
from __future__ import annotations

import time


class Heartbeat:
    def __init__(self, check_interval_seconds: int = 30):
        self.check_interval_seconds = check_interval_seconds
        self.last_cycle_ok: bool | None = None
        self.last_cycle_at: float | None = None

    def beat(self, ok: bool) -> None:
        self.last_cycle_ok = bool(ok)
        self.last_cycle_at = time.time()

    def is_alive(self, max_age_seconds: int = 300) -> bool:
        if self.last_cycle_at is None:
            return False
        return (time.time() - self.last_cycle_at) <= max_age_seconds
