import { useMemo, useState } from 'react';
import { Alert, Button, Group, SegmentedControl, Select, SimpleGrid, Stack, Text, TextInput } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { IconUserSearch } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useHotelQuery } from '@/api/hooks';
import type { Guest, GuestDuplicate, Page } from '@/api/types';
import { LANGUAGES } from '@/i18n';
import { countryName } from '@/lib/format';
import { COUNTRY_CODES } from '@/lib/refdata';

export interface NewGuest {
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  nationality: string | null;
  preferred_language: string | null;
}

export const EMPTY_GUEST: NewGuest = { first_name: '', last_name: '', email: '', phone: '', nationality: null, preferred_language: null };

export type GuestChoice = { mode: 'existing'; guest: Guest | null } | { mode: 'new'; data: NewGuest };

export function guestLabel(g: Pick<Guest, 'first_name' | 'last_name' | 'email' | 'phone'>): string {
  const contact = g.email || g.phone;
  return `${g.first_name} ${g.last_name}${contact ? ` — ${contact}` : ''}`;
}

export function GuestPicker({ value, onChange, errors }: { value: GuestChoice; onChange: (v: GuestChoice) => void; errors?: Record<string, string> }) {
  const { t, i18n } = useTranslation();
  const [search, setSearch] = useState('');
  const [q] = useDebouncedValue(search, 250);
  const results = useHotelQuery<Page<Guest>>('guest', '/guests', { q, limit: 20 }, value.mode === 'existing');

  const data = value.mode === 'new' ? value.data : EMPTY_GUEST;
  const [dupParams] = useDebouncedValue(
    { first_name: data.first_name.trim(), last_name: data.last_name.trim(), email: data.email.trim() || undefined, phone: data.phone.trim() || undefined },
    400,
  );
  const checkDuplicates = value.mode === 'new' && dupParams.first_name.length > 1 && dupParams.last_name.length > 1;
  const duplicates = useHotelQuery<GuestDuplicate[]>('guest', '/guests/duplicates', dupParams, checkDuplicates);

  const countries = useMemo(
    () => COUNTRY_CODES.map((c) => ({ value: c, label: countryName(c, i18n.language) })).sort((a, b) => a.label.localeCompare(b.label, i18n.language)),
    [i18n.language],
  );
  const options = useMemo(() => {
    const list = results.data?.items ?? [];
    const selected = value.mode === 'existing' && value.guest && !list.some((g) => g.id === value.guest!.id) ? [value.guest] : [];
    return [...selected, ...list].map((g) => ({ value: g.id, label: guestLabel(g) }));
  }, [results.data, value]);

  const set = (patch: Partial<NewGuest>) => onChange({ mode: 'new', data: { ...data, ...patch } });

  return (
    <Stack gap="sm">
      <SegmentedControl
        value={value.mode}
        onChange={(mode) => onChange(mode === 'new' ? { mode: 'new', data: EMPTY_GUEST } : { mode: 'existing', guest: null })}
        data={[
          { value: 'new', label: t('reservations.form.new_guest') },
          { value: 'existing', label: t('reservations.form.existing_guest') },
        ]}
      />
      {value.mode === 'existing' ? (
        <Select
          label={t('reservations.form.find_guest')}
          placeholder={t('reservations.form.find_guest_placeholder')}
          leftSection={<IconUserSearch size={16} />}
          searchable
          searchValue={search}
          onSearchChange={setSearch}
          filter={({ options: o }) => o}
          data={options}
          value={value.guest?.id ?? null}
          onChange={(id) => onChange({ mode: 'existing', guest: (results.data?.items ?? []).find((g) => g.id === id) ?? (value.guest?.id === id ? value.guest : null) })}
          nothingFoundMessage={q ? t('reservations.form.no_guest_found') : undefined}
          error={errors?.guest_id}
          required
        />
      ) : (
        <>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label={t('guests.first_name')} required value={data.first_name} onChange={(e) => set({ first_name: e.currentTarget.value })} error={errors?.['guest.first_name']} />
            <TextInput label={t('guests.last_name')} required value={data.last_name} onChange={(e) => set({ last_name: e.currentTarget.value })} error={errors?.['guest.last_name']} />
            <TextInput label={t('guests.email')} type="email" value={data.email} onChange={(e) => set({ email: e.currentTarget.value })} error={errors?.['guest.email']} />
            <TextInput label={t('guests.phone')} type="tel" value={data.phone} onChange={(e) => set({ phone: e.currentTarget.value })} error={errors?.['guest.phone']} />
            <Select label={t('guests.nationality')} searchable clearable data={countries} value={data.nationality} onChange={(v) => set({ nationality: v })} />
            <Select
              label={t('guests.preferred_language')}
              clearable
              data={LANGUAGES.map((l) => ({ value: l.code, label: l.label }))}
              value={data.preferred_language}
              onChange={(v) => set({ preferred_language: v })}
            />
          </SimpleGrid>
          {checkDuplicates && (duplicates.data?.length ?? 0) > 0 && (
            <Alert color="yellow" variant="light" title={t('reservations.form.possible_duplicate')}>
              <Stack gap={6}>
                {duplicates.data!.slice(0, 3).map((d) => (
                  <Group key={d.guest.id} justify="space-between" wrap="nowrap" gap="xs">
                    <div>
                      <Text size="sm" fw={600}>
                        {guestLabel(d.guest)}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {d.reasons.map((r) => t(`guests.duplicate_reason.${r}`)).join(' · ')}
                      </Text>
                    </div>
                    <Button size="xs" variant="white" onClick={() => onChange({ mode: 'existing', guest: d.guest })}>
                      {t('reservations.form.use_this_guest')}
                    </Button>
                  </Group>
                ))}
              </Stack>
            </Alert>
          )}
        </>
      )}
    </Stack>
  );
}
