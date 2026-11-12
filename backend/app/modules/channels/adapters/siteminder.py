"""SiteMinder pmsXchange adapter (PMS side).

Built from SiteMinder's public developer documentation
(developer.siteminder.com/pmsxchange-api, read 2026-11-12):

* SOAP 1.1, OTA 2003/05 messages, WS-Security UsernameToken (PasswordText),
  `Content-Type: text/xml; charset=utf-8`, minified XML, a unique UUID
  EchoToken per request, RequestorID Type 22 = the PMS code.
* Availability: OTA_HotelAvailNotifRQ at room level (InvTypeCode, BookingLimit).
  Restrictions: OTA_HotelAvailNotifRQ at room-rate level, only the changed
  restriction types (MaxLOS removed with Time="999"). Rates: PDP
  OTA_HotelRateAmountNotifRQ with CurrencyCode (no conversion by SiteMinder).
* Reservations pull: OTA_ReadRQ (hotel level, SelectionType "Undelivered"),
  OTA_ResRetrieveRS, then OTA_NotifReportRQ per message id (successes and
  errors in separate messages).
* Mapping: REST GET /core-api/pmses/{pms}/hotels/{hotel}/room-rates with
  HTTP Basic authentication.

Limits applied: messages stay far below 2 MB (at most 400 updates each), one
request at a time per property (the caller never runs two syncs of the same
connection concurrently), 90 s timeout.
"""

from __future__ import annotations

import time
import uuid
import xml.etree.ElementTree as ET  # building only; parsing uses defusedxml
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.sax.saxutils import escape as xml_escape

import httpx
from defusedxml.ElementTree import ParseError
from defusedxml.ElementTree import fromstring as safe_fromstring

from app.modules.channels.adapters.base import (
    Capability,
    ChannelError,
    ConfirmItem,
    ConnectionConfig,
    ErrorKind,
    Exchange,
    ExchangeLog,
    ExternalProduct,
    InboundBooking,
    InboundGuest,
    InboundNight,
    InboundStay,
    InventoryUpdate,
    RateUpdate,
    RestrictionUpdate,
    TestResult,
)
from app.modules.channels.redact import redact

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
WSSE_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
OTA_NS = "http://www.opentravel.org/OTA/2003/05"
# WS-Security UsernameToken profile URI (the password type is a URI, not a secret).
WSSE_PROFILE_URI = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0"
PASSWORD_TYPE = f"{WSSE_PROFILE_URI}#PasswordText"

TEST_BASE_URL = "https://tpi-pmsx.preprod.siteminderlabs.com"
TIMEOUT = httpx.Timeout(90.0, connect=15.0)
MAX_UPDATES_PER_MESSAGE = 400
MAX_LOS_NONE = 999  # SiteMinder: "To remove MaxLOS, set @Time to 999"

# Error codes (OTA ERR table) that mean "this code is not mapped / not known".
_CONFIG_CODES = {"249", "375", "392", "402", "436", "783", "842", "137"}
_TRANSIENT_CODES = {"187"}
# Booking agent codes (SiteMinder reference table) mapped to reservation sources.
CHANNEL_SOURCES = {"BDC": "booking_com", "AGO": "agoda"}


