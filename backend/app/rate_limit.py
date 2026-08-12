"""Minimal in-memory sliding-window rate limiter for public tracking endpoints.

Dependency-free (no Redis required) which keeps the demo simple. For a
multi-process production deployment swap this for a shared store (Redis).
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from .config import settings


class SlidingWindowRateLimiter:
    def __init__(self, max_per_minute: int, window_seconds: float = 60.0) -> None:
        self.max = max_per_minute
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        dq = self._hits[key]
        while dq and now - dq[0] > self.window:
            dq.popleft()
        if len(dq) >= self.max:
            return False
        dq.append(now)
        return True


tracking_limiter = SlidingWindowRateLimiter(settings.tracking_rate_limit_per_minute)
