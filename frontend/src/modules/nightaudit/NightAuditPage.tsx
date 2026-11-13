import { useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { ActionIcon, Alert, Anchor, Badge, Button, Card, Checkbox, Group, Loader, Modal, SimpleGrid, Stack, Table, Text, Textarea, Title } from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { modals } from '@mantine/modals';
import {
  IconAlertTriangle,
  IconCalendarCheck,
  IconChevronLeft,
  IconChevronRight,
  IconCircleCheck,
  IconFileTypePdf,
  IconLock,
  IconMoonStars,
} from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { api } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { AuditStay, DayClosureRow, NightAudit, NightAuditItems } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { EmptyState, PageHeader, SectionTitle } from '@/components/ui';
import { addDays } from '@/lib/dates';
import { applyFieldErrors, notifyError, notifySuccess } from '@/lib/errors';
import { formatDate, formatDateTime, formatMoney, formatNumber } from '@/lib/format';
import { pickLocalized } from '@/lib/localized';
import { useDocumentUrl } from '@/modules/billing/shared';

export default function NightAuditPage() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const [search, setSearch] = useSearchParams();
  const requested = search.get('date');
  const audit = useHotelQuery<NightAudit>('night_audit', '/night-audit', { date: requested ?? undefined });
  const history = useHotelQuery<DayClosureRow[]>('night_audit', '/night-audit/closures', { limit: 30 });
  const [closing, setClosing] = useState(false);
  const docUrl = useDocumentUrl();
  const a = audit.data;
  const go = (day: string | null) =>
    setSearch(
      (p) => {
        const out = new URLSearchParams(p);
        if (day) out.set('date', day);
        else out.delete('date');
        return out;
      },
      { replace: true },
    );

  return (
    <>
      <PageHeader
        title={t('nav.night_audit')}
        description={t('nightaudit.description')}
        actions={
          a && (
            <>
              <ActionIcon variant="default" size="lg" aria-label={t('calendar.previous')} onClick={() => go(addDays(a.date, -1))}>
                <IconChevronLeft size={18} />
              </ActionIcon>
              <DatePickerInput
                value={a.date}
                maxDate={a.today}
                onChange={(v) => v && go(v)}
                valueFormat="ddd D MMM YYYY"
                w={170}
                aria-label={t('nightaudit.day')}
              />
              <ActionIcon variant="default" size="lg" aria-label={t('calendar.next')} disabled={a.date >= a.today} onClick={() => go(addDays(a.date, 1))}>
                <IconChevronRight size={18} />
              </ActionIcon>
              {requested && (
                <Button variant="default" onClick={() => go(null)}>
                  {t('nightaudit.next_to_close')}
                </Button>
              )}
            </>
          )
        }
      />
      {audit.isPending || !a ? (
        <Loader size="sm" />
      ) : (
        <Stack gap="lg">
          <Status audit={a} onClose={() => setClosing(true)} onGo={go} pdf={docUrl(`/night-audit/${a.date}/report.pdf`, i18n.language)} />
          {!a.closure && <OpenItems items={a.open_items} count={a.open_count} />}
          {a.closure && a.open_count > 0 && <OpenItems items={a.open_items} count={a.open_count} recorded />}
          <Report audit={a} />
          <Stack gap="xs">
            <SectionTitle>{t('nightaudit.history')}</SectionTitle>
            {(history.data ?? []).length === 0 ? (
              <EmptyState title={t('nightaudit.no_history')} />
            ) : (
              <Table.ScrollContainer minWidth={720}>
                <Table verticalSpacing={6} highlightOnHover data-testid="closures">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{t('nightaudit.day')}</Table.Th>
                      <Table.Th>{t('nightaudit.closed_by')}</Table.Th>
                      <Table.Th ta="right">{t('reports.occupancy')}</Table.Th>
                      <Table.Th ta="right">{t('nightaudit.revenue')}</Table.Th>
                      <Table.Th ta="right">{t('nightaudit.net_received')}</Table.Th>
                      <Table.Th ta="right">{t('nightaudit.open_at_close')}</Table.Th>
                      <Table.Th />
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {history.data?.map((c) => (
                      <Table.Tr key={c.id} style={{ cursor: 'pointer' }} onClick={() => go(c.date)}>
                        <Table.Td fw={600}>{formatDate(c.date, i18n.language)}</Table.Td>
                        <Table.Td>
                          <Text size="sm">{c.closed_by_name ?? '—'}</Text>
                          <Text size="xs" c="dimmed">
                            {formatDateTime(c.closed_at, i18n.language, hotel.timezone)}
                          </Text>
                        </Table.Td>
                        <Table.Td ta="right" className="hms-num">
                          {c.occupancy != null ? `${formatNumber(c.occupancy, i18n.language, 1)} %` : '—'}
                        </Table.Td>
                        <Table.Td ta="right" className="hms-num">
                          {c.revenue != null ? formatMoney(c.revenue, c.currency, i18n.language) : '—'}
                        </Table.Td>
                        <Table.Td ta="right" className="hms-num">
                          {c.payments_net != null ? formatMoney(c.payments_net, c.currency, i18n.language) : '—'}
                        </Table.Td>
                        <Table.Td ta="right">{c.open_items > 0 ? <Badge color="orange" variant="light">{c.open_items}</Badge> : '0'}</Table.Td>
                        <Table.Td ta="right">
                          <Anchor size="sm" href={docUrl(`/night-audit/${c.date}/report.pdf`, i18n.language)} target="_blank" onClick={(e) => e.stopPropagation()}>
                            PDF
                          </Anchor>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            )}
          </Stack>
        </Stack>
      )}
      {closing && a && <CloseModal audit={a} onClose={() => setClosing(false)} onClosed={() => go(a.date)} />}
    </>
  );
}

function Status({ audit: a, onClose, onGo, pdf }: { audit: NightAudit; onClose: () => void; onGo: (day: string | null) => void; pdf: string }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const day = formatDate(a.date, i18n.language);
  if (a.closure) {
    return (
      <Alert color="teal" icon={<IconLock size={18} />} title={t('nightaudit.closed_title', { date: day })}>
        <Group justify="space-between" align="flex-end">
          <Stack gap={2}>
            <Text size="sm">
              {t('nightaudit.closed_by_at', {
                name: a.closure.closed_by_name ?? '—',
                at: formatDateTime(a.closure.closed_at, i18n.language, hotel.timezone),
              })}
            </Text>
            <Text size="sm" c="dimmed">
              {t('nightaudit.closed_frozen')}
            </Text>
            {a.closure.notes && (
              <Text size="sm" mt={4}>
                {a.closure.notes}
              </Text>
            )}
          </Stack>
          <Button component="a" href={pdf} target="_blank" variant="light" leftSection={<IconFileTypePdf size={16} />}>
            {t('nightaudit.report_pdf')}
          </Button>
        </Group>
      </Alert>
    );
  }
  if (a.blocker === 'DAY_NOT_OVER') {
    return (
      <Alert color="blue" icon={<IconMoonStars size={18} />} title={t('nightaudit.not_over_title', { date: day })}>
        {t('nightaudit.not_over_body')}
      </Alert>
    );
  }
  if (a.blocker === 'PREVIOUS_DAY_OPEN' && a.last_closed) {
    const next = addDays(a.last_closed, 1);
    return (
      <Alert color="orange" icon={<IconAlertTriangle size={18} />} title={t('nightaudit.previous_open_title')}>
        <Group justify="space-between">
          <Text size="sm">{t('nightaudit.previous_open_body', { date: formatDate(next, i18n.language) })}</Text>
          <Button size="xs" variant="light" color="orange" onClick={() => onGo(next)}>
            {t('nightaudit.go_to', { date: formatDate(next, i18n.language) })}
          </Button>
        </Group>
      </Alert>
    );
  }
  return (
    <Card withBorder padding="md">
      <Group justify="space-between">
        <Stack gap={2}>
          <Title order={3}>{t('nightaudit.ready_title', { date: day })}</Title>
          <Text size="sm" c="dimmed">
            {a.open_count > 0 ? t('nightaudit.ready_open', { count: a.open_count }) : t('nightaudit.ready_clear')}
          </Text>
        </Stack>
        <Button leftSection={<IconCalendarCheck size={16} />} onClick={onClose} disabled={!a.can_close}>
          {t('nightaudit.close_day')}
        </Button>
      </Group>
    </Card>
  );
}

function StayLine({ s, children }: { s: AuditStay; children?: React.ReactNode }) {
  const { i18n } = useTranslation();
  return (
    <Group justify="space-between" wrap="nowrap" gap="xs">
      <div style={{ minWidth: 0 }}>
        <Anchor component={Link} to={`/reservations/${s.reservation_id}`} size="sm" fw={600}>
          {s.guest_name}
        </Anchor>
        <Text size="xs" c="dimmed">
          {[s.code, s.room_number, `${formatDate(s.arrival, i18n.language)} → ${formatDate(s.departure, i18n.language)}`].filter(Boolean).join(' · ')}
        </Text>
      </div>
      {children}
    </Group>
  );
}

function ItemCard({ title, hint, count, children }: { title: string; hint: string; count: number; children: React.ReactNode }) {
  return (
    <Card withBorder padding="md">
      <Group justify="space-between" mb={4}>
        <Text fw={700}>{title}</Text>
        <Badge color="orange" variant="light">
          {count}
        </Badge>
      </Group>
      <Text size="xs" c="dimmed" mb="sm">
        {hint}
      </Text>
      <Stack gap="xs">{children}</Stack>
    </Card>
  );
}

function OpenItems({ items, count, recorded = false }: { items: NightAuditItems; count: number; recorded?: boolean }) {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const noShow = useHotelMutation<AuditStay, unknown>((h, s) => api.post(h(`/reservations/${s.reservation_id}/no-show`), { version: s.version, waive_fee: false }), [
    'night_audit',
    'reservation',
  ]);
  const confirmNoShow = (s: AuditStay) =>
    modals.openConfirmModal({
      title: t('nightaudit.no_show_title', { name: s.guest_name }),
      children: <Text size="sm">{t('nightaudit.no_show_body')}</Text>,
      labels: { confirm: t('nightaudit.mark_no_show'), cancel: t('common.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: () => void noShow.mutateAsync(s).then(() => notifySuccess(t('nightaudit.marked_no_show')), notifyError),
    });
  const balances = items.balances_due;
  return (
    <Stack gap="xs">
      <SectionTitle description={recorded ? t('nightaudit.recorded_hint') : t('nightaudit.open_hint')}>{recorded ? t('nightaudit.open_at_close') : t('nightaudit.before_closing')}</SectionTitle>
      {count === 0 && !recorded && (
        <Alert color="teal" icon={<IconCircleCheck size={18} />}>
          {t('nightaudit.nothing_open')}
        </Alert>
      )}
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        {items.not_arrived.length > 0 && (
          <ItemCard title={t('nightaudit.items.not_arrived')} hint={t('nightaudit.items.not_arrived_hint')} count={items.not_arrived.length}>
            {items.not_arrived.map((s) => (
              <StayLine key={s.reservation_id} s={s}>
                {!recorded && can('reservations.cancel') && (
                  <Button size="xs" variant="light" color="red" onClick={() => confirmNoShow(s)}>
                    {t('nightaudit.mark_no_show')}
                  </Button>
                )}
              </StayLine>
            ))}
          </ItemCard>
        )}
        {items.not_departed.length > 0 && (
          <ItemCard title={t('nightaudit.items.not_departed')} hint={t('nightaudit.items.not_departed_hint')} count={items.not_departed.length}>
            {items.not_departed.map((s) => (
              <StayLine key={s.reservation_id} s={s} />
            ))}
          </ItemCard>
        )}
        {items.open_checks.length > 0 && (
          <ItemCard title={t('nightaudit.items.open_checks')} hint={t('nightaudit.items.open_checks_hint')} count={items.open_checks.length}>
            {items.open_checks.map((c) => (
              <Group key={c.order_id} justify="space-between" wrap="nowrap">
                <div>
                  <Anchor component={Link} to={`/restaurant/orders/${c.order_id}`} size="sm" fw={600}>
                    {c.number}
                  </Anchor>
                  <Text size="xs" c="dimmed">
                    {[pickLocalized(c.outlet, i18n.language), c.table, formatDate(c.business_date, i18n.language)].filter(Boolean).join(' · ')}
                  </Text>
                </div>
                <Text size="sm" className="hms-num">
                  {formatMoney(c.total, hotel.currency_code, i18n.language)}
                </Text>
              </Group>
            ))}
          </ItemCard>
        )}
        {items.overdue_rentals.length > 0 && (
          <ItemCard title={t('nightaudit.items.overdue_rentals')} hint={t('nightaudit.items.overdue_rentals_hint')} count={items.overdue_rentals.length}>
            {items.overdue_rentals.map((r) => (
              <Group key={r.rental_id} justify="space-between">
                <Anchor component={Link} to="/vehicles/today" size="sm" fw={600}>
                  {r.number} · {r.vehicle}
                </Anchor>
                <Text size="xs" c="dimmed">
                  {formatDateTime(r.end_at, i18n.language, hotel.timezone)}
                </Text>
              </Group>
            ))}
          </ItemCard>
        )}
        {items.unassigned_tomorrow.length > 0 && (
          <ItemCard title={t('nightaudit.items.unassigned_tomorrow')} hint={t('nightaudit.items.unassigned_tomorrow_hint')} count={items.unassigned_tomorrow.length}>
            {items.unassigned_tomorrow.map((s) => (
              <StayLine key={s.reservation_id} s={s} />
            ))}
          </ItemCard>
        )}
        {balances.count > 0 && (
          <Card withBorder padding="md">
            <Group justify="space-between" mb={4}>
              <Text fw={700}>{t('nightaudit.items.balances_due')}</Text>
              <Text fw={700} className="hms-num">
                {formatMoney(balances.total, hotel.currency_code, i18n.language)}
              </Text>
            </Group>
            <Text size="xs" c="dimmed" mb="sm">
              {t('nightaudit.items.balances_due_hint', { count: balances.count })}
            </Text>
            <Stack gap="xs">
              {balances.stays.slice(0, 6).map((s) => (
                <StayLine key={s.reservation_id} s={s}>
                  <Text size="sm" c="red.7" className="hms-num">
                    {formatMoney(s.balance, s.currency, i18n.language)}
                  </Text>
                </StayLine>
              ))}
            </Stack>
          </Card>
        )}
      </SimpleGrid>
    </Stack>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card withBorder padding="sm">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text fw={700} size="lg" className="hms-num">
        {value}
      </Text>
      {hint && (
        <Text size="xs" c="dimmed">
          {hint}
        </Text>
      )}
    </Card>
  );
}

function Report({ audit: a }: { audit: NightAudit }) {
  const { t, i18n } = useTranslation();
  const r = a.report;
  const cur = r.currency;
  const money = (v: string | null | undefined) => (v == null ? '—' : formatMoney(v, cur, i18n.language));
  const pct = (v: string | null) => (v == null ? '—' : `${formatNumber(v, i18n.language, 1)} %`);
  const mv = r.movements;
  return (
    <Stack gap="xs" data-testid="day-report">
      <SectionTitle description={a.closure ? t('nightaudit.report_closed_hint') : t('nightaudit.report_live_hint')}>
        {t('nightaudit.report_title', { date: formatDate(a.date, i18n.language) })}
      </SectionTitle>
      <SimpleGrid cols={{ base: 2, sm: 4 }}>
        <Tile label={t('reports.occupancy')} value={pct(r.rooms.occupancy)} hint={t('reports.sold_of', { sold: r.rooms.sold, available: r.rooms.available })} />
        <Tile label={t('reports.room_revenue')} value={money(r.rooms.revenue)} />
        <Tile label={t('reports.adr')} value={money(r.rooms.adr)} />
        <Tile label={t('reports.revpar')} value={money(r.rooms.revpar)} />
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, md: 3 }}>
        <Card withBorder padding="md">
          <Text fw={700} mb="xs">
            {t('nightaudit.movements')}
          </Text>
          <Table verticalSpacing={4}>
            <Table.Tbody>
              {(['arrivals', 'departures', 'walk_ins', 'no_shows', 'bookings_made', 'cancellations', 'arrivals_tomorrow'] as const).map((k) => (
                <Table.Tr key={k}>
                  <Table.Td>{t(`nightaudit.mv.${k}`)}</Table.Td>
                  <Table.Td ta="right" className="hms-num">
                    {mv[k]}
                  </Table.Td>
                </Table.Tr>
              ))}
              <Table.Tr>
                <Table.Td>{t('nightaudit.mv.occupancy_tomorrow')}</Table.Td>
                <Table.Td ta="right" className="hms-num">
                  {pct(mv.occupancy_tomorrow)}
                </Table.Td>
              </Table.Tr>
            </Table.Tbody>
          </Table>
        </Card>
        <Card withBorder padding="md">
          <Text fw={700} mb="xs">
            {t('nightaudit.revenue')}
          </Text>
          {r.revenue ? (
            <Table verticalSpacing={4}>
              <Table.Tbody>
                {(['rooms', 'restaurant', 'vehicles', 'services', 'fees', 'adjustments'] as const).map((k) => (
                  <Table.Tr key={k}>
                    <Table.Td>{t(`reports.departments.${k}`)}</Table.Td>
                    <Table.Td ta="right" className="hms-num">
                      {money(r.revenue?.[k])}
                    </Table.Td>
                  </Table.Tr>
                ))}
                <Table.Tr>
                  <Table.Td fw={700}>{t('nightaudit.total')}</Table.Td>
                  <Table.Td ta="right" fw={700} className="hms-num">
                    {money(r.revenue.total)}
                  </Table.Td>
                </Table.Tr>
              </Table.Tbody>
            </Table>
          ) : (
            <Text size="sm" c="dimmed">
              {t('reports.no_financial')}
            </Text>
          )}
        </Card>
        <Card withBorder padding="md">
          <Text fw={700} mb="xs">
            {t('nightaudit.payments')}
          </Text>
          {r.payments_net == null ? (
            <Text size="sm" c="dimmed">
              {t('nightaudit.no_payments_permission')}
            </Text>
          ) : (
            <Table verticalSpacing={4} data-testid="cash-up">
              <Table.Tbody>
                {r.payments.length === 0 && (
                  <Table.Tr>
                    <Table.Td c="dimmed">{t('nightaudit.no_payments')}</Table.Td>
                  </Table.Tr>
                )}
                {r.payments.map((p, i) => (
                  <Table.Tr key={i}>
                    <Table.Td>
                      <Text size="sm">
                        {t(`billing.methods.${p.method}`)}
                        {p.kind !== 'payment' ? ` · ${t(`billing.payment_kinds.${p.kind}`)}` : ''}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {t(`nightaudit.sources.${p.source}`)} · {p.count}
                      </Text>
                    </Table.Td>
                    <Table.Td ta="right" className="hms-num">
                      {p.kind === 'refund' ? '−' : ''}
                      {formatMoney(p.amount, p.currency, i18n.language)}
                    </Table.Td>
                  </Table.Tr>
                ))}
                <Table.Tr>
                  <Table.Td fw={700}>{t('nightaudit.net_received')}</Table.Td>
                  <Table.Td ta="right" fw={700} className="hms-num">
                    {money(r.payments_net)}
                  </Table.Td>
                </Table.Tr>
                {r.invoices && (
                  <Table.Tr>
                    <Table.Td c="dimmed">{t('nightaudit.invoices_issued', { count: r.invoices.issued })}</Table.Td>
                    <Table.Td ta="right" c="dimmed" className="hms-num">
                      {money(r.invoices.total)}
                    </Table.Td>
                  </Table.Tr>
                )}
              </Table.Tbody>
            </Table>
          )}
        </Card>
      </SimpleGrid>
    </Stack>
  );
}

function CloseModal({ audit: a, onClose, onClosed }: { audit: NightAudit; onClose: () => void; onClosed: () => void }) {
  const { t, i18n } = useTranslation();
  const [notes, setNotes] = useState('');
  const [accept, setAccept] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const close = useHotelMutation<void, NightAudit>(
    (h) => api.post(h(`/night-audit/${a.date}/close`), { notes: notes.trim() || null, accept_open_items: accept }),
    ['night_audit', 'payment', 'folio'],
  );
  const day = formatDate(a.date, i18n.language);
  return (
    <Modal opened onClose={onClose} title={<Title order={4}>{t('nightaudit.close_title', { date: day })}</Title>} size="lg">
      <Stack>
        <Text size="sm">{t('nightaudit.close_body')}</Text>
        {a.open_count > 0 && (
          <Checkbox
            checked={accept}
            onChange={(e) => setAccept(e.currentTarget.checked)}
            label={t('nightaudit.accept_open', { count: a.open_count })}
            error={error}
          />
        )}
        <Textarea label={t('nightaudit.notes')} description={t('nightaudit.notes_hint')} autosize minRows={2} maxLength={2000} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            leftSection={<IconLock size={16} />}
            disabled={a.open_count > 0 && !accept}
            loading={close.isPending}
            onClick={() =>
              void close.mutateAsync().then(
                () => {
                  notifySuccess(t('nightaudit.closed_notice', { date: day }));
                  onClose();
                  onClosed();
                },
                (e) => {
                  if (!applyFieldErrors(e, (_, m) => setError(m))) notifyError(e);
                },
              )
            }
          >
            {t('nightaudit.close_day')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
