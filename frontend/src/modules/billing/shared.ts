import { useMemo } from 'react';
import type { TFunction } from 'i18next';

import { API_BASE } from '@/api/client';
import { useHotelQuery } from '@/api/hooks';
import type { CardBrand, Currency, FeeType, FolioCharge, PaymentMethod } from '@/api/types';
import { useHotel } from '@/auth/AuthProvider';
import { LANGUAGES } from '@/i18n';
import { pickLocalized } from '@/lib/localized';

export const PAYMENT_METHODS: PaymentMethod[] = ['cash', 'card', 'bank_transfer', 'online', 'other'];
export const CARD_BRANDS: CardBrand[] = ['visa', 'mastercard', 'amex', 'unionpay', 'jcb', 'discover', 'other'];
export const FEE_TYPES: FeeType[] = ['late_checkout', 'early_departure', 'damage', 'cancellation', 'no_show', 'other'];

/** Same-origin URL of a PDF document (the session cookie authenticates it). */
export function useDocumentUrl() {
  const hotel = useHotel();
  return (path: string, language?: string | null) =>
    `${API_BASE}/hotels/${hotel.id}${path}${language ? `?language=${encodeURIComponent(language)}` : ''}`;
}

export function languageOptions() {
  return LANGUAGES.map((l) => ({ value: l.code, label: l.label }));
}

/** Currencies a payment can be taken in: the hotel's own plus active foreign ones. */
export function usePaymentCurrencies() {
  const hotel = useHotel();
  const currencies = useHotelQuery<Currency[]>('currency', '/currencies');
  return useMemo(() => {
    const active = (currencies.data ?? []).filter((c) => c.is_active);
    return {
      base: hotel.currency_code,
      list: [hotel.currency_code, ...active.map((c) => c.code)],
      rate: (code: string) => (code === hotel.currency_code ? '1' : (active.find((c) => c.code === code)?.units_per_base ?? null)),
      loading: currencies.isPending,
    };
  }, [currencies.data, currencies.isPending, hotel.currency_code]);
}

/** Convert a tendered amount to the hotel currency (display only; the server is authoritative). */
export function toBase(amount: number, unitsPerBase: string | null): number | null {
  if (!unitsPerBase || !Number.isFinite(amount)) return null;
  return Math.round((amount / Number(unitsPerBase)) * 100) / 100;
}

export function chargeTitle(c: FolioCharge, t: TFunction, language: string, fallback: string): string {
  if (c.kind === 'service') return pickLocalized(c.name, language, fallback) || c.description || '';
  if (c.kind === 'outlet') return `${pickLocalized(c.name, language, fallback)} · ${c.description ?? ''}`;
  if (c.kind === 'fee') return t(`billing.fee_types.${c.fee_type ?? 'other'}`);
  return t('billing.adjustment');
}

/** Default quantity for a catalog service, from its pricing unit and the stay. */
export function defaultQuantity(unit: string, nights: number, persons: number): number {
  switch (unit) {
    case 'per_night':
      return Math.max(1, nights);
    case 'per_person':
      return Math.max(1, persons);
    case 'per_person_night':
      return Math.max(1, nights * persons);
    default:
      return 1;
  }
}
