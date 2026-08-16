// src/transport/http.js — static file serving, /healthz, the /auth/* routes,
// and the per-IP login throttle.
'use strict';

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const config = require('../config');
const log = require('../logger');
const { hub } = require('../state/hub');
const auth = require('../auth');
const { repository } = require('../messages/repository');

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
};

// — login throttle: scrypt is deliberately expensive, so an unthrottled
//   endpoint burns CPU as readily as it leaks passwords. Checked BEFORE the
//   body is parsed.
const attempts = new Map(); // ip -> { n, until }

function throttled(ip) {
  const now = Date.now();
  const rec = attempts.get(ip);
  if (!rec || rec.until <= now) {
    attempts.set(ip, { n: 1, until: now + config.AUTH_WINDOW_MS });
    return false;
  }
  rec.n++;
  return rec.n > config.AUTH_MAX_ATTEMPTS;
}

function sweepThrottle() {
  const now = Date.now();
  for (const [ip, rec] of attempts) if (rec.until <= now) attempts.delete(ip);
}

function json(res, status, body) {
  const raw = JSON.stringify(body);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    'content-length': Buffer.byteLength(raw),
  });
  res.end(raw);
}

// 4 KB cap. An unbounded read lets one request buffer the process to death.
function readBody(req, limit = 4096) {
  return new Promise((resolve, reject) => {
    let size = 0;
    let over = false;
    const chunks = [];
    req.on('data', (c) => {
      if (over) return; // keep draining so the response can still be written
      size += c.length;
      if (size > limit) {
        over = true;
        chunks.length = 0;
        reject(new Error('too large'));
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => {
      if (over) return;
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'));
      } catch {
        reject(new Error('unparseable'));
      }
    });
    req.on('error', reject);
  });
}

function serveStatic(req, res, pathname) {
  const rel = pathname === '/' ? '/index.html' : pathname;
  // Normalise FIRST, then check — a crafted path escapes the directory otherwise.
  const target = path.join(config.PUBLIC_DIR, path.normalize(rel));
  if (target !== config.PUBLIC_DIR && !target.startsWith(config.PUBLIC_DIR + path.sep)) {
    res.writeHead(403).end('Forbidden');
    return;
  }
  fs.readFile(target, (err, data) => {
    if (err) {
      res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' }).end('Not found');
      return;
    }
    res.writeHead(200, {
      'content-type': TYPES[path.extname(target).toLowerCase()] || 'application/octet-stream',
      'cache-control': 'no-cache',
      'content-length': data.length,
    });
    res.end(data);
  });
}

function healthz() {
  let sockets = 0;
  let users = 0;
  let lockedRooms = 0;
  for (const s of hub.clients.values()) {
    sockets++;
    if (s.named) users++;
  }
  for (const r of hub.rooms.values()) if (r.locked) lockedRooms++;
  const mem = process.memoryUsage();
  return {
    ok: true,
    users,
    sockets,
    rooms: hub.rooms.size,
    uptime: Math.round((Date.now() - hub.startedAt) / 1000),
    auth: config.AUTH_ENABLED ? (config.USE_POSTGRES ? 'postgres' : 'memory') : 'disabled',
    persistence: config.PERSISTENCE_ENABLED ? repository.kind : 'nothing',
    // Reported separately from `persistence` on purpose: a server can record
    // every message and still hand a joining client nothing.
    historyReplay: config.HISTORY_REPLAY,
    encryption: config.ENCRYPTION_ENABLED,
    lockedRooms,
    memory: { rss: mem.rss, heapUsed: mem.heapUsed },
  };
}

async function handleAuth(req, res, pathname, ip) {
  if (!config.AUTH_ENABLED) {
    return json(res, 404, { code: 'DISABLED', message: 'This server does not keep accounts.' });
  }
  if (req.method !== 'POST') {
    return json(res, 405, { code: 'BAD_REQUEST', message: 'POST only.' });
  }
  if (throttled(ip)) {
    return json(res, 429, { code: 'RATE_LIMIT', message: 'Too many attempts. Wait a minute.' });
  }

  let body;
  try {
    body = await readBody(req);
  } catch {
    return json(res, 400, { code: 'BAD_REQUEST', message: 'Could not read that request.' });
  }

  try {
    if (pathname === '/auth/logout') {
      await auth.logout(body.token);
      return json(res, 200, { ok: true }); // always 200, even for an unknown token
    }
    const fn = pathname === '/auth/register' ? auth.register : auth.login;
    const result = await fn(body.username, body.password);
    if (result.error) {
      const status =
        { NAME_TAKEN: 409, WEAK_PASSWORD: 400, NAME_INVALID: 400, BAD_LOGIN: 401, UNAVAILABLE: 503 }[
          result.error.code
        ] || 400;
      return json(res, status, result.error);
    }
    return json(res, 200, { token: result.token, user: { name: result.user.name } });
  } catch (err) {
    log.error('auth route failed:', err.message);
    return json(res, 503, { code: 'UNAVAILABLE', message: 'The account store could not be reached.' });
  }
}

function createServer() {
  return http.createServer((req, res) => {
    const { pathname } = new URL(req.url, 'http://localhost');
    const ip = (req.headers['x-forwarded-for'] || '').split(',')[0].trim() || req.socket.remoteAddress || 'unknown';

    if (pathname === '/healthz') return json(res, 200, healthz());
    if (pathname.startsWith('/auth/')) return handleAuth(req, res, pathname, ip);
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      return json(res, 405, { code: 'BAD_REQUEST', message: 'GET only.' });
    }
    return serveStatic(req, res, pathname);
  });
}

module.exports = { createServer, healthz, sweepThrottle, attempts };
