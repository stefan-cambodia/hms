# SiteMinder pmsXchange official samples

Copied verbatim on 2026-11-12 from SiteMinder's public developer documentation
(https://developer.siteminder.com/pmsxchange-api/...), used as contract-test
fixtures for `app/modules/channels/adapters/siteminder.py`.

| File | Source page |
|------|-------------|
| avail_single_date.xml | reference/availability.md ("Single date") |
| restriction_*.xml | reference/restrictions/pms-to-sm.md |
| rates_pdp.xml, rates_success.xml | reference/rates/pms-to-sm.md |
| read_rq_hotel_level.xml, res_retrieve_*.xml, confirm_reservation.xml | reference/reservations/pull.md |
| error_invalid_credentials.xml, error_invalid_hotel.xml | guides/error-handling.md |
| fault_payload_too_large.xml | guides/integration-requirements.md |

Corrections of documentation defects (the samples as published are not
well-formed XML):

* `res_retrieve_min_content_fixed.xml`: the missing `</ReservationsList>` was added.
* `confirm_reservation.xml`: the envelope uses the `SOAP-ENV:` prefix but only
  declares `xmlns:soap`; `xmlns:SOAP-ENV` was added.

The card number in `res_retrieve_max_content.xml` (4444 4444 4444 4444) is
SiteMinder's documentation test value, not real card data.
