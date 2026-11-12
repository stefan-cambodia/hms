import { describe, expect, it } from 'vitest';

import { csvFormat, toCsv } from './csv';

describe('CSV export', () => {
  it('uses the separators a spreadsheet expects in the locale', () => {
    expect(csvFormat('en')).toEqual({ separator: ',', decimal: '.' });
    expect(csvFormat('fr')).toEqual({ separator: ';', decimal: ',' });
    expect(csvFormat('ru')).toEqual({ separator: ';', decimal: ',' });
    expect(csvFormat('zh-CN')).toEqual({ separator: ',', decimal: '.' });
  });

  it('writes a BOM, plain numbers and quoted text', () => {
    const out = toCsv(['Date', 'Occupancy %', 'Revenue (USD)'], [['2026-11-12', '26.3', '1234.50'], ['Total, all', 5, null]], 'en');
    expect(out.startsWith('\uFEFF')).toBe(true);
    expect(out.slice(1).split('\r\n')).toEqual(['Date,Occupancy %,Revenue (USD)', '2026-11-12,26.3,1234.50', '"Total, all",5,', '']);
  });

  it('uses decimal commas and semicolons in French', () => {
    const out = toCsv(['Taux', 'Nom'], [['26.3', 'Chambre; vue "fleuve"']], 'fr');
    expect(out.slice(1).split('\r\n')[1]).toBe('26,3;"Chambre; vue ""fleuve"""');
  });

  it('neutralises text that a spreadsheet would run as a formula', () => {
    const out = toCsv(['Guest'], [['=HYPERLINK("http://x")'], ['@SUM(A1)'], ['-5'], ['+cmd']], 'en');
    const lines = out.slice(1).split('\r\n');
    expect(lines[1]).toBe('"\'=HYPERLINK(""http://x"")"');
    expect(lines[2]).toBe("'@SUM(A1)");
    expect(lines[3]).toBe('-5'); // a negative number stays a number
    expect(lines[4]).toBe("'+cmd");
  });

  it('keeps Khmer and Chinese text intact', () => {
    expect(toCsv(['ប្រភព'], [['直接预订']], 'km')).toContain('直接预订');
  });
});
