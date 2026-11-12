"""Live checks against SiteMinder's public pmsXchange TEST environment.

Skipped unless HMS_SITEMINDER_LIVE=1. SiteMinder publishes shared test
credentials for this purpose (developer.siteminder.com, pmsXchange Quick
Start: PMS code PMSXTEST, hotels PMSXTEST1-3, username/password in its public
Postman workspace). They are read from the environment, never stored here:

    HMS_SITEMINDER_LIVE=1 HMS_SITEMINDER_USERNAME=... HMS_SITEMINDER_PASSWORD=... \
        pytest tests/test_siteminder_live.py -s

Only test data is sent, for dates about ten months ahead, to the shared test
hotel. The shared hotels return no reservations, so the pull check only
proves that the request is accepted.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.channels.adapters.base import (
    ConnectionConfig,
    InventoryUpdate,
    RateUpdate,
    RestrictionUpdate,
)
from app.modules.channels.adapters.siteminder import SiteMinderAdapter

pytestmark = pytest.mark.skipif(os.environ.get("HMS_SITEMINDER_LIVE") != "1", reason="live SiteMinder check")


def conn() -> ConnectionConfig:
    return ConnectionConfig(
        endpoint_url=None,
        environment="test",
        account_code=os.environ.get("HMS_SITEMINDER_PMS_CODE", "PMSXTEST"),
        username=os.environ["HMS_SITEMINDER_USERNAME"],
        password=os.environ["HMS_SITEMINDER_PASSWORD"],
        hotel_code=os.environ.get("HMS_SITEMINDER_HOTEL_CODE", "PMSXTEST1"),
    )


async def test_live_siteminder_test_environment():
    adapter = SiteMinderAdapter()
    log: list = []
    c = conn()
    result = await adapter.test_connection(c, log.append)
    print("test connection:", result)
    assert result.ok, result.message
    products = await adapter.fetch_mapping(c, log.append)
    print("room rates:", [(p.room_code, p.rate_code, p.included_occupancy) for p in products])
    product = next(p for p in products if p.rate_code)
    day = date.today() + timedelta(days=300)

    await adapter.push_inventory(c, [InventoryUpdate(product.room_code, day, day, 3)], log.append)
    await adapter.push_restrictions(
        c, [RestrictionUpdate(product.room_code, product.rate_code or "", day, day, closed=False)], log.append
    )
    await adapter.push_rates(
        c,
        [RateUpdate(product.room_code, product.rate_code or "", day, day, Decimal("101.00"), "USD", True)],
        log.append,
    )
    bookings = await adapter.pull_bookings(c, log.append)
    print("pulled:", len(bookings))
    for e in log:
        print(f"{e.operation:24} {e.outcome:6} HTTP {e.http_status} {e.duration_ms:5} ms  {e.summary}")
        assert c.password not in (e.request_body or "")  # redacted before logging
    assert all(e.outcome == "ok" for e in log)
