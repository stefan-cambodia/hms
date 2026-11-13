import { useHotelQuery } from '@/api/hooks';
import type { CompanyAccount } from '@/api/types';
import { useAuth } from '@/auth/AuthProvider';

/** The hotel's company accounts (for users who may see them). */
export function useCompanyAccounts() {
  const { can } = useAuth();
  const list = useHotelQuery<CompanyAccount[]>('company_account', '/company-accounts', undefined, can('accounts.view'));
  return {
    list: list.data ?? [],
    byId: (id: string | null | undefined) => (id ? list.data?.find((a) => a.id === id) : undefined),
  };
}
