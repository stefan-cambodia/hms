# 3. Channel Manager, Booking.com and Agoda Strategy

This covers deliverables 7 (Booking.com) and 8 (Agoda). It rests on primary-source
research recorded in [`docs/research/ota-connectivity.md`](../research/ota-connectivity.md)
(researched 2026-11-12, every claim linked to its source).

## 3.1 Findings that drive the design

| Platform | Direct connection possible for this project today? | Why |
|----------|-----------------------------------------------------|-----|
| **Booking.com** | **No** | connect.booking.com states Booking.com is *pausing integrations with new connectivity providers* and *does not accept direct connections from individual properties*. |
| **Agoda** | **Not realistically, for now** | Requires Agoda Tech Partner status (questionnaire written for channel-manager businesses, contract) and certification with a **pilot on 2–3 live properties**. |
| **SiteMinder (pmsXchange)** | **Yes, with a partnership agreement** | A PMS-facing API built for this purpose. SiteMinder then distributes to Booking.com, Agoda and other channels. Public documentation; **shared public test credentials** allow building and verifying ARI push and mapping retrieval before signing; certification needs **one** pilot property (~60 days end to end). The hotel needs its own SiteMinder subscription. |
| Cloudbeds | No (as an intermediary) | Its API extends the Cloudbeds PMS; the terms prohibit using it to compete with Cloudbeds products. |

**Decision.** For a single self-built PMS, connecting to Booking.com and Agoda
through an approved intermediary (SiteMinder pmsXchange) is the only route that is
both legal and achievable. Direct Booking.com and Agoda adapters stay part of the
architecture, but are built only once the hotel (or the software vendor) obtains
partner access. **Nothing is simulated in the meantime.** No fake connection,
no fake reservations, and no "connected" badge unless a real call succeeded.

## 3.2 Architecture

```
            business tx (reservation, rate, block, room change)
                    │  same transaction
                    ▼
        channel_dirty_ranges (connection, room_type, rate_plan, from, to)   ◀── coalesced
                    │
          worker: ARI sync job (per connection, one in flight at a time)
                    │ 1. compute CURRENT availability/rates/restrictions (inventory + pricing services)
                    │ 2. diff against channel_ari_state (last values the channel acknowledged)
                    │ 3. send only the deltas (provider message limits, batching)
                    │ 4. on success → update channel_ari_state; on failure → retry with backoff
                    ▼
            ChannelAdapter  ── SiteMinderPmsxAdapter | BookingComAdapter* | AgodaYcsAdapter*
                    ▲                                    (*built when partner access exists)
                    │ poll (pull) or receive (push)
        channel_inbound_reservations (idempotent on connection + external id + message id)
                    │
          reservation import service → reservations engine (same rules as manual bookings,
                                         except OTA bookings are never rejected: overbooking is
                                         flagged and alerted instead)
                    │
                    └─▶ marks the affected range dirty → availability pushed back to all channels
```

### Adapter contract (`app/modules/channels/adapters/base.py`)

```python
class ChannelAdapter(Protocol):
    channel: str                                        # "siteminder", "booking_com", "agoda"
    capabilities: set[Capability]                       # ARI_PUSH, RES_PULL, RES_PUSH, MAPPING_FETCH, ...
    async def test_connection(self, conn) -> TestResult            # a real call; never mocked in prod
    async def fetch_mapping(self, conn) -> list[ExternalRoomRate]  # if supported
    async def push_ari(self, conn, deltas: list[AriDelta]) -> PushResult
    async def pull_reservations(self, conn) -> list[InboundReservation]
    async def confirm_reservations(self, conn, ids: list[ConfirmItem]) -> None
```

The core (dirty ranges, delta computation, retries, idempotent import, logging,
dashboard) is provider-independent. An adapter only translates messages and
handles transport.

### Design rules derived from the provider documentation

| Rule | Source requirement |
|------|-------------------|
| **Delta-only ARI**: store the last-acknowledged value per (connection, room type, rate plan, date) in `channel_ari_state` and send only differences. Full refresh only on explicit operator action or after re-mapping. | SiteMinder: delta updates "strictly enforced", frequent full flushes prohibited. |
| **Fresh, not stale**: jobs carry *ranges*, not values; values are computed when the job runs, so a delayed job never sends outdated data. | Our offline requirement (§1.6 of the architecture). |
| **Latency**: changes are pushed within 2 minutes; one in-flight request per property; wait for the response before sending the next. | SiteMinder integration requirements. |
| **Atomic, size-limited messages**: split payloads under 2 MB; treat a failed message as entirely failed. | SiteMinder. |
| **Idempotent ingestion** keyed on (connection, external reservation id, message/revision id); out-of-order modifications handled (a modify can arrive before the original "new"). | Redelivery: Booking.com until acknowledged, SiteMinder retries for hours, Agoda overlapping polls. |
| **Confirm after commit**: acknowledge or confirm a reservation to the provider only *after* it is committed locally. | All three providers re-deliver unconfirmed bookings. |
| **Push availability after every imported reservation.** | SiteMinder requirement; also our unified-inventory rule. |
| **Pull by default** (OTA_ReadRQ every 2–5 min + OTA_NotifReportRQ). Push receiver available for cloud deployments with a public HTTPS domain. | On-premise hotel servers usually cannot accept inbound HTTPS. |
| **Mapping verification**: fetch the provider's room/rate mapping and flag every local room type or rate plan that is unmapped, because an unmapped code is *silently ignored* by SiteMinder. | SiteMinder FAQ. |
| **Currency**: rates are pushed in the rate plan's configured currency, with no implicit conversion. | SiteMinder rate push requires `CurrencyCode`. |

