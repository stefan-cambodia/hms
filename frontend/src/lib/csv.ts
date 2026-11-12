/**
 * CSV exports that open correctly in Excel and LibreOffice in every language:
 *
 * - UTF-8 with a byte-order mark, so Khmer, Chinese and Cyrillic display.
 * - Where the locale writes decimals with a comma (French, Russian...),
 *   fields are separated by ";" and decimals use ","; otherwise "," and ".".
 *   That is what a spreadsheet expects by default in that locale.
 * - Numbers stay plain (no thousands separators, no currency symbol) so they
 *   are numbers in the spreadsheet; the currency is in the column title.
 * - Text that a spreadsheet would run as a formula (=, +, -, @, tab, CR at the
 *   start) is prefixed with an apostrophe (CSV injection).
 */

export type Cell = string | number | null | undefined;

export interface CsvFormat {
  separator: ',' | ';';
  decimal: '.' | ',';
}

export function csvFormat(locale: string): CsvFormat {
  const decimal = new Intl.NumberFormat(locale).formatToParts(1.5).find((p) => p.type === 'decimal')?.value;
  return decimal === ',' ? { separator: ';', decimal: ',' } : { separator: ',', decimal: '.' };
}

const NUMERIC = /^-?\d+(\.\d+)?$/;
const FORMULA_START = /^[=+\-@\t\r]/;

function cell(value: Cell, fmt: CsvFormat): string {
  if (value === null || value === undefined) return '';
  let text: string;
  if (typeof value === 'number' || NUMERIC.test(value)) {
    text = String(value);
    if (fmt.decimal === ',') text = text.replace('.', ',');
  } else {
    text = FORMULA_START.test(value) ? `'${value}` : value;
  }
  const quote = text.includes(fmt.separator) || /["\n\r]/.test(text) || text !== text.trim();
  return quote ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(header: Cell[], rows: Cell[][], locale: string): string {
  const fmt = csvFormat(locale);
  return '\uFEFF' + [header, ...rows].map((r) => r.map((v) => cell(v, fmt)).join(fmt.separator)).join('\r\n') + '\r\n';
}

/** Offer the CSV as a download. */
export function downloadCsv(filename: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
