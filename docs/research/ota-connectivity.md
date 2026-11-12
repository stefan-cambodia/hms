# OTA connectivity research: Booking.com, Agoda, SiteMinder, Cloudbeds

- **Purpose:** input for the design of the hms channel-manager module (FastAPI + PostgreSQL).
- **Researched:** 2026-11-12. All pages were fetched on that date. Vendors change these pages often, so re-check before committing to a design.
- **Method:** primary vendor documentation fetched directly. developers.booking.com is server-rendered HTML. developer.agoda.com, developer.siteminder.com and developers.cloudbeds.com all serve `.md` versions and an `llms.txt` index. Third-party pages are used only where noted.
- **Labels used below:**
  - No label: read on the vendor's own public site (primary source).
  - **[2nd-hand]:** found only on a third-party site, or in a search-engine summary I could not open myself.
  - **[unverified / memory]:** background knowledge that I did not confirm on any page during this research.

---

## 0. Decision summary

| | Booking.com | Agoda | SiteMinder (pmsXchange) | Cloudbeds |
|---|---|---|---|---|
| Can this project (one self-built PMS, one hotel) integrate directly today? | **No.** New providers are paused and individual properties are not accepted ([connect.booking.com](https://connect.booking.com/)) | **Unlikely, not impossible.** You apply through a questionnaire written for channel managers and PMS vendors, with no response timeline, and certification needs a pilot on 2–3 live properties ([become partner](https://developer.agoda.com/supply/docs/how-to-become-a-partner), [certification](https://developer.agoda.com/supply/docs/certification)) | **Plausible.** PMS partner programme. The application form asks how many hotels you serve but publishes no minimum. One pilot property is needed ([integration process](https://developer.siteminder.com/get-started/partner-lifecycle/integration-process.md)) | **Not a fit as an intermediary.** The API extends Cloudbeds' own PMS, and the terms forbid using it to compete with core Cloudbeds products ([about](https://developers.cloudbeds.com/docs/about-cloudbeds-api.md), [terms](https://developers.cloudbeds.com/docs/terms-and-conditions.md)) |
| Programme | Booking.com Connectivity Partner (Connectivity Partner Programme / Provider Portal) | Agoda Tech Partner (Connectivity Partner), YCS API | SiteMinder technology partner, pmsXchange API | Cloudbeds Technology Partner / Marketplace |
| Message format | OTA 2003B XML plus Booking.com B.XML plus some JSON | Proprietary XML over a single endpoint with a `type` code (YCS API). Separately, OTA 2013A/2015B for "direct connect" properties | SOAP 1.1 with OTA 2003/05 XML for ARI and reservations, REST/JSON for mapping and import | REST/JSON |
| Auth | Machine account client_id/secret exchanged for a JWT (1 h). IP allowlist optional | OAuth2 client credentials from the YCS "API access" page exchanged for a JWT (1 h). IP whitelist required. API keys stop working at end of 2026 | WS-Security UsernameToken (SOAP) and HTTP Basic (REST). One credential set covers all hotels | API key or OAuth2 |
| Reservations | **Pull.** Poll every 20 s and acknowledge. Unacknowledged bookings fall back to email after 30 min | **Pull** (GetBookingList, then GetBookingDetails), with an optional **push hint** (BookingHint). No API acknowledgement | **Push** (SiteMinder calls your SOAP endpoint and you must answer within 60 s) **or pull** (poll every 2–5 min, then confirm) | Webhooks plus GET (for Cloudbeds-PMS apps) |

---

## 1. Booking.com

### 1.1 Programme and how a vendor joins

- **Programme name.** Booking.com calls these companies "Booking.com Connectivity Partners", meaning companies that use the Connectivity APIs to manage availability, reservations and prices for properties ([About the Connectivity APIs](https://developers.booking.com/connectivity/docs)). Partners manage their connection offering in the "Provider Portal" and read articles in the "Connectivity Hub" ([docs](https://developers.booking.com/connectivity/docs)). The landing page also mentions a "Partner Programme" in which partners "earn points" for benefits ([connect.booking.com](https://connect.booking.com/)).
- **Onboarding is currently closed.** The landing page says: "Thank you for your interest in a connectivity partnership with Booking.com. In an effort to ensure our teams are able to provide the strong partnership experience, we are pausing integrations with new connectivity providers until further notice." ([connect.booking.com](https://connect.booking.com/), fetched 2026-11-12; the page carries no date).
- **Requirements.** "To become Booking.com Connectivity Partners, companies must meet specific onboarding requirements." That link leads to the Connectivity Portal topic catalogue at `portal.connectivity.booking.com`, which I could not read (see §6) ([docs](https://developers.booking.com/connectivity/docs)).
- **Ongoing expectations.** Partners should support all available API functions, "load at least a full year of rates and availability for each property", and "minimise the number of reservations falling back to e-mail" ([docs](https://developers.booking.com/connectivity/docs)).
- **Certification and compliance before go-live** ([Going Live](https://developers.booking.com/connectivity/docs/going_live)):
  - Reservations API needs **PCI and PII compliance** plus **certification** through Connectivity Support.
  - Rates & Availability API needs **certification**, covering the pricing types you implement.
  - Room type and rate plan management API needs certification. Connections API needs only a self-assessment.
  - Booking.com recommends "a small beta group for the first few weeks" after go-live.
- **Contracts and costs.** No costs are published. Every docs page ends with: "All information contained in this document is subject to the terms and conditions of your contractual agreement with Booking.com" ([docs](https://developers.booking.com/connectivity/docs)). The contract itself is not public.
- **Minimum property count.** Nothing in the public developer docs. **[2nd-hand]** A third-party summary (hospitable.com, seen via search) mentions region-specific minimum property counts, PCI/PII, real-time reservations and a year of ARI. I could not verify this.
- **Partner tiers.** The landing page mentions a points-based Partner Programme ([connect.booking.com](https://connect.booking.com/)). **[2nd-hand]** Tier names (Standard / Advanced / Premier / Premier Plus) appear only in vendor press releases such as travelnest.com and hoteltechreport.com.

### 1.2 Can a single hotel build its own direct connection?

**No.** The FAQ on connect.booking.com says: "I own a property listed on Booking.com. Can I use the Connectivity APIs? We don't accept direct connections from individual properties right now, but you can connect via a channel manager." ([connect.booking.com](https://connect.booking.com/)). Together with the pause on new providers, a direct Booking.com integration is not currently possible for this project.

### 1.3 API surface relevant to a channel manager

Base hosts ([docs](https://developers.booking.com/connectivity/docs)):

- `https://supply-xml.booking.com`: non-PCI traffic (ARI, content, mapping).
- `https://secure-supply-xml.booking.com`: PCI traffic (reservation retrieval and confirmation).
- HTTPS only, HTTP/1.1 over TLS 1.2.

| Function | Endpoint(s) | Format | Source |
|---|---|---|---|
| Availability (rooms to sell), open/close, restrictions | `POST /hotels/ota/OTA_HotelAvailNotif` | OTA XML | [OTA_HotelAvailNotif](https://developers.booking.com/connectivity/docs/ota-hotelavailnotif) |
| Rates | `POST /hotels/ota/OTA_HotelRateAmountNotif` | OTA XML | [OTA_HotelRateAmountNotif](https://developers.booking.com/connectivity/docs/ota-rateamountnotif) |
| All-in-one ARI (prices, roomstosell, closed, min/max stay, CTA/CTD, advance-booking window) | `POST /hotels/xml/availability` | B.XML | [B.XML availability](https://developers.booking.com/connectivity/docs/b_xml-availability) |
| Read current ARI before sending deltas | `roomRateAvailability` | B.XML | [b_xml-roomrateavailability](https://developers.booking.com/connectivity/docs/b_xml-roomrateavailability) (linked from the ARI pages; page not read in detail) |
| Room/rate mapping (list active room-rates) | `POST /hotels/xml/roomrates`, `GET OTA_HotelProductNotif` | B.XML / OTA | [ARI FAQ](https://developers.booking.com/connectivity/docs/con-faq-rates-availability), [docs header examples](https://developers.booking.com/connectivity/docs) |
| Create/manage room types and rate plans | Room type and rate plan management API | OTA / JSON | [Going Live](https://developers.booking.com/connectivity/docs/going_live), [understanding pricing types](https://developers.booking.com/connectivity/docs/understanding-pricing-types) |
| New reservations: retrieve, then acknowledge | `GET` then `POST /hotels/ota/OTA_HotelResNotif` | OTA XML | [retrieving new](https://developers.booking.com/connectivity/docs/reservations-api/retrieving-new-reservations-ota), [acknowledging new](https://developers.booking.com/connectivity/docs/reservations-api/acknowledging-new-reservations-ota) |
| Modifications and cancellations: retrieve, then acknowledge | `GET` then `POST /hotels/ota/OTA_HotelResModifyNotif` | OTA XML | [retrieving modified/cancelled](https://developers.booking.com/connectivity/docs/reservations-api/retrieving-modifcancel-reservations-ota) |
| All reservation types in one call, **no acknowledgement** | `POST /hotels/xml/reservations` | B.XML | [reservations overview](https://developers.booking.com/connectivity/docs/reservations-api/reservations-overview) |
| Backfill (reservations made before the property connected) | `/xml/reservationssummary` | B.XML | [reservations overview](https://developers.booking.com/connectivity/docs/reservations-api/reservations-overview) |
| Missed-reservation recovery | `GET /reservations-flow-control/missed-reservations` | JSON | [Reservation Recovery API](https://developers.booking.com/connectivity/docs/reservations-flow-control-api/reservations-recovery-overview) |
| Accept or reject property connection requests | Connections API | JSON | [Connections API](https://developers.booking.com/connectivity/docs/connections-api/connections-overview) |
| Content, photos, property creation | Content / Property / Rooms / Photo / Licences APIs | OTA / JSON | [home](https://developers.booking.com/connectivity/home), [Going Live](https://developers.booking.com/connectivity/docs/going_live) |
| Event notifications (not reservations) | Connectivity Notification Service, a webhook to your endpoint | JSON | [CNS overview](https://developers.booking.com/connectivity/docs/notification-service/notification-service-overview) |

**Reservation delivery is pull-based.** Booking.com keeps each provider's reservation messages in a dedicated queue. You poll for them and acknowledge them over OTA ([reservations overview](https://developers.booking.com/connectivity/docs/reservations-api/reservations-overview)). The Connectivity Notification Service is a webhook, but it carries "simple alerts", and none of the pages I read list reservations among its notification types ([CNS overview](https://developers.booking.com/connectivity/docs/notification-service/notification-service-overview)).

**Restriction support:**

- Supported:
  - MinLOS and MaxLOS, both stay-through and arrival-based.
  - Exact LOS on arrival (`FixedLOS`).
  - Closed to arrival and closed to departure (`Restriction="Arrival"` / `"Departure"`).
  - Closed, at room level or room-rate level.
  - Minimum and maximum advance booking offsets, up to 360D.
  - Source: [OTA_HotelAvailNotif](https://developers.booking.com/connectivity/docs/ota-hotelavailnotif).
- B.XML names for the same fields: `minimumstay`, `minimumstay_arrival`, `maximumstay`, `maximumstay_arrival`, `exactstay_arrival`, `closedonarrival`, `closedondeparture`, `closed`, `min_advance_res`, `max_advance_res` ([B.XML availability](https://developers.booking.com/connectivity/docs/b_xml-availability)).

**Pricing models:**

- Standard, Derived (RLO), Occupancy-Based (OBP) and Length-of-Stay (LOS).
- Each pricing type needs certification before use ([ARI overview](https://developers.booking.com/connectivity/docs/ari), [Going Live](https://developers.booking.com/connectivity/docs/going_live)).
- One table on the ARI overview says Standard and Derived need no certification, which contradicts the statement above it. Treat this as ambiguous.

### 1.4 Authentication, rate limits, sandbox

- **Machine accounts.** You create them in the Connectivity Portal, at property level, and can attach several properties to one account. Access depends on the connection type the property granted ([Authentication](https://developers.booking.com/connectivity/docs/authentication)). Use separate test and production machine accounts ([Authentication](https://developers.booking.com/connectivity/docs/authentication)).
- **Token flow** ([token-based auth](https://developers.booking.com/connectivity/docs/token-based-authentication)):
  - `POST https://connectivity-authentication.booking.com/token-based-authentication/exchange` with `client_id` and `client_secret` (JSON or XML).
  - Returns a JWT valid for **1 hour**. You can request at most **30 tokens per hour per machine account**.
  - Send it as `Authorization: Bearer {JWT}`.
  - The JWKS for signature checks is at `.../.well-known/jwks.json`, limited to 300 requests per hour.
- **Old method retired.** Credential-based (per-request username/password) authentication was sunset on **31 Dec 2025** ([Authentication](https://developers.booking.com/connectivity/docs/authentication)).
- **Endpoint access.** A call is authorised only if the property is linked to the machine account, the property has the right connection type, the endpoint is enabled for the account, any required certification is held, and the token is valid. Otherwise you get HTTP 403 ([managing endpoint access](https://developers.booking.com/connectivity/docs/managing-endpoint-access)).
- **IP allowlisting.** On Booking.com's side it is optional: "if no IP address is specified, then we won't filter requests by IP" ([token-based auth FAQ](https://developers.booking.com/connectivity/docs/token-based-authentication)). If you allowlist Booking.com on your side, allowlist domain names, not IPs ([docs](https://developers.booking.com/connectivity/docs)).
- **Rate limits** ([docs](https://developers.booking.com/connectivity/docs)):
  - 10,000 calls/min across all endpoints.
  - `/xml/reservationssummary`: 700/min.
  - `OTA_HotelInvNotif`, `OTA_HotelProductNotif`, `OTA_HotelSummaryNotif`, `OTA_HotelDescriptiveContentNotif`: 75/min each.
  - `OTA_HotelDescriptiveInfo`: 100/min.
  - Exceeding a limit returns HTTP 429. Booking.com may change limits without notice.
- **Sandbox.** There is no separate sandbox hostname in the docs. You test against **test properties**, which can never become bookable ([tutorial: create a test property](https://developers.booking.com/connectivity/docs/tut-ready-to-check)), and create **test reservations** on them ([tutorial: create a test reservation](https://developers.booking.com/connectivity/docs/tut-create-test-reservation)). Both tutorials require a machine account from the Connectivity Portal, so in practice you need partner access first.

### 1.5 Documentation access

- **Public, no login:** all of `developers.booking.com/connectivity/...`, including endpoint references, XML examples, reservation flows, auth and rate limits. I read everything cited above without logging in.
- **Gated or unreadable:**
  - `portal.connectivity.booking.com` and `connectivity.booking.com` (the Connectivity Hub / Provider Portal articles). These hold the "specific onboarding requirements", "Introduction on PCI and PII compliance", and "Rates & Availability API requirements" (the mandatory functionalities for certification).
  - The docs link to these pages, but my fetches failed on a TLS certificate-chain error and the pages appear to be a partner portal. See §6.

### 1.6 Gotchas

- **Acknowledgement window: 30 minutes.** If a reservation is not acknowledged (OTA) or retrieved (B.XML) within 30 minutes of its creation, modification or cancellation, Booking.com emails it to the property. Support can extend this to 24 h ([reservations overview](https://developers.booking.com/connectivity/docs/reservations-api/reservations-overview)). With the Reservation Recovery API enabled the window is 24 h, except for check-ins within 48 h, which still fall back after 30 minutes ([recovery overview](https://developers.booking.com/connectivity/docs/reservations-flow-control-api/reservations-recovery-overview)).
- **Polling cadence.** `GET OTA_HotelResNotif` and `GET OTA_HotelResModifyNotif` once every **20 s**, waiting at least **5 s** after an acknowledgement before the next GET. Use a **5-minute HTTP client timeout** on pull and acknowledge calls ([retrieving new](https://developers.booking.com/connectivity/docs/reservations-api/retrieving-new-reservations-ota), [reservations overview](https://developers.booking.com/connectivity/docs/reservations-api/reservations-overview)).
- **Retrieval filters** are for outage recovery only: `id`, `hotel_ids`, `last_change` (Europe/Amsterdam time, at most 2 weeks back) and `limit` (10–200). `last_change` returns HTTP 400 once the Recovery API is enabled ([retrieving new](https://developers.booking.com/connectivity/docs/reservations-api/retrieving-new-reservations-ota)).
- **Unacknowledged reservations are redelivered**, so handle duplicates idempotently ([reservations overview](https://developers.booking.com/connectivity/docs/reservations-api/reservations-overview)).
- **Modifications before acknowledgement.** If a booking changes before you acknowledged the original, it still arrives as a *new* reservation message ([retrieving modified/cancelled](https://developers.booking.com/connectivity/docs/reservations-api/retrieving-modifcancel-reservations-ota)).
- **409 race on acknowledgement.** With the `ota_res_response_token` feature, acknowledging a reservation that changed in the meantime returns 409. Re-GET it and acknowledge both `ResID_Value`s ([OTA reservations process](https://developers.booking.com/connectivity/docs/reservations-api/reservations-process-ota)).
- **Rejecting a reservation.** Sending an `<Errors>` acknowledgement does **not** cancel the booking. Booking.com immediately emails the property instead ([reservations overview](https://developers.booking.com/connectivity/docs/reservations-api/reservations-overview)).
- **Delta updates only:**
  - Send only changes, never full refreshes.
  - One hotel per request, and **one month per request**.
  - Several room-rates may share a request.
  - Send at least 12 months ahead.
  - Dates may run from 1 day in the past (CET) to 5 years ahead.
  - Sources: [OTA_HotelAvailNotif](https://developers.booking.com/connectivity/docs/ota-hotelavailnotif), [OTA_HotelRateAmountNotif](https://developers.booking.com/connectivity/docs/ota-rateamountnotif).
- **Date-range semantics differ by format.** OTA `End` is **inclusive**. B.XML `date to` is **exclusive** ("up to and not including") ([B.XML availability](https://developers.booking.com/connectivity/docs/b_xml-availability)).
- **Do not mix OTA and B.XML** within one multi-step process such as reservation retrieval and acknowledgement ([docs](https://developers.booking.com/connectivity/docs)).
- **Rate amounts:**
  - Rates are set **per night** for a room/rate/date. LOS pricing sets a per-night price per length of stay (`UnitMultiplier`, up to 90).
  - Send `AmountAfterTax` **or** `AmountBeforeTax`, never both. Which one depends on whether the property has both "Including VAT" and "Including taxes" enabled in its extranet.
  - `0` means not bookable. `CurrencyCode` must equal the hotel's currency.
  - `DecimalPlaces` scaling applies, for example `8550` with `DecimalPlaces="2"` is 85.50.
  - Sources: [OTA_HotelRateAmountNotif](https://developers.booking.com/connectivity/docs/ota-rateamountnotif).
  - Prices are validated between €5 and €50,000 per night or the equivalent ([ARI FAQ](https://developers.booking.com/connectivity/docs/con-faq-rates-availability)).
- **Availability limits.** `BookingLimit`/`roomstosell` is at most 254, and 255 means unlimited. A closed room keeps its other values. **You must reopen a closed room before new availability becomes visible** ([OTA_HotelAvailNotif](https://developers.booking.com/connectivity/docs/ota-hotelavailnotif)).
- **Reservation amounts:**
  - Amounts are integers with `DecimalPlaces`.
  - The response uses `AmountAfterTax` or `AmountBeforeTax` according to the same property tax settings.
  - The RoomStay `Total` covers all nights of that room. The reservation `Total` covers all rooms times all nights.
  - The commission currency is fixed per property.
  - Source: [retrieving new](https://developers.booking.com/connectivity/docs/reservations-api/retrieving-new-reservations-ota).
  - For a detailed tax and fee breakdown, enable "Payments Clarity Package v2" (same page).
- **Opt-in fields.** Many reservation fields only appear after you enable a "feature" in the Provider Portal, for example cancellation policy (`res_cancel_policies`), room-level guest counts, VCC details and the response token ([reservations overview](https://developers.booking.com/connectivity/docs/reservations-api/reservations-overview), [retrieving modified/cancelled](https://developers.booking.com/connectivity/docs/reservations-api/retrieving-modifcancel-reservations-ota)).
- **Cancellations:**
  - OTA: delivered through `OTA_HotelResModifyNotif`.
  - B.XML: `status` is `new`, `modified` or `cancelled`, plus `total_cancellation_fee`, and `totalprice` is 0 when cancelled ([B.XML managing reservations](https://developers.booking.com/connectivity/docs/reservations-api/managing-reservations-bxml)).
  - Booking.com automatically puts cancelled rooms back into inventory ("auto-replenishment") ([general FAQ](https://developers.booking.com/connectivity/docs/con-faq-reservations-general-information)). Your system must not add them back a second time.
  - I did not find the exact marker that distinguishes a cancellation from a modification inside the OTA payload (see §6).
- **Rates that bypass the API.** Rates can be "XML Default", "XML Res" or "No XML". Bookings on No-XML or unmapped rates go to the property **by email, not through the API** ([ARI FAQ](https://developers.booking.com/connectivity/docs/con-faq-rates-availability), [reservations overview](https://developers.booking.com/connectivity/docs/reservations-api/reservations-overview)).
- **Required display data.** Certification expects the PMS to show reservation ID, status, created/changed timestamps, booker details, guest names, room and rate IDs and names, meal plan, cancellation policy, promotions, add-ons, per-night price, taxes and fees, total, special requests, and card data in a PCI-compliant form ([testing the Reservations API](https://developers.booking.com/connectivity/docs/con-faq-reservations-testing-res-api)).

---

## 2. Agoda

### 2.1 Programme and how a vendor joins

- **Programme names.** The docs portal is "Agoda Direct Supply APIs". Joining means becoming an "Agoda Tech Partner". The main API for channel managers is the **YCS API** (YCS is the extranet, now called "Agoda Partner Portal") ([getting started](https://developer.agoda.com/supply/docs/getting-started), [YCS API intro](https://developer.agoda.com/supply/docs/introduction)).
- **Application.** Submit the "new partners questionnaire". "We cannot provide a specific timeline for when you will hear back from us. We will get back to you when we are able to support your onboarding." ([How to become an Agoda Tech Partner](https://developer.agoda.com/supply/docs/how-to-become-a-partner)).
- **What the questionnaire asks** (Google Form linked from that page, [forms.gle/F9DE4KcemYbHy2zS7](https://forms.gle/F9DE4KcemYbHy2zS7). I read it through a fetch tool that summarises, so the wording is close but not verbatim):
  - Channel manager name and website.
  - "How many properties do you have connected to your channel manager?"
  - Whether you are authorised to enable OTA channels for your properties.
  - PCI compliance (Yes/No).
  - Revenue model (subscription or % revenue share).
  - Accommodation types and region.
  - APIs of interest: ARI, child rates, booking retrieval, booking push, BookingHint, content, promotions, messaging and others.
  - Product type: Channel Manager, PMS, CRS, and so on.
  - Contract details and a signatory for a **DocuSign agreement**.
  - The form says eligible partners hear back in 2–4 weeks and must integrate the **YCS API and OAuth 2.0**.
  - **No minimum property count is stated.**
- **Certification** ([Certification & Limit](https://developer.agoda.com/supply/docs/certification)):
  - Mandatory functions: `GetProduct`, `SetAriV2`, `GetBookingList` and `GetBookingDetails`.
  - Step 1 is a **self-certification** survey ([survey](https://survey.alchemer.com/s3/5438498/Agoda-Connectivity-Certification-Process)).
  - Step 2 is a **pilot with 2–3 live properties**.
- **Costs.** None published.

### 2.2 Can a single hotel build its own direct connection?

- **Nothing explicitly forbids it, but the process is not designed for it.**
  - The questionnaire is written for "Channel Manager" companies and asks for their property count and revenue model.
  - The certification pilot needs **2–3 live properties**, which a single-hotel project cannot provide.
  - Agoda gives no timeline for a response.
- **The "OTA API (Direct Connect)" route.** Its audience is "properties that are directly integrated with our systems". It still points new partners to the same Tech Partner questionnaire, and its certification page repeats the YCS requirements ([OTA API intro](https://developer.agoda.com/supply/docs/introduction-2), [OTA certification](https://developer.agoda.com/supply/docs/certification-3)). **[unverified / memory]** In practice this route serves hotel chains and large suppliers. The public docs do not say so.
- **How a property links to a channel manager.** The property selects it under Partner Portal → Property Settings → "Enable channel manager mode", or emails `agoda.chain.support@agoda.com` ([connecting to a property](https://developer.agoda.com/supply/docs/connecting-to-a-property), [Partner Hub](https://partnerhub.agoda.com/how-do-i-connect-or-change-my-channel-manager/)). The dropdown only lists channel managers Agoda has onboarded.

### 2.3 API surface (YCS API, the channel-manager API)

- **Endpoint.** `https://supply.agoda.com/api`, one generic endpoint. A numeric `type` in the XML body selects the operation:
  - `1` SetAri, `2` GetAri, `3` GetBookingList, `4` GetBookingDetail, `5` GetProduct, `8` SetProduct, `9` GetBookingListV2, `10` SetAriV2.
  - Sources: [Availability and Rates](https://developer.agoda.com/supply/docs/availability-and-rates). The certification page also mentions "unique" per-operation endpoints ([Certification & Limit](https://developer.agoda.com/supply/docs/certification)).
- **Format.** Agoda's own XML (`<request type="10" timestamp="…"><criteria property_id="…">…`), **not OTA**. Content-Type is `application/xml` or `text/xml`. FPLOS (length-of-stay) pricing uses JSON on `POST /api/rate/fplos` ([FPLOS](https://developer.agoda.com/supply/docs/fplos-pricing-spec)).

| Function | Operation | Notes | Source |
|---|---|---|---|
| Room/rate mapping | `GetProduct` (type 5) | Returns room IDs and rate plans with `rate_type` (Net/Sell), `tax_included`, `master_rate` (child/linked rates), cxl_code, LOS and advance-booking settings | [Product Management](https://developer.agoda.com/supply/docs/product-management) |
| Product settings | `SetProduct` (type 8) | Room- and rate-plan-level defaults (min_rate, num_persons, min_los, …) | [Product Management](https://developer.agoda.com/supply/docs/product-management) |
| Inventory, rates, restrictions | `SetAriV2` (type 10) | `allotment` per room, `prices` (default, per-occupancy, or deviation by amount or %), `extra_bed`, `child_rates`, `closed`, `cta`, `ctd`, `los min/max`, advance purchase min/max, stay-through min | [Availability and Rates](https://developer.agoda.com/supply/docs/availability-and-rates) |
| Read ARI | `GetAriV2` (type 2) | At most 31 days per request, at most 5 properties | [Availability and Rates](https://developer.agoda.com/supply/docs/availability-and-rates) |
| List bookings | `GetBookingList` (type 3, up to 5 properties, 90-day window) / `GetBookingListV2` (type 9, all properties, 60-minute window) | Filter by status Confirm/Amend/Cancel | [Booking Retrieval](https://developer.agoda.com/supply/docs/booking-retrieval) |
| Booking details | `GetBookingDetail` (type 4) | One property and up to 50 booking IDs per call. Details are kept for 90 days | [Booking Retrieval](https://developer.agoda.com/supply/docs/booking-retrieval) |
| Push notification | **BookingHint** (Agoda POSTs to your URL) | Hint only. You then call GetBookingDetails | [Booking Hint](https://developer.agoda.com/supply/docs/booking-hint) |
| Content, promotions, messaging | Content Push API, Promotion API, Messaging API (webhooks) | Separate certifications | [docs index](https://developer.agoda.com/supply/llms.txt) |

**Push or pull for reservations.** From the Agoda FAQ: "Agoda doesn't have push booking, only BookingHint (Booking Notification), and pull booking calls such as GetBookingList (v1 or v2) and GetBookingDetails." ([Best Practices / FAQ](https://developer.agoda.com/supply/docs/faqs-1)).

- **BookingHint behaviour:**
  - Agoda pushes every 1–2 minutes and retries 3 times, 15 s apart.
  - After that it emails a list of failed hints.
  - Your endpoint must return `<result><success/></result>`.
  - Source: [Booking Hint](https://developer.agoda.com/supply/docs/booking-hint).
  - To activate it, email `connectivity-tech-support@agoda.com` with your URL and an alert email address.

**OTA API (Direct Connect, separate product).**

- OTA 2013A and 2015B. Calls: `OTA_HotelAvailNotifRQ`, `OTA_HotelBookingRuleNotifRQ`, `OTA_HotelRateAmountNotifRQ`.
- Host: `supplyota.agoda.com/b2b/ota/{2013A|2015B}/hotels`. The docs print the URLs as `http://`.
- Auth: **HTTP Basic** ([OTA API overview](https://developer.agoda.com/supply/reference/ota-api-overview)).
- Bookings are **pushed by Agoda to the supplier**: Agoda sends `OTA_HotelResRQ` and `OTA_CancelRQ`, and the booking is confirmed only once Agoda receives the supplier's confirmation number. Modification is "not currently live". Suppliers must de-duplicate on the Agoda reservation ID ([Generic Push Booking API](https://developer.agoda.com/supply/reference/generic-push-booking-api)).

### 2.4 Authentication, rate limits, sandbox

- **Credentials** ([OAuth Authorization](https://developer.agoda.com/supply/docs/authentication-2025)):
  - OAuth 2.0 client credentials. You generate the Client ID and Secret yourself in **YCS → "API access"**, which needs a partner login.
  - The secret arrives through a Nextcloud link that expires after 24 h. The secret itself is valid for **1 year** and generating a new one invalidates the old one immediately.
  - Only one client ID per email address.
- **Token:**
  - v1: `POST https://supply.agoda.com/token-based-authentication/exchange` (JSON).
  - v2: `.../v2/exchange` (RFC 6749 form-encoded `grant_type=client_credentials`).
  - The JWT is valid **1 h**. Send it as `Authorization: Bearer`. An expired token returns **HTTP 403**, not 401 (same page).
- **IP whitelist.** Required. You manage it in YCS API access. A request from a non-whitelisted IP fails with response code 60 or `unauthorized_client` (same page).
- **Legacy API key.** The `?apiKey=` URL parameter is still accepted during the migration period, but "Cut-off for API Key Authentication: End of 2026". Remove the apiKey parameter once you use OAuth (same page).
- **Rate limits** (same page):
  - By Client ID: 100 attempts / 90 successes per hour, 2,100 / 2,000 per day.
  - By IP: 220 / 200 per hour, 4,400 / 4,000 per day.
  - Hitting the daily limit blocks API access, ARI updates included, "for 24 hours". The page also says enforcement uses rolling windows.
  - These limits appear in the OAuth guide. The context, which tells you to reuse tokens and not generate one per request, suggests they cover the **token exchange** calls. The page does not say so explicitly.
  - For YCS calls themselves: "Currently there is no limit for requests per day", with a request size limit of 1 MB ([Certification & Limit](https://developer.agoda.com/supply/docs/certification)).
- **Sandbox.** "Test bookings can only be created in production environment on a test hotel assigned to you." Test bookings require a real card. Use Book Now Pay Later and cancel before the charge date ([FAQ](https://developer.agoda.com/supply/docs/faqs-1)).

### 2.5 Documentation access

- **Public, no login:** all of `developer.agoda.com/supply` (ReadMe), including the YCS spec, booking retrieval, BookingHint, error codes and OAuth. An `llms.txt` index is published ([llms.txt](https://developer.agoda.com/supply/llms.txt)).
- **Gated:** the YCS / Agoda Partner Portal self-service pages (API access, IP whitelist, credentials). Some response examples and request URLs on the public pages appear empty in places, but the XML request examples are present.

### 2.6 Gotchas

- **No acknowledgement over the API.** "Booking acknowledgement is not yet supported via API", so `acknowledge="0"` is normal ([FAQ](https://developer.agoda.com/supply/docs/faqs-1)). There is no "unacknowledged queue" like Booking.com's, so the PMS must poll by time window and reconcile itself.
- **Polling pattern.** Call `GetBookingList` every **5 minutes**, with slightly overlapping windows such as 09:54:55–10:00:05, then 09:59:55–10:05:05 ([FAQ](https://developer.agoda.com/supply/docs/faqs-1)).
- **Time windows and timezones.** `GetBookingListV2` windows are at most 60 minutes. `from` may go back at most 740 days. Hint and booking timestamps are in **ICT (GMT+7)** ([Booking Retrieval](https://developer.agoda.com/supply/docs/booking-retrieval), [Booking Hint](https://developer.agoda.com/supply/docs/booking-hint)).
- **Statuses** are `ConfirmBooking`, `AmendBooking` and `CancelBooking`. You may receive `AmendBooking` **without ever seeing `ConfirmBooking`** if the guest amended within 2–3 minutes. With BookingHint, a fast change sends only the latest status ([FAQ](https://developer.agoda.com/supply/docs/faqs-1), [Booking Hint](https://developer.agoda.com/supply/docs/booking-hint)).
- **One room type per booking.** A booking can contain one room type only, with a room count ([FAQ](https://developer.agoda.com/supply/docs/faqs-1)).
- **ARI date limits.**
  - SetAri accepts up to **730 days** ahead.
  - Dates may run from yesterday to 730 days ahead.
  - At most 31 explicit `date_values` per update, otherwise use `date_range` (inclusive).
  - Day-of-week filter `dow` 1–7.
  - Sources: [Certification & Limit](https://developer.agoda.com/supply/docs/certification), [Availability and Rates](https://developer.agoda.com/supply/docs/availability-and-rates), [error codes](https://developer.agoda.com/supply/docs/error-codes-1).
- **Partial success.** SetAriV2 can return **HTTP 207** for partial success, and the partial-success XML format must be enabled per channel manager. Updates are processed asynchronously, so a success response does not guarantee the change is immediately readable ([Availability and Rates](https://developer.agoda.com/supply/docs/availability-and-rates), [FPLOS](https://developer.agoda.com/supply/docs/fplos-pricing-spec)).
- **Restriction defaults:**
  - Omitted restriction elements leave the extranet value unchanged.
  - To clear restrictions, send `min=1` for MinLOS and `max=0` for MaxLOS.
  - Min LOS is arrival-based. "Stay-through" min is a separate field.
  - Sources: [Availability and Rates](https://developer.agoda.com/supply/docs/availability-and-rates), [FAQ](https://developer.agoda.com/supply/docs/faqs-1).
- **Price conventions:**
  - Prices are per night, per room/rateplan/date. "The Currency must match with the property currency". At most 2 decimals.
  - Whether a pushed price is **Net or Sell**, and **tax-inclusive or exclusive**, depends on the rate plan's `rate_type` and `tax_included` from `GetProduct`.
  - Sources: [Availability and Rates](https://developer.agoda.com/supply/docs/availability-and-rates), [Product Management](https://developer.agoda.com/supply/docs/product-management), [FAQ](https://developer.agoda.com/supply/docs/faqs-1).
- **Reservation price fields vary** by payment model and location:
  - Agoda Collect (default): `net_inclusive_amt` plus `refsell_amt`.
  - Property Collect: `sell_inclusive_amt`.
  - Taiwan, the US and Mexican chains differ again.
  - Prices come per date. Agoda says to display `net_inclusive_amt`, the amount after commission. There is no commission attribute.
  - `paymentmodel` 1 means Agoda Collect and 2 means Property Collect.
  - Sources: [FAQ](https://developer.agoda.com/supply/docs/faqs-1), [Booking Retrieval](https://developer.agoda.com/supply/docs/booking-retrieval).
- **Cancellation policy** is a code string such as `1D1N_1N` (cancel within 1 day costs 1 night, no-show costs 1 night) or `365D100P_100P` (non-refundable) ([Booking Retrieval](https://developer.agoda.com/supply/docs/booking-retrieval)).
- **Updates silently ignored.** Updates to Beds Network and Rocket Travel rate plans return success but have no effect ([FAQ](https://developer.agoda.com/supply/docs/faqs-1)).
- **GDPR-wiped bookings.** GetBookingDetails may fail for these and you must read them from the extranet ([delivery check](https://developer.agoda.com/supply/docs/how-to-check-if-booking-has-been-delivered-to-channel-manager-system-booking-retrieval)).
- **Guest contact data.** Email (obfuscated) and phone appear only if the property enabled "request customer info" ([FAQ](https://developer.agoda.com/supply/docs/faqs-1)).

---

## 3. SiteMinder: pmsXchange (PMS-facing API)

There are two relevant SiteMinder APIs: **pmsXchange**, which connects PMS/RMS/CRS systems to SiteMinder, and **SiteConnect**, which is for booking channels pushing into SiteMinder ([docs index](https://developer.siteminder.com/llms.txt)). **pmsXchange is the one this project needs.**

- **What it does.** "pmsXchange connects PMS, RMS, and CRS providers to the SiteMinder Platform — pushing real-time rates, availability, and restrictions, while retrieving reservations, modifications, and cancellations." SiteMinder then distributes to its channels ([pmsXchange](https://developer.siteminder.com/pmsxchange-api/pmsxchange-api.md)).
- **Partner requirements:**
  - "Access to pmsXchange requires an active partnership agreement with SiteMinder" ([Quick Start](https://developer.siteminder.com/pmsxchange-api/guides/quick-start.md)).
  - The process is: apply, sign the partnership agreement with the Ecosystem team, Initiation (1–3 days), Development (4–6 weeks), Certification (1 week), Production with **one pilot property**, then Live. That is "~60 days" in total ([Integration Process](https://developer.siteminder.com/get-started/partner-lifecycle/integration-process.md), [PMS integration type](https://developer.siteminder.com/get-started/integration-types/pms.md), [FAQ](https://developer.siteminder.com/pmsxchange-api/additional-resources/faq.md)).
- **Application form** ([apply now](https://www.siteminder.com/integrations/apply-now/), read with curl; WebFetch was blocked with HTTP 403):
  - Number of hotels under contract.
  - "How many properties are requesting to be connected via SiteMinder?" and a list of those hotels.
  - Other channel managers you integrate with.
  - "Are you PCI compliant?"
  - Monthly reservations (bands start at 0–500).
  - Internal or external developers.
  - The page also contains an NDA text.
  - **No minimum is stated.** Approval is at SiteMinder's discretion.
- **Costs.** Partner fees are not published. **[unverified / memory]** The hotel also needs its own paid SiteMinder subscription. This is implied because SiteMinder assigns the `HotelCode` and mapping is done inside the hotel's SiteMinder platform under "Distribution > Connectivities > {PMS Name}" ([Integration Requirements](https://developer.siteminder.com/pmsxchange-api/guides/integration-requirements.md), [FAQ](https://developer.siteminder.com/pmsxchange-api/additional-resources/faq.md)).
- **Required to go live:**
  - Rooms and Rates (SM → PMS, REST).
  - Availability (PMS → SM, SOAP).
  - Reservations Push **or** Pull.
- **Recommended:** Rates (PDP or OBP), Restrictions, and modification/cancellation handling ([PMS integration type](https://developer.siteminder.com/get-started/integration-types/pms.md), [FAQ](https://developer.siteminder.com/pmsxchange-api/additional-resources/faq.md)).
- **Format:**
  - **SOAP 1.1 only**, with **OTA 2003/05** messages: `OTA_HotelAvailNotifRQ` for availability and restrictions, `OTA_HotelRateAmountNotifRQ` for rates, `OTA_HotelResNotifRQ` for reservation push, `OTA_ReadRQ` plus `OTA_NotifReportRQ` for pull.
  - REST/JSON for room-rate mapping, reservation import and the beta "UltraSync" (SM → PMS rates and restrictions).
  - Sources: [Integration Requirements](https://developer.siteminder.com/pmsxchange-api/guides/integration-requirements.md), [API Overview](https://developer.siteminder.com/pmsxchange-api/guides/api-overview.md).
- **Auth.** WS-Security `UsernameToken` for SOAP and HTTP Basic for REST. **PMS-level credentials** (one set for all hotels) are mandatory for new integrations. Passwords must be ASCII, at least 12 characters, and avoid `&`, `"` and `'`. TLS 1.2 or higher on port 443. IP whitelisting is optional ([Integration Requirements](https://developer.siteminder.com/pmsxchange-api/guides/integration-requirements.md)).
- **Hosts:**
  - Test SOAP: `https://tpi-pmsx.preprod.siteminderlabs.com/webservices/{RequestorID}`.
  - Test REST: the docs disagree. The Quick Start says `https://tpi-pmsx.preprod.siteminderlabs.com/core-api/pmses/{pmsCode}` and the Integration Requirements page says `https://pmsx-core-api.dev.siteminderlabs.com/pmses/{pmsCode}`.
  - Production endpoints are given at go-live ([Quick Start](https://developer.siteminder.com/pmsxchange-api/guides/quick-start.md), [Integration Requirements](https://developer.siteminder.com/pmsxchange-api/guides/integration-requirements.md)).
- **Sandbox.** **Shared public test credentials** (`PMSXTEST`, hotels `PMSXTEST1–3`) come in the public Postman workspace. They let you build mapping retrieval and ARI pushes **before** signing an agreement. Pull returns no reservations on these accounts. Once you are a partner you get a dedicated test hotel and a booking-engine simulator ([Quick Start](https://developer.siteminder.com/pmsxchange-api/guides/quick-start.md)).
- **Reservations:**
  - **Push (recommended):**
    - SiteMinder POSTs one reservation per `OTA_HotelResNotifRQ` (`ResStatus` = `Book`, `Modify` or `Cancel`) to your SOAP endpoint, which must be HTTPS on a registered domain.
    - You must answer `OTA_HotelResNotifRS` **within 60 s**.
    - Without a valid answer SiteMinder retries every minute 10 times, then every 5 minutes.
    - An `<Errors>` response is final and is not retried.
    - Source: [Reservations Push](https://developer.siteminder.com/pmsxchange-api/reference/reservations/push.md).
  - **Pull:**
    - `OTA_ReadRQ` with `SelectionType="Undelivered"`, **no more often than every 2 minutes and no less often than every 5 minutes**.
    - Then confirm every retrieved reservation with `OTA_NotifReportRQ`.
    - Source: [Reservations Pull](https://developer.siteminder.com/pmsxchange-api/reference/reservations/pull.md).
  - The delivery method is set per PMS and cannot be mixed across hotels ([Integration Requirements](https://developer.siteminder.com/pmsxchange-api/guides/integration-requirements.md)).
- **Gotchas** (all from [Integration Requirements](https://developer.siteminder.com/pmsxchange-api/guides/integration-requirements.md) and the [FAQ](https://developer.siteminder.com/pmsxchange-api/additional-resources/faq.md) unless noted):
  - **Delta updates are "strictly enforced".** Frequent full flushes are prohibited.
  - Send updates within 2 minutes of a PMS change. Wait for the response before sending the next request for the same property.
  - Messages are minified XML, at most **2 MB**, and **atomic** (all-or-nothing).
  - Every request needs a UUID `EchoToken`.
  - A success response only proves the XML was valid. **Unmapped codes are silently ignored.**
  - There is no release-period field, so send Stop Sell instead.
  - After processing a reservation, the PMS must push updated availability back.
  - Cards: messages may contain raw `CardNumber` (PCI scope). Tokenisation goes through certified proxies (FreedomPay for push, Payrails for pull) and requires agreements with the proxy and per property ([Credit Card Tokenization](https://developer.siteminder.com/pmsxchange-api/additional-resources/credit-card-tokenization.md)).
  - Rate pushes need `CurrencyCode` and are not converted. PDP means a single rate per room per night ([Rates PMS→SM](https://developer.siteminder.com/pmsxchange-api/reference/rates/pms-to-sm.md)).
  - Non-compliance must be fixed within 90 days or the interface may be deactivated.
- **Docs access.** Fully public (GitBook), including WSDL URL patterns, OpenAPI YAML downloads, Postman workspace and certification scenarios.

---

## 4. Cloudbeds

- **What the API is.** "Cloudbeds' APIs provide a comprehensive set of endpoints which allow users to extend the Cloudbeds PMS." It is aimed at product companies such as door locks, POS and accounting, and at properties using Cloudbeds ([About Cloudbeds APIs](https://developers.cloudbeds.com/docs/about-cloudbeds-api.md)).
  - The use-case blueprints cover accounting, door locks, booking engine, RMS, CRM, POS, housekeeping and similar. **None covers "third-party PMS using Cloudbeds as a channel manager"** ([docs index](https://developers.cloudbeds.com/llms.txt)).
- **What would technically be possible.** An external system can push rates and restrictions into Cloudbeds with `patchRate`/`putRate` (asynchronous, up to 30 intervals per call, non-derived rates only) and read reservations through webhooks plus `getReservations` ([RMS blueprint](https://developers.cloudbeds.com/docs/revenue-management-system-rms.md)). The property would still have to run **Cloudbeds PMS** as the system of record, and the OTAs would be connected to Cloudbeds, not to hms. That is a satellite architecture, not a channel-manager API.
- **Licence restriction.** The API terms forbid using "the API to substantially replicate or compete with core products or services offered by Cloudbeds" (clause 4.4, [Terms](https://developers.cloudbeds.com/docs/terms-and-conditions.md)). A self-built PMS that uses Cloudbeds only for distribution would be at risk under this clause.
- **OTA Build-To-Us API.** This is for **OTAs and channels** connecting *into* the Cloudbeds channel manager (heritage myallocator, `api.myallocator.com/callback/ota/...`), so it runs in the wrong direction for this project ([OTA Build-To-Us intro](https://developers.cloudbeds.com/reference/ota-build-to-us-introduction.md)).
- **Partner programme:**
  - Request a sandbox, then a Partnerships evaluation, then "mutually agreed commercial terms" and "an executed partnership agreement" for the Marketplace ([request your sandbox](https://developers.cloudbeds.com/docs/request-your-sandbox.md), [5 steps](https://developers.cloudbeds.com/docs/getting-started-as-a-partner-in-5-steps.md)).
  - Go-live needs "a minimum of 5 pilot properties and up to 10" ([FAQ](https://developers.cloudbeds.com/docs/faq.md)).
  - Rate limits are 5 requests/s for properties and 10 requests/s for tech partners (same FAQ).
  - Property-level API access is either included in the package or "on request and for an additional cost" ([property API access](https://developers.cloudbeds.com/docs/property-and-group-account-api-access.md)).
- **Standalone channel manager (myallocator).**
  - **[2nd-hand]** A Checkfront help article and a HostelSnap post, seen only through search summaries (both returned 403 to my fetch), say Cloudbeds stopped selling myallocator standalone to new users around April 2024 and discontinued third-party PMS access.
  - myallocator's legacy PMS-side API (`api.myallocator.com/pms/...`) is documented only in an unofficial Go SDK, and the myallocator help centre returned 403.
  - **Treat Cloudbeds as unavailable as a neutral channel manager for a third-party PMS** unless Cloudbeds confirms otherwise in writing.
- **Docs access.** Fully public (ReadMe) at developers.cloudbeds.com.

---

## 5. Implications for the hms channel-manager module (my inference, not vendor statements)

1. **Realistic path for one self-built hotel PMS.** Integrate with a channel manager that has a public PMS-facing API. Of the two researched here, that is SiteMinder pmsXchange. Let the channel manager hold the Booking.com and Agoda connections. Booking.com is closed to new providers and to single properties. Agoda's process expects a channel-manager business with live pilot properties.
2. **Design the module as provider adapters behind one internal interface.** The interface needs `push_availability`, `push_rates`, `push_restrictions`, `fetch_mapping` and `ingest_reservation`. The transports differ: SOAP push receiver, polling worker, or XML POST client.
3. **Reservation ingestion must be idempotent**, keyed on the channel reservation ID plus the message ID. All three systems redeliver: Booking.com repeats until acknowledged, SiteMinder retries for minutes to hours, and Agoda polls with overlapping windows. A modification may arrive before or instead of the "new" message.
4. **The ARI outbox must send deltas only.** Store last-sent state per (room, rate, date) and diff against it. Batch per hotel, and per month for Booking.com. Respect the forward windows: 12+ months recommended by Booking.com, 730 days maximum at Agoda.
5. **Money.** Store integer minor units plus currency. Record tax-inclusive or tax-exclusive and net or sell per rate plan, because both Booking.com and Agoda make this depend on property configuration.
6. **PCI.** Every route (Booking.com Reservations API, SiteMinder push, the Agoda questionnaire) involves card data or a PCI attestation. Plan for tokenisation, or a PCI-DSS scope decision, before building reservation ingestion.

---

## 6. Unverified / could not access

- **Booking.com Connectivity Hub / Provider Portal articles.** I could not read `portal.connectivity.booking.com/s/topiccatalog`, `.../Introduction-on-PCI-and-PII-compliance`, `.../How-can-I-implement-the-Rates-Availability-API-and-Reservations-API` or `connectivity.booking.com`. My fetch failed TLS certificate verification. I did not bypass it. These pages most likely sit behind a partner login. As a result, the **exact onboarding requirements, any minimum property counts, the mandatory R&A functionality list, and contract terms are unknown**.
- **Booking.com minimum property counts and tier names** (Standard / Advanced / Premier / Premier Plus): **[2nd-hand]** only (hospitable.com, travelnest.com, hoteltechreport.com via search).
- **When the Booking.com pause started or will end:** the connect.booking.com text has no date. A third-party report seen in search also mentioned the pause. I cannot date it.
- **Booking.com OTA cancellation marker:** I did not find the attribute or element that marks an `OTA_HotelResModifyNotif` message as a cancellation rather than a modification. **[unverified / memory]** Historically it is a `HotelResModify` with no `RoomStays` (or an empty one). Confirm this against the full response tables or a test cancellation.
- **Booking.com sandbox:** no separate test hostname is documented. My understanding that test properties live on the production hosts is an inference from the tutorials and the `test` claim in the JWT.
- **Agoda questionnaire wording:** read through a summarising fetch tool, so not verbatim. The "2–4 weeks" and "must integrate YCS API and OAuth 2.0" lines come from that summary of the form.
- **Agoda OAuth rate limits:** it is unclear whether they apply only to token exchange or to all API calls (see §2.4).
- **Agoda OTA "Direct Connect" eligibility:** whether a single independent hotel would ever be accepted is not documented. The "chains / large suppliers" characterisation is **[unverified / memory]**.
- **SiteMinder partner fees, hotel subscription cost, and any minimum hotel count:** not published. The "hotel needs its own SiteMinder subscription" point is an inference (§3).
- **SiteMinder test REST host:** the two docs pages contradict each other (§3).
- **Cloudbeds / myallocator standalone discontinuation and the PMS-side API status:** **[2nd-hand]** only. The Checkfront, HostelSnap and myallocator help-centre pages returned HTTP 403 to my fetches.
- **Costs and commissions** for Booking.com, Agoda and SiteMinder partner programmes: not public anywhere I could read.

---

## 7. Primary source index

- **Booking.com:**
  - https://connect.booking.com/
  - https://developers.booking.com/connectivity/home
  - https://developers.booking.com/connectivity/docs
  - https://developers.booking.com/connectivity/docs/going_live
  - https://developers.booking.com/connectivity/docs/authentication
  - https://developers.booking.com/connectivity/docs/token-based-authentication
  - https://developers.booking.com/connectivity/docs/managing-endpoint-access
  - https://developers.booking.com/connectivity/docs/ari
  - https://developers.booking.com/connectivity/docs/ota-hotelavailnotif
  - https://developers.booking.com/connectivity/docs/ota-rateamountnotif
  - https://developers.booking.com/connectivity/docs/b_xml-availability
  - https://developers.booking.com/connectivity/docs/understanding-pricing-types
  - https://developers.booking.com/connectivity/docs/con-faq-rates-availability
  - https://developers.booking.com/connectivity/docs/reservations-api/reservations-overview
  - https://developers.booking.com/connectivity/docs/reservations-api/retrieving-new-reservations-ota
  - https://developers.booking.com/connectivity/docs/reservations-api/acknowledging-new-reservations-ota
  - https://developers.booking.com/connectivity/docs/reservations-api/retrieving-modifcancel-reservations-ota
  - https://developers.booking.com/connectivity/docs/reservations-api/acknowledging-modif-cancel-reservations-ota
  - https://developers.booking.com/connectivity/docs/reservations-api/reservations-process-ota
  - https://developers.booking.com/connectivity/docs/reservations-api/managing-reservations-bxml
  - https://developers.booking.com/connectivity/docs/reservations-flow-control-api/reservations-recovery-overview
  - https://developers.booking.com/connectivity/docs/con-faq-reservations-testing-res-api
  - https://developers.booking.com/connectivity/docs/con-faq-reservations-general-information
  - https://developers.booking.com/connectivity/docs/connections-api/connections-overview
  - https://developers.booking.com/connectivity/docs/notification-service/notification-service-overview
  - https://developers.booking.com/connectivity/docs/tut-ready-to-check
  - https://developers.booking.com/connectivity/docs/tut-create-test-reservation
- **Agoda:**
  - https://developer.agoda.com/supply/llms.txt
  - https://developer.agoda.com/supply/docs/getting-started
  - https://developer.agoda.com/supply/docs/how-to-become-a-partner
  - https://forms.gle/F9DE4KcemYbHy2zS7
  - https://developer.agoda.com/supply/docs/contact-us
  - https://developer.agoda.com/supply/docs/authentication-2025
  - https://developer.agoda.com/supply/docs/introduction
  - https://developer.agoda.com/supply/docs/certification
  - https://developer.agoda.com/supply/docs/connecting-to-a-property
  - https://developer.agoda.com/supply/docs/availability-and-rates
  - https://developer.agoda.com/supply/docs/booking-retrieval
  - https://developer.agoda.com/supply/docs/product-management
  - https://developer.agoda.com/supply/docs/booking-hint
  - https://developer.agoda.com/supply/docs/faqs-1
  - https://developer.agoda.com/supply/docs/error-codes-1
  - https://developer.agoda.com/supply/docs/fplos-pricing-spec
  - https://developer.agoda.com/supply/docs/introduction-2
  - https://developer.agoda.com/supply/docs/certification-3
  - https://developer.agoda.com/supply/reference/ota-api-overview
  - https://developer.agoda.com/supply/reference/generic-push-booking-api
  - https://partnerhub.agoda.com/how-do-i-connect-or-change-my-channel-manager/
- **SiteMinder:**
  - https://developer.siteminder.com/llms.txt
  - https://developer.siteminder.com/get-started/integration-types/pms.md
  - https://developer.siteminder.com/get-started/partner-lifecycle/integration-process.md
  - https://developer.siteminder.com/pmsxchange-api/pmsxchange-api.md
  - https://developer.siteminder.com/pmsxchange-api/guides/quick-start.md
  - https://developer.siteminder.com/pmsxchange-api/guides/integration-requirements.md
  - https://developer.siteminder.com/pmsxchange-api/guides/api-overview.md
  - https://developer.siteminder.com/pmsxchange-api/guides/testing-and-certification.md
  - https://developer.siteminder.com/pmsxchange-api/reference/reservations/push.md
  - https://developer.siteminder.com/pmsxchange-api/reference/reservations/pull.md
  - https://developer.siteminder.com/pmsxchange-api/reference/rates/pms-to-sm.md
  - https://developer.siteminder.com/pmsxchange-api/additional-resources/faq.md
  - https://developer.siteminder.com/pmsxchange-api/additional-resources/credit-card-tokenization.md
  - https://www.siteminder.com/integrations/apply-now/
- **Cloudbeds:**
  - https://developers.cloudbeds.com/llms.txt
  - https://developers.cloudbeds.com/docs/about-cloudbeds-api.md
  - https://developers.cloudbeds.com/docs/getting-started-as-a-partner-in-5-steps.md
  - https://developers.cloudbeds.com/docs/request-your-sandbox.md
  - https://developers.cloudbeds.com/docs/faq.md
  - https://developers.cloudbeds.com/docs/property-and-group-account-api-access.md
  - https://developers.cloudbeds.com/docs/terms-and-conditions.md
  - https://developers.cloudbeds.com/docs/revenue-management-system-rms.md
  - https://developers.cloudbeds.com/docs/booking-engine.md
  - https://developers.cloudbeds.com/reference/ota-build-to-us-introduction.md
