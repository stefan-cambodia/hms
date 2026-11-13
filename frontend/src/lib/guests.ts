import type { TFunction } from 'i18next';

/** "2 adults", "1 adult · 1 child": plural forms of every language; children
 * are only mentioned when there are some. */
export function guestsLabel(t: TFunction, adults: number, children: number): string {
  const parts = [t('reservations.adults_count', { count: adults })];
  if (children > 0) parts.push(t('reservations.children_count', { count: children }));
  return parts.join(' · ');
}
