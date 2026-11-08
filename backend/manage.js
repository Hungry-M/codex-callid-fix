#!/usr/bin/env node
/**
 * manage.js — turn codex-callid-fix on/off, choose its egress, switch the
 * active Codex model provider, and manage Codex `.env` / Windows autostart.
 *
 * The proxy itself (server.js) is deliberately passive: it only reads
 * callidfix.config.json and state.json. This file is the only component that
 * touches ~/.codex/config.toml and ~/.codex/.env.
 *
 * Commands:
 *   on                       start proxy + point providers' base_url at it
 *   off                      restore original base_url(s) + stop proxy
 *   toggle                   on <-> off
 *   route fix|upstream|direct [proxy|direct|auto]
 *   status [--json]          show everything
 *   restart                  stop and re-apply (keeps on/off state)
 *   egress <mode>            proxy | direct | auto (also parks/restores .env)
 *   provider list [--json]   list custom model providers
 *   provider use <id|openai> switch Codex's active model_provider
 *   autostart <on|off|status>
 *   boot                     used by the autostart entry; reconciles state
 */

'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const net = require('net');
const http = require('http');
const { spawn, spawnSync } = require('child_process');

const VERSION = '0.1.3';
const TOOL_DIR = __dirname;
const DATA_DIR = path.resolve(process.env.CALLIDFIX_DATA_DIR || TOOL_DIR);
const CONFIG_FILE = path.join(DATA_DIR, 'callidfix.config.json');
const STATE_FILE = path.join(DATA_DIR, 'state.json');
const LOG_FILE = path.join(DATA_DIR, 'server.log');
const NODE_PATH_FILE = path.join(DATA_DIR, 'node-path.txt');
const SERVER_JS = path.join(TOOL_DIR, 'server.js');
const START_VBS = path.join(TOOL_DIR, 'start-hidden.vbs');

const CODEX_HOME = path.resolve(
  expandHome(process.env.CODEX_HOME || path.join(os.homedir(), '.codex'))
);
const CODEX_CONFIG = path.join(CODEX_HOME, 'config.toml');
const CODEX_ENV = path.join(CODEX_HOME, '.env');
const CODEX_ENV_PARKED = path.join(CODEX_HOME, '.env.callidfix-parked');
const CODEX_ENV_BACKUP = path.join(CODEX_HOME, '.env.callidfix-backup');

const RUN_KEY =
  process.env.CALLIDFIX_RUN_KEY ||
  'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run';
const RUN_VALUE = 'codex-callid-fix';

const EGRESS_MODES = new Set(['proxy', 'direct', 'auto']);
const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '::1']);
const ENV_PROXY_KEYS = new Set(['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY']);

function normalizeEgressMode(value) {
  const mode = String(value || '').toLowerCase();
  if (mode === 'clash') return 'proxy'; // legacy config from v2
  return EGRESS_MODES.has(mode) ? mode : 'proxy';
}

// ---------------------------------------------------------------------------
// generic helpers
// ---------------------------------------------------------------------------

function expandHome(p) {
  const s = String(p || '');
  if (s === '~') return os.homedir();
  if (s.startsWith('~/') || s.startsWith('~\\')) {
    return path.join(os.homedir(), s.slice(2));
  }
  return s;
}

function ensureDataDir() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function writeFileAtomic(file, text) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
  try {
    fs.writeFileSync(tmp, text, 'utf8');
    fs.renameSync(tmp, file);
    return;
  } catch (_) {
    try {
      fs.unlinkSync(tmp);
    } catch (_) {
      /* ignore */
    }
    // Some sandboxes deny creating new files in a directory but allow
    // overwriting an existing file. Fall back to an in-place write.
    fs.writeFileSync(file, text, 'utf8');
  }
}

function toolLog(line) {
  try {
    ensureDataDir();
    fs.appendFileSync(LOG_FILE, `[${new Date().toISOString()}] [manage] ${line}\n`);
  } catch (_) {
    /* ignore */
  }
}

function readTextIfExists(file) {
  try {
    let text = fs.readFileSync(file, 'utf8');
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    return text;
  } catch (_) {
    return null;
  }
}

/** Runs a command and captures output through files (works under sandboxes
 *  that forbid Node's pipe-based child_process stdio). */
function captureExec(command, args) {
  ensureDataDir();
  const token = `${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const outFile = path.join(DATA_DIR, `.exec-${token}.out`);
  const errFile = path.join(DATA_DIR, `.exec-${token}.err`);
  let outFd = null;
  let errFd = null;
  try {
    outFd = fs.openSync(outFile, 'w');
    errFd = fs.openSync(errFile, 'w');
    const result = spawnSync(command, args, {
      stdio: ['ignore', outFd, errFd],
      windowsHide: true,
    });
    fs.closeSync(outFd);
    outFd = null;
    fs.closeSync(errFd);
    errFd = null;
    return {
      status: result.status,
      error: result.error || null,
      stdout: readTextIfExists(outFile) || '',
      stderr: readTextIfExists(errFile) || '',
    };
  } finally {
    if (outFd !== null) {
      try {
        fs.closeSync(outFd);
      } catch (_) {
        /* ignore */
      }
    }
    if (errFd !== null) {
      try {
        fs.closeSync(errFd);
      } catch (_) {
        /* ignore */
      }
    }
    for (const f of [outFile, errFile]) {
      try {
        fs.unlinkSync(f);
      } catch (_) {
        /* ignore */
      }
    }
  }
}

function formatHostForUrl(host) {
  const h = String(host || '127.0.0.1');
  return h.includes(':') && !h.startsWith('[') ? `[${h}]` : h;
}

function healthHost(cfg) {
  if (cfg.listenHost === '0.0.0.0') return '127.0.0.1';
  if (cfg.listenHost === '::' || cfg.listenHost === '[::]') return '::1';
  return cfg.listenHost;
}

// ---------------------------------------------------------------------------
// config.toml (targeted editing, no external TOML dependency)
// ---------------------------------------------------------------------------

const PROVIDER_HEADER_RE =
  /^\s*\[\s*model_providers\s*\.\s*(?:"((?:[^"\\]|\\.)*)"|'([^']*)'|([A-Za-z0-9_-]+))\s*\]\s*(.*)$/;

function findProviderSection(lines, providerId) {
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(PROVIDER_HEADER_RE);
    if (!m) continue;
    const name =
      m[1] !== undefined
        ? tomlUnescapeBasic(m[1])
        : m[2] !== undefined
          ? m[2]
          : m[3];
    if (name === providerId) return { headerIndex: i, startIndex: i + 1 };
  }
  return null;
}

function listProviderSections(text) {
  const lines = text.split(/\r?\n/);
  const found = [];
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(PROVIDER_HEADER_RE);
    if (!m) continue;
    const id =
      m[1] !== undefined
        ? tomlUnescapeBasic(m[1])
        : m[2] !== undefined
          ? m[2]
          : m[3];
    found.push({ id, headerIndex: i });
  }
  return found;
}

const BASE_URL_LINE_RE =
  /^(\s*base_url\s*=\s*)("(?:[^"\\]|\\.)*"|'[^']*')(.*)$/;

function readProviderBaseUrl(text, providerId) {
  const lines = text.split(/\r?\n/);
  const section = findProviderSection(lines, providerId);
  if (!section) return { sectionFound: false, found: false };

  for (let i = section.startIndex; i < lines.length; i++) {
    if (/^\s*\[/.test(lines[i])) break;
    const m = lines[i].match(BASE_URL_LINE_RE);
    if (!m) continue;
    const raw = m[2];
    const value =
      raw.startsWith('"') && raw.endsWith('"')
        ? tomlUnescapeBasic(raw.slice(1, -1))
        : raw.slice(1, -1);
    return { sectionFound: true, found: true, value, lineIndex: i };
  }
  return { sectionFound: true, found: false };
}

function tomlUnescapeBasic(s) {
  let out = '';
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c !== '\\') {
      out += c;
      continue;
    }
    const n = s[++i];
    switch (n) {
      case 'b':
        out += '\b';
        break;
      case 't':
        out += '\t';
        break;
      case 'n':
        out += '\n';
        break;
      case 'f':
        out += '\f';
        break;
      case 'r':
        out += '\r';
        break;
      case '"':
        out += '"';
        break;
      case '\\':
        out += '\\';
        break;
      case 'u': {
        const hex = s.slice(i + 1, i + 5);
        const code = parseInt(hex, 16);
        if (Number.isFinite(code)) {
          out += String.fromCharCode(code);
          i += 4;
        } else {
          out += 'u';
        }
        break;
      }
      default:
        out += n === undefined ? '\\' : n;
    }
  }
  return out;
}

function applyBaseUrlEdits(text, edits) {
  const eol = detectEol(text);
  const lines = text.split(/\r?\n/);
  for (const [providerId, value] of Object.entries(edits)) {
    const section = findProviderSection(lines, providerId);
    if (!section) {
      throw new Error(`[model_providers.${providerId}] not found in ${CODEX_CONFIG}`);
    }
    let lineIndex = -1;
    for (let i = section.startIndex; i < lines.length; i++) {
      if (/^\s*\[/.test(lines[i])) break;
      const m = lines[i].match(BASE_URL_LINE_RE);
      if (m) {
        lineIndex = i;
        lines[i] = m[1] + JSON.stringify(String(value)) + m[3];
        break;
      }
    }
    if (lineIndex === -1) {
      throw new Error(
        `base_url line not found in [model_providers.${providerId}] of ${CODEX_CONFIG}`
      );
    }
  }
  return lines.join(eol);
}

function readCodexConfig() {
  if (!fs.existsSync(CODEX_CONFIG)) {
    throw new Error(`Codex config.toml not found: ${CODEX_CONFIG}`);
  }
  const raw = fs.readFileSync(CODEX_CONFIG, 'utf8');
  const bom = raw.charCodeAt(0) === 0xfeff;
  return { text: bom ? raw.slice(1) : raw, bom };
}

function writeCodexConfig(text, bom) {
  writeFileAtomic(CODEX_CONFIG, (bom ? '\uFEFF' : '') + text);
}

/** Reads a top-level (pre-first-table) string key from config.toml. */
function readTopLevelString(text, key) {
  const lines = text.split(/\r?\n/);
  const re = new RegExp(
    `^\\s*${key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*=\\s*("(?:[^"\\\\]|\\\\.)*"|'[^']*')\\s*(?:#.*)?$`
  );
  for (const line of lines) {
    if (/^\s*\[/.test(line)) break;
    const m = line.match(re);
    if (!m) continue;
    const raw = m[1];
    return raw.startsWith('"') && raw.endsWith('"')
      ? tomlUnescapeBasic(raw.slice(1, -1))
      : raw.slice(1, -1);
  }
  return null;
}

