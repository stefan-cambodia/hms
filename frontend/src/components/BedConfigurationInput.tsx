import { ActionIcon, Button, Group, Input, NumberInput, Select, Stack } from '@mantine/core';
import { IconPlus, IconTrash } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import type { BedItem, BedType } from '@/api/types';

export const BED_TYPES: BedType[] = ['single', 'double', 'queen', 'king', 'twin', 'sofa_bed', 'bunk', 'crib'];

export function BedConfigurationInput({ value, onChange, label }: { value: BedItem[]; onChange: (v: BedItem[]) => void; label?: string }) {
  const { t } = useTranslation();
  const update = (i: number, patch: Partial<BedItem>) => onChange(value.map((b, j) => (j === i ? { ...b, ...patch } : b)));
  return (
    <Input.Wrapper label={label ?? t('rooms.beds')}>
      <Stack gap={6} mt={4}>
        {value.map((bed, i) => (
          <Group key={i} gap="xs" wrap="nowrap">
            <Select
              aria-label={t('rooms.bed_type')}
              data={BED_TYPES.map((b) => ({ value: b, label: t(`rooms.bed.${b}`) }))}
              value={bed.type}
              onChange={(v) => v && update(i, { type: v as BedType })}
              allowDeselect={false}
              style={{ flex: 1 }}
            />
            <NumberInput aria-label={t('rooms.bed_count')} min={1} max={20} w={90} value={bed.count} onChange={(v) => update(i, { count: Number(v) || 1 })} />
            <ActionIcon variant="subtle" color="red" aria-label={t('common.remove')} onClick={() => onChange(value.filter((_, j) => j !== i))}>
              <IconTrash size={16} />
            </ActionIcon>
          </Group>
        ))}
        <Group>
          <Button variant="light" size="xs" leftSection={<IconPlus size={14} />} onClick={() => onChange([...value, { type: 'double', count: 1 }])}>
            {t('rooms.add_bed')}
          </Button>
        </Group>
      </Stack>
    </Input.Wrapper>
  );
}

export function useBedSummary() {
  const { t } = useTranslation();
  return (beds: BedItem[] | null | undefined) =>
    (beds ?? []).map((b) => `${b.count} × ${t(`rooms.bed.${b.type}`)}`).join(', ') || '—';
}
