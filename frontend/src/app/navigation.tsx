import type { ComponentType } from 'react';
import {
  IconBuildingCommunity,
  IconCalendarMonth,
  IconClipboardList,
  IconDoor,
  IconAddressBook,
  IconLayoutDashboard,
  IconSettings,
  IconSwimming,
  IconUsersGroup,
} from '@tabler/icons-react';

/**
 * Navigation is generated from this registry. A module appears here only once
 * it is implemented end to end, so the menu never contains dead entries; each
 * entry is shown only to users holding its permission in the current hotel.
 * Planned modules (front desk, housekeeping, payments, ...) are
 * added as their phases are delivered (see docs/CHECKLIST.md).
 */
export interface NavItem {
  key: string;
  path: string;
  icon: ComponentType<{ size?: number; stroke?: number }>;
  permission: string | null;
}

export const NAV_ITEMS: NavItem[] = [
  { key: 'dashboard', path: '/', icon: IconLayoutDashboard, permission: 'hotel.view' },
  { key: 'reservations', path: '/reservations', icon: IconClipboardList, permission: 'reservations.view' },
  { key: 'calendar', path: '/calendar', icon: IconCalendarMonth, permission: 'reservations.view' },
  { key: 'rooms', path: '/rooms', icon: IconDoor, permission: 'rooms.view' },
  { key: 'guests', path: '/guests', icon: IconAddressBook, permission: 'guests.view' },
  { key: 'services', path: '/services', icon: IconSwimming, permission: 'hotel.view' },
  { key: 'users', path: '/users', icon: IconUsersGroup, permission: 'users.view' },
  { key: 'configuration', path: '/settings', icon: IconSettings, permission: 'hotel.view' },
];

export const HotelIcon = IconBuildingCommunity;
