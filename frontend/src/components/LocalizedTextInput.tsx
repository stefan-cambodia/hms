import { useState } from 'react';
import { Box, Group, Input, SegmentedControl, Text, Textarea, TextInput } from '@mantine/core';
import { useTranslation } from 'react-i18next';

import { LANGUAGES } from '@/i18n';
import type { LocalizedText } from '@/lib/localized';

interface Props {
  label: string;
  description?: string;
  value: LocalizedText;
  onChange: (value: LocalizedText) => void;
  languages: string[]; // the hotel's supported languages, default first
  multiline?: boolean;
  required?: boolean;
  error?: string;
  maxLength?: number;
}

/**
 * Edits one translatable field in all of the hotel's languages. A dot on each
 * language tab shows which translations are filled in.
 */
export function LocalizedTextInput({ label, description, value, onChange, languages, multiline, required, error, maxLength }: Props) {
  const { i18n } = useTranslation();
  const ordered = languages.length ? languages : ['en'];
  const [lang, setLang] = useState(ordered.includes(i18n.language) ? i18n.language : ordered[0]);
  const current = value?.[lang] ?? '';
  const set = (text: string) => onChange({ ...value, [lang]: text });

  return (
    <Input.Wrapper label={label} description={description} required={required} error={error}>
      <Box mt={4}>
        <SegmentedControl
          size="xs"
          value={lang}
          onChange={setLang}
          mb={6}
          data={ordered.map((code) => ({
            value: code,
            label: (
              <Group gap={6} wrap="nowrap" justify="center">
                <Text size="xs" span>
                  {LANGUAGES.find((l) => l.code === code)?.label ?? code}
                </Text>
                <Box
                  w={6}
                  h={6}
                  style={{ borderRadius: 3 }}
                  bg={value?.[code]?.trim() ? 'lagoon.6' : 'gray.4'}
                  aria-hidden
                />
              </Group>
            ),
          }))}
        />
        {multiline ? (
          <Textarea
            value={current}
            onChange={(e) => set(e.currentTarget.value)}
            autosize
            minRows={3}
            maxRows={10}
            maxLength={maxLength ?? 10000}
            lang={lang}
            error={!!error}
          />
        ) : (
          <TextInput value={current} onChange={(e) => set(e.currentTarget.value)} maxLength={maxLength ?? 200} lang={lang} error={!!error} />
        )}
      </Box>
    </Input.Wrapper>
  );
}
