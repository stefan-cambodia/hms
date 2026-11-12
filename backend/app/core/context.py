"""Who is acting, and in which hotel. Passed explicitly to services."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    session_id: uuid.UUID | None = None
    is_superadmin: bool = False
    ip: str | None = None
    request_id: str | None = None
    source: str = "api"  # api | worker | channel | cli

    @classmethod
    def system(cls, organization_id: uuid.UUID | None = None, source: str = "worker") -> Actor:
        return cls(user_id=None, organization_id=organization_id, source=source)


@dataclass(frozen=True, slots=True)
class HotelContext:
    actor: Actor
    hotel_id: uuid.UUID
    permissions: frozenset[str] = field(default_factory=frozenset)

    def has(self, permission: str) -> bool:
        return permission in self.permissions
