"""Rate limiter shared by every API process, stored in PostgreSQL.

Used for the login endpoint (per client IP). Account lockout, also stored in the
database, protects each account; this limiter throttles bursts from one address
whichever API process or server receives them. Caddy applies a coarser global
per-IP limit in front of it.

Algorithm: sliding window approximated from two fixed windows (the current
and the previous one, weighted by how much of it still overlaps the window).
Counters live in an UNLOGGED table: losing them in a crash only resets the
throttle, and nothing else depends on them.
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import sessionmaker

_HIT = text(
    """
    WITH cur AS (
        INSERT INTO rate_limit_buckets (key, bucket, hits)
        VALUES (:key, to_timestamp(floor(extract(epoch FROM clock_timestamp()) / :window) * :window), 1)
        ON CONFLICT (key, bucket) DO UPDATE SET hits = rate_limit_buckets.hits + 1
        RETURNING bucket, hits
    )
    SELECT cur.hits,
           coalesce(prev.hits, 0),
           extract(epoch FROM clock_timestamp() - cur.bucket)
    FROM cur
    LEFT JOIN rate_limit_buckets prev
      ON prev.key = :key AND prev.bucket = cur.bucket - make_interval(secs => :window)
    """
)

_PURGE = text("DELETE FROM rate_limit_buckets WHERE bucket < clock_timestamp() - make_interval(secs => :w)")


class DbRateLimiter:
    def __init__(self, scope: str, limit: int, window_seconds: int) -> None:
        self.scope = scope
        self.limit = limit
        self.window = window_seconds

    async def hit(self, key: str) -> bool:
        """Record a hit; return False if the key is over its limit.

        Runs in its own short transaction so the count is kept whatever the
        caller's transaction does afterwards."""
        async with sessionmaker()() as db:
            current, previous, elapsed = (
                await db.execute(_HIT, {"key": f"{self.scope}:{key}"[:200], "window": self.window})
            ).one()
            if current == 1:  # a new window began for this key: forget old windows
                await db.execute(_PURGE, {"w": self.window * 3})
            await db.commit()
        weight = max(0.0, 1.0 - float(elapsed) / self.window)
        return current + previous * weight <= self.limit