/** Sets or removes a top-level string key, preserving the rest of the file. */
function setTopLevelString(text, key, value) {
  const eol = detectEol(text);
  const lines = text.split(/\r?\n/);
  const safeKey = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const lineRe = new RegExp(
    `^(\\s*${safeKey}\\s*=\\s*)("(?:[^"\\\\]|\\\\.)*"|'[^']*')(.*)$`
  );
  let found = -1;
  for (let i = 0; i < lines.length; i++) {
    if (/^\s*\[/.test(lines[i])) break;
    const m = lines[i].match(lineRe);
    if (m) {
      found = i;
      break;
    }
  }

  if (value === null || value === undefined) {
    if (found !== -1) lines.splice(found, 1);
    return lines.join(eol);
  }

  const literal = JSON.stringify(String(value));
  if (found !== -1) {
    const m = lines[found].match(lineRe);
    lines[found] = m[1] + literal + m[3];
    return lines.join(eol);
  }

  // Insert after `model = ...` when possible, otherwise at the very top.
  const modelRe = /^\s*model\s*=\s*/;
  let insertAt = 0;
  for (let i = 0; i < lines.length; i++) {
    if (/^\s*\[/.test(lines[i])) break;
    if (modelRe.test(lines[i])) {
      insertAt = i + 1;
      break;
    }
  }
  lines.splice(insertAt, 0, `${key} = ${literal}`);
  return lines.join(eol);
}

function readProviderMeta(text, providerId) {
  const lines = text.split(/\r?\n/);
  const section = findProviderSection(lines, providerId);
  if (!section) return null;
  const meta = { id: providerId, baseUrl: null, name: null, wireApi: null };
  for (let i = section.startIndex; i < lines.length; i++) {
    if (/^\s*\[/.test(lines[i])) break;
    for (const key of ['base_url', 'name', 'wire_api']) {
      const m = lines[i].match(
        new RegExp(
          `^\\s*${key}\\s*=\\s*("(?:[^"\\\\]|\\\\.)*"|'[^']*')\\s*(?:#.*)?$`
        )
      );
      if (m) {
        const raw = m[1];
        const value =
          raw.startsWith('"') && raw.endsWith('"')
            ? tomlUnescapeBasic(raw.slice(1, -1))
            : raw.slice(1, -1);
        if (key === 'base_url') meta.baseUrl = value;
        if (key === 'name') meta.name = value;
        if (key === 'wire_api') meta.wireApi = value;
      }
    }
  }
  return meta;
}

// ---------------------------------------------------------------------------
// runtime config + state
// ---------------------------------------------------------------------------

function defaultConfig() {
  return {
    listenHost: '127.0.0.1',
    listenPort: 7891,
    providers: 'all',
    fallbackOriginalBaseUrls: {},
    egress: {
      mode: 'proxy',
      proxyHost: '127.0.0.1',
      proxyPort: 7890,
      connectTimeoutMs: 15000,
      autoProbeMs: 3000,
    },
    codexEnv: {
      manage: true,
      noProxy: 'localhost,127.0.0.1,::1',
    },
  };
}

function loadRawConfig() {
  ensureDataDir();
  if (!fs.existsSync(CONFIG_FILE)) {
    const cfg = defaultConfig();
    writeFileAtomic(CONFIG_FILE, JSON.stringify(cfg, null, 2) + '\n');
    return cfg;
  }
  let raw;
  try {
    let text = fs.readFileSync(CONFIG_FILE, 'utf8');
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    raw = JSON.parse(text);
  } catch (err) {
    throw new Error(`cannot parse ${CONFIG_FILE}: ${err.message}`);
  }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error(`${CONFIG_FILE} must contain a JSON object`);
  }
  return raw;
}

function saveRawConfig(raw) {
  writeFileAtomic(CONFIG_FILE, JSON.stringify(raw, null, 2) + '\n');
}

function normalizeProviders(raw) {
  if (raw === undefined || raw === null || raw === 'all') {
    return { all: true, list: [] };
  }
  if (!Array.isArray(raw)) {
    throw new Error('providers must be "all" or an array of provider ids');
  }
  const list = raw
    .map((p) => {
      if (typeof p === 'string') return { id: p };
      if (!p || typeof p !== 'object') return null;
      const id = String(p.id || '');
      if (!id) return null;
      const out = { id };
      if (p.egress !== undefined) {
        out.egress = normalizeEgressMode(p.egress);
      }
      return out;
    })
    .filter(Boolean);
  return { all: false, list };
}

function normalizeConfig(raw) {
  const defaults = defaultConfig();
  const egressRaw =
    raw.egress && typeof raw.egress === 'object' ? raw.egress : {};
  const mode = normalizeEgressMode(egressRaw.mode);
  const listenPort = Number(raw.listenPort);
  const fallback = {};
  if (raw.fallbackOriginalBaseUrls && typeof raw.fallbackOriginalBaseUrls === 'object') {
    for (const [id, value] of Object.entries(raw.fallbackOriginalBaseUrls)) {
      if (typeof value === 'string' && /^https?:\/\//i.test(value)) fallback[id] = value;
    }
  }
  const providers = normalizeProviders(
    raw.providers === undefined ? defaults.providers : raw.providers
  );
  return {
    listenHost: String(raw.listenHost || defaults.listenHost),
    listenPort:
      Number.isInteger(listenPort) && listenPort > 0 && listenPort < 65536
        ? listenPort
        : defaults.listenPort,
    providers: providers.list,
    providersAll: providers.all,
    fallbackOriginalBaseUrls: fallback,
    egress: {
      mode,
      proxyHost: String(
        egressRaw.proxyHost || egressRaw.clashHost || defaults.egress.proxyHost
      ),
      proxyPort:
        Number(egressRaw.proxyPort || egressRaw.clashPort) ||
        defaults.egress.proxyPort,
      connectTimeoutMs:
        Number(egressRaw.connectTimeoutMs) || defaults.egress.connectTimeoutMs,
      autoProbeMs: Number(egressRaw.autoProbeMs) || defaults.egress.autoProbeMs,
    },
    codexEnv: {
      manage:
        raw.codexEnv && raw.codexEnv.manage !== undefined
          ? raw.codexEnv.manage !== false
          : true,
      noProxy: String(
        (raw.codexEnv && raw.codexEnv.noProxy) || defaults.codexEnv.noProxy
      ),
    },
  };
}

function loadConfig() {
  return normalizeConfig(loadRawConfig());
}

function defaultState() {
  return {
    version: 1,
    enabled: false,
    applied: {},
    originalBaseUrls: {},
    serverPid: null,
    listenHost: null,
    listenPort: null,
    updatedAt: null,
  };
}

function loadState() {
  let raw = readTextIfExists(STATE_FILE);
  if (!raw) return defaultState();
  if (raw.charCodeAt(0) === 0xfeff) raw = raw.slice(1);
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return defaultState();
    return {
      ...defaultState(),
      ...parsed,
      applied:
        parsed.applied && typeof parsed.applied === 'object' && !Array.isArray(parsed.applied)
          ? parsed.applied
          : {},
      originalBaseUrls:
        parsed.originalBaseUrls && typeof parsed.originalBaseUrls === 'object'
          ? parsed.originalBaseUrls
          : {},
    };
  } catch (_) {
    return defaultState();
  }
}

function saveState(state) {
  state.updatedAt = new Date().toISOString();
  writeFileAtomic(STATE_FILE, JSON.stringify(state, null, 2) + '\n');
}

// ---------------------------------------------------------------------------
// proxy URL helpers
// ---------------------------------------------------------------------------

function proxyOrigin(cfg) {
  let host = cfg.listenHost;
  if (host === '0.0.0.0') host = '127.0.0.1';
  else if (host === '::' || host === '[::]') host = '::1';
  return `http://${formatHostForUrl(host)}:${cfg.listenPort}`;
}

function makeProxiedBaseUrl(cfg, providerId, originalBaseUrl) {
  const url = new URL(originalBaseUrl);
  const basePath = url.pathname.replace(/\/+$/, '');
  return (
    `${proxyOrigin(cfg)}/_p/${encodeURIComponent(providerId)}` + basePath
  );
}

function isLoopbackHost(hostname) {
  return LOOPBACK_HOSTS.has(String(hostname || '').toLowerCase());
}

function normalizeListenHost(hostname) {
  const h = String(hostname || '').toLowerCase();
  if (h === 'localhost' || h === '127.0.0.1' || h === '::1' || h === '[::1]') {
    return '<loopback>';
  }
  return h;
}

function isLocalProxyUrl(value, cfg) {
  let url;
  try {
    url = new URL(value);
  } catch (_) {
    return false;
  }
  if (!isLoopbackHost(url.hostname)) return false;
  // The /_p/ marker is ours. Do not require the current port here: it lets
  // "off" recover a config written before listenPort was changed.
  return url.pathname === '/_p' || url.pathname.startsWith('/_p/');
}

function isProxyBaseUrl(value, cfg, applied) {
  if (applied && applied.proxiedBaseUrl && value === applied.proxiedBaseUrl) {
    return true;
  }
  if (isLocalProxyUrl(value, cfg)) return true;
  // Legacy v1 layout: http://<loopback>:<listenPort>/<original path> (no /_p/).
  try {
    const url = new URL(value);
    if (
      isLoopbackHost(url.hostname) &&
      url.port === String(cfg.listenPort)
    ) {
      return true;
    }
  } catch (_) {
    /* ignore */
  }
  return false;
}

function validateOriginalBaseUrl(value, providerId) {
  let url;
  try {
    url = new URL(value);
  } catch (_) {
    throw new Error(
      `base_url of [model_providers.${providerId}] is not a URL: ${value}`
    );
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error(
      `base_url of [model_providers.${providerId}] must be http(s): ${value}`
    );
  }
  return url;
}

// ---------------------------------------------------------------------------
// Codex .env management
// ---------------------------------------------------------------------------

function envProxyUrl(cfg) {
  return `http://${formatHostForUrl(cfg.egress.proxyHost)}:${cfg.egress.proxyPort}`;
}

function detectEol(text) {
  return text.includes('\r\n') ? '\r\n' : '\n';
}

function splitEnvLines(text) {
  return String(text || '').split(/\r?\n/);
}

function parseEnvLine(line) {
  const m = String(line).match(
    /^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/
  );
  if (!m) return null;
  return {
    prefix: m[1],
    key: m[2],
    value: m[3].trim(),
  };
}

function isProxyEnvKey(key) {
  return ENV_PROXY_KEYS.has(String(key).toUpperCase());
}

function envHasProxyLines(text) {
  return splitEnvLines(text).some((line) => {
    const info = parseEnvLine(line);
    return info && isProxyEnvKey(info.key);
  });
}

function mergeNoProxy(current, required) {
  const wanted = String(required || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  const parts = String(current || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  if (parts.some((p) => p === '*')) return parts.join(',');
  for (const item of wanted) {
    if (!parts.some((p) => p.toLowerCase() === item.toLowerCase())) {
      parts.push(item);
    }
  }
  return parts.join(',');
}

function backupEnvOnce(existingText) {
  if (existingText === null) return;
  if (fs.existsSync(CODEX_ENV_BACKUP)) return;
  writeFileAtomic(CODEX_ENV_BACKUP, existingText);
}

function parkCodexEnv(cfg) {
  if (!cfg.codexEnv.manage) return { managed: false, changed: false };
  const text = readTextIfExists(CODEX_ENV);
  if (text === null) {
    return { managed: true, changed: false, state: 'already absent' };
  }
  if (!envHasProxyLines(text)) {
    return { managed: true, changed: false, state: 'no proxy lines' };
  }

  backupEnvOnce(text);
  const eol = detectEol(text);
  writeFileAtomic(CODEX_ENV_PARKED, text);

  const kept = splitEnvLines(text).filter((line) => {
    const info = parseEnvLine(line);
    return !(info && isProxyEnvKey(info.key));
  });
  while (kept.length > 0 && kept[kept.length - 1].trim() === '') kept.pop();

  const keptText = kept.length > 0 ? kept.join(eol) + eol : '';
  if (keptText.trim() === '') {
    try {
      fs.unlinkSync(CODEX_ENV);
    } catch (err) {
      throw new Error(`cannot remove ${CODEX_ENV}: ${err.message}`);
    }
    return {
      managed: true,
      changed: true,
      state: 'parked (file removed)',
      parked: CODEX_ENV_PARKED,
    };
  }
  writeFileAtomic(CODEX_ENV, keptText);
  return {
    managed: true,
    changed: true,
    state: 'parked (non-proxy vars kept)',
    parked: CODEX_ENV_PARKED,
  };
}

function activateCodexEnv(cfg) {
  if (!cfg.codexEnv.manage) return { managed: false, changed: false };
  const existingText = readTextIfExists(CODEX_ENV);
  let baseText = existingText;
  let restoredFromParked = false;

  if (baseText === null) {
    const parkedText = readTextIfExists(CODEX_ENV_PARKED);
    if (parkedText !== null) {
      baseText = parkedText;
      restoredFromParked = true;
    } else {
      baseText = '';
    }
  }

  const eol = detectEol(baseText);
  const lines = splitEnvLines(baseText);
  const proxyUrl = envProxyUrl(cfg);
  const noProxy = cfg.codexEnv.noProxy;

  const seen = new Set();
  let changed = existingText === null || restoredFromParked;

  for (let i = 0; i < lines.length; i++) {
    const info = parseEnvLine(lines[i]);
    if (!info || !isProxyEnvKey(info.key)) continue;
    const key = info.key.toUpperCase();
    seen.add(key);
    const value = key === 'NO_PROXY' ? mergeNoProxy(info.value, noProxy) : proxyUrl;
    const nextLine = `${info.prefix}${info.key}=${value}`;
    if (nextLine !== lines[i]) {
      lines[i] = nextLine;
      changed = true;
    }
  }

  const append = [];
  for (const key of ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']) {
    if (!seen.has(key)) append.push(`${key}=${proxyUrl}`);
  }
  if (!seen.has('NO_PROXY')) append.push(`NO_PROXY=${noProxy}`);

  if (append.length > 0) {
    if (lines.length > 0 && lines[lines.length - 1].trim() === '') lines.pop();
    lines.push(...append);
    changed = true;
  }

  if (changed) {
    if (existingText !== null) backupEnvOnce(existingText);
    let out = lines.join(eol);
    if (out.length > 0 && !out.endsWith(eol)) out += eol;
    writeFileAtomic(CODEX_ENV, out);
  }

  if (fs.existsSync(CODEX_ENV_PARKED)) {
    try {
      fs.unlinkSync(CODEX_ENV_PARKED);
    } catch (_) {
      /* ignore */
    }
  }

  return {
    managed: true,
    changed,
    state: restoredFromParked ? 'restored' : 'active',
    proxyUrl,
    noProxy,
  };
}

function ensureCodexEnv(cfg, mode) {
  if (!cfg.codexEnv.manage) {
    return { managed: false, changed: false, state: 'not managed' };
  }
  if (mode === 'direct') return parkCodexEnv(cfg);
  return activateCodexEnv(cfg);
}

function getEnvStatus(cfg) {
  const text = readTextIfExists(CODEX_ENV);
  const parked = fs.existsSync(CODEX_ENV_PARKED);
  const backup = fs.existsSync(CODEX_ENV_BACKUP);
  const hasProxy = text !== null && envHasProxyLines(text);
  let httpProxy = null;
  if (text !== null) {
    for (const line of splitEnvLines(text)) {
      const info = parseEnvLine(line);
      if (info && info.key.toUpperCase() === 'HTTP_PROXY') {
        httpProxy = info.value;
        break;
      }
    }
  }
  let state;
  if (!cfg.codexEnv.manage) state = 'not managed';
  else if (hasProxy) state = 'active';
  else if (parked) state = 'parked';
  else if (text === null) state = 'absent';
  else state = 'direct (no proxy lines)';
  return {
    path: CODEX_ENV,
    parkedPath: CODEX_ENV_PARKED,
    backupPath: CODEX_ENV_BACKUP,
    exists: text !== null,
    hasProxy,
    httpProxy,
    parked,
    backup,
    state,
    desiredProxyUrl: envProxyUrl(cfg),
  };
}

// ---------------------------------------------------------------------------
// process / health helpers
// ---------------------------------------------------------------------------

function httpGetJson(cfg, pathname, timeoutMs = 1500) {
  return new Promise((resolve) => {
    const req = http.get(
      {
        host: healthHost(cfg),
        port: cfg.listenPort,
        path: pathname,
        timeout: timeoutMs,
      },
      (res) => {
        const chunks = [];
        res.on('data', (chunk) => chunks.push(chunk));
        res.on('end', () => {
          try {
            resolve({
              statusCode: res.statusCode,
              body: JSON.parse(Buffer.concat(chunks).toString('utf8')),
            });
          } catch (_) {
            resolve(null);
          }
        });
      }
    );
    req.on('timeout', () => req.destroy());
    req.on('error', () => resolve(null));
  });
}

async function getHealth(cfg) {
  const res = await httpGetJson(cfg, '/__callidfix/health', 1200);
  return res && res.statusCode === 200 ? res.body : null;
}

function findListenerPid(port) {
  if (process.platform !== 'win32') return null;
  const res = captureExec('netstat', ['-ano', '-p', 'tcp']);
  if (res.status !== 0) return null;
  for (const line of res.stdout.split(/\r?\n/)) {
    const cols = line.trim().split(/\s+/);
    if (cols.length < 5) continue;
    const localAddress = cols[1];
    const state = cols[3];
    const pid = Number(cols[4]);
    if (state !== 'LISTENING') continue;
    if (!localAddress.endsWith(`:${port}`)) continue;
    if (Number.isInteger(pid) && pid > 0) return pid;
  }
  return null;
}

function rotateLogIfNeeded() {
  try {
    const stat = fs.statSync(LOG_FILE);
    if (stat.size < 5 * 1024 * 1024) return;
    const old = LOG_FILE + '.1';
    try {
      fs.unlinkSync(old);
    } catch (_) {
      /* ignore */
    }
    fs.renameSync(LOG_FILE, old);
  } catch (_) {
    /* ignore */
  }
}

function spawnServer() {
  rotateLogIfNeeded();
  const fd = fs.openSync(LOG_FILE, 'a');
  let child;
  try {
    child = spawn(process.execPath, [SERVER_JS], {
      detached: true,
      windowsHide: true,
      stdio: ['ignore', fd, fd],
      env: { ...process.env, CALLIDFIX_DATA_DIR: DATA_DIR },
    });
    child.unref();
  } finally {
    try {
      fs.closeSync(fd);
    } catch (_) {
      /* ignore */
    }
  }
  return child;
}

async function ensureServer(cfg, state) {
  // If the listen address/port changed since the last apply, take the old
  // instance down first so we do not leave an orphan on the old port.
  if (
    state.serverPid &&
    state.listenPort &&
    (state.listenPort !== cfg.listenPort ||
      (state.listenHost && state.listenHost !== cfg.listenHost))
  ) {
    const oldCfg = {
      ...cfg,
      listenHost: state.listenHost || cfg.listenHost,
      listenPort: state.listenPort,
    };
    try {
      await stopServer(oldCfg, state);
    } catch (_) {
      /* old port may already be gone or re-used; carry on */
    }
  }

  let health = await getHealth(cfg);

  if (health) {
    if (health.dataDir && path.resolve(health.dataDir) !== DATA_DIR) {
      throw new Error(
        `port ${cfg.listenPort} is held by another codex-callid-fix instance ` +
          `using data dir ${health.dataDir}; stop it first`
      );
    }
    const sameAddress =
      health.listen &&
      Number(health.listen.port) === Number(cfg.listenPort) &&
      normalizeListenHost(health.listen.host) === normalizeListenHost(cfg.listenHost);
    if (health.version !== VERSION || !sameAddress) {
      await stopServer(cfg, state);
      health = null;
    }
  }

  if (!health) {
    const listener = findListenerPid(cfg.listenPort);
    if (listener) {
      throw new Error(
        `port ${cfg.listenPort} is already in use by pid ${listener} ` +
          `(not a healthy codex-callid-fix); free the port or change listenPort`
      );
    }

    const child = spawnServer();
    for (let i = 0; i < 60; i++) {
      health = await getHealth(cfg);
      if (health) break;
      if (child.exitCode !== null) break;
      await sleep(150);
    }
    if (!health) {
      throw new Error(
        `proxy did not become healthy on port ${cfg.listenPort}; see ${LOG_FILE}`
      );
    }
    return { pid: health.pid || child.pid || null, started: true, health };
  }

  return { pid: health.pid || state.serverPid || null, started: false, health };
}

async function waitForPortClosed(port, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (!findListenerPid(port)) return true;
    if (Date.now() >= deadline) return false;
    await sleep(125);
  }
}

function tryKill(pid, signal) {
  try {
    process.kill(pid, signal);
    return true;
  } catch (_) {
    return false;
  }
}

async function stopServer(cfg, state) {
  const health = await getHealth(cfg);
  const listener = findListenerPid(cfg.listenPort);

  if (!health && !listener) {
    return { stopped: false, pid: null, reason: 'not running' };
  }

  if (!health && listener && state.serverPid !== listener) {
    throw new Error(
      `port ${cfg.listenPort} is held by pid ${listener}, which is not the ` +
        `recorded codex-callid-fix process; refusing to kill it`
    );
  }

  if (health && health.dataDir && path.resolve(health.dataDir) !== DATA_DIR) {
    throw new Error(
      `port ${cfg.listenPort} is held by a codex-callid-fix instance using ` +
        `data dir ${health.dataDir}; refusing to kill it`
    );
  }

  const pid = (health && health.pid) || listener || state.serverPid;
  if (!pid) return { stopped: false, pid: null, reason: 'no pid' };

  // process.kill works even where taskkill is blocked by a sandbox/job object.
  tryKill(pid, 'SIGTERM');
  if (await waitForPortClosed(cfg.listenPort, 3000)) {
    return { stopped: true, pid };
  }

  tryKill(pid, 'SIGKILL');
  if (await waitForPortClosed(cfg.listenPort, 2000)) {
    return { stopped: true, pid };
  }

  // Last resort on Windows: PowerShell's Stop-Process.
  captureExec('powershell', [
    '-NoProfile',
    '-NonInteractive',
    '-Command',
    `Stop-Process -Id ${pid} -Force -ErrorAction SilentlyContinue`,
  ]);
  if (await waitForPortClosed(cfg.listenPort, 2000)) {
    return { stopped: true, pid };
  }

  throw new Error(
    `pid ${pid} was asked to stop but port ${cfg.listenPort} is still listening`
  );
}

// ---------------------------------------------------------------------------
// autostart (HKCU\...\Run)
// ---------------------------------------------------------------------------

function wscriptPath() {
  const root = process.env.SystemRoot || process.env.windir || 'C:\\Windows';
  const p = path.join(root, 'System32', 'wscript.exe');
  return fs.existsSync(p) ? p : 'wscript.exe';
}

function autostartCommand() {
  return `"${wscriptPath()}" //B //Nologo "${START_VBS}"`;
}

function getAutostart() {
  if (process.platform !== 'win32') return null;
  const res = captureExec('reg', ['query', RUN_KEY, '/v', RUN_VALUE]);
  if (res.status !== 0) return null;
  const m = res.stdout.match(
    new RegExp(`^\\s*${RUN_VALUE.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s+REG_SZ\\s+(.*)$`, 'm')
  );
  return m ? m[1].trim() : null;
}

function setAutostart(enabled) {
  if (process.platform !== 'win32') {
    throw new Error('autostart is only implemented on Windows');
  }
  if (enabled) {
    writeFileAtomic(NODE_PATH_FILE, process.execPath + '\r\n');
    const res = captureExec('reg', [
      'add',
      RUN_KEY,
      '/v',
      RUN_VALUE,
      '/t',
      'REG_SZ',
      '/d',
      autostartCommand(),
      '/f',
    ]);
    if (res.status !== 0) {
      throw new Error(
        `reg add failed (${res.status}): ${(res.stderr || res.stdout).trim()}`
      );
    }
    return getAutostart();
  }

  const res = captureExec('reg', ['delete', RUN_KEY, '/v', RUN_VALUE, '/f']);
  if (res.status !== 0 && !/unable to find|not find|找不到/i.test(res.stderr)) {
    throw new Error(
      `reg delete failed (${res.status}): ${(res.stderr || res.stdout).trim()}`
    );
  }
  return null;
}

// ---------------------------------------------------------------------------
// status helpers
// ---------------------------------------------------------------------------

function probeTcp(host, port, timeoutMs = 400) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port });
    let settled = false;
    let timer = null;
    const done = (value) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      socket.destroy();
      resolve(value);
    };
    timer = setTimeout(() => done(false), timeoutMs);
    socket.once('connect', () => done(true));
    socket.once('error', () => done(false));
  });
}

