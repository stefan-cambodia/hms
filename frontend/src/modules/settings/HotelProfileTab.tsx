import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Grid, Group, MultiSelect, Select, SimpleGrid, Stack, Text, TextInput } from '@mantine/core';
import { TimeInput } from '@mantine/dates';
import { useForm } from '@mantine/form';
import { useTranslation } from 'react-i18next';

import { api, ApiError } from '@/api/client';
import { useHotelMutation, useHotelQuery } from '@/api/hooks';
import type { Hotel } from '@/api/types';
import { PageLoader } from '@/app/AppLayout';
import { useAuth } from '@/auth/AuthProvider';
import { LogoCard } from '@/components/HotelLogo';
import { LocalizedTextInput } from '@/components/LocalizedTextInput';
import { SectionTitle, SubmitButton } from '@/components/ui';
import { LANGUAGES } from '@/i18n';
import { applyFieldErrors, notifyError, notifySuccess } from '@/lib/errors';
import { countryName, currencyName } from '@/lib/format';
import { COUNTRY_CODES, CURRENCY_CODES, timeZones } from '@/lib/refdata';

const SOCIAL = ['facebook', 'instagram', 'tiktok', 'x', 'youtube', 'tripadvisor', 'linkedin', 'wechat', 'telegram', 'line', 'whatsapp'] as const;

type FormValues = Omit<Hotel, 'id' | 'organization_id' | 'code' | 'updated_at' | 'is_active'>;

function toForm(h: Hotel): FormValues {
  return {
    ...h,
    check_in_time: h.check_in_time.slice(0, 5),
    check_out_time: h.check_out_time.slice(0, 5),
    policies: { cancellation: {}, payment: {}, house_rules: {}, ...h.policies },
    billing_info: { invoice_footer: {}, ...h.billing_info },
  };
}

const blank = (v: string | null | undefined) => (v === '' || v === undefined ? null : v);