def _q(tag: str) -> str:
    """OTA element name. Messages are built with plain names and an explicit
    xmlns attribute on the root (exactly SiteMinder's form), so serialisation
    never depends on ElementTree's process-wide namespace registry, which
    other libraries (the PDF renderer) modify."""
    return tag


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class SiteMinderAdapter:
    provider = "siteminder"
    capabilities = frozenset(
        {Capability.TEST, Capability.MAPPING_FETCH, Capability.ARI_PUSH, Capability.RES_PULL}
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # A transport is injected only by the test suite.
        self._transport = transport

    # --- transport ---------------------------------------------------------

    def _base_url(self, conn: ConnectionConfig) -> str:
        if conn.endpoint_url:
            return conn.endpoint_url.rstrip("/")
        if conn.environment == "test":
            return TEST_BASE_URL
        raise ChannelError(
            ErrorKind.CONFIG, "Production endpoint URL is required (given by SiteMinder at go-live)"
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport, follow_redirects=False)

    def envelope(self, conn: ConnectionConfig, body: ET.Element) -> bytes:
        """The envelope exactly as in SiteMinder's minified sample, with the
        OTA namespace declared on the OTA root element."""
        inner = ET.tostring(body, encoding="unicode")
        return (
            f'<SOAP-ENV:Envelope xmlns:SOAP-ENV="{SOAP_NS}"><SOAP-ENV:Header>'
            f'<wsse:Security xmlns:wsse="{WSSE_NS}" SOAP-ENV:mustUnderstand="1"><wsse:UsernameToken>'
            f"<wsse:Username>{xml_escape(conn.username)}</wsse:Username>"
            f'<wsse:Password Type="{PASSWORD_TYPE}">{xml_escape(conn.password)}</wsse:Password>'
            f"</wsse:UsernameToken></wsse:Security></SOAP-ENV:Header>"
            f"<SOAP-ENV:Body>{inner}</SOAP-ENV:Body></SOAP-ENV:Envelope>"
        ).encode()

    def ota_root(self, name: str, conn: ConnectionConfig) -> ET.Element:
        root = ET.Element(
            _q(name), {"xmlns": OTA_NS, "EchoToken": str(uuid.uuid4()), "TimeStamp": _now(), "Version": "1.0"}
        )
        source = ET.SubElement(ET.SubElement(root, _q("POS")), _q("Source"))
        ET.SubElement(source, _q("RequestorID"), {"Type": "22", "ID": conn.account_code})
        return root

    async def _soap(
        self, conn: ConnectionConfig, operation: str, body: ET.Element, log: ExchangeLog, summary: str
    ) -> ET.Element:
        url = f"{self._base_url(conn)}/webservices/{conn.account_code}"
        payload = self.envelope(conn, body)
        started = time.monotonic()
        status: int | None = None
        text: str | None = None
        try:
            async with self._client() as client:
                r = await client.post(
                    url,
                    content=payload,
                    headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": operation},
                )
            status, text = r.status_code, r.text
            result = self._parse_soap(status, text)
        except ChannelError as exc:
            detail = f"{summary}: {exc.message}"
            log(self._exchange(operation, "error", status, started, detail, payload, text))
            raise
        except httpx.HTTPError as exc:
            message = f"{type(exc).__name__}: {exc}"[:300]
            log(self._exchange(operation, "error", status, started, f"{summary}: {message}", payload, text))
            raise ChannelError(ErrorKind.TRANSIENT, message) from exc
        log(self._exchange(operation, "ok", status, started, summary, payload, text))
        return result

    @staticmethod
    def _exchange(
        operation: str,
        outcome: str,
        status: int | None,
        started: float,
        summary: str,
        request: bytes | None,
        response: str | None,
    ) -> Exchange:
        return Exchange(
            operation=operation,
            outcome=outcome,
            http_status=status,
            duration_ms=int((time.monotonic() - started) * 1000),
            summary=summary[:500],
            request_body=redact(request),
            response_body=redact(response),
        )

    @staticmethod
    def _parse_soap(status: int, text: str) -> ET.Element:
        """Return the OTA response element, or raise a classified ChannelError."""
        if status >= 500 and not text.lstrip().startswith("<"):
            raise ChannelError(ErrorKind.TRANSIENT, f"HTTP {status}", http_status=status)
        try:
            env = safe_fromstring(text.encode("utf-8")) if text else None
        except ParseError:
            env = None
        if env is None:
            kind = ErrorKind.TRANSIENT if status >= 500 else ErrorKind.DATA
            if status in (401, 403):
                kind = ErrorKind.AUTH
            raise ChannelError(kind, f"HTTP {status}: response is not XML", http_status=status)
        body = env.find(f"{{{SOAP_NS}}}Body")
        if body is None or len(body) == 0:
            raise ChannelError(ErrorKind.DATA, "Response has no SOAP body", http_status=status)
        response = body[0]
        if response.tag == f"{{{SOAP_NS}}}Fault":
            fault = (response.findtext("faultstring") or "SOAP fault").strip()
            code = (response.findtext("faultcode") or "").lower()
            lowered = fault.lower()
            if "auth" in lowered or "password" in lowered:
                kind = ErrorKind.AUTH
            elif code.endswith("server") and "too large" not in lowered:
                kind = ErrorKind.TRANSIENT
            else:
                kind = ErrorKind.DATA
            raise ChannelError(kind, fault, http_status=status)
        errors = _find(response, "Errors")
        if errors is not None:
            raise _ota_error(errors, status)
        if status >= 400:
            kind = ErrorKind.TRANSIENT if status >= 500 else ErrorKind.DATA
            raise ChannelError(kind, f"HTTP {status}", http_status=status)
        if _find(response, "Success") is None:
            raise ChannelError(ErrorKind.DATA, "Response has neither Success nor Errors", http_status=status)
        return response

    # --- connection test and mapping ----------------------------------------

    async def fetch_mapping(self, conn: ConnectionConfig, log: ExchangeLog) -> list[ExternalProduct]:
        rest_base = conn.settings.get("rest_base_url") or f"{self._base_url(conn)}/core-api"
        url = f"{rest_base.rstrip('/')}/pmses/{conn.account_code}/hotels/{conn.hotel_code}/room-rates"
        started = time.monotonic()
        status: int | None = None
        text: str | None = None
        try:
            async with self._client() as client:
                r = await client.get(
                    url,
                    auth=(conn.username, conn.password),
                    headers={"X-SM-TRACE-TOKEN": str(uuid.uuid4()), "Accept": "application/json"},
                )
            status, text = r.status_code, r.text
        except httpx.HTTPError as exc:
            message = f"{type(exc).__name__}: {exc}"[:300]
            log(self._exchange("room_rates", "error", None, started, message, None, None))
            raise ChannelError(ErrorKind.TRANSIENT, message) from exc
        if status != 200:
            kind = {401: ErrorKind.AUTH, 403: ErrorKind.AUTH, 404: ErrorKind.CONFIG}.get(
                status, ErrorKind.TRANSIENT if status >= 500 or status == 429 else ErrorKind.DATA
            )
            message = _rest_error(text) or f"HTTP {status}"
            log(self._exchange("room_rates", "error", status, started, message, None, text))
            raise ChannelError(kind, message, http_status=status)
        try:
            rows = r.json()
            products = [
                ExternalProduct(
                    room_code=str(row["roomTypeCode"]),
                    room_name=row.get("roomTypeName") or None,
                    rate_code=row.get("ratePlanCode") or None,
                    rate_name=row.get("ratePlanName") or None,
                    included_occupancy=int(row["includedAdultOccupancy"])
                    if str(row.get("includedAdultOccupancy") or "").isdigit()
                    else None,
                )
                for row in rows
            ]
        except (ValueError, KeyError, TypeError) as exc:
            log(self._exchange("room_rates", "error", status, started, "Unexpected response", None, text))
            raise ChannelError(ErrorKind.DATA, "Unexpected room-rates response") from exc
        log(self._exchange("room_rates", "ok", status, started, f"{len(products)} room rates", None, text))
        return products

    async def test_connection(self, conn: ConnectionConfig, log: ExchangeLog) -> TestResult:
        """A real call: retrieving the hotel's room rates checks the endpoint,
        the PMS credentials and the hotel code together."""
        try:
            products = await self.fetch_mapping(conn, log)
        except ChannelError as exc:
            return TestResult(False, exc.message)
        rooms = {p.room_code for p in products}
        return TestResult(True, f"{len(rooms)} room types, {len(products)} room rates")

    # --- ARI -------------------------------------------------------------------

    def availability_message(self, conn: ConnectionConfig, updates: list[InventoryUpdate]) -> ET.Element:
        root = self.ota_root("OTA_HotelAvailNotifRQ", conn)
        msgs = ET.SubElement(root, _q("AvailStatusMessages"), {"HotelCode": conn.hotel_code})
        for u in updates:
            m = ET.SubElement(msgs, _q("AvailStatusMessage"), {"BookingLimit": str(max(0, u.available))})
            ET.SubElement(
                m,
                _q("StatusApplicationControl"),
                {"Start": u.start.isoformat(), "End": u.end.isoformat(), "InvTypeCode": u.room_code},
            )
        return root

    async def push_inventory(
        self, conn: ConnectionConfig, updates: list[InventoryUpdate], log: ExchangeLog
    ) -> None:
        by_room: dict[str, list[InventoryUpdate]] = {}
        for u in updates:
            by_room.setdefault(u.room_code, []).append(u)
        for room, items in by_room.items():  # one room type per request (provider best practice)
            for chunk in _chunks(items):
                await self._soap(
                    conn,
                    "HotelAvailNotifRQ",
                    self.availability_message(conn, chunk),
                    log,
                    f"Availability {room}: {len(chunk)} range(s)",
                )

    def restriction_message(self, conn: ConnectionConfig, updates: list[RestrictionUpdate]) -> ET.Element:
        root = self.ota_root("OTA_HotelAvailNotifRQ", conn)
        msgs = ET.SubElement(root, _q("AvailStatusMessages"), {"HotelCode": conn.hotel_code})
        for u in updates:
            m = ET.SubElement(msgs, _q("AvailStatusMessage"))
            ET.SubElement(
                m,
                _q("StatusApplicationControl"),
                {
                    "Start": u.start.isoformat(),
                    "End": u.end.isoformat(),
                    "InvTypeCode": u.room_code,
                    "RatePlanCode": u.rate_code,
                },
            )
            if u.min_stay is not None or u.max_stay is not None:
                los = ET.SubElement(m, _q("LengthsOfStay"))
                if u.min_stay is not None:
                    ET.SubElement(
                        los,
                        _q("LengthOfStay"),
                        {"MinMaxMessageType": "SetMinLOS", "Time": str(u.min_stay or 1)},
                    )
                if u.max_stay is not None:
                    ET.SubElement(
                        los,
                        _q("LengthOfStay"),
                        {"MinMaxMessageType": "SetMaxLOS", "Time": str(u.max_stay or MAX_LOS_NONE)},
                    )
            # One RestrictionStatus per message element: stop sell, CTA and CTD
            # are separate messages for the same dates when several changed.
            statuses = [
                (u.closed, None),
                (u.closed_to_arrival, "Arrival"),
                (u.closed_to_departure, "Departure"),
            ]
            first = True
            for value, kind in statuses:
                if value is None:
                    continue
                target = m
                if not first:
                    target = ET.SubElement(msgs, _q("AvailStatusMessage"))
                    ET.SubElement(
                        target,
                        _q("StatusApplicationControl"),
                        {
                            "Start": u.start.isoformat(),
                            "End": u.end.isoformat(),
                            "InvTypeCode": u.room_code,
                            "RatePlanCode": u.rate_code,
                        },
                    )
                attrs = {"Status": "Close" if value else "Open"}
                if kind:
                    attrs["Restriction"] = kind
                ET.SubElement(target, _q("RestrictionStatus"), attrs)
                first = False
        return root

    async def push_restrictions(
        self, conn: ConnectionConfig, updates: list[RestrictionUpdate], log: ExchangeLog
    ) -> None:
        by_product: dict[tuple[str, str], list[RestrictionUpdate]] = {}
        for u in updates:
            by_product.setdefault((u.room_code, u.rate_code), []).append(u)
        for (room, rate), items in by_product.items():
            for chunk in _chunks(items, MAX_UPDATES_PER_MESSAGE // 3):
                await self._soap(
                    conn,
                    "HotelAvailNotifRQ",
                    self.restriction_message(conn, chunk),
                    log,
                    f"Restrictions {room}/{rate}: {len(chunk)} range(s)",
                )

    def rate_message(self, conn: ConnectionConfig, updates: list[RateUpdate]) -> ET.Element:
        root = self.ota_root("OTA_HotelRateAmountNotifRQ", conn)
        msgs = ET.SubElement(root, _q("RateAmountMessages"), {"HotelCode": conn.hotel_code})
        for u in updates:
            m = ET.SubElement(msgs, _q("RateAmountMessage"))
            ET.SubElement(
                m, _q("StatusApplicationControl"), {"InvTypeCode": u.room_code, "RatePlanCode": u.rate_code}
            )
            rate = ET.SubElement(
                ET.SubElement(m, _q("Rates")),
                _q("Rate"),
                {"CurrencyCode": u.currency, "Start": u.start.isoformat(), "End": u.end.isoformat()},
            )
            amount = f"{u.amount:.2f}"
            ET.SubElement(
                ET.SubElement(rate, _q("BaseByGuestAmts")),
                _q("BaseByGuestAmt"),
                {"AmountAfterTax" if u.after_tax else "AmountBeforeTax": amount},
            )
        return root

    async def push_rates(self, conn: ConnectionConfig, updates: list[RateUpdate], log: ExchangeLog) -> None:
        # SiteMinder requires a positive amount; a zero price cannot be sold.
        sendable = [u for u in updates if u.amount > 0]
        by_product: dict[tuple[str, str], list[RateUpdate]] = {}
        for u in sendable:
            by_product.setdefault((u.room_code, u.rate_code), []).append(u)
        for (room, rate), items in by_product.items():
            for chunk in _chunks(items):
                await self._soap(
                    conn,
                    "HotelRateAmountNotifRQ",
                    self.rate_message(conn, chunk),
                    log,
                    f"Rates {room}/{rate}: {len(chunk)} range(s)",
                )

    # --- reservations ---------------------------------------------------------

    def read_request(self, conn: ConnectionConfig) -> ET.Element:
        root = self.ota_root("OTA_ReadRQ", conn)
        req = ET.SubElement(
            ET.SubElement(root, _q("ReadRequests")), _q("HotelReadRequest"), {"HotelCode": conn.hotel_code}
        )
        ET.SubElement(req, _q("SelectionCriteria"), {"SelectionType": "Undelivered"})
        return root

    async def pull_bookings(self, conn: ConnectionConfig, log: ExchangeLog) -> list[InboundBooking]:
        response = await self._soap(conn, "ReadRQ", self.read_request(conn), log, "Reservations pull")
        return parse_reservations(response)

    def notif_report(self, conn: ConnectionConfig, items: list[ConfirmItem], ok: bool) -> ET.Element:
        root = ET.Element(
            _q("OTA_NotifReportRQ"),
            {"xmlns": OTA_NS, "EchoToken": str(uuid.uuid4()), "TimeStamp": _now(), "Version": "1.0"},
        )
        if ok:
            ET.SubElement(root, _q("Success"))
        else:
            errors = ET.SubElement(root, _q("Errors"))
            for item in items:
                ET.SubElement(errors, _q("Error"), {"Type": "3", "Code": "450"}).text = (
                    item.error_text or "The reservation could not be recorded in the PMS"
                )[:250]
        hres = ET.SubElement(
            ET.SubElement(ET.SubElement(root, _q("NotifDetails")), _q("HotelNotifReport")),
            _q("HotelReservations"),
        )
        for item in items:
            stamp = item.at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            attrs = {"ResStatus": item.action.capitalize()}
            attrs["CreateDateTime" if item.action == "book" else "LastModifyDateTime"] = stamp
            h = ET.SubElement(hres, _q("HotelReservation"), attrs)
            ET.SubElement(h, _q("UniqueID"), {"Type": "16", "ID": item.message_id})
            if ok and item.pms_reference:
                ids = ET.SubElement(ET.SubElement(h, _q("ResGlobalInfo")), _q("HotelReservationIDs"))
                ET.SubElement(
                    ids, _q("HotelReservationID"), {"ResID_Type": "14", "ResID_Value": item.pms_reference}
                )
        return root

    async def confirm_bookings(
        self, conn: ConnectionConfig, items: list[ConfirmItem], log: ExchangeLog
    ) -> None:
        ok = [i for i in items if i.ok]
        failed = [i for i in items if not i.ok]
        if ok:
            await self._confirm(
                conn, self.notif_report(conn, ok, True), log, f"Confirm {len(ok)} reservation(s)"
            )
        for item in failed:  # the error text belongs to the whole message: one per failure
            await self._confirm(
                conn, self.notif_report(conn, [item], False), log, f"Report error for {item.external_id}"
            )

    async def _confirm(
        self, conn: ConnectionConfig, body: ET.Element, log: ExchangeLog, summary: str
    ) -> None:
        try:
            await self._soap(conn, "NotifReportRQ", body, log, summary)
        except ChannelError as exc:
            # 385: "Could not find Notifications to confirm": already confirmed.
            if exc.kind == ErrorKind.DATA and "385" in exc.message:
                return
            raise


# --- parsing helpers ---------------------------------------------------------------


def _find(el: ET.Element, *path: str) -> ET.Element | None:
    """Namespace-tolerant find (SiteMinder samples use both OTA and ota casing)."""
    current: ET.Element | None = el
    for name in path:
        if current is None:
            return None
        current = next((c for c in current if _local(c.tag) == name), None)
    return current


def _findall(el: ET.Element | None, *path: str) -> list[ET.Element]:
    if el is None:
        return []
    *parents, last = path
    parent = _find(el, *parents) if parents else el
    if parent is None:
        return []
    return [c for c in parent if _local(c.tag) == last]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _ota_error(errors: ET.Element, status: int | None) -> ChannelError:
    items = _findall(errors, "Error")
    texts = []
    kind = ErrorKind.DATA
    for e in items:
        etype, code = e.get("Type", ""), e.get("Code", "")
        text = (e.text or e.get("ShortText") or "").strip()
        texts.append(f"[{etype}{'/' + code if code else ''}] {text}")
        if etype in ("4", "5", "9"):
            kind = ErrorKind.AUTH
        elif kind != ErrorKind.AUTH and (etype == "6" or code in _CONFIG_CODES):
            kind = ErrorKind.CONFIG
        elif kind == ErrorKind.DATA and (code in _TRANSIENT_CODES or etype in ("12", "13")):
            kind = ErrorKind.TRANSIENT
    return ChannelError(kind, "; ".join(texts) or "Error response", http_status=status)


def _rest_error(text: str | None) -> str | None:
    import json

    try:
        data = json.loads(text or "")
    except ValueError:
        return None
    errors = data.get("errors") if isinstance(data, dict) else None
    if isinstance(errors, list) and errors:
        e = errors[0]
        meta = e.get("meta") or {}
        return str(meta.get("message") or e.get("message") or e.get("code"))[:300]
    if isinstance(data, dict) and data.get("message"):
        return str(data["message"])[:300]
    return None


def _chunks(items: list[Any], size: int = MAX_UPDATES_PER_MESSAGE) -> Iterable[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _amount(el: ET.Element | None) -> tuple[Decimal | None, bool]:
    """(amount, after_tax) from an element with AmountAfterTax / AmountBeforeTax."""
    if el is None:
        return None, True
    for attr, after in (("AmountAfterTax", True), ("AmountBeforeTax", False)):
        raw = el.get(attr)
        if raw:
            try:
                return Decimal(raw), after
            except InvalidOperation:
                return None, after
    return None, True


def _guest(profile_parent: ET.Element | None) -> InboundGuest | None:
    customer = _find(profile_parent, "Customer") if profile_parent is not None else None
    if customer is None:
        return None
    first = _text(_find(customer, "PersonName", "GivenName"))
    last = _text(_find(customer, "PersonName", "Surname"))
    phones = [t.get("PhoneNumber") for t in _findall(customer, "Telephone") if t.get("PhoneNumber")]
    email_el = _find(customer, "Email")
    country_el = _find(customer, "Address", "CountryName")
    country = country_el.get("Code") if country_el is not None else None
    if not (first or last):
        return None
    return InboundGuest(
        first_name=first or "-",
        last_name=last or first,
        email=_text(email_el) or None,
        phone=phones[0] if phones else None,
        country=country.upper() if country and len(country) == 2 else None,
    )


def _attr(el: ET.Element | None, name: str) -> str | None:
    return el.get(name) if el is not None else None


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _texts(el: ET.Element | None) -> list[str]:
    out = []
    for c in _findall(el, "Comments", "Comment"):
        text = _find(c, "Text")
        if text is not None and text.text and text.text.strip():
            label = c.get("Name")
            out.append(f"{label}: {text.text.strip()}" if label else text.text.strip())
    return out


def parse_reservations(response: ET.Element) -> list[InboundBooking]:
    """OTA_ResRetrieveRS → bookings. Card numbers are never copied: only the
    card brand and the last four digits are kept."""
    bookings = []
    for hr in _findall(response, "ReservationsList", "HotelReservation"):
        ids = _findall(hr, "UniqueID")
        external_id = next((u.get("ID") for u in ids if u.get("Type") == "14"), None)
        message_id = next(
            (
                u.get("ID")
                for u in ids
                if u.get("Type") == "16" and u.get("ID_Context") == "MESSAGE_UNIQUE_ID"
            ),
            None,
        )
        if not external_id or not message_id:
            continue
        action = (hr.get("ResStatus") or "Book").lower()
        if action not in ("book", "modify", "cancel"):
            action = "modify"
        sources = _findall(hr, "POS", "Source")
        primary = next(
            (
                s
                for s in sources
                if (b := _find(s, "BookingChannel")) is not None and b.get("Primary") != "false"
            ),
            None,
        )
        company = _find(primary, "BookingChannel", "CompanyName") if primary is not None else None
        glob = _find(hr, "ResGlobalInfo")
        channel_ref = next(
            (
                h.get("ResID_Value")
                for h in _findall(glob, "HotelReservationIDs", "HotelReservationID")
                if h.get("ResID_Type") == "14"
            ),
            None,
        )
        total_el = _find(glob, "Total") if glob is not None else None
        total, total_after = _amount(total_el)
        currency = total_el.get("CurrencyCode") if total_el is not None else None
        hotel_el = _find(glob, "BasicPropertyInfo") if glob is not None else None

        stays: list[InboundStay] = []
        after_tax = total_after
        for rs in _findall(hr, "RoomStays", "RoomStay"):
            span = _find(rs, "TimeSpan")
            arrival = _date(span.get("Start")) if span is not None else None
            departure = _date(span.get("End")) if span is not None else None
            room_type = _find(rs, "RoomTypes", "RoomType")
            room_code = room_type.get("RoomTypeCode") if room_type is not None else None
            counts = {
                g.get("AgeQualifyingCode"): int(g.get("Count") or 0)
                for g in _findall(rs, "GuestCounts", "GuestCount")
            }
            nights: list[InboundNight] = []
            first_rate: str | None = None
            for rr in _findall(rs, "RoomRates", "RoomRate"):
                rate_code = rr.get("RatePlanCode")
                first_rate = first_rate or rate_code
                room_code = room_code or rr.get("RoomTypeCode")
                for rate in _findall(rr, "Rates", "Rate"):
                    start = _date(rate.get("EffectiveDate"))
                    end = _date(rate.get("ExpireDate"))
                    amount, after = _amount(_find(rate, "Total"))
                    if amount is None:
                        amount, after = _amount(_find(rate, "Base"))
                    if start is None or end is None or amount is None:
                        continue
                    after_tax = after
                    day = start
                    while day < end:
                        nights.append(InboundNight(day, amount, rate_code))
                        day += timedelta(days=1)
            if (first_rate is None) and (rp := _find(rs, "RatePlans", "RatePlan")) is not None:
                first_rate = rp.get("RatePlanCode")
            stay_total, _ = _amount(_find(rs, "Total"))
            if hotel_el is None:
                hotel_el = _find(rs, "BasicPropertyInfo")
            if arrival is None or departure is None:
                continue
            stays.append(
                InboundStay(
                    room_code=room_code,
                    rate_code=first_rate,
                    arrival=arrival,
                    departure=departure,
                    adults=max(1, counts.get("10", 0) or 1),
                    children=counts.get("8", 0) + counts.get("7", 0),
                    nights=nights,
                    total=stay_total,
                    comments=_texts(rs),
                )
            )

        booker = None
        for info in _findall(glob, "Profiles", "ProfileInfo"):
            profile = _find(info, "Profile")
            if profile is not None and profile.get("ProfileType") == "1":
                booker = _guest(profile)
                break
        guest_comments: list[str] = []
        for rg in _findall(hr, "ResGuests", "ResGuest"):
            guest_comments += _texts(rg)
            if booker is None:
                for info in _findall(rg, "Profiles", "ProfileInfo"):
                    booker = _guest(_find(info, "Profile")) or booker

        card = (
            _find(glob, "Guarantee", "GuaranteesAccepted", "GuaranteeAccepted", "PaymentCard")
            if glob is not None
            else None
        )
        brand = last4 = None
        if card is not None:
            brand = card.get("CardCode")
            digits = "".join(
                ch for ch in (card.get("CardNumber") or card.get("MaskedCardNumber") or "") if ch.isdigit()
            )
            last4 = digits[-4:] if len(digits) >= 4 else None
            for attr in ("CardNumber", "SeriesCode"):  # do not keep it in memory longer than needed
                card.attrib.pop(attr, None)
        extra: dict[str, Any] = {}
        deposit = (
            _find(glob, "DepositPayments", "GuaranteePayment", "AmountPercent") if glob is not None else None
        )
        if deposit is not None and deposit.get("Amount"):
            extra["deposit"] = deposit.get("Amount")
        fees = [
            f"{_attr(_find(f, 'Description'), 'Name') or 'Fee'} {f.get('Amount')}"
            for f in _findall(glob, "Fees", "Fee")
        ]
        if fees:
            extra["fees"] = fees
        services = []
        for svc in _findall(hr, "Services", "Service"):
            price = _find(svc, "Price")
            amount, _ = _amount(_find(price, "Total") if price is not None else None)
            desc = _find(price, "RateDescription", "Text") if price is not None else None
            services.append(
                f"{svc.get('ServiceInventoryCode') or 'EXTRA'}"
                f"{' ' + str(amount) if amount is not None else ''}"
                f"{' - ' + desc.text.strip() if desc is not None and desc.text else ''}"
            )
        if services:
            extra["services"] = services

        bookings.append(
            InboundBooking(
                external_id=external_id,
                message_id=message_id,
                action=action,
                message_at=_datetime(hr.get("LastModifyDateTime") or hr.get("CreateDateTime")),
                hotel_code=hotel_el.get("HotelCode") if hotel_el is not None else None,
                channel_code=company.get("Code") if company is not None else None,
                channel_name=_text(company) or None,
                channel_reference=channel_ref,
                currency=currency or _first_currency(hr),
                amounts_after_tax=after_tax,
                total=total,
                stays=stays,
                booker=booker,
                comments=_texts(glob) + guest_comments + [c for s in stays for c in s.comments],
                card_brand=brand,
                card_last4=last4,
                extra=extra,
            )
        )
    return bookings


def _first_currency(hr: ET.Element) -> str | None:
    for el in hr.iter():
        code = el.get("CurrencyCode")
        if code:
            return code
    return None
