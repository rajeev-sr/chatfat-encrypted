// test/auth.js — accounts. Runs with DATABASE_URL=memory and a deliberately
// raised AUTH_MAX_ATTEMPTS, because the limiter gets its own server below.
//
// Pointing DATABASE_URL at a real Postgres must run these same assertions
// unchanged.
'use strict';

const WebSocket = require('ws');
const { ok, eq, bail, report, startServer, client, sleep, post } = require('./harness');

const PORT = 8098;
const THROTTLE_PORT = 8096;

async function main() {
  const server = await startServer(PORT, {
    DATABASE_URL: 'memory',
    AUTH_MAX_ATTEMPTS: '500',
    HEARTBEAT_MS: '2000',
  });

  // ── the server announces its policy before anything is attempted ─────────
  const health = await (await fetch(`http://127.0.0.1:${PORT}/healthz`)).json();
  eq(health.auth, 'memory', '/healthz reports the account store');
  eq(health.persistence, 'memory', 'and that messages are stored');

  const probe = await client(PORT);
  const hello = await probe.next('hello');
  eq(hello.d.auth, true, 'hello tells the client accounts are required');
  probe.close();

  // ── registration ─────────────────────────────────────────────────────────
  const weak = await post(PORT, '/auth/register', { username: 'kavya', password: 'short' });
  eq(weak.status, 400, 'a short password is refused');
  eq(weak.body.code, 'WEAK_PASSWORD', 'with WEAK_PASSWORD');

  const badName = await post(PORT, '/auth/register', { username: '!', password: 'correct-horse' });
  eq(badName.body.code, 'NAME_INVALID', 'a malformed name is refused');

  const reg = await post(PORT, '/auth/register', { username: 'kavya', password: 'correct-horse' });
  eq(reg.status, 200, 'registration succeeds');
  ok(typeof reg.body.token === 'string' && reg.body.token.length > 20, 'and returns a session token');
  eq(reg.body.user.name, 'kavya', 'and the account name');
  ok(reg.body.user.password === undefined, 'and never echoes the password back');

  const dupe = await post(PORT, '/auth/register', { username: 'KAVYA', password: 'another-one' });
  eq(dupe.status, 409, 'a duplicate name is refused case-insensitively');
  eq(dupe.body.code, 'NAME_TAKEN', 'with NAME_TAKEN');

  await post(PORT, '/auth/register', { username: 'meera', password: 'correct-horse-2' });

  // ── login ────────────────────────────────────────────────────────────────
  const good = await post(PORT, '/auth/login', { username: 'kavya', password: 'correct-horse' });
  eq(good.status, 200, 'a correct login succeeds');
  ok(good.body.token !== reg.body.token, 'and issues a fresh token each time');

  const wrong = await post(PORT, '/auth/login', { username: 'kavya', password: 'wrong-horse' });
  eq(wrong.status, 401, 'a wrong password is refused');
  eq(wrong.body.code, 'BAD_LOGIN', 'with BAD_LOGIN');

  const unknown = await post(PORT, '/auth/login', { username: 'nobody', password: 'wrong-horse' });
  eq(unknown.body.code, 'BAD_LOGIN', 'an unknown user gets the SAME code as a wrong password');
  eq(unknown.body.message, wrong.body.message, 'and the same message, so nothing is leaked');

  // ── timing parity: an unknown username must not be answered faster ───────
  const timeOf = async (username) => {
    const runs = [];
    for (let i = 0; i < 4; i++) {
      const t0 = process.hrtime.bigint();
      await post(PORT, '/auth/login', { username, password: 'wrong-horse-entirely' });
      runs.push(Number(process.hrtime.bigint() - t0) / 1e6);
    }
    runs.sort((x, y) => x - y);
    return runs[1]; // a low quantile, to shrug off scheduler noise
  };
  const knownMs = await timeOf('kavya');
  const unknownMs = await timeOf('ghost-user');
  // An unknown user burns a dummy scrypt, so the two must be within a factor
  // of ~2. Without wasteTime the unknown case is orders of magnitude faster.
  ok(unknownMs > knownMs * 0.4, `an unknown user is not answered faster (${knownMs.toFixed(0)}ms vs ${unknownMs.toFixed(0)}ms)`);

  // ── the wrong method, and an oversized body ──────────────────────────────
  const wrongMethod = await fetch(`http://127.0.0.1:${PORT}/auth/login`, { method: 'GET' });
  eq(wrongMethod.status, 405, 'the auth routes reject a non-POST');

  const huge = await fetch(`http://127.0.0.1:${PORT}/auth/login`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ username: 'kavya', password: 'x'.repeat(9000) }),
  });
  eq(huge.status, 400, 'an oversized body is refused rather than buffered');

  // ── the token on the socket ──────────────────────────────────────────────
  const a = await client(PORT);
  await a.next('hello');
  const noToken = await a.joinToken('not-a-real-token');
  eq(noToken.t, 'error', 'a bogus token cannot join');
  eq(noToken.d.code, 'UNAUTHORIZED', 'with UNAUTHORIZED, so the client drops it and shows sign-in');
  ok(a.ws.readyState === 1, 'and even that does not close the socket');

  const b = await client(PORT);
  await b.next('hello');
  const welcome = await b.joinToken(good.body.token);
  eq(welcome.t, 'welcome', 'a real token joins');
  eq(welcome.d.you.name, 'kavya', 'as the account it belongs to');

  // ── impersonation: a username in the payload is ignored ENTIRELY ─────────
  const meeraLogin = await post(PORT, '/auth/login', { username: 'meera', password: 'correct-horse-2' });
  const imposter = await client(PORT);
  await imposter.next('hello');
  imposter.send('join', { token: meeraLogin.body.token, username: 'kavya' });
  const impostorWelcome = await imposter.next('welcome');
  eq(impostorWelcome.d.you.name, 'meera', 'a username sent alongside a token is ignored — the account wins');

  // ── /nick renames the account, so it survives sign-out ───────────────────
  imposter.send('nick', { username: 'meera-lab' });
  const renamed = await imposter.next('you');
  eq(renamed.d.name, 'meera-lab', 'nick renames you');
  const relogin = await post(PORT, '/auth/login', { username: 'meera-lab', password: 'correct-horse-2' });
  eq(relogin.status, 200, 'and the rename reached the account, not just the session');
  const oldName = await post(PORT, '/auth/login', { username: 'meera', password: 'correct-horse-2' });
  eq(oldName.status, 401, 'so the old name no longer signs in');

  imposter.drain().send('nick', { username: 'kavya' });
  eq((await imposter.next('error')).d.code, 'NAME_TAKEN', 'and a rename onto a live name is refused');

  // ── sign-out revokes ─────────────────────────────────────────────────────
  const logout = await post(PORT, '/auth/logout', { token: good.body.token });
  eq(logout.status, 200, 'sign-out answers 200');
  eq(logout.body.ok, true, 'with ok');

  const revoked = await client(PORT);
  await revoked.next('hello');
  const afterLogout = await revoked.joinToken(good.body.token);
  eq(afterLogout.d.code, 'UNAUTHORIZED', 'and the token is dead afterwards');

  const unknownLogout = await post(PORT, '/auth/logout', { token: 'never-existed' });
  eq(unknownLogout.status, 200, 'signing out an unknown token is still 200 — it leaks nothing');

  // ── the Origin policy ────────────────────────────────────────────────────
  const badOrigin = await new Promise((resolve) => {
    const ws = new WebSocket(`ws://127.0.0.1:${PORT}/ws`, { headers: { Origin: 'http://evil.example' } });
    ws.on('open', () => { ws.close(); resolve('opened'); });
    ws.on('error', () => resolve('refused'));
  });
  eq(badOrigin, 'refused', 'a foreign Origin cannot open a socket');

  const goodOrigin = await new Promise((resolve) => {
    const ws = new WebSocket(`ws://127.0.0.1:${PORT}/ws`, { headers: { Origin: `http://127.0.0.1:${PORT}` } });
    ws.on('open', () => { ws.close(); resolve('opened'); });
    ws.on('error', () => resolve('refused'));
  });
  eq(goodOrigin, 'opened', 'the Origin it dialled is allowed');

  a.close(); b.close(); imposter.close(); revoked.close();
  await sleep(150);
  server.stop();

  // ── the brute-force throttle, on its own server ──────────────────────────
  const throttled = await startServer(THROTTLE_PORT, { DATABASE_URL: 'memory', AUTH_MAX_ATTEMPTS: '5' });
  await post(THROTTLE_PORT, '/auth/register', { username: 'target', password: 'correct-horse' });
  let sawLimit = null;
  for (let i = 0; i < 12; i++) {
    const attempt = await post(THROTTLE_PORT, '/auth/login', { username: 'target', password: 'guess-' + i });
    if (attempt.status === 429) { sawLimit = attempt; break; }
  }
  ok(sawLimit !== null, 'repeated failures are throttled per IP');
  eq(sawLimit && sawLimit.body.code, 'RATE_LIMIT', 'with RATE_LIMIT');
  const stillThrottled = await post(THROTTLE_PORT, '/auth/login', { username: 'target', password: 'correct-horse' });
  eq(stillThrottled.status, 429, 'and the throttle is checked BEFORE the password, so it cannot be worked around');
  throttled.stop();

  report('auth');
}

main().catch(bail);
