#!/usr/bin/env node
/**
 * codex-callid-fix — local repair proxy for Codex Desktop + strict Responses APIs.
 *
 * Bug being worked around:
 *   Codex Desktop seeds app-tool delegations (create_thread /
 *   send_message_to_thread) into child threads as `function_call_output`
 *   items WITHOUT `call_id`. Strict Responses implementations reject them:
 *     Invalid 'call_id': call_id is required for function_call_output.
 *
 * Fix strategy:
 *   Codex -> http://<listenHost>:<listenPort>/_p/<provider>/...  (this proxy)
 *        -> either CONNECT through an upstream HTTP proxy or direct TLS
 *        -> the provider's original base_url
 *
 * Synthetic function_call_output items (no call_id) are converted into
 * ordinary user messages, which every Responses implementation accepts.
 *
 * The listening port, egress mode and the active routes are maintained by
 * manage.js in callidfix.config.json / state.json (same directory unless
 * CALLIDFIX_DATA_DIR is set). This file deliberately has no side effects on
 * Codex's config.toml; manage.js owns that.
 */

'use strict';

const http = require('http');
const net = require('net');
const tls = require('tls');
const fs = require('fs');
const path = require('path');

const VERSION = '0.1.0';
const TOOL_DIR = __dirname;
const DATA_DIR = path.resolve(process.env.CALLIDFIX_DATA_DIR || TOOL_DIR);
const CONFIG_FILE = path.join(DATA_DIR, 'callidfix.config.json');
const STATE_FILE = path.join(DATA_DIR, 'state.json');
const LOG_FILE = path.join(DATA_DIR, 'server.log');

const PROVIDER_PREFIX = '/_p/';
const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '::1']);

const DEFAULTS = {
  listenHost: '127.0.0.1',
  listenPort: 7891,
  egress: {
    mode: 'proxy',
    proxyHost: '127.0.0.1',
    proxyPort: 7890,
    connectTimeoutMs: 15000,
    autoProbeMs: 3000,
  },
};

const EGRESS_MODES = new Set(['proxy', 'direct', 'auto']);

function normalizeEgressMode(value) {
  const mode = String(value || '').toLowerCase();
  if (mode === 'clash') return 'proxy'; // legacy config from v2
  return EGRESS_MODES.has(mode) ? mode : 'proxy';
}

// Filled in once the listener is bound, so health reports the real address
// rather than whatever the config file says right now.
let actualListen = null;

// ---------------------------------------------------------------------------
// small utilities
// ---------------------------------------------------------------------------

function ts() {
  return new Date().toISOString();
}

function log(line) {
  const entry = `[${ts()}] ${line}`;
  try {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    fs.appendFileSync(LOG_FILE, entry + '\n');
  } catch (_) {
    // Logging must never break proxying.
  }
  try {
    // When started by manage.js stdout is redirected to the same log file, so
    // only echo on an interactive terminal to avoid duplicate lines.
    if (process.stdout.isTTY) console.log(entry);
  } catch (_) {
    /* ignore */
  }
}

function safeJson(file, fallback) {
  try {
    let text = fs.readFileSync(file, 'utf8');
    if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
    return JSON.parse(text);
  } catch (_) {
    return fallback;
  }
}

// Cheap mtime/size based cache: manage.js rewrites these files atomically, so
// the proxy sees egress / route changes without a restart.
const jsonCache = new Map();

function readJsonCached(file, fallback) {
  let stat;
  try {
    stat = fs.statSync(file);
  } catch (_) {
    return fallback;
  }
  const prev = jsonCache.get(file);
  if (prev && prev.mtimeMs === stat.mtimeMs && prev.size === stat.size) {
    return prev.value;
  }
  const value = safeJson(file, fallback);
  jsonCache.set(file, { mtimeMs: stat.mtimeMs, size: stat.size, value });
  return value;
}

function loadRuntimeConfig() {
  const raw = readJsonCached(CONFIG_FILE, {}) || {};
  const rawEgress = raw.egress && typeof raw.egress === 'object' ? raw.egress : {};
  const mode = normalizeEgressMode(rawEgress.mode);
  const listenPort = Number(raw.listenPort);
  return {
    listenHost: String(raw.listenHost || DEFAULTS.listenHost),
    listenPort:
      Number.isInteger(listenPort) && listenPort > 0 && listenPort < 65536
        ? listenPort
        : DEFAULTS.listenPort,
    egress: {
      mode,
      proxyHost: String(
        rawEgress.proxyHost || rawEgress.clashHost || DEFAULTS.egress.proxyHost
      ),
      proxyPort:
        Number(rawEgress.proxyPort || rawEgress.clashPort) ||
        DEFAULTS.egress.proxyPort,
      connectTimeoutMs:
        Number(rawEgress.connectTimeoutMs) || DEFAULTS.egress.connectTimeoutMs,
      autoProbeMs: Number(rawEgress.autoProbeMs) || DEFAULTS.egress.autoProbeMs,
    },
  };
}