function printOnResult(result) {
  const { cfg, plans, ensured, configChanged, env, warnings } = result;
  console.log('');
  console.log(`codex-callid-fix: ON (v${VERSION})`);
  console.log(`  proxy      : ${proxyOrigin(cfg)} (pid ${ensured.pid || '?'})`);
  console.log(
    `  egress     : ${cfg.egress.mode}` +
      (cfg.egress.mode === 'direct'
        ? ' (direct outbound)'
        : ` -> ${cfg.egress.proxyHost}:${cfg.egress.proxyPort}`)
  );
  const envLine = env.managed
    ? `${env.state}` +
      (env.proxyUrl && cfg.egress.mode !== 'direct' ? ` (${env.proxyUrl})` : '')
    : 'not managed';
  console.log(`  codex .env : ${envLine}`);
  console.log(`  config.toml: ${CODEX_CONFIG}${configChanged ? '  [updated]' : '  [unchanged]'}`);
  console.log('  providers  :');
  for (const plan of plans) {
    console.log(`    - ${plan.id}${plan.egress ? ` (egress=${plan.egress})` : ''}`);
    console.log(`        ${plan.originalBaseUrl}`);
    console.log(`        -> ${plan.proxiedBaseUrl}`);
  }
  if (configChanged || env.changed) {
    console.log('');
    console.log('  ! Restart Codex Desktop completely so it re-reads config.toml/.env.');
  }
  const allWarnings = warnings || [];
  if (allWarnings.length > 0) {
    console.log('');
    console.log('  warnings:');
    for (const w of allWarnings) console.log(`    - ${w}`);
  }
  console.log('');
}

