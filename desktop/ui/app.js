// Connection screen of the HMS desktop shell. Talks to the Rust side through
// Tauri's IPC (commands defined in src-tauri/src/lib.rs). No framework, no
// network access of its own: the shell performs the checks.
import { LANGUAGES, pickLanguage, translate } from './i18n.js';

const RETRY_SECONDS = 10;
const invoke = (cmd, args) => window.__TAURI_INTERNALS__.invoke(cmd, args);
const $ = (id) => document.getElementById(id);

let lang = pickLanguage(safeGet('hms.desktop.language'), navigator.language);
let timer = null;

function safeGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode: the choice is not remembered */
  }
}

const t = (key, params) => translate(lang, key, params);

function applyLanguage() {
  document.documentElement.lang = lang;
  for (const el of document.querySelectorAll('[data-t]')) el.textContent = t(el.dataset.t);
  $('url').placeholder = t('placeholder');
}

function setBusy(busy) {
  for (const id of ['test', 'connect', 'url']) $(id).disabled = busy;
}

function stopRetry() {
  clearInterval(timer);
  timer = null;
  $('countdown').hidden = true;
}

function show(kind, text, detail) {
  $('status').hidden = false;
  $('status').dataset.kind = kind;
  $('message').textContent = text;
  $('details').hidden = !detail;
  $('detail-text').textContent = detail ?? '';
}

function explain(result) {
  if (result.kind === 'ok') return t('ok', { url: result.url });
  return t(`results.${result.kind}`, { status: result.status ?? '' });
}

async function test() {
  stopRetry();
  setBusy(true);
  try {
    const result = await invoke('check_server', { url: $('url').value });
    show(result.kind === 'ok' ? 'ok' : 'error', explain(result), result.detail);
  } catch (e) {
    show('error', String(e));
  } finally {
    setBusy(false);
  }
}

/** Connect; on success the window leaves this page for the hotel server. */
async function connect(url, { automatic = false } = {}) {
  stopRetry();
  setBusy(true);
  show('pending', t('connecting', { url }));
  try {
    const result = await invoke('connect', { url });
    if (result.kind === 'ok') return; // navigating to the server
    show('error', explain(result), result.detail);
    // A remembered server that is temporarily unreachable: keep trying.
    if (automatic && ['unreachable', 'timeout', 'http_status'].includes(result.kind)) scheduleRetry(url);
  } catch (e) {
    show('error', String(e));
  } finally {
    setBusy(false);
  }
}

function scheduleRetry(url) {
  let left = RETRY_SECONDS;
  $('retry-actions').hidden = false;
  $('countdown').hidden = false;
  $('countdown').textContent = t('retrying', { s: left });
  timer = setInterval(() => {
    left -= 1;
    $('countdown').textContent = t('retrying', { s: left });
    if (left <= 0) connect(url, { automatic: true });
  }, 1000);
  $('retry').onclick = () => connect(url, { automatic: true });
}

async function start() {
  const select = $('language');
  for (const [code, name] of Object.entries(LANGUAGES)) select.add(new Option(name, code, false, code === lang));
  select.onchange = () => {
    lang = select.value;
    safeSet('hms.desktop.language', lang);
    applyLanguage();
  };
  applyLanguage();

  $('form').onsubmit = (e) => {
    e.preventDefault();
    connect($('url').value);
  };
  $('test').onclick = test;
  $('change').onclick = async () => {
    stopRetry();
    $('retry-actions').hidden = true;
    $('status').hidden = true;
    $('form').hidden = false;
    $('url').focus();
  };

  const saved = await invoke('saved_server').catch(() => null);
  if (saved) $('url').value = saved;
  const changing = new URLSearchParams(location.search).has('change');
  if (saved && !changing) {
    $('form').hidden = true;
    await connect(saved, { automatic: true });
    if (!timer) $('retry-actions').hidden = false;
  } else {
    $('url').focus();
  }
}

start();
