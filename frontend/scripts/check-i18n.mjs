#!/usr/bin/env node
/**
 * Translation integrity check (runs in CI):
 *  1. every literal key used in the source (t('a.b'), i18n.t('a.b')) exists in en.json;
 *  2. every dynamic key prefix (t(`a.b.${x}`)) exists as an object in en.json;
 *  3. every locale has exactly the same keys as en.json;
 *  4. interpolation variables ({{name}}) match between en and each locale;
 *  5. no locale value is empty.
 * Usage: node scripts/check-i18n.mjs [--list-missing]
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = new URL('..', import.meta.url).pathname;
const LOCALES = ['en', 'fr', 'zh-CN', 'ru', 'km'];
const load = (lng) => JSON.parse(readFileSync(join(ROOT, 'src/locales', `${lng}.json`), 'utf8'));

function flatten(obj, prefix = '', out = {}) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object') flatten(v, key, out);
    else out[key] = v;
  }
  return out;
}

function walk(dir, files = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, files);
    else if (/\.(tsx?|mjs)$/.test(name) && !name.endsWith('.test.tsx')) files.push(p);
  }
  return files;
}

const en = flatten(load('en'));
const enKeys = new Set(Object.keys(en));
const PLURAL = /_(zero|one|two|few|many|other)$/;
const baseKeys = new Set([...enKeys].map((k) => k.replace(PLURAL, '')));
const errors = [];

// 1 & 2: keys used in source.
const literal = /\bt\(\s*['"]([a-zA-Z0-9_.\-]+)['"]/g;
const dynamic = /\bt\(\s*`([a-zA-Z0-9_.\-]+)\.\$\{/g;
for (const file of walk(join(ROOT, 'src'))) {
  const src = readFileSync(file, 'utf8');
  for (const m of src.matchAll(literal)) {
    if (!baseKeys.has(m[1])) errors.push(`missing in en.json: ${m[1]}  (${file.replace(ROOT, '')})`);
  }
  for (const m of src.matchAll(dynamic)) {
    const prefix = `${m[1]}.`;
    if (![...enKeys].some((k) => k.startsWith(prefix))) errors.push(`missing prefix in en.json: ${m[1]}.*  (${file.replace(ROOT, '')})`);
  }
}

// 3-5: locale parity.
const vars = (s) => new Set([...String(s).matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1]));
for (const lng of LOCALES.slice(1)) {
  let data;
  try {
    data = flatten(load(lng));
  } catch (e) {
    errors.push(`${lng}: cannot load (${e.message})`);
    continue;
  }
  // Plural forms differ per language (ru has one/few/many/other, zh/km only other).
  const norm = (keys) => new Set([...keys].map((k) => k.replace(PLURAL, '')));
  const have = norm(Object.keys(data));
  for (const k of baseKeys) if (!have.has(k)) errors.push(`${lng}: missing ${k}`);
  for (const k of have) if (!baseKeys.has(k)) errors.push(`${lng}: extra ${k}`);
  for (const [k, v] of Object.entries(data)) {
    if (!String(v).trim()) errors.push(`${lng}: empty ${k}`);
    const base = en[k] ?? en[`${k.replace(PLURAL, '')}_other`] ?? en[k.replace(PLURAL, '')];
    if (base === undefined) continue;
    const a = [...vars(base)].sort().join(',');
    const b = [...vars(v)].sort().join(',');
    if (a !== b && !(k.match(PLURAL) && b.split(',').every((x) => !x || a.includes(x)))) {
      errors.push(`${lng}: variables differ in ${k}: en={${a}} ${lng}={${b}}`);
    }
  }
}

if (errors.length) {
  console.error(errors.join('\n'));
  console.error(`\n${errors.length} i18n problem(s)`);
  process.exit(1);
}
console.log(`i18n OK: ${enKeys.size} keys × ${LOCALES.length} languages`);