function printOffResult(result) {
  const { cfg, restored, configChanged, stop, env, warnings } = result;
  console.log('');
  console.log(`codex-callid-fix: OFF (v${VERSION})`);
  console.log(`  proxy      : ${stop.stopped ? `stopped (pid ${stop.pid})` : 'not running'}`);
  console.log(
    `  egress     : ${cfg.egress.mode}` +
      (cfg.egress.mode === 'direct'
        ? ' (direct outbound)'
        : ` -> ${cfg.egress.proxyHost}:${cfg.egress.proxyPort}`)
  );
  console.log(`  codex .env : ${env.managed ? env.state : 'not managed'}`);
  console.log('  restored   :');
  const ids = Object.keys(restored);
  if (ids.length === 0) {
    console.log('    (no proxied base_url found; config.toml already direct)');
  } else {
    for (const id of ids) console.log(`    - ${id} -> ${restored[id]}`);
  }
  console.log('');
  if (configChanged || env.changed) {
    console.log('  ! Restart Codex Desktop completely so it re-reads config.toml/.env.');
  }
  if (warnings.length > 0) {
    console.log('');
    console.log('  warnings:');
    for (const w of warnings) console.log(`    - ${w}`);
  }
  console.log('');
}

function collectProxySections(text, cfg, state, skipIds) {
  const edits = {};
  const warnings = [];
  const unresolved = [];

  for (const section of listProviderSections(text)) {
    if (skipIds.has(section.id)) continue;
    const info = readProviderBaseUrl(text, section.id);
    if (!info.found) continue;
    const applied = state.applied[section.id];
    if (!isProxyBaseUrl(info.value, cfg, applied)) continue;

    const original =
      (applied && applied.originalBaseUrl) ||
      state.originalBaseUrls[section.id] ||
      cfg.fallbackOriginalBaseUrls[section.id];
    if (!original) {
      warnings.push(
        `[model_providers.${section.id}] points at the proxy but no original ` +
          `base_url is known; add it to fallbackOriginalBaseUrls`
      );
      unresolved.push({ id: section.id, baseUrl: info.value });
      continue;
    }
    edits[section.id] = original;
  }

  for (const id of Object.keys(state.applied)) {
    if (skipIds.has(id)) continue;
    if (edits[id]) continue;
    const stillThere = listProviderSections(text).some((s) => s.id === id);
    if (!stillThere) {
      warnings.push(`state.json has a route for ${id}, but config.toml has no such provider`);
    }
  }

  return { edits, warnings, unresolved };
}

