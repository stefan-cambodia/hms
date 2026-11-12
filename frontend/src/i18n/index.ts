import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import dayjs from 'dayjs';
import 'dayjs/locale/fr';
import 'dayjs/locale/zh-cn';
import 'dayjs/locale/ru';
import 'dayjs/locale/km';

import en from '@/locales/en.json';
import fr from '@/locales/fr.json';
import km from '@/locales/km.json';
import ru from '@/locales/ru.json';
import zhCN from '@/locales/zh-CN.json';

export const LANGUAGES = [
  { code: 'en', label: 'English', dayjs: 'en' },
  { code: 'fr', label: 'Français', dayjs: 'fr' },
  { code: 'zh-CN', label: '简体中文', dayjs: 'zh-cn' },
  { code: 'ru', label: 'Русский', dayjs: 'ru' },
  { code: 'km', label: 'ខ្មែរ', dayjs: 'km' },
] as const;

export type LanguageCode = (typeof LANGUAGES)[number]['code'];
export const LANGUAGE_CODES = LANGUAGES.map((l) => l.code) as LanguageCode[];

const STORAGE_KEY = 'hms.language';

export function isLanguage(value: unknown): value is LanguageCode {
  return typeof value === 'string' && (LANGUAGE_CODES as string[]).includes(value);
}

/** Language before login: last choice on this device, else the browser's. */
export function initialLanguage(): LanguageCode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (isLanguage(stored)) return stored;
  } catch {
    /* storage unavailable (private mode) */
  }
  for (const nav of navigator.languages ?? [navigator.language]) {
    if (/^zh/i.test(nav)) return 'zh-CN';
    const base = nav.split('-')[0];
    if (isLanguage(base)) return base;
  }
  return 'en';
}

export async function applyLanguage(lang: LanguageCode): Promise<void> {
  await i18n.changeLanguage(lang);
  dayjs.locale(LANGUAGES.find((l) => l.code === lang)?.dayjs ?? 'en');
  document.documentElement.lang = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* ignore */
  }
}

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    fr: { translation: fr },
    'zh-CN': { translation: zhCN },
    ru: { translation: ru },
    km: { translation: km },
  },
  lng: initialLanguage(),
  fallbackLng: 'en',
  supportedLngs: LANGUAGE_CODES,
  load: 'currentOnly',
  interpolation: { escapeValue: false }, // React already escapes
  returnNull: false,
});
dayjs.locale(LANGUAGES.find((l) => l.code === i18n.language)?.dayjs ?? 'en');
document.documentElement.lang = i18n.language;

export default i18n;
