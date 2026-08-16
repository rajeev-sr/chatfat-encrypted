// src/app.js — the composition root: boot order, the banner, and shutdown.
'use strict';

const os = require('node:os');
const config = require('./config');
const log = require('./logger');
const pool = require('./db/pool');
const auth = require('./auth');
const rooms = require('./rooms');
const history = require('./messages/history');
const { repository } = require('./messages/repository');
const http = require('./transport/http');
const websocket = require('./transport/websocket');

let server = null;
let throttleSweep = null;
let shuttingDown = false;

function addresses() {
  const out = [['local', `http://localhost:${config.PORT}`]];
  for (const list of Object.values(os.networkInterfaces())) {
    for (const iface of list || []) {
      if (iface.family === 'IPv4' && !iface.internal) out.push(['lan', `http://${iface.address}:${config.PORT}`]);
    }
  }
  return out;
}

function banner() {
  log.raw('');
  log.raw('  ChatFat');
  for (const [label, url] of addresses()) log.raw(`    ${label.padEnd(6)} ${url}`);
  log.raw('');

  const accounts = config.AUTH_ENABLED
    ? `required — ${config.USE_POSTGRES ? 'postgres' : 'memory'}`
    : 'disabled — set DATABASE_URL to turn accounts on';
  const messages = config.PERSISTENCE_ENABLED
    ? `stored in ${repository.kind} · joining a room ${
        config.HISTORY_REPLAY > 0 ? `replays ${config.HISTORY_REPLAY}` : 'replays nothing'
      }`
    : 'in memory only — nothing is stored or replayed';
  const encryption = config.ENCRYPTION_ENABLED
    ? 'rooms may be locked — keys never reach the server'
    : 'disabled — rooms cannot be locked on this server';

  log.raw(`    accounts    ${accounts}`);
  log.raw(`    messages    ${messages}`);
  log.raw(`    encryption  ${encryption}`);
  log.raw('');
}

async function start() {
  if (config.PERSISTENCE_ENABLED) {
    // All-or-nothing. A configured database that cannot be reached must never
    // degrade silently into an unauthenticated server.
    try {
      if (config.USE_POSTGRES) await pool.migrate();
      await auth.store.init();
      await repository.init();
    } catch (err) {
      log.error('DATABASE_URL is set but the store could not be prepared:', err.message);
      log.error('Refusing to start unauthenticated. Fix the database or unset DATABASE_URL.');
      process.exit(1);
    }
  }

  const count = await rooms.loadRooms();
  log.info(`room directory ready — ${count} room${count === 1 ? '' : 's'}`);

  server = http.createServer();
  websocket.attach(server);

  server.on('error', (err) => {
    if (err.code === 'EADDRINUSE') {
      log.error(`port ${config.PORT} is already in use. Try: PORT=${config.PORT + 1} npm start`);
      process.exit(1);
    }
    log.error('http server error', err);
  });

  await new Promise((resolve) => server.listen(config.PORT, config.HOST, resolve));

  websocket.startHeartbeat();
  throttleSweep = setInterval(http.sweepThrottle, config.AUTH_WINDOW_MS);
  if (throttleSweep.unref) throttleSweep.unref();

  banner();
  return server;
}

// Idempotent: two signals in quick succession must not run this twice.
function shutdown(signal = 'shutdown') {
  if (shuttingDown) return;
  shuttingDown = true;
  log.info(`${signal} — closing down`);

  websocket.stopHeartbeat();
  if (throttleSweep) clearInterval(throttleSweep);
  history.clearAllTimers();
  rooms.directory.flushSync();

  // 1001 "server going away", so clients reconnect deliberately rather than
  // treating it as a crash.
  websocket.closeAll(1001, 'server going away');

  const finish = async () => {
    try {
      await repository.close();
      await auth.store.close();
      await pool.close();
    } catch (err) {
      log.warn('closing stores:', err.message);
    }
    if (server) server.close(() => process.exit(0));
    else process.exit(0);
  };
  finish();

  // A socket that refuses to close cannot hang the process.
  const backstop = setTimeout(() => process.exit(0), 1500);
  if (backstop.unref) backstop.unref();
}

module.exports = { start, shutdown, get server() { return server; } };