async function applyOn() {
  const cfg = loadConfig();
  const state = loadState();

  const { text, bom } = readCodexConfig();
  const plans = [];
  const warnings = [];

  const providerSpecs = [];
  if (cfg.providersAll) {
    for (const section of listProviderSections(text)) {
      const info = readProviderBaseUrl(text, section.id);
      if (!info.found) {
        warnings.push(
          `skipping [model_providers.${section.id}]: base_url is missing`
        );
        continue;
      }
      providerSpecs.push({ id: section.id });
    }
    if (providerSpecs.length === 0) {
      throw new Error(
        `no usable [model_providers.*] sections found in ${CODEX_CONFIG}; ` +
          'add a custom provider or use OpenAI directly'
      );
    }
  } else {
    if (cfg.providers.length === 0) {
      throw new Error(
        'no providers configured in callidfix.config.json (providers: [])'
      );
    }
    providerSpecs.push(...cfg.providers);
  }

  for (const provider of providerSpecs) {
    const info = readProviderBaseUrl(text, provider.id);
    if (!info.sectionFound) {
      throw new Error(
        `[model_providers.${provider.id}] not found in ${CODEX_CONFIG}; ` +
          `fix providers in callidfix.config.json`
      );
    }
    if (!info.found) {
      throw new Error(
        `base_url is missing from [model_providers.${provider.id}] in ${CODEX_CONFIG}`
      );
    }

    let original = info.value;
    const applied = state.applied[provider.id];
    if (isProxyBaseUrl(original, cfg, applied)) {
      original =
        (applied && applied.originalBaseUrl) ||
        state.originalBaseUrls[provider.id] ||
        cfg.fallbackOriginalBaseUrls[provider.id];
      if (!original) {
        throw new Error(
          `[model_providers.${provider.id}] already points at the proxy but ` +
            `the original base_url is unknown; add it to fallbackOriginalBaseUrls`
        );
      }
    }

    validateOriginalBaseUrl(original, provider.id);
    const plan = {
      id: provider.id,
      originalBaseUrl: original,
      proxiedBaseUrl: makeProxiedBaseUrl(cfg, provider.id, original),
    };
    if (provider.egress) plan.egress = provider.egress;
    plans.push(plan);
  }

  // Publish the originals into the config file as a durable fallback, so a
  // lost state.json can still be recovered by "off".
  try {
    const raw = loadRawConfig();
    const existing =
      raw.fallbackOriginalBaseUrls &&
      typeof raw.fallbackOriginalBaseUrls === 'object'
        ? { ...raw.fallbackOriginalBaseUrls }
        : {};
    let fallbackChanged = false;
    for (const plan of plans) {
      if (existing[plan.id] !== plan.originalBaseUrl) {
        existing[plan.id] = plan.originalBaseUrl;
        fallbackChanged = true;
      }
    }
    if (fallbackChanged) {
      raw.fallbackOriginalBaseUrls = existing;
      saveRawConfig(raw);
    }
  } catch (err) {
    warnings.push(`could not update fallbackOriginalBaseUrls: ${err.message}`);
  }

  const skipIds = new Set(plans.map((p) => p.id));
  const restores = collectProxySections(text, cfg, state, skipIds);
  if (restores.unresolved.length > 0) {
    throw new Error(
      'some providers still point at the proxy but their original base_url is ' +
        'unknown: ' +
        restores.unresolved.map((u) => u.id).join(', ') +
        '. Add them to fallbackOriginalBaseUrls in callidfix.config.json first.'
    );
  }
  warnings.push(...restores.warnings);

  const edits = { ...restores.edits };
  for (const plan of plans) edits[plan.id] = plan.proxiedBaseUrl;

  const ensured = await ensureServer(cfg, state);

  const applied = {};
  for (const plan of plans) {
    applied[plan.id] = {
      originalBaseUrl: plan.originalBaseUrl,
      proxiedBaseUrl: plan.proxiedBaseUrl,
    };
    if (plan.egress) applied[plan.id].egress = plan.egress;
  }

  const nextState = {
    ...state,
    version: 1,
    enabled: true,
    applied,
    originalBaseUrls: {
      ...state.originalBaseUrls,
      ...Object.fromEntries(plans.map((p) => [p.id, p.originalBaseUrl])),
    },
    serverPid: ensured.pid || null,
    listenHost: cfg.listenHost,
    listenPort: cfg.listenPort,
    updatedAt: new Date().toISOString(),
  };

  let configChanged = false;
  try {
    saveState(nextState);
    const nextText = applyBaseUrlEdits(text, edits);
    if (nextText !== text) {
      writeCodexConfig(nextText, bom);
      configChanged = true;
    }
  } catch (err) {
    saveState(state);
    if (ensured.started) {
      try {
        await stopServer(cfg, nextState);
      } catch (_) {
        /* ignore */
      }
    }
    throw err;
  }

  let env = { managed: cfg.codexEnv.manage, changed: false, state: 'not managed' };
  try {
    env = ensureCodexEnv(cfg, cfg.egress.mode);
  } catch (err) {
    warnings.push(`.env update failed: ${err.message}`);
  }

  toolLog(
    `on: pid=${ensured.pid || '?'}, configChanged=${configChanged}, ` +
      `envChanged=${!!env.changed}, providers=${plans.map((p) => p.id).join(',')}`
  );

  return { cfg, plans, restores, ensured, configChanged, env, warnings };
}

