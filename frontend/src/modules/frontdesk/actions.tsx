import { useState } from 'react';
import { Button, Group, Stack, Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { api, ApiError } from '@/api/client';
import { hotelKey } from '@/api/realtime';
import type { PaymentKind, Reservation } from '@/api/types';
import { useAuth, useHotel } from '@/auth/AuthProvider';
import { errorMessage, notifyError, notifySuccess } from '@/lib/errors';
import { formatDate, formatMoney } from '@/lib/format';
import { useCompanyAccounts } from '@/modules/accounts/shared';
import { PaymentModal } from '@/modules/billing/FolioDialogs';

const AFFECTED = ['reservation', 'front_desk', 'room_board', 'folio', 'calendar', 'room', 'payment'];

interface PendingPayment {
  reservation: Reservation;
  kind: PaymentKind;
  amount: string;
  then: () => void;
}

/**
 * Check-in / check-out with the server as the single source of the rules:
 * when an action is refused for a reason the user can resolve (room not
 * ready, early departure, open balance), the user is asked how to proceed
 * and the action is retried with that explicit decision.
 */
export function useStayActions() {
  const { t, i18n } = useTranslation();
  const hotel = useHotel();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [payment, setPayment] = useState<PendingPayment | null>(null);
  const [busy, setBusy] = useState(false);
  const companies = useCompanyAccounts();

  const base = `/hotels/${hotel.id}/reservations`;
  const refresh = () => {
    for (const entity of AFFECTED) void qc.invalidateQueries({ queryKey: hotelKey(hotel.id, entity) });
  };
  const fetchReservation = (id: string) => api.get<Reservation>(`${base}/${id}`);

  const choose = (title: string, body: string, options: { label: string; color?: string; variant?: string; onClick: () => void }[]) => {
    const id = modals.open({
      title,
      children: (
        <Stack>
          <Text size="sm">{body}</Text>
          <Group justify="flex-end" gap="xs">
            <Button variant="default" onClick={() => modals.close(id)}>
              {t('common.cancel')}
            </Button>
            {options.map((o) => (
              <Button
                key={o.label}
                color={o.color}
                variant={o.variant ?? 'filled'}
                onClick={() => {
                  modals.close(id);
                  o.onClick();
                }}
              >
                {o.label}
              </Button>
            ))}
          </Group>
        </Stack>
      ),
    });
  };

  async function checkIn(resId: string, version: number, extra: Record<string, unknown> = {}): Promise<void> {
    setBusy(true);
    try {
      const res = await api.post<Reservation>(`${base}/${resId}/check-in`, { version, ...extra });
      notifySuccess(t('frontdesk.checked_in_done', { code: res.code }));
      refresh();
    } catch (err) {
      if (err instanceof ApiError && err.code === 'ROOM_NOT_READY' && !extra.ignore_room_status) {
        choose(t('frontdesk.room_not_ready_title'), `${errorMessage(err)} ${t('frontdesk.room_not_ready_body')}`, [
          { label: t('frontdesk.check_in_anyway'), onClick: () => void checkIn(resId, version, { ...extra, ignore_room_status: true }) },
        ]);
      } else notifyError(err);
    } finally {
      setBusy(false);
    }
  }

  async function checkOut(resId: string, version: number, extra: Record<string, unknown> = {}): Promise<void> {
    setBusy(true);
    const retryFresh = async (more: Record<string, unknown> = {}) => {
      const fresh = await fetchReservation(resId);
      await checkOut(resId, fresh.version, { ...extra, ...more });
    };
    try {
      const res = await api.post<Reservation>(`${base}/${resId}/check-out`, { version, ...extra });
      notifySuccess(res.status === 'checked_out' ? t('frontdesk.checked_out_done', { code: res.code }) : t('frontdesk.room_checked_out_done'));
      refresh();
    } catch (err) {
      if (!(err instanceof ApiError)) return notifyError(err);
      const p = err.params as Record<string, string>;
      if (err.code === 'EARLY_DEPARTURE') {
        choose(
          t('frontdesk.early_departure_title'),
          t('frontdesk.early_departure_body', { count: Number(p.nights), date: formatDate(p.departure, i18n.language) }),
          [{ label: t('frontdesk.release_and_check_out'), onClick: () => void checkOut(resId, version, { ...extra, shorten_stay: true }) }],
        );
      } else if (err.code === 'BALANCE_DUE' || err.code === 'CREDIT_BALANCE') {
        const due = err.code === 'BALANCE_DUE';
        const amount = formatMoney(p.balance, p.currency, i18n.language);
        const options = [];
        // Billed to a company: its balance goes to the company's account.
        const company = due && can('payments.record') ? companies.byId((await fetchReservation(resId)).company_account_id) : undefined;
        if (company)
          options.push({
            label: t('accounts.transfer_to', { name: company.name }),
            onClick: async () => {
              try {
                await api.post(`${base}/${resId}/transfer-to-account`, {});
                notifySuccess(t('accounts.transferred', { name: company.name }));
                await retryFresh();
              } catch (e) {
                notifyError(e);
              }
            },
          });
        if (due ? can('payments.record') : can('payments.refund'))
          options.push({
            label: due ? t('frontdesk.take_payment_amount', { amount }) : t('frontdesk.refund_amount', { amount }),
            onClick: async () => {
              const reservation = await fetchReservation(resId);
              setPayment({ reservation, kind: due ? 'payment' : 'refund', amount: p.balance, then: () => void retryFresh() });
            },
          });
        if (!due || can('folio.adjust'))
          options.push({
            label: due ? t('frontdesk.leave_balance_open') : t('frontdesk.keep_credit'),
            variant: 'light',
            color: due ? 'red' : undefined,
            onClick: () => void checkOut(resId, version, { ...extra, allow_open_balance: true }),
          });
        choose(due ? t('frontdesk.balance_due_title') : t('frontdesk.credit_title'), due ? t('frontdesk.balance_due_body', { amount }) : t('frontdesk.credit_body', { amount }), options);
      } else notifyError(err);
    } finally {
      setBusy(false);
    }
  }

  async function undoCheckIn(res: Reservation, stayId: string) {
    try {
      await api.post<Reservation>(`${base}/${res.id}/undo-check-in`, { version: res.version, reservation_room_id: stayId });
      notifySuccess(t('frontdesk.undo_done'));
      refresh();
    } catch (err) {
      notifyError(err);
    }
  }

  const element = payment ? (
    <PaymentModal
      reservation={payment.reservation}
      initialKind={payment.kind}
      initialAmount={payment.amount}
      onClose={() => setPayment(null)}
      onDone={() => {
        setPayment(null);
        payment.then();
      }}
    />
  ) : null;

  return { checkIn, checkOut, undoCheckIn, busy, element };
}
