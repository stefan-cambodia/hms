/** Reference code lists; display names come from Intl.DisplayNames in the user's language. */

export const CURRENCY_CODES = (
  'AED AFN ALL AMD AOA ARS AUD AZN BAM BBD BDT BGN BHD BND BOB BRL BSD BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC ' +
  'CZK DKK DOP DZD EGP ETB EUR FJD GBP GEL GHS GTQ HKD HNL HUF IDR ILS INR IQD ISK JMD JOD JPY KES KGS KHR KRW KWD KZT ' +
  'LAK LBP LKR MAD MDL MGA MKD MMK MNT MOP MUR MVR MXN MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG ' +
  'QAR RON RSD RUB RWF SAR SCR SEK SGD THB TJS TND TRY TTD TWD TZS UAH UGX USD UYU UZS VND XAF XOF XPF ZAR ZMW'
).split(' ');

export const COUNTRY_CODES = (
  'AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD ' +
  'CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF ' +
  'GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN ' +
  'KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA ' +
  'NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI ' +
  'SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI ' +
  'VN VU WF WS YE YT ZA ZM ZW'
).split(' ');

export function timeZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  const zones = intl.supportedValuesOf?.('timeZone') ?? [];
  return zones.length ? (zones.includes('UTC') ? zones : ['UTC', ...zones]) : ['UTC', 'Asia/Phnom_Penh', 'Asia/Bangkok', 'Europe/Paris'];
}