function loadState() {
  const raw = readJsonCached(STATE_FILE, {}) || {};
  const applied =
    raw.applied && typeof raw.applied === 'object' && !Array.isArray(raw.applied)
      ? raw.applied
      : {};
  return { enabled: raw.enabled === true, applied };
}

function isValidRoute(route) {
  return (
    route &&
    typeof route === 'object' &&
    typeof route.originalBaseUrl === 'string' &&
    /^https?:\/\//i.test(route.originalBaseUrl)
  );
}

function upstreamOf(route) {
  const url = new URL(route.originalBaseUrl);
  const protocol = url.protocol === 'https:' ? 'https:' : 'http:';
  return {
    protocol,
    hostname: url.hostname,
    port: Number(url.port) || (protocol === 'https:' ? 443 : 80),
    hostHeader: url.host,
  };
}

function routeEgress(route, egress) {
  if (route && route.egress) {
    const mode = normalizeEgressMode(route.egress);
    if (EGRESS_MODES.has(mode)) return mode;
  }
  return egress.mode;
}

// ---------------------------------------------------------------------------
// egress: direct TCP/TLS or CONNECT through an upstream HTTP proxy
// ---------------------------------------------------------------------------

function connectTcp(host, port, timeoutMs) {
  return new Promise((resolve, reject) => {
    const socket = net.connect({ host, port });
    let settled = false;

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      socket.destroy();
      reject(new Error(`connect to ${host}:${port} timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    const onError = (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      reject(new Error(`connect to ${host}:${port} failed: ${err.message}`));
    };

    socket.once('error', onError);
    socket.once('connect', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.removeListener('error', onError);
      socket.setNoDelay(true);
      resolve(socket);
    });
  });
}

function tlsWrap(socket, host, timeoutMs, leftover) {
  return new Promise((resolve, reject) => {
    const tlsSocket = tls.connect({ socket, servername: host });
    let settled = false;

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      tlsSocket.destroy();
      reject(new Error(`TLS handshake with ${host} timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    const onError = (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      tlsSocket.destroy();
      reject(new Error(`TLS handshake with ${host} failed: ${err.message}`));
    };

    tlsSocket.once('error', onError);
    tlsSocket.once('secureConnect', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      tlsSocket.removeListener('error', onError);
      tlsSocket.setNoDelay(true);
      if (leftover && leftover.length) tlsSocket.unshift(leftover);
      resolve(tlsSocket);
    });
  });
}

function tlsConnectDirect(host, port, timeoutMs) {
  return new Promise((resolve, reject) => {
    const socket = tls.connect({ host, port, servername: host });
    let settled = false;

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      socket.destroy();
      reject(new Error(`direct TLS connect to ${host}:${port} timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    const onError = (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      reject(new Error(`direct TLS connect to ${host}:${port} failed: ${err.message}`));
    };

    socket.once('error', onError);
    socket.once('secureConnect', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.removeListener('error', onError);
      socket.setNoDelay(true);
      resolve(socket);
    });
  });
}

/** Sends CONNECT and resolves with any bytes already read after the headers. */
function proxyConnect(socket, target, timeoutMs) {
  return new Promise((resolve, reject) => {
    let buffered = Buffer.alloc(0);
    let settled = false;

    const cleanup = () => {
      clearTimeout(timer);
      socket.removeListener('data', onData);
      socket.removeListener('error', onError);
      socket.removeListener('close', onClose);
    };

    const fail = (err) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(err);
    };

    const timer = setTimeout(() => {
      fail(new Error(`CONNECT ${target} timed out after ${timeoutMs}ms`));
      socket.destroy();
    }, timeoutMs);

    const onError = (err) => fail(new Error(`CONNECT ${target} failed: ${err.message}`));
    const onClose = () => fail(new Error(`CONNECT ${target} closed before a response`));

    const onData = (chunk) => {
      buffered = Buffer.concat([buffered, chunk]);
      if (buffered.length > 128 * 1024) {
        fail(new Error(`CONNECT ${target} response headers too large`));
        socket.destroy();
        return;
      }
      const end = buffered.indexOf('\r\n\r\n');
      if (end === -1) return;

      const statusLine = buffered.subarray(0, end).toString('latin1').split('\r\n')[0];
      if (!/^HTTP\/1\.[01] 200\b/.test(statusLine)) {
        fail(new Error(`upstream proxy CONNECT ${target} rejected: ${statusLine}`));
        socket.destroy();
        return;
      }

      settled = true;
      cleanup();
      resolve(buffered.subarray(end + 4));
    };

    socket.on('data', onData);
    socket.once('error', onError);
    socket.once('close', onClose);
    socket.write(
      `CONNECT ${target} HTTP/1.1\r\n` +
        `Host: ${target}\r\n` +
        `Proxy-Connection: keep-alive\r\n\r\n`
    );
  });
}

async function openViaProxy(upstream, egress, timeoutMs) {
  const socket = await connectTcp(egress.proxyHost, egress.proxyPort, timeoutMs);
  try {
    const leftover = await proxyConnect(
      socket,
      `${upstream.hostname}:${upstream.port}`,
      timeoutMs
    );
    if (upstream.protocol === 'https:') {
      return await tlsWrap(socket, upstream.hostname, timeoutMs, leftover);
    }
    if (leftover.length) socket.unshift(leftover);
    return socket;
  } catch (err) {
    socket.destroy();
    throw err;
  }
}

async function openDirect(upstream, egress, timeoutMs) {
  if (upstream.protocol === 'https:') {
    return tlsConnectDirect(upstream.hostname, upstream.port, timeoutMs);
  }
  return connectTcp(upstream.hostname, upstream.port, timeoutMs);
}

async function openUpstreamSocket(upstream, mode, egress) {
  if (mode === 'direct') {
    return openDirect(upstream, egress, egress.connectTimeoutMs);
  }
  if (mode === 'proxy') {
    return openViaProxy(upstream, egress, egress.connectTimeoutMs);
  }

  // auto: prefer the upstream proxy, but do not let it block Codex.
  try {
    return await openViaProxy(
      upstream,
      egress,
      Math.min(egress.connectTimeoutMs, egress.autoProbeMs)
    );
  } catch (err) {
    log(
      `egress auto: upstream proxy ${egress.proxyHost}:${egress.proxyPort} unavailable ` +
        `(${err.message}); falling back to direct`
    );
    return openDirect(upstream, egress, egress.connectTimeoutMs);
  }
}

// ---------------------------------------------------------------------------
// request rewriting
// ---------------------------------------------------------------------------

function outputToText(output) {
  if (typeof output === 'string') return output;
  if (Array.isArray(output)) {
    return output
      .map((part) => (part && typeof part === 'object' ? part.text : String(part ?? '')))
      .filter((s) => s.length > 0)
      .join('\n');
  }
  if (output && typeof output === 'object') {
    if (typeof output.text === 'string') return output.text;
    try {
      return JSON.stringify(output);
    } catch (_) {
      return String(output);
    }
  }
  return String(output ?? '');
}

/**
 * Mutates a parsed Responses request body. Returns the number of synthetic
 * function_call_output items that were rewritten into user messages.
 */
function rewriteBody(obj) {
  let changed = 0;
  if (!obj || !Array.isArray(obj.input)) return changed;

  const out = [];
  for (const item of obj.input) {
    const isSyntheticOutput =
      item &&
      typeof item === 'object' &&
      item.type === 'function_call_output' &&
      (item.call_id === undefined || item.call_id === null || item.call_id === '');

    if (!isSyntheticOutput) {
      out.push(item);
      continue;
    }

    changed += 1;
    const nsName = item.namespace ? `${item.namespace}.` : '';
    const toolName = item.name ? `${nsName}${item.name}` : 'codex_app';
    const text = outputToText(item.output);
    out.push({
      type: 'message',
      role: 'user',
      content: [
        {
          type: 'input_text',
          text: `[Delegated task delivered by ${toolName}]\n${text}`,
        },
      ],
    });
  }

  obj.input = out;
  return changed;
}

// ---------------------------------------------------------------------------
// routing
// ---------------------------------------------------------------------------

function decodeProviderId(raw) {
  try {
    return decodeURIComponent(raw);
  } catch (_) {
    return raw;
  }
}

/**
 * Resolves the incoming request path to a provider route and the upstream path.
 * Two URL shapes are supported:
 *   /_p/<provider>/<original base path>/...  (written by manage.js; multi-provider)
 *   <original base path>/...                 (legacy single-provider form)
 */
function resolveTarget(rawUrl, state) {
  let url;
  try {
    url = new URL(rawUrl, 'http://callidfix.local');
  } catch (_) {
    return { error: 400, message: 'invalid request URL' };
  }

  const applied = state.applied || {};
  const ids = Object.keys(applied).filter((id) => isValidRoute(applied[id]));

  if (url.pathname.startsWith(PROVIDER_PREFIX)) {
    const rest = url.pathname.slice(PROVIDER_PREFIX.length);
    const slash = rest.indexOf('/');
    const rawId = slash === -1 ? rest : rest.slice(0, slash);
    const id = decodeProviderId(rawId);
    const route = applied[id];

    if (!isValidRoute(route)) {
      return {
        error: 404,
        message:
          `no active route for provider '${id}'. ` +
          `Run "node manage.js on" so manage.js adds it to state.json.`,
      };
    }

    const suffix = slash === -1 ? '' : rest.slice(slash);
    return {
      provider: id,
      route,
      // The proxied base_url keeps the provider's original path, so everything
      // after /_p/<provider> is already the upstream path.
      upstreamPath: (suffix || '/') + url.search,
    };
  }

  if (ids.length === 1) {
    const id = ids[0];
    return {
      provider: id,
      route: applied[id],
      // Legacy base_url already contains the provider's path prefix.
      upstreamPath: url.pathname + url.search,
    };
  }

  if (ids.length === 0) {
    return {
      error: 503,
      message:
        'codex-callid-fix has no active provider routes. ' +
        'Run "node manage.js on" and restart Codex Desktop.',
    };
  }

  return {
    error: 400,
    message:
      'multiple providers are proxied; use the /_p/<provider>/... base_url ' +
      'that manage.js wrote into config.toml',
  };
}

// ---------------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------------

function sendJson(res, status, obj) {
  const body = Buffer.from(JSON.stringify(obj), 'utf8');
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': String(body.length),
    'cache-control': 'no-store',
  });
  res.end(body);
}

function healthPayload() {
  const cfg = loadRuntimeConfig();
  const state = loadState();
  const listen = actualListen
    ? { host: actualListen.address, port: actualListen.port }
    : { host: cfg.listenHost, port: cfg.listenPort };
  const routes = [];
  for (const [id, route] of Object.entries(state.applied || {})) {
    if (!isValidRoute(route)) continue;
    try {
      const upstream = upstreamOf(route);
      routes.push({
        id,
        upstream: `${upstream.hostname}:${upstream.port}`,
        proxiedBaseUrl: route.proxiedBaseUrl || null,
        egress: routeEgress(route, cfg.egress),
      });
    } catch (_) {
      routes.push({ id, error: 'invalid originalBaseUrl' });
    }
  }
  return {
    ok: true,
    service: 'codex-callid-fix',
    version: VERSION,
    pid: process.pid,
    dataDir: DATA_DIR,
    enabled: state.enabled,
    listen,
    egress: cfg.egress,
    providers: routes,
  };
}

function createServer() {
  const server = http.createServer((req, res) => {
    const pathname = String(req.url || '').split('?')[0];

    if (req.method === 'GET' && pathname === '/__callidfix/health') {
      sendJson(res, 200, healthPayload());
      return;
    }

    const cfg = loadRuntimeConfig();
    const state = loadState();
    const target = resolveTarget(req.url || '/', state);

    if (target.error) {
      sendJson(res, target.error, {
        error: 'codex-callid-fix',
        message: target.message,
      });
      return;
    }

    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('error', (err) => {
      log(`client request read error: ${err.message}`);
      if (!res.headersSent) res.writeHead(400);
      res.end();
    });

    req.on('end', () => {
      let body = Buffer.concat(chunks);
      let rewrote = 0;
      const contentType = String(req.headers['content-type'] || '');
      const startedAt = Date.now();

      if (
        req.method === 'POST' &&
        contentType.includes('application/json') &&
        body.length > 0
      ) {
        try {
          const parsed = JSON.parse(body.toString('utf8'));
          rewrote = rewriteBody(parsed);
          if (rewrote > 0) {
            body = Buffer.from(JSON.stringify(parsed), 'utf8');
          }
        } catch (err) {
          log(`body JSON parse failed (${req.method} ${req.url}): ${err.message}`);
        }
      }

      let upstream;
      try {
        upstream = upstreamOf(target.route);
      } catch (err) {
        log(`invalid route for ${target.provider}: ${err.message}`);
        sendJson(res, 500, {
          error: 'codex-callid-fix invalid route',
          message: `provider ${target.provider} has an invalid originalBaseUrl in state.json`,
        });
        return;
      }
      const mode = routeEgress(target.route, cfg.egress);

      const headers = { ...req.headers };
      for (const h of [
        'host',
        'content-length',
        'transfer-encoding',
        'connection',
        'keep-alive',
        'proxy-connection',
        'proxy-authorization',
      ]) {
        delete headers[h];
      }
      headers.host = upstream.hostHeader;
      if (
        body.length > 0 ||
        req.method === 'POST' ||
        req.method === 'PUT' ||
        req.method === 'PATCH'
      ) {
        headers['content-length'] = String(body.length);
      }

      const agent = new http.Agent({ keepAlive: false, maxSockets: 1 });
      agent.createConnection = (options, callback) => {
        openUpstreamSocket(upstream, mode, cfg.egress).then(
          (socket) => callback(null, socket),
          (err) => callback(err)
        );
      };

      let upstreamRes = null;
      const upstreamReq = http.request(
        {
          host: upstream.hostname,
          port: upstream.port,
          method: req.method,
          path: target.upstreamPath,
          headers,
          agent,
        },
        (response) => {
          upstreamRes = response;
          const resHeaders = { ...response.headers };
          delete resHeaders['connection'];
          delete resHeaders['keep-alive'];
          delete resHeaders['transfer-encoding'];
          delete resHeaders['content-length'];

          res.writeHead(response.statusCode || 502, resHeaders);
          response.pipe(res);

          response.on('end', () => {
            log(
              `${req.method} ${target.upstreamPath} -> ${response.statusCode} ` +
                `(provider=${target.provider}, egress=${mode}, rewrote=${rewrote}, ` +
                `${Date.now() - startedAt}ms)`
            );
          });
          response.on('error', (err) => {
            log(`upstream response error (${target.provider}): ${err.message}`);
            res.destroy(err);
          });
        }
      );

      res.on('close', () => {
        if (!res.writableFinished) {
          try {
            upstreamReq.destroy();
          } catch (_) {
            /* ignore */
          }
        }
        agent.destroy();
      });

      upstreamReq.on('error', (err) => {
        log(
          `upstream error (${req.method} ${target.upstreamPath}, ` +
            `provider=${target.provider}, egress=${mode}): ${err.message}`
        );
        if (!res.headersSent) {
          sendJson(res, 502, {
            error: 'codex-callid-fix upstream error',
            message: err.message,
            provider: target.provider,
            egress: mode,
          });
        } else {
          res.destroy(err);
        }
      });

      if (body.length > 0) upstreamReq.write(body);
      upstreamReq.end();
    });
  });

  // Long agent turns / SSE streams must not be cut off by default timeouts.
  server.requestTimeout = 0;
  server.headersTimeout = 0;
  server.keepAliveTimeout = 0;
  return server;
}

// ---------------------------------------------------------------------------
// bootstrap
// ---------------------------------------------------------------------------

process.on('uncaughtException', (err) => {
  log(`uncaught exception: ${err && err.stack ? err.stack : err}`);
  process.exit(1);
});
process.on('unhandledRejection', (err) => {
  log(`unhandled rejection: ${err && err.stack ? err.stack : err}`);
});

const cfg = loadRuntimeConfig();
const state = loadState();
const server = createServer();

server.on('error', (err) => {
  if (err && err.code === 'EADDRINUSE') {
    log(
      `port ${cfg.listenPort} already in use; another instance is likely running ` +
        `(or another app owns the port).`
    );
    process.exit(1);
  }
  log(`server error: ${err.message}`);
  process.exit(1);
});

server.listen(cfg.listenPort, cfg.listenHost, () => {
  actualListen = server.address();
  const routes = Object.keys(state.applied || {});
  log(
    `codex-callid-fix v${VERSION} listening on http://${cfg.listenHost}:${cfg.listenPort} ` +
      `(egress=${cfg.egress.mode} ${cfg.egress.proxyHost}:${cfg.egress.proxyPort}; ` +
      `enabled=${state.enabled}; routes=${routes.length ? routes.join(',') : 'none'})`
  );
  if (!state.enabled || routes.length === 0) {
    log('no providers are proxied yet; run "node manage.js on" to apply config.toml');
  }
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    log(`received ${signal}; shutting down`);
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 1500).unref();
  });
}
