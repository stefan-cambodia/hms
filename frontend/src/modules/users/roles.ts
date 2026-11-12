import { useTranslation } from 'react-i18next';

import type { Role } from '@/api/types';

/** System roles are named in the user's language; custom roles keep their own name. */
export function useRoleName() {
  const { t, i18n } = useTranslation();
  return (role: Pick<Role, 'code' | 'name' | 'is_system'>) => {
    const key = `roles.system.${role.code}`;
    return role.is_system && i18n.exists(key) ? t(key) : role.name;
  };
}