export default function HotelProfileTab() {
  const { t, i18n } = useTranslation();
  const { can, refresh } = useAuth();
  const canEdit = can('config.hotel.manage');
  const query = useHotelQuery<Hotel>('hotel', '');
  const save = useHotelMutation<Record<string, unknown>, Hotel>((h, body) => api.patch<Hotel>(h(''), body), ['hotel']);
  const form = useForm<FormValues>({ mode: 'controlled' });
  const [stale, setStale] = useState(false);

  const load = (h: Hotel) => {
    form.setValues(toForm(h));
    form.resetDirty(toForm(h));
    setStale(false);
  };

  // Another device saved this profile: never overwrite unsaved edits silently.
  useEffect(() => {
    if (!query.data) return;
    if (form.getValues().version === undefined || !form.isDirty()) load(query.data);
    else if (form.getValues().version !== query.data.version) setStale(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query.data]);

  const countries = useMemo(
    () => COUNTRY_CODES.map((c) => ({ value: c, label: countryName(c, i18n.language) })).sort((a, b) => a.label.localeCompare(b.label, i18n.language)),
    [i18n.language],
  );
  const currencies = useMemo(() => CURRENCY_CODES.map((c) => ({ value: c, label: `${c} — ${currencyName(c, i18n.language)}` })), [i18n.language]);
  const zones = useMemo(() => timeZones(), []);

  if (!query.data || form.getValues().version === undefined) return <PageLoader />;
  const v = form.getValues();
  const langs = v.supported_languages;

  const submit = form.onSubmit(async (values) => {
    const body: Record<string, unknown> = {
      version: values.version,
      name: values.name,
      legal_name: blank(values.legal_name),
      description: values.description,
      address_line1: blank(values.address_line1),
      address_line2: blank(values.address_line2),
      city: blank(values.city),
      region: blank(values.region),
      postal_code: blank(values.postal_code),
      country_code: blank(values.country_code),
      latitude: blank(values.latitude as string | null),
      longitude: blank(values.longitude as string | null),
      phone: blank(values.phone),
      email: blank(values.email),
      website: blank(values.website),
      social_links: Object.fromEntries(Object.entries(values.social_links ?? {}).filter(([, s]) => s?.trim())),
      timezone: values.timezone,
      default_language: values.default_language,
      supported_languages: values.supported_languages,
      currency_code: values.currency_code,
      check_in_time: values.check_in_time,
      check_out_time: values.check_out_time,
      tax_id: blank(values.tax_id),
      billing_info: {
        legal_address: blank(values.billing_info.legal_address),
        bank_details: blank(values.billing_info.bank_details),
        invoice_footer: values.billing_info.invoice_footer ?? {},
        invoice_prefix: blank(values.billing_info.invoice_prefix),
        receipt_prefix: blank(values.billing_info.receipt_prefix),
      },
      policies: values.policies,
    };
    try {
      load(await save.mutateAsync(body));
      notifySuccess(t('common.saved'));
      await refresh();
    } catch (err) {
      if (err instanceof ApiError && err.code === 'VERSION_CONFLICT') setStale(true);
      else if (!applyFieldErrors(err, form.setFieldError)) notifyError(err);
    }
  });

  return (
    <Stack gap="lg">
      <LogoCard canEdit={canEdit} />
      <form onSubmit={submit}>
        {stale && (
          <Alert color="yellow" mb="lg" title={t('common.stale_title')}>
            <Group justify="space-between" gap="sm">
              <Text size="sm">{t('common.stale_body')}</Text>
              <Button size="xs" variant="white" color="yellow" onClick={() => query.data && load(query.data)}>
                {t('common.reload')}
              </Button>
            </Group>
          </Alert>
        )}
        <fieldset disabled={!canEdit} style={{ border: 0, padding: 0, margin: 0 }}>
          <Stack gap="lg">
            <Card>
              <SectionTitle>{t('settings.profile.identity')}</SectionTitle>
              <Grid>
                <Grid.Col span={{ base: 12, md: 6 }}>
                  <TextInput label={t('settings.profile.name')} required {...form.getInputProps('name')} />
                </Grid.Col>
                <Grid.Col span={{ base: 12, md: 6 }}>
                  <TextInput label={t('settings.profile.legal_name')} {...form.getInputProps('legal_name')} value={v.legal_name ?? ''} />
                </Grid.Col>
                <Grid.Col span={12}>
                  <LocalizedTextInput label={t('settings.profile.description')} multiline languages={langs} value={v.description} onChange={(d) => form.setFieldValue('description', d)} />
                </Grid.Col>
              </Grid>
            </Card>

            <Card>
              <SectionTitle>{t('settings.profile.location_contact')}</SectionTitle>
              <SimpleGrid cols={{ base: 1, md: 2 }}>
                <TextInput label={t('settings.profile.address_line1')} {...form.getInputProps('address_line1')} value={v.address_line1 ?? ''} />
                <TextInput label={t('settings.profile.address_line2')} {...form.getInputProps('address_line2')} value={v.address_line2 ?? ''} />
                <TextInput label={t('settings.profile.city')} {...form.getInputProps('city')} value={v.city ?? ''} />
                <TextInput label={t('settings.profile.region')} {...form.getInputProps('region')} value={v.region ?? ''} />
                <TextInput label={t('settings.profile.postal_code')} {...form.getInputProps('postal_code')} value={v.postal_code ?? ''} />
                <Select label={t('settings.profile.country')} data={countries} searchable clearable {...form.getInputProps('country_code')} />
                <TextInput label={t('settings.profile.latitude')} inputMode="decimal" {...form.getInputProps('latitude')} value={v.latitude ?? ''} />
                <TextInput label={t('settings.profile.longitude')} inputMode="decimal" {...form.getInputProps('longitude')} value={v.longitude ?? ''} />
                <TextInput label={t('settings.profile.phone')} type="tel" {...form.getInputProps('phone')} value={v.phone ?? ''} />
                <TextInput label={t('settings.profile.email')} type="email" {...form.getInputProps('email')} value={v.email ?? ''} />
                <TextInput label={t('settings.profile.website')} placeholder="https://" {...form.getInputProps('website')} value={v.website ?? ''} />
              </SimpleGrid>
              <Text size="sm" fw={600} mt="lg" mb="xs">
                {t('settings.profile.social_links')}
              </Text>
              <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
                {SOCIAL.map((key) => (
                  <TextInput
                    key={key}
                    label={t(`settings.social.${key}`)}
                    value={v.social_links?.[key] ?? ''}
                    onChange={(e) => form.setFieldValue('social_links', { ...v.social_links, [key]: e.currentTarget.value })}
                    error={form.errors.social_links}
                  />
                ))}
              </SimpleGrid>
            </Card>

            <Card>
              <SectionTitle description={t('settings.profile.operations_hint')}>{t('settings.profile.operations')}</SectionTitle>
              <SimpleGrid cols={{ base: 1, md: 2 }}>
                <Select label={t('settings.profile.timezone')} data={zones} searchable required allowDeselect={false} {...form.getInputProps('timezone')} />
                <Select label={t('settings.profile.currency')} data={currencies} searchable required allowDeselect={false} {...form.getInputProps('currency_code')} />
                <TimeInput label={t('settings.profile.check_in_time')} required {...form.getInputProps('check_in_time')} />
                <TimeInput label={t('settings.profile.check_out_time')} required {...form.getInputProps('check_out_time')} />
                <MultiSelect
                  label={t('settings.profile.supported_languages')}
                  data={LANGUAGES.map((l) => ({ value: l.code, label: l.label }))}
                  {...form.getInputProps('supported_languages')}
                />
                <Select
                  label={t('settings.profile.default_language')}
                  data={LANGUAGES.filter((l) => langs.includes(l.code)).map((l) => ({ value: l.code, label: l.label }))}
                  allowDeselect={false}
                  {...form.getInputProps('default_language')}
                />
              </SimpleGrid>
            </Card>

            <Card>
              <SectionTitle>{t('settings.profile.policies')}</SectionTitle>
              <Stack>
                {(['cancellation', 'payment', 'house_rules'] as const).map((key) => (
                  <LocalizedTextInput
                    key={key}
                    label={t(`settings.profile.policy_${key}`)}
                    multiline
                    languages={langs}
                    value={v.policies[key] ?? {}}
                    onChange={(text) => form.setFieldValue('policies', { ...v.policies, [key]: text })}
                  />
                ))}
              </Stack>
            </Card>

            <Card>
              <SectionTitle description={t('settings.profile.billing_hint')}>{t('settings.profile.billing')}</SectionTitle>
              <SimpleGrid cols={{ base: 1, md: 2 }}>
                <TextInput label={t('settings.profile.tax_id')} {...form.getInputProps('tax_id')} value={v.tax_id ?? ''} />
                <TextInput label={t('settings.profile.legal_address')} {...form.getInputProps('billing_info.legal_address')} value={v.billing_info.legal_address ?? ''} />
                <TextInput label={t('settings.profile.invoice_prefix')} placeholder="INV-" {...form.getInputProps('billing_info.invoice_prefix')} value={v.billing_info.invoice_prefix ?? ''} />
                <TextInput label={t('settings.profile.receipt_prefix')} placeholder="RCP-" {...form.getInputProps('billing_info.receipt_prefix')} value={v.billing_info.receipt_prefix ?? ''} />
              </SimpleGrid>
              <Stack mt="md">
                <TextInput label={t('settings.profile.bank_details')} {...form.getInputProps('billing_info.bank_details')} value={v.billing_info.bank_details ?? ''} />
                <LocalizedTextInput
                  label={t('settings.profile.invoice_footer')}
                  multiline
                  languages={langs}
                  value={v.billing_info.invoice_footer ?? {}}
                  onChange={(text) => form.setFieldValue('billing_info', { ...v.billing_info, invoice_footer: text })}
                />
              </Stack>
            </Card>
          </Stack>
        </fieldset>
        {canEdit && (
          <Group justify="flex-end" mt="lg" pos="sticky" bottom={16}>
            <SubmitButton size="md" loading={save.isPending} disabled={!form.isDirty()}>
              {t('common.save_changes')}
            </SubmitButton>
          </Group>
        )}
      </form>
    </Stack>
  );
}
