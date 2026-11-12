/**
 * Translatable content stored by the hotel (room category names, facility
 * descriptions...) is a map language -> text. Display falls back from the
 * user's language to the hotel default, then to any available translation.
 */
export type LocalizedText = Partial<Record<string, string>>;

export function pickLocalized(text: LocalizedText | null | undefined, lang: string, fallbackLang = 'en'): string {
  if (!text) return '';
  return text[lang] || text[fallbackLang] || Object.values(text).find((v) => !!v) || '';
}

export function hasTranslation(text: LocalizedText | null | undefined, lang: string): boolean {
  return !!text?.[lang]?.trim();
}
