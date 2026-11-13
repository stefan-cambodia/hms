from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from app.core.schemas import InputModel, SafeText


class CloseIn(InputModel):
    notes: Annotated[SafeText, StringConstraints(max_length=2000)] | None = None
    # Required when items are still open (guests expected, checks open...):
    # closing records them as they are.
    accept_open_items: bool = False


class HistoryQuery(InputModel):
    limit: int = Field(30, ge=1, le=366)
