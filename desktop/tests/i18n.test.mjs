// node --test tests/*.test.mjs  (no dependency: Node's built-in test runner)
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { LANGUAGES, STRINGS, pickLanguage, translate } from '../ui/i18n.js';

const flat = (o, prefix = '') =>
  Object.entries(o).flatMap(([k, v]) => (typeof v === 'object' ? flat(v, `${prefix}${k}.`) : [`${prefix}${k}`]));

test('every language has every string, with the same placeholders', () => {
  const reference = flat(STRINGS.en).sort();
  for (const lang of Object.keys(LANGUAGES)) {
    assert.deepEqual(flat(STRINGS[lang]).sort(), reference, lang);
    for (const key of reference) {
      const holes = (s) => (s.match(/\{\w+\}/g) ?? []).sort().join();
      assert.equal(holes(translate(lang, key)), holes(translate('en', key)), `${lang} ${key}`);
    }
  }
});

test('the system language is followed, with English as fallback', () => {
  assert.equal(pickLanguage(null, 'fr-FR'), 'fr');
  assert.equal(pickLanguage(null, 'zh-TW'), 'zh-CN');
  assert.equal(pickLanguage(null, 'km-KH'), 'km');
  assert.equal(pickLanguage(null, 'de-DE'), 'en');
  assert.equal(pickLanguage('ru', 'fr-FR'), 'ru'); // the user's choice wins
});

test('placeholders are filled', () => {
  assert.equal(translate('en', 'connecting', { url: 'https://hms.local/' }), 'Connecting to https://hms.local/…');
  assert.equal(translate('fr', 'results.http_status', { status: 502 }), 'Le serveur a répondu par une erreur (HTTP 502).');
  assert.equal(translate('xx', 'test'), 'Test');
});