async function stopServerForState(cfg, state) {
  const warnings = [];
  let stop = { stopped: false, pid: null, reason: 'not running' };
  const ports = new Set([cfg.listenPort]);
  if (state.serverPid && state.listenPort) ports.add(state.listenPort);

  for (const port of ports) {
    const portCfg = port === cfg.listenPort ? cfg : { ...cfg, listenPort: port };
    try {
      const result = await stopServer(portCfg, state);
      if (result.stopped) stop = result;
    } catch (err) {
      if (port === cfg.listenPort) {
        warnings.push(`proxy stop failed: ${err.message}`);
      }
    }
  }
  return { stop, warnings };
}

async function applyOff() {
  const cfg = loadConfig();
  const state = loadState();
  const warnings = [];
  let text = null;
  let bom = false;

  try {
    ({ text, bom } = readCodexConfig());
  } catch (err) {
    warnings.push(err.message);
  }

  let restored = {};
  let configChanged = false;
  if (text !== null) {
    const collected = collectProxySections(text, cfg, state, new Set());
    warnings.push(...collected.warnings);
    if (collected.unresolved.length > 0) {
      throw new Error(
        'refusing to stop while these providers still point at the proxy but ' +
          'their original base_url is unknown: ' +
          collected.unresolved.map((u) => u.id).join(', ') +
          '. Add them to fallbackOriginalBaseUrls in callidfix.config.json first.'
      );
    }
    restored = collected.edits;
    if (Object.keys(restored).length > 0) {
      const nextText = applyBaseUrlEdits(text, restored);
      if (nextText !== text) {
        writeCodexConfig(nextText, bom);
        configChanged = true;
      }
    }
  }

  const nextState = {
    ...state,
    version: 1,
    enabled: false,
    applied: {},
    serverPid: null,
    listenHost: null,
    listenPort: null,
    updatedAt: new Date().toISOString(),
  };
  saveState(nextState);

  const stopped = await stopServerForState(cfg, state);
  warnings.push(...stopped.warnings);

  let env = { managed: cfg.codexEnv.manage, changed: false, state: 'not managed' };
  try {
    env = ensureCodexEnv(cfg, cfg.egress.mode);
  } catch (err) {
    warnings.push(`.env update failed: ${err.message}`);
  }

  toolLog(
    `off: restored=${Object.keys(restored).join(',') || 'none'}, ` +
      `stopped=${stopped.stop.stopped}, envChanged=${!!env.changed}`
  );

  return {
    cfg,
    restored,
    configChanged,
    stop: stopped.stop,
    env,
    warnings,
  };
}

async function cmdOn() {
  printOnResult(await applyOn());
}

async function cmdOff() {
  printOffResult(await applyOff());
}

async function cmdToggle() {
  const state = loadState();
  if (state.enabled) await cmdOff();
  else await cmdOn();
}

async function cmdRestart() {
  const cfg = loadConfig();
  const state = loadState();
  const stopped = await stopServerForState(cfg, state);
  for (const warning of stopped.warnings) console.warn(`warning: ${warning}`);
  if (!state.enabled) {
    console.log('codex-callid-fix is currently OFF; run "node manage.js on" instead.');
    return;
  }
  printOnResult(await applyOn());
}

function saveEgressMode(mode) {
  const raw = loadRawConfig();
  raw.egress = { ...(raw.egress || {}), mode };
  saveRawConfig(raw);
  return normalizeConfig(raw);
}

async function cmdEgress(mode) {
  const raw = loadRawConfig();
  const cfg = normalizeConfig(raw);

  if (!mode) {
    console.log(`egress: ${cfg.egress.mode}`);
    console.log(
      `  upstream proxy: ${cfg.egress.proxyHost}:${cfg.egress.proxyPort}` +
        (cfg.egress.mode === 'direct' ? ' (unused in direct mode)' : '')
    );
    console.log(`  .env : ${getEnvStatus(cfg).state}`);
    return;
  }

  const wanted = String(mode).toLowerCase() === 'clash'
    ? 'proxy'
    : String(mode).toLowerCase();
  if (!EGRESS_MODES.has(wanted)) {
    throw new Error(`invalid egress mode '${mode}' (use proxy|direct|auto)`);
  }

  raw.egress = { ...(raw.egress || {}), mode: wanted };
  saveRawConfig(raw);
  const nextCfg = normalizeConfig(raw);

  let env = { managed: nextCfg.codexEnv.manage, changed: false, state: 'not managed' };
  const warnings = [];
  try {
    env = ensureCodexEnv(nextCfg, wanted);
  } catch (err) {
    warnings.push(`.env update failed: ${err.message}`);
  }

  console.log('');
  console.log(`codex-callid-fix: egress = ${wanted}`);
  if (wanted === 'direct') {
    console.log('  proxy      : direct outbound (no upstream HTTP proxy)');
  } else if (wanted === 'auto') {
    console.log(
      `  proxy      : try ${nextCfg.egress.proxyHost}:${nextCfg.egress.proxyPort}, ` +
        `fall back to direct`
    );
  } else {
    console.log(
      `  proxy      : ${nextCfg.egress.proxyHost}:${nextCfg.egress.proxyPort}`
    );
  }
  console.log(`  codex .env : ${env.managed ? env.state : 'not managed'}`);
  if (env.changed) {
    console.log('');
    console.log('  ! Restart Codex Desktop so it re-reads .env.');
  }
  for (const w of warnings) console.log(`  warning: ${w}`);
  console.log('');
}

