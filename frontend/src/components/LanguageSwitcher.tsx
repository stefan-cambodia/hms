import { Button, Menu } from '@mantine/core';
import { IconCheck, IconLanguage } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';

import { useAuth } from '@/auth/AuthProvider';
import { LANGUAGES, type LanguageCode } from '@/i18n';
import { notifyError } from '@/lib/errors';

export function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const { i18n, t } = useTranslation();
  const { setLanguage } = useAuth();
  const current = LANGUAGES.find((l) => l.code === i18n.language) ?? LANGUAGES[0];

  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <Button variant="subtle" color="gray" leftSection={<IconLanguage size={18} />} aria-label={t('common.language')} px={compact ? 'xs' : undefined}>
          {compact ? current.code.toUpperCase() : current.label}
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        {LANGUAGES.map((l) => (
          <Menu.Item
            key={l.code}
            lang={l.code}
            rightSection={l.code === current.code ? <IconCheck size={14} /> : null}
            onClick={() => setLanguage(l.code as LanguageCode).catch(notifyError)}
          >
            {l.label}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}