## 3.3 Payment card data (open decision)

Reservation messages from every route can contain full card numbers. This PMS
**never stores card data** (security strategy §4.3). Before reservation import
goes live, the hotel must pick one of:

1. **Channel-collect / virtual-card only**: configure channels so the PMS receives no card numbers. If one arrives anyway, the adapter drops the card elements in memory and stores only brand and last 4 digits.
2. **Tokenisation proxy**: SiteMinder supports certified proxies (FreedomPay for push, Payrails for pull) under separate agreements, so the PMS receives tokens instead of card numbers.

Raw provider payloads are stored for diagnostics **only after card fields have been
redacted**, and this is covered by tests.

## 3.4 Connection states shown to staff

| State | Meaning |
|-------|---------|
| `not_configured` | No credentials. The PMS works fully; OTA bookings can be entered manually with their source. |
| `credentials_saved` | Credentials stored (encrypted). No successful call yet. |
| `test_ok` | `test_connection` succeeded against the provider's **test** environment, at the timestamp shown. |
| `live` | A production call succeeded within the last sync interval. |
| `degraded` | Live, but recent failures are pending retry (with the count and the last error). |
| `paused` | Disabled by an administrator; changes still accumulate as dirty ranges and are sent on resume. |

The dashboard shows, per connection: last successful push and pull, pending
dirty ranges, failed/dead jobs, recent message log (redacted), unmapped room
types/rate plans, and manual "sync now" / "full refresh" controls.

## 3.5 Delivery status (Phase 7)

1. **Core — done and tested** (`app/modules/channels/`):
   * Change queue written by database triggers (`channel_dirty_ranges`), so no code path can forget to notify the channels.
   * Delta computation from the inventory and pricing engines against the acknowledged state; consecutive nights with the same value are merged into ranges; only the restriction types that changed are sent.
   * Plan conditions (inactive, validity dates, booking window, categories) are sent as a stop sell; availability is never negative; MinLOS ≤ MaxLOS.
   * Worker: one leader among API processes (PostgreSQL advisory lock), one request at a time per property, changes sent within seconds (polling every 5 s), backoff 5 s → 30 min on failure, state shown to staff.
   * Reservation import through the reservations engine:
     * idempotent per revision, tolerant of out-of-order messages;
     * never refused (overbooking is flagged and announced);
     * channel prices converted to the hotel's tax convention and currency;
     * modification applied in place (same reservation number);
     * cancellation without fee (the channel applies its own terms);
     * acknowledgement only after the local commit, and failures reported to the provider with a readable text.
   * Card data: brand and last 4 digits only; message bodies redacted before storage.
   * Screens: connection, mapping, received bookings, activity log.
   * Tested with an in-memory adapter that exists only in the test suite.
2. **SiteMinder pmsXchange adapter — implemented, contract-tested, not yet verified live.**
   * Implemented: availability, restrictions and PDP rates push; room-rates mapping fetch (also used as the connection test); reservation pull and confirmation.
   * Messages are built and parsed with SiteMinder's own published samples as fixtures (`tests/fixtures/siteminder/`), including the minified envelope, the restriction, rate, read and confirmation messages and the reservation samples, plus an end-to-end exchange over the HTTP layer.
   * XML from the provider is parsed with `defusedxml`.
   * The live check against SiteMinder's public test environment (`tests/test_siteminder_live.py`, shared credentials published by SiteMinder for this purpose) **has not been run yet**. Until it passes, the adapter is not reported as working. To run it:

     ```bash
     cd backend
     HMS_SITEMINDER_LIVE=1 HMS_SITEMINDER_USERNAME=<username> HMS_SITEMINDER_PASSWORD=<password> \
       .venv/bin/pytest -s tests/test_siteminder_live.py
     ```

     (username and password: SiteMinder's public Postman workspace, environment "pmsXchange - Rooms and Rates TEST").
   * Reservation pull can only be verified with a partner test account (the shared hotels return no reservations).
   * Not implemented: OBP (occupancy-based) rates (PDP only), reservation push delivery (pull is used; push needs a public HTTPS endpoint), unmapped-rate delivery, virtual card handling, payment transaction records.
3. Booking.com and Agoda direct adapters: **not started** until partner access is granted.

## 3.6 Onboarding procedure for the hotel (summary)

1. **Today, without any agreement:** the PMS manages inventory, rates and reservations. Booking.com and Agoda bookings received by email or extranet are entered with the right source. Availability is kept in sync manually in the extranets, and the dashboard says so explicitly.
2. **Via SiteMinder:**
   - The software vendor applies to the SiteMinder partner programme and signs the agreement.
   - The hotel subscribes to SiteMinder and connects Booking.com and Agoda inside SiteMinder.
   - In the PMS, the administrator enters the SiteMinder credentials and HotelCode, maps room types and rate plans, and runs the connection test.
   - Certification follows with the hotel as pilot property, then go-live.
3. **Direct Booking.com / Agoda:** only if their programmes accept this vendor (Booking.com is currently closed to new providers; Agoda requires a pilot on 2–3 properties).