async function cmdProvider(sub, arg, asJson) {
  const action = sub || 'list';
  const cfg = loadConfig();
  const { text, bom } = readCodexConfig();

  if (action === 'list' || action === 'status') {
    const active = readTopLevelString(text, 'model_provider');
    const model = readTopLevelString(text, 'model');
    const catalog = readTopLevelString(text, 'model_catalog_json');
    const state = loadState();
    const providers = listProviderSections(text).map((section) => {
      const meta = readProviderMeta(text, section.id) || {};
      return {
        id: section.id,
        baseUrl: meta.baseUrl || null,
        name: meta.name || null,
        wireApi: meta.wireApi || null,
        active: active === section.id,
        proxied:
          !!meta.baseUrl &&
          isProxyBaseUrl(meta.baseUrl, cfg, state.applied[section.id]),
      };
    });
    const warnings = [];
    if (active && !providers.some((p) => p.id === active)) {
      warnings.push(`model_provider = "${active}" but [model_providers.${active}] was not found`);
    }
    if (!active && catalog) {
      warnings.push(
        `OpenAI built-in mode, but model_catalog_json still points to ${catalog}`
      );
    }
    const payload = {
      active,
      builtIn: active === null,
      model,
      catalog,
      providers,
      warnings,
    };
    if (asJson) {
      console.log(JSON.stringify(payload, null, 2));
      return;
    }
    console.log(`provider : ${active || 'OpenAI (built-in)'}`);
    console.log(`model    : ${model || '(not set)'}`);
    console.log(`catalog  : ${catalog || '(built-in)'}`);
    console.log('providers:');
    for (const p of providers) {
      const flags = [];
      if (p.active) flags.push('active');
      if (p.proxied) flags.push('proxied');
      console.log(`  - ${p.id}${flags.length ? ` [${flags.join(', ')}]` : ''}`);
      console.log(`      ${p.baseUrl || '(missing base_url)'}`);
    }
    if (warnings.length) {
      console.log('warnings:');
      for (const w of warnings) console.log(`  - ${w}`);
    }
    return;
  }

  if (action !== 'use') {
    throw new Error('usage: node manage.js provider list [--json] | provider use <id|openai>');
  }
  if (!arg) {
    throw new Error('usage: node manage.js provider use <id|openai>');
  }

  const isBuiltIn = /^(openai|built-?in|none|default)$/i.test(arg);
  const target = isBuiltIn ? null : arg;
  if (target !== null && !findProviderSection(text.split(/\r?\n/), target)) {
    throw new Error(`[model_providers.${target}] not found in ${CODEX_CONFIG}`);
  }

  const previous = readTopLevelString(text, 'model_provider');
  const nextText = setTopLevelString(text, 'model_provider', target);
  const changed = nextText !== text;
  if (changed) writeCodexConfig(nextText, bom);

  const model = readTopLevelString(nextText, 'model');
  const catalog = readTopLevelString(nextText, 'model_catalog_json');
  const warnings = [];
  if (target === null) {
    if (model) {
      warnings.push(
        `model is still "${model}"; if Codex reports an unknown model, pick an OpenAI model in Codex`
      );
    }
    if (catalog) {
      warnings.push(
        `model_catalog_json is still ${catalog}; it may only contain models for the previous provider`
      );
    }
  } else if (!cfg.providersAll && !cfg.providers.some((p) => p.id === target)) {
    warnings.push(
      `${target} is not in callidfix.config.json providers; add it or set providers to "all"`
    );
  }

  const result = {
    active: target,
    builtIn: target === null,
    previous,
    changed,
    model,
    catalog,
    warnings,
  };
  if (asJson) {
    console.log(JSON.stringify(result, null, 2));
    return;
  }
  console.log(
    `provider: ${target || 'OpenAI (built-in)'}` +
      (changed ? '  [updated]' : '  [unchanged]')
  );
  if (target !== null) console.log(`  base_url: ${readProviderMeta(nextText, target).baseUrl}`);
  if (model) console.log(`  model   : ${model}`);
  for (const w of warnings) console.log(`  warning: ${w}`);
}

async function cmdRoute(sub, mode) {
  const action = String(sub || '').toLowerCase();
  if (!['fix', 'upstream', 'proxy', 'direct'].includes(action)) {
    throw new Error('usage: node manage.js route fix [proxy|direct|auto] | route upstream | route direct');
  }

  if (action === 'fix') {
    if (mode) {
      const rawMode = String(mode).toLowerCase() === 'clash'
        ? 'proxy'
        : String(mode).toLowerCase();
      if (!EGRESS_MODES.has(rawMode)) {
        throw new Error(`invalid egress mode '${mode}' (use proxy|direct|auto)`);
      }
      saveEgressMode(rawMode);
    }
    printOnResult(await applyOn());
    return;
  }

  saveEgressMode(action === 'direct' ? 'direct' : 'proxy');
  printOffResult(await applyOff());
}

async function cmdAutostart(sub) {
  const action = sub || 'status';
  if (action === 'on') {
    const value = setAutostart(true);
    console.log(`autostart: ON`);
    console.log(`  ${value}`);
    console.log('  (starts hidden at logon; boot respects the last on/off state)');
    return;
  }
  if (action === 'off') {
    setAutostart(false);
    console.log('autostart: OFF');
    return;
  }
  if (action === 'status') {
    const value = getAutostart();
    if (value) {
      console.log('autostart: ON');
      console.log(`  ${value}`);
    } else {
      console.log('autostart: OFF');
    }
    return;
  }
  throw new Error('usage: node manage.js autostart <on|off|status>');
}

