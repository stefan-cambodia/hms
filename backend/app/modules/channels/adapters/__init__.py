"""Adapter registry. Only real provider adapters are registered here; the
test suite registers its own in-memory adapter, which can never be selected
in the product (the API only accepts the providers in models.PROVIDERS)."""

from __future__ import annotations

from app.modules.channels.adapters.base import ChannelAdapter
from app.modules.channels.adapters.siteminder import SiteMinderAdapter

ADAPTERS: dict[str, ChannelAdapter] = {"siteminder": SiteMinderAdapter()}


def get_adapter(provider: str) -> ChannelAdapter:
    try:
        return ADAPTERS[provider]
    except KeyError:
        raise LookupError(f"No adapter for provider {provider!r}") from None
