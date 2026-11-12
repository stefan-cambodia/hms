import { Link } from 'react-router';
import { Anchor, Badge, Card, Group, Progress, RingProgress, SimpleGrid, Skeleton, Stack, Text, ThemeIcon, Title } from '@mantine/core';
import { IconBed, IconCheck, IconCircleDashed, IconDoor, IconSparkles, IconSwimming } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { Building, Facility, Hotel, Room, RoomType, TaxRate } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { PageHeader } from '@/components/ui';
import { formatNumber } from '@/lib/format';
import { pickLocalized } from '@/lib/localized';
import TodayPanel from './TodayPanel';

const HK = ['clean', 'inspected', 'in_progress', 'dirty'] as const;
const HK_COLOR: Record<(typeof HK)[number], string> = { clean: 'lagoon.6', inspected: 'teal.4', in_progress: 'blue.5', dirty: 'orange.5' };

function Stat({ label, value, icon: Icon, hint, loading }: { label: string; value: string; icon: typeof IconDoor; hint?: string; loading: boolean }) {
  return (
    <Card>
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <div>
          <Text size="sm" c="dimmed">
            {label}
          </Text>
          {loading ? (
            <Skeleton h={36} w={64} mt={4} />
          ) : (
            <Text fz={28} fw={650} lh={1.25} mt={2}>
              {value}
            </Text>
          )}
          {hint && (
            <Text size="xs" c="dimmed" mt={2}>
              {hint}
            </Text>
          )}
        </div>
        <ThemeIcon variant="light" size={42} radius="md">
          <Icon size={22} stroke={1.6} />
        </ThemeIcon>
      </Group>
    </Card>
  );
}