async function cmdStatus(asJson) {
  const cfg = loadConfig();
  const state = loadState();
  const health = await getHealth(cfg);
  const listenerPid = findListenerPid(cfg.listenPort);
  const autostart = getAutostart();
  const env = getEnvStatus(cfg);
  const proxyReachable =
    cfg.egress.mode === 'direct'
      ? null
      : await probeTcp(cfg.egress.proxyHost, cfg.egress.proxyPort, 450);

  let configText = null;
  let configError = null;
  try {
    configText = readCodexConfig().text;
  } catch (err) {
    configError = err.message;
  }

  const providerRows = [];
  let activeProvider = null;
  let currentModel = null;
  let currentCatalog = null;
  if (configText) {
    activeProvider = readTopLevelString(configText, 'model_provider');
    currentModel = readTopLevelString(configText, 'model');
    currentCatalog = readTopLevelString(configText, 'model_catalog_json');
    const explicitIds = new Set(cfg.providers.map((p) => p.id));
    for (const section of listProviderSections(configText)) {
      const info = readProviderBaseUrl(configText, section.id);
      const applied = state.applied[section.id];
      providerRows.push({
        id: section.id,
        found: !!info.found,
        baseUrl: info.found ? info.value : null,
        proxied: info.found ? isProxyBaseUrl(info.value, cfg, applied) : false,
        applied: applied || null,
        managed: cfg.providersAll || explicitIds.has(section.id),
        active: activeProvider === section.id,
      });
    }
    for (const provider of cfg.providers) {
      if (providerRows.some((row) => row.id === provider.id)) continue;
      providerRows.push({
        id: provider.id,
        found: false,
        baseUrl: null,
        proxied: false,
        applied: state.applied[provider.id] || null,
        managed: true,
        active: activeProvider === provider.id,
      });
    }
  }

  const extraProxied = providerRows.filter((row) => row.proxied && !row.managed);
  const managedRows = providerRows.filter((row) => row.managed);

  const warnings = [];
  if (configError) warnings.push(configError);
  if (state.enabled && !health) {
    warnings.push('state says ON, but the proxy is not answering; run "node manage.js on"');
  }
  if (!state.enabled && health) {
    warnings.push('the proxy is running while state says OFF; run "node manage.js off"');
  }
  if (!state.enabled && managedRows.some((item) => item.proxied)) {
    warnings.push(
      'config.toml still points at the proxy while state says OFF; run "node manage.js off"'
    );
  }
  if (!state.enabled && Object.keys(state.applied).length > 0) {
    warnings.push(
      'state.json still has active routes while OFF; run "node manage.js off" to clean up'
    );
  }
  if (health && health.version !== VERSION) {
    warnings.push(
      `running proxy is v${health.version}, tool is v${VERSION}; run restart`
    );
  }
  if (listenerPid && !health) {
    warnings.push(`port ${cfg.listenPort} is held by pid ${listenerPid} (not this proxy)`);
  }
  if (state.enabled) {
    for (const item of managedRows) {
      if (!item.found) {
        warnings.push(`[model_providers.${item.id}] is not present in config.toml`);
      } else if (!item.applied) {
        warnings.push(`${item.id} is managed but has no active route; run on`);
      } else if (item.baseUrl !== item.applied.proxiedBaseUrl) {
        warnings.push(
          `${item.id}: config.toml base_url drifted from the proxy URL; run on`
        );
      }
    }
  }
  if (extraProxied.length > 0) {
    warnings.push(
      `other providers still point at the proxy: ${extraProxied
        .map((p) => p.id)
        .join(', ')}; remove them from providers or run off`
    );
  }
  if (env.managed) {
    if (cfg.egress.mode === 'direct' && env.hasProxy) {
      warnings.push('.env still sets an HTTP proxy while egress=direct');
    }
    if (cfg.egress.mode !== 'direct' && !env.hasProxy) {
      warnings.push(
        `.env has no proxy lines while egress=${cfg.egress.mode}; run "node manage.js egress ${cfg.egress.mode}"`
      );
    }
    if (
      cfg.egress.mode !== 'direct' &&
      env.hasProxy &&
      env.httpProxy &&
      env.httpProxy.replace(/\/+$/, '') !== env.desiredProxyUrl.replace(/\/+$/, '')
    ) {
      warnings.push(
        `.env HTTP_PROXY is ${env.httpProxy}, expected ${env.desiredProxyUrl}`
      );
    }
  }
  if (proxyReachable === false) {
    warnings.push(
      `upstream proxy is not listening on ${cfg.egress.proxyHost}:${cfg.egress.proxyPort}` +
        (cfg.egress.mode === 'auto' ? ' (auto will fall back to direct)' : '')
    );
  }

  const payload = {
    version: VERSION,
    state: {
      enabled: state.enabled,
      applied: state.applied,
      originalBaseUrls: state.originalBaseUrls,
      serverPid: state.serverPid,
      updatedAt: state.updatedAt,
    },
    proxy: {
      running: !!health,
      pid: health ? health.pid : null,
      listenerPid,
      health,
    },
    listen: {
      host: cfg.listenHost,
      port: cfg.listenPort,
      url: proxyOrigin(cfg),
    },
    egress: {
      ...cfg.egress,
      proxyReachable,
    },
    env,
    autostart,
    provider: {
      active: activeProvider,
      model: currentModel,
      catalog: currentCatalog,
      providersAll: cfg.providersAll,
      providers: providerRows,
    },
    config: {
      path: CODEX_CONFIG,
      error: configError,
    },
    paths: {
      dataDir: DATA_DIR,
      configFile: CONFIG_FILE,
      stateFile: STATE_FILE,
      logFile: LOG_FILE,
    },
    warnings,
  };

  if (asJson) {
    console.log(JSON.stringify(payload, null, 2));
    return;
  }

  console.log('');
  console.log(`codex-callid-fix v${VERSION}`);
  console.log(`  state      : ${state.enabled ? 'ON' : 'OFF'}`);
  console.log(
    `  proxy      : ${
      health
        ? `running (pid ${health.pid})`
        : listenerPid
          ? `port ${cfg.listenPort} held by pid ${listenerPid}`
          : 'stopped'
    }`
  );
  console.log(`  listen     : ${proxyOrigin(cfg)}`);
  console.log(
    `  egress     : ${cfg.egress.mode}` +
      (cfg.egress.mode === 'direct'
        ? ' (direct)'
        : ` -> ${cfg.egress.proxyHost}:${cfg.egress.proxyPort}` +
          (proxyReachable === null ? '' : proxyReachable ? ' [reachable]' : ' [NOT reachable]'))
  );
  console.log(`  provider   : ${activeProvider || 'OpenAI (built-in)'}`);
  if (currentModel) console.log(`  model      : ${currentModel}`);
  if (currentCatalog) console.log(`  catalog    : ${currentCatalog}`);
  console.log(`  autostart  : ${autostart ? 'ON' : 'OFF'}`);
  if (autostart) console.log(`               ${autostart}`);
  console.log(`  codex .env : ${env.state}`);
  if (env.httpProxy) console.log(`               HTTP_PROXY=${env.httpProxy}`);
  if (env.parked) console.log(`               parked: ${env.parkedPath}`);
  console.log(`  data dir   : ${DATA_DIR}`);
  console.log(`  codex home : ${CODEX_HOME}`);
  console.log(`  config.toml: ${CODEX_CONFIG}`);
  if (configError) console.log(`               ${configError}`);
  console.log('  providers  :');
  if (providerRows.length === 0) console.log('    (none found)');
  for (const item of providerRows) {
    const flags = [];
    if (item.active) flags.push('active');
    if (item.proxied) flags.push('proxied');
    if (!item.managed) flags.push('not managed');
    console.log(`    - ${item.id}${flags.length ? ` [${flags.join(', ')}]` : ''}`);
    console.log(`        base_url: ${item.baseUrl || '(missing base_url)'}`);
    if (item.applied) {
      console.log(`        original: ${item.applied.originalBaseUrl}`);
    }
  }
  if (extraProxied.length > 0) {
    console.log('  other proxied providers:');
    for (const item of extraProxied) {
      console.log(`    - ${item.id}: ${item.baseUrl}`);
    }
  }
  if (warnings.length > 0) {
    console.log('');
    console.log('  warnings:');
    for (const w of warnings) console.log(`    - ${w}`);
  }
  console.log('');
}

async function cmdBoot() {
  try {
    const state = loadState();
    if (state.enabled) {
      const result = await applyOn();
      toolLog(
        `boot: ON (pid=${result.ensured.pid}, configChanged=${result.configChanged}, ` +
          `envChanged=${!!result.env.changed})`
      );
    } else {
      const result = await applyOff();
      toolLog(
        `boot: OFF (restored=${Object.keys(result.restored).length}, ` +
          `stopped=${result.stop.stopped})`
      );
    }
  } catch (err) {
    toolLog(`boot failed: ${err && err.stack ? err.stack : err.message}`);
    process.exitCode = 1;
  }
}

function printHelp() {
  console.log(`codex-callid-fix v${VERSION}

Usage:
  node manage.js on                       start proxy + rewrite config.toml base_url(s)
  node manage.js off                      restore base_url(s) + stop proxy
  node manage.js toggle                   switch between on and off
  node manage.js route fix [proxy|direct|auto]
  node manage.js route upstream           Codex goes through the upstream proxy, proxy off
  node manage.js route direct             Codex goes direct, proxy off
  node manage.js status [--json]          show status
  node manage.js restart                  stop proxy and re-apply
  node manage.js egress <mode>            proxy | direct | auto
  node manage.js provider list [--json]   list custom model providers
  node manage.js provider use <id|openai> switch Codex's active model_provider
  node manage.js autostart <on|off|status>
  node manage.js boot                     internal: run by the autostart entry

Egress modes:
  proxy   proxy traffic goes through the configured upstream HTTP proxy
  direct  proxy traffic connects to the provider directly
  auto    try the upstream proxy first, fall back to direct

Listen and upstream-proxy ports come from callidfix.config.json (GUI: settings).
egress also parks/restores ~/.codex/.env so Codex itself follows the same
choice when the proxy is off. A full Codex Desktop restart is required after
on/off/egress/provider changes.
`);
}

// ---------------------------------------------------------------------------
// entry point
// ---------------------------------------------------------------------------

async function main() {
  const args = process.argv.slice(2);
  const command = args[0] || 'help';

  switch (command) {
    case 'on':
      await cmdOn();
      break;
    case 'off':
      await cmdOff();
      break;
    case 'toggle':
      await cmdToggle();
      break;
    case 'status':
      await cmdStatus(args.includes('--json'));
      break;
    case 'restart':
      await cmdRestart();
      break;
    case 'egress':
      await cmdEgress(args[1]);
      break;
    case 'route':
      await cmdRoute(args[1], args[2]);
      break;
    case 'provider':
      await cmdProvider(args[1], args[2], args.includes('--json'));
      break;
    case 'autostart':
      await cmdAutostart(args[1]);
      break;
    case 'boot':
      await cmdBoot();
      break;
    case 'help':
    case '--help':
    case '-h':
      printHelp();
      break;
    default:
      printHelp();
      process.exitCode = 1;
  }
}

if (require.main === module) {
  main().catch((err) => {
    console.error(`error: ${err && err.message ? err.message : err}`);
    process.exitCode = 1;
  });
}

module.exports = {
  // exported for tests
  VERSION,
  applyBaseUrlEdits,
  readProviderBaseUrl,
  listProviderSections,
  normalizeConfig,
  defaultConfig,
  isLocalProxyUrl,
  makeProxiedBaseUrl,
  mergeNoProxy,
  envHasProxyLines,
  parseEnvLine,
};
