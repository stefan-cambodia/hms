import type { TFunction } from 'i18next';
import { notifications } from '@mantine/notifications';

import { ApiError } from '@/api/client';
import i18n from '@/i18n';

/** Translate a server error code. Unknown codes fall back to a generic message. */
export function errorMessage(error: unknown, t: TFunction = i18n.t): string {
  if (error instanceof ApiError) {
    const key = `errors.${error.code}`;
    if (i18n.exists(key)) return t(key, error.params as Record<string, string>);
    return t('errors.GENERIC', { code: error.code });
  }
  return t('errors.GENERIC', { code: 'UNKNOWN' });
}

/** Translate a field-level validation code (server or Pydantic type). */
export function fieldMessage(code: string, ctx: Record<string, unknown> = {}, t: TFunction = i18n.t): string {
  for (const key of [`errors.${code}`, `validation.${code}`]) {
    if (i18n.exists(key)) return t(key, ctx as Record<string, string>);
  }
  return t('validation.invalid');
}

/**
 * Map API field errors onto a Mantine form. Returns true if at least one
 * field error was applied (so the caller can skip a generic toast).
 */
export function applyFieldErrors(
  error: unknown,
  setFieldError: (path: string, message: string) => void,
  fieldPrefix: (string | number)[] = ['body'],
): boolean {
  if (!(error instanceof ApiError) || error.fields.length === 0) return false;
  let applied = false;
  for (const f of error.fields) {
    const loc = f.loc.slice(fieldPrefix.length).map(String);
    if (loc.length === 0) continue;
    setFieldError(loc.join('.'), fieldMessage(f.code, f.ctx));
    applied = true;
  }
  return applied;
}

export function notifyError(error: unknown): void {
  notifications.show({ color: 'red', title: i18n.t('common.error'), message: errorMessage(error) });
}

export function notifySuccess(message: string): void {
  notifications.show({ color: 'lagoon', message, autoClose: 2500 });
}
