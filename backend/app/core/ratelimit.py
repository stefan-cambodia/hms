"""In-process sliding-window rate limiter.

Per-process is sufficient for the login endpoint because account lockout (stored
in the database) is the cross-process protection; this limiter only throttles
bursts from one IP. Caddy applies a global per-IP limit in front of it.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> bool:
        """Record a hit; return False if the key is over its limit."""
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self._hits) > 10_000:  # bound memory under address-spoofing floods
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                del self._hits[k]
        return True

    def reset(self) -> None:
        self._hits.clear()
