// test/harness.js — a real spawned server and real WebSocket clients. There is
// no mocked clock anywhere in these suites: the heartbeat reaper and the burn
// fuse are real timers and the suites wait them out.
'use strict';

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const WebSocket = require('ws');

const PROTOCOL_VERSION = 2;

// — assertions —

let passed = 0;
const failures = [];

function ok(condition, label) {
  if (condition) {
    passed++;
    process.stdout.write('.');
  } else {
    failures.push(label);
    process.stdout.write('X');
  }
}

function eq(actual, expected, label) {
  ok(actual === expected, `${label} — expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}

// A suite that throws part-way still prints what it had learned, so one broken
// assertion never hides the twenty behind it.
function bail(err) {
  process.stdout.write('\n\n');
  for (const f of failures) console.log('  ✗ ' + f);
  console.error('\n' + err.stack);
  process.exit(1);
}

function report(name) {
  process.stdout.write('\n\n');
  if (failures.length) {
    console.log(`${name}: ${passed} passed, ${failures.length} FAILED`);
    for (const f of failures) console.log('  ✗ ' + f);
    process.exitCode = 1;
  } else {
    console.log(`${name}: ${passed} assertions passed`);
  }
  return failures.length === 0;
}

// — the server under test —

async function startServer(port, env = {}) {
  // Every suite gets an isolated DATA_DIR and ChatFat_ENV_FILE=off. Without
  // that, a developer's .env reaches the suite and assertions fail for the
  // wrong reason.
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'chatfat-test-'));
  const child = spawn(process.execPath, [path.join(__dirname, '..', 'server.js')], {
    // DATABASE_URL defaults to the explicit off switch, not to unset: since P1
    // an unset DATABASE_URL is a startup error, and a suite that wants no
    // persistence has to say so like everybody else. A suite that wants
    // storage overrides it through `env`.
    env: {
      ...process.env,
      ChatFat_ENV_FILE: 'off',
      PORT: String(port),
      HOST: '127.0.0.1',
      DATA_DIR: dataDir,
      DATABASE_URL: 'none',
      ...env,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let stdout = '';
  child.stdout.on('data', (b) => { stdout += b.toString(); });
  child.stderr.on('data', (b) => { stdout += b.toString(); });

  const stop = () => {
    try { child.kill('SIGKILL'); } catch {}
    try { fs.rmSync(dataDir, { recursive: true, force: true }); } catch {}
  };
  process.on('exit', stop);

  // Wait for the port to answer.
  const deadline = Date.now() + 15000;
  for (;;) {
    if (child.exitCode !== null) throw new Error('server exited early:\n' + stdout);
    try {
      const res = await fetch(`http://127.0.0.1:${port}/healthz`);
      if (res.ok) break;
    } catch {}
    if (Date.now() > deadline) throw new Error('server never came up:\n' + stdout);
    await sleep(80);
  }

  return { child, dataDir, stop, out: () => stdout, port };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// — clients —

function client(port, opts = {}) {
  return new Promise((resolve, reject) => {
    // `headers` carries the session cookie: since P3 the upgrade is what
    // authenticates, so a client that cannot send one cannot connect at all.
    const ws = new WebSocket(`ws://127.0.0.1:${port}/ws`, opts.headers ? { headers: opts.headers } : undefined);
    const c = {
      ws,
      frames: [],
      waiters: [],
      // A silent client never answers a ping — this is the pulled-cable case,
      // where no close event will ever arrive and only the reaper notices.
      silent: !!opts.silent,
      send(t, d) { ws.send(JSON.stringify({ v: PROTOCOL_VERSION, t, d: d || {} })); },
      close(code = 1000) { ws.close(code); },
      kill() { ws.terminate(); },
      // Wait for the next frame of any of these types (already-received ones
      // count). One waiter per call, resolved by exactly one frame — a
      // Promise.race here would strand the losing waiter, and the stranded one
      // would then swallow a later frame that somebody else is waiting for.
      nextAny(types, timeout = 6000) {
        const want = [].concat(types);
        const found = c.frames.find((f) => want.includes(f.t) && !f._taken);
        if (found) { found._taken = true; return Promise.resolve(found); }
        return new Promise((res, rej) => {
          const timer = setTimeout(() => {
            c.waiters = c.waiters.filter((w) => w.timer !== timer);
            rej(new Error(`timed out waiting for “${want.join('” or “')}”`));
          }, timeout);
          c.waiters.push({ want, res, timer });
        });
      },
      next(t, timeout = 6000) { return c.nextAny([t], timeout); },
      typed(t) { return c.frames.filter((f) => f.t === t); },
      // Mark everything received so far as consumed, so the next `next('error')`
      // cannot pick up a rate-limit frame left over from an earlier burst.
      drain() { c.frames.forEach((f) => { f._taken = true; }); return c; },
      // The bucket is burst 5 then 1/s, so a suite that wants a clean burst
      // waits for it rather than fighting it.
      refill() { return sleep(5200); },
      async join(username) {
        c.send('join', { username });
        return c.next('welcome');
      },
      async joinToken(token) {
        c.send('join', { token });
        return c.nextAny(['welcome', 'error']);
      },
      async enter(room) {
        c.send('room:join', { room });
        return c.next('room:joined');
      },
      async create(room, lock) {
        c.send('room:create', lock ? { room, lock } : { room });
        return c.next('room:joined');
      },
    };

    ws.on('message', (raw) => {
      let frame;
      try { frame = JSON.parse(raw.toString()); } catch { return; }
      c.frames.push(frame);
      if (frame.t === 'ping' && !c.silent) c.send('pong', { t: frame.d.t });
      const at = c.waiters.findIndex((w) => w.want.includes(frame.t));
      if (at >= 0) {
        const w = c.waiters.splice(at, 1)[0];
        clearTimeout(w.timer);
        frame._taken = true;
        w.res(frame);
      }
    });
    ws.on('open', () => resolve(c));
    ws.on('error', reject);
  });
}

async function post(port, route, body) {
  const res = await fetch(`http://127.0.0.1:${port}${route}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return { status: res.status, body: await res.json().catch(() => ({})) };
}

module.exports = { ok, eq, bail, report, startServer, client, sleep, post, PROTOCOL_VERSION };
