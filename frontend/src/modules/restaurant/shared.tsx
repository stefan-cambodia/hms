import { useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { Badge } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { LineStatus, MenuCategory, MenuItem, Outlet } from '@/api/types';
import { useHotel } from '@/auth/AuthProvider';
import { type LocalizedText, pickLocalized } from '@/lib/localized';

export const LINE_COLORS: Record<LineStatus, string> = {
  new: 'gray',
  sent: 'orange',
  preparing: 'blue',
  ready: 'teal',
  served: 'green',
  void: 'red',
};

export function LineStatusBadge({ status }: { status: LineStatus }) {
  const { t } = useTranslation();
  return (
    <Badge size="xs" color={LINE_COLORS[status]} variant={status === 'ready' ? 'filled' : 'light'} radius="sm">
      {t(`restaurant.line_status.${status}`)}
    </Badge>
  );
}

export function useLocalized() {
  const { i18n } = useTranslation();
  const hotel = useHotel();
  return (value: LocalizedText | null | undefined) => pickLocalized(value ?? {}, i18n.language, hotel.default_language);
}

/** The active outlets and the one selected (kept in the URL as ?outlet=). */
export function useOutlet() {
  const outlets = useHotelQuery<Outlet[]>('restaurant_outlet', '/restaurant/outlets');
  const [params, setParams] = useSearchParams();
  const active = useMemo(() => (outlets.data ?? []).filter((o) => o.is_active), [outlets.data]);
  const wanted = params.get('outlet');
  const outlet = active.find((o) => o.id === wanted) ?? active[0] ?? null;
  const select = (id: string) =>
    setParams(
      (p) => {
        const out = new URLSearchParams(p);
        out.set('outlet', id);
        return out;
      },
      { replace: true },
    );
  return { outlets: outlets.data ?? [], active, outlet, select, loading: outlets.isPending };
}

export function useMenu(outletId: string | null | undefined) {
  const categories = useHotelQuery<MenuCategory[]>('menu_item', '/restaurant/categories', { outlet_id: outletId }, !!outletId);
  const items = useHotelQuery<MenuItem[]>('menu_item', '/restaurant/menu-items', { outlet_id: outletId }, !!outletId);
  return {
    categories: (categories.data ?? []).filter((c) => c.is_active),
    allCategories: categories.data ?? [],
    items: (items.data ?? []).filter((i) => i.is_active),
    allItems: items.data ?? [],
    loading: categories.isPending || items.isPending,
  };
}

/** Minutes elapsed since an ISO instant (for kitchen tickets). */
export function minutesSince(iso: string | null, now: number): number {
  return iso ? Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60000)) : 0;
}
