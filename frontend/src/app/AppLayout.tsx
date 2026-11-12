import { Suspense, useCallback } from 'react';
import { NavLink as RouterNavLink, Outlet, useLocation } from 'react-router';
import {
  AppShell,
  Avatar,
  Box,
  Burger,
  Center,
  Group,
  Loader,
  Menu,
  NavLink,
  ScrollArea,
  Select,
  Text,
  UnstyledButton,
} from '@mantine/core';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import { IconChevronDown, IconLogout, IconUserCircle } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';

import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/client';
import { hotelKey, useRealtime } from '@/api/realtime';
import type { Outlet as SalesOutlet } from '@/api/types';
import { HotelIcon, NAV_ITEMS } from '@/app/navigation';
import { useAuth } from '@/auth/AuthProvider';
import { ConnectionBanner, ConnectionIndicator } from '@/components/ConnectionIndicator';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';

export function PageLoader() {
  return (
    <Center h="60vh">
      <Loader />
    </Center>
  );
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('');
}

export function AppLayout() {
  const { t } = useTranslation();
  const { me, hotel, can, logout, refresh, selectHotel } = useAuth();
  const [opened, { toggle, close }] = useDisclosure();
  const location = useLocation();
  const navigate = useNavigate();
  const compact = useMediaQuery('(max-width: 48em)');

  const onMeChanged = useCallback(() => void refresh().catch(() => undefined), [refresh]);
  const onSessionEnded = useCallback(() => void refresh().catch(() => undefined), [refresh]);
  useRealtime(hotel?.id, onMeChanged, onSessionEnded);
  // Optional modules appear only when the hotel uses them (e.g. has a restaurant);
  // managers always see them so they can set them up.
  const outlets = useQuery({
    queryKey: hotel ? hotelKey(hotel.id, 'restaurant_outlet', 'nav') : ['no-hotel'],
    queryFn: ({ signal }) => api.get<SalesOutlet[]>(`/hotels/${hotel!.id}/restaurant/outlets`, signal),
    enabled: !!hotel && can('restaurant.view'),
    staleTime: 60_000,
  });
  const features = { restaurant: can('restaurant.manage') || (outlets.data ?? []).some((o) => o.is_active) };

  if (!me || !hotel) return null;
  const items = NAV_ITEMS.filter((i) => (!i.permission || can(i.permission)) && (!i.feature || features[i.feature]));
  const isActive = (path: string) => (path === '/' ? location.pathname === '/' : location.pathname.startsWith(path));

  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{ width: 248, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding={{ base: 'md', md: 'xl' }}
      styles={{ main: { background: 'var(--hms-canvas)' } }}
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label={t('nav.toggle')} />
            <HotelIcon size={26} stroke={1.6} />
            {me.hotels.length > 1 ? (
              <Select
                aria-label={t('nav.hotel')}
                value={hotel.id}
                data={me.hotels.map((h) => ({ value: h.id, label: h.name }))}
                onChange={(id) => id && selectHotel(id)}
                allowDeselect={false}
                w={compact ? 160 : 240}
                variant="filled"
              />
            ) : (
              <Text fw={650} truncate>
                {hotel.name}
              </Text>
            )}
          </Group>
          <Group gap="xs" wrap="nowrap">
            {!compact && <ConnectionIndicator />}
            <LanguageSwitcher compact={compact} />
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <UnstyledButton aria-label={t('nav.account')}>
                  <Group gap={8} wrap="nowrap">
                    <Avatar color="lagoon" radius="xl" size={34}>
                      {initials(me.user.full_name)}
                    </Avatar>
                    {!compact && (
                      <>
                        <Box maw={160}>
                          <Text size="sm" fw={600} truncate>
                            {me.user.full_name}
                          </Text>
                        </Box>
                        <IconChevronDown size={14} />
                      </>
                    )}
                  </Group>
                </UnstyledButton>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Label>{me.user.email}</Menu.Label>
                <Menu.Item leftSection={<IconUserCircle size={16} />} onClick={() => navigate('/account')}>
                  {t('nav.my_account')}
                </Menu.Item>
                <Menu.Divider />
                <Menu.Item color="red" leftSection={<IconLogout size={16} />} onClick={() => void logout()}>
                  {t('auth.logout')}
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        <AppShell.Section grow component={ScrollArea}>
          {items.map((item) => (
            <NavLink
              key={item.key}
              component={RouterNavLink}
              to={item.path}
              label={t(`nav.${item.key}`)}
              leftSection={<item.icon size={20} stroke={1.6} />}
              active={isActive(item.path)}
              onClick={close}
              variant="light"
              style={{ borderRadius: 'var(--mantine-radius-md)', minHeight: 44 }}
              mb={2}
            />
          ))}
        </AppShell.Section>
        {compact && (
          <AppShell.Section pt="sm">
            <ConnectionIndicator />
          </AppShell.Section>
        )}
      </AppShell.Navbar>

      <AppShell.Main>
        <Box mx={{ base: -16, md: -32 }} mt={{ base: -16, md: -32 }} mb="md">
          <ConnectionBanner />
        </Box>
        <Box maw={1400} mx="auto">
          <Suspense fallback={<PageLoader />}>
            <Outlet />
          </Suspense>
        </Box>
      </AppShell.Main>
    </AppShell>
  );
}
