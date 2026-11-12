"""Gapless per-hotel document numbering (reservations, invoices, receipts).

The counter row is incremented with an upsert, which keeps a row lock until
the transaction ends: concurrent issuers queue behind each other, and a
transaction that rolls back also rolls back its increment. Committed numbers
are therefore unique and contiguous (no gaps), as invoice law usually requires.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def next_value(db: AsyncSession, hotel_id: uuid.UUID, kind: str) -> int:
    n = await db.scalar(
        text(
            "INSERT INTO document_sequences (hotel_id, kind, next_value) VALUES (:h, :k, 2) "
            "ON CONFLICT (hotel_id, kind) DO UPDATE SET next_value = document_sequences.next_value + 1 "
            "RETURNING next_value - 1"
        ),
        {"h": hotel_id, "k": kind},
    )
    return int(n)