export default function DashboardPage() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const lang = i18n.language;
  const rooms = useHotelQuery<Room[]>('room', '/rooms');
  const types = useHotelQuery<RoomType[]>('room_type', '/room-types');
  const facilities = useHotelQuery<Facility[]>('facility', '/facilities');
  const buildings = useHotelQuery<Building[]>('building', '/buildings');
  const taxes = useHotelQuery<TaxRate[]>('tax_rate', '/tax-rates');
  const profile = useHotelQuery<Hotel>('hotel', '');

  // Never show zeros while data is loading: they would read as "no rooms".
  const loading = [rooms, types, facilities, buildings, taxes, profile].some((q) => q.isPending);
  const active = (rooms.data ?? []).filter((r) => r.is_active);
  const hkCounts = Object.fromEntries(HK.map((s) => [s, active.filter((r) => r.housekeeping_status === s).length])) as Record<(typeof HK)[number], number>;
  const ready = hkCounts.clean + hkCounts.inspected;

  // First-run checklist: derived from real configuration, links to the screens.
  const steps = [
    { key: 'profile', done: !!(profile.data?.address_line1 && profile.data?.phone), to: '/settings/profile' },
    { key: 'structure', done: (buildings.data?.length ?? 0) > 0, to: '/settings/structure' },
    { key: 'room_types', done: (types.data?.length ?? 0) > 0, to: '/settings/room-types' },
    { key: 'rooms', done: active.length > 0, to: '/rooms' },
    { key: 'taxes', done: (taxes.data?.length ?? 0) > 0, to: '/settings/taxes' },
    { key: 'facilities', done: (facilities.data?.length ?? 0) > 0, to: '/services' },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  const showSetup = !loading && can('config.hotel.manage') && doneCount < steps.length;

  return (
    <>
      <PageHeader title={t('dashboard.welcome', { hotel: hotel.name })} description={t('dashboard.description')} />
      {(can('reports.view') || can('reservations.view')) && <TodayPanel />}
      <SimpleGrid cols={{ base: 1, xs: 2, lg: 4 }} mb="lg">
        <Stat label={t('dashboard.rooms_in_service')} value={formatNumber(active.length, lang)} icon={IconDoor} loading={loading} />
        <Stat label={t('dashboard.room_categories')} value={formatNumber(types.data?.filter((x) => x.is_active).length ?? 0, lang)} icon={IconBed} loading={loading} />
        <Stat label={t('dashboard.rooms_ready')} value={formatNumber(ready, lang)} icon={IconSparkles} hint={t('dashboard.rooms_ready_hint')} loading={loading} />
        <Stat label={t('dashboard.facilities')} value={formatNumber(facilities.data?.filter((f) => f.is_active).length ?? 0, lang)} icon={IconSwimming} loading={loading} />
      </SimpleGrid>

      <SimpleGrid cols={{ base: 1, md: showSetup ? 3 : 2 }} spacing="lg">
        {showSetup && (
          <Card>
            <Group justify="space-between" mb="sm">
              <Title order={3}>{t('dashboard.setup.title')}</Title>
              <Badge variant="light">
                {doneCount}/{steps.length}
              </Badge>
            </Group>
            <Progress value={(doneCount / steps.length) * 100} mb="md" />
            <Stack gap="xs">
              {steps.map((s) => (
                <Group key={s.key} gap="sm" wrap="nowrap">
                  <ThemeIcon size={22} radius="xl" variant={s.done ? 'filled' : 'light'} color={s.done ? 'lagoon' : 'gray'}>
                    {s.done ? <IconCheck size={14} /> : <IconCircleDashed size={14} />}
                  </ThemeIcon>
                  <Anchor component={Link} to={s.to} size="sm" c={s.done ? 'dimmed' : undefined} td={s.done ? 'line-through' : undefined}>
                    {t(`dashboard.setup.${s.key}`)}
                  </Anchor>
                </Group>
              ))}
            </Stack>
          </Card>
        )}

        <Card>
          <Title order={3} mb="md">
            {t('dashboard.housekeeping')}
          </Title>
          {loading ? (
            <Skeleton h={140} />
          ) : active.length === 0 ? (
            <Text c="dimmed" size="sm">
              {t('dashboard.no_rooms')}
            </Text>
          ) : (
            <Group wrap="nowrap" align="center">
              <RingProgress
                size={140}
                thickness={14}
                roundCaps
                sections={HK.filter((s) => hkCounts[s]).map((s) => ({ value: (hkCounts[s] / active.length) * 100, color: HK_COLOR[s], tooltip: `${t(`rooms.hk.${s}`)}: ${hkCounts[s]}` }))}
                label={
                  <Text ta="center" fw={700} className="hms-num">
                    {Math.round((ready / active.length) * 100)}%
                  </Text>
                }
              />
              <Stack gap={6}>
                {HK.map((s) => (
                  <Group key={s} gap="xs" wrap="nowrap">
                    <span style={{ width: 10, height: 10, borderRadius: 3, background: `var(--mantine-color-${HK_COLOR[s].replace('.', '-')})` }} />
                    <Text size="sm">
                      {t(`rooms.hk.${s}`)} · <b className="hms-num">{hkCounts[s]}</b>
                    </Text>
                  </Group>
                ))}
              </Stack>
            </Group>
          )}
        </Card>

        <Card>
          <Title order={3} mb="md">
            {t('dashboard.inventory')}
          </Title>
          <Stack gap="sm">
            {(types.data ?? [])
              .filter((x) => x.is_active)
              .map((x) => (
                <div key={x.id}>
                  <Group justify="space-between" mb={4}>
                    <Text size="sm">{pickLocalized(x.name, lang, hotel.default_language)}</Text>
                    <Text size="sm" fw={600} className="hms-num">
                      {x.room_count}
                    </Text>
                  </Group>
                  <Progress value={active.length ? (x.room_count / active.length) * 100 : 0} color={x.color ?? undefined} size="sm" />
                </div>
              ))}
            {loading && <Skeleton h={80} />}
            {types.data?.length === 0 && (
              <Text c="dimmed" size="sm">
                {t('dashboard.no_categories')}
              </Text>
            )}
          </Stack>
        </Card>
      </SimpleGrid>
    </>
  );
}
