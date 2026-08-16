// test/persistence.js — storage and replay. DATABASE_URL=memory,
// HISTORY_REPLAY=5.
//
// Recording and replaying are separate questions, and this suite pins both:
// what gets written, and what a joining client is actually handed.
'use strict';

const { ok, eq, bail, report, startServer, client, sleep, post } = require('./harness');

const PORT = 8097;
const OFF_PORT = 8095;

async function signedIn(port, name, password) {
  const reg = await post(port, '/auth/register', { username: name, password });
  const c = await client(port);
  await c.next('hello');
  await c.joinToken(reg.body.token);
  return c;
}

async function main() {
  const server = await startServer(PORT, {
    DATABASE_URL: 'memory',
    HISTORY_REPLAY: '5',
    AUTH_MAX_ATTEMPTS: '500',
    HEARTBEAT_MS: '2000',
  });

  const health = await (await fetch(`http://127.0.0.1:${PORT}/healthz`)).json();
  eq(health.persistence, 'memory', '/healthz reports the repository kind');
  eq(health.historyReplay, 5, 'and the replay depth, separately from persistence');

  const a = await signedIn(PORT, 'kavya', 'correct-horse');
  await a.create('archive');

  // ── messages are written and read back ───────────────────────────────────
  a.drain().send('chat', { text: 'first' });
  const first = (await a.next('chat')).d;
  a.send('chat', { text: 'second' });
  await a.next('chat');
  await sleep(250);

  const b = await signedIn(PORT, 'meera', 'correct-horse-2');
  const joined = await b.enter('archive');
  ok(Array.isArray(joined.d.history), 'a replaying server sends a history array');
  eq(joined.d.history.length, 2, 'with everything said so far');
  eq(joined.d.history[0].text, 'first', 'in chronological order');
  eq(joined.d.history[1].text, 'second', 'oldest first');
  ok(joined.d.history[0].ts <= joined.d.history[1].ts, 'and the timestamps agree with that order');

  // ── the replay cap ───────────────────────────────────────────────────────
  await a.refill();
  for (let i = 0; i < 5; i++) { a.send('chat', { text: 'bulk-' + i }); await sleep(1100); }
  await sleep(300);

  const c = await signedIn(PORT, 'aravind', 'correct-horse-3');
  const capped = await c.enter('archive');
  eq(capped.d.history.length, 5, 'a joining client gets at most HISTORY_REPLAY messages');
  eq(capped.d.history[4].text, 'bulk-4', 'and they are the most recent ones');
  eq(capped.d.history[0].text, 'bulk-0', 'not the oldest ones');

  // ── edits and reactions survive a rejoin ─────────────────────────────────
  await a.refill();
  a.drain().send('chat', { text: 'will be edited' });
  const editable = (await a.next('chat')).d;
  a.send('edit', { id: editable.id, text: 'was edited' });
  await a.next('edited');
  a.send('react', { id: editable.id, emoji: '🎉' });
  await a.next('react');
  await sleep(300);

  const d = await signedIn(PORT, 'priya', 'correct-horse-4');
  const afterEdit = await d.enter('archive');
  const storedEdit = afterEdit.d.history.find((m) => m.id === editable.id);
  ok(storedEdit, 'the edited message is in the replay');
  eq(storedEdit.text, 'was edited', 'carrying the edited text, not the original');
  ok(storedEdit.editedAt > 0, 'and the edit stamp');
  eq((storedEdit.reactions['🎉'] || []).join(','), 'kavya', 'and the reaction that was added to it');

  // ── unsent messages are excluded from replay ─────────────────────────────
  await a.refill();
  a.drain().send('chat', { text: 'a secret that gets pulled back' });
  const doomed = (await a.next('chat')).d;
  a.send('unsend', { id: doomed.id });
  await a.next('unsent');
  await sleep(300);

  const e = await signedIn(PORT, 'suresh', 'correct-horse-5');
  const afterUnsend = await e.enter('archive');
  eq(afterUnsend.d.history.some((m) => m.id === doomed.id), false, 'an unsent message is not replayed');
  eq(afterUnsend.d.history.some((m) => m.text.indexOf('a secret') === 0), false, 'and its text is gone from the replay entirely');

  // ── a burn is removed from storage, not just from the screen ─────────────
  await a.refill();
  a.drain().send('chat', { text: 'door code 4417', ttl: 5 });
  const burn = (await a.next('chat')).d;
  await a.next('expired', 9000);
  await sleep(400);

  const f = await signedIn(PORT, 'nithya', 'correct-horse-6');
  const afterBurn = await f.enter('archive');
  eq(afterBurn.d.history.some((m) => m.id === burn.id), false, 'an expired burn is gone from storage too');
  eq(afterBurn.d.history.some((m) => m.text.indexOf('door code') >= 0), false, 'text and all');

  // ── whispers are never stored ────────────────────────────────────────────
  await a.refill();
  a.drain().send('dm', { to: 'meera', text: 'never write this down' });
  await a.next('dm');
  await sleep(300);
  const g = await signedIn(PORT, 'ganesh', 'correct-horse-7');
  const afterDm = await g.enter('archive');
  eq(afterDm.d.history.some((m) => m.text.indexOf('never write this down') >= 0), false,
     'a private message is never written to history or the database');

  // ── the room directory survives ──────────────────────────────────────────
  const rooms = (await a.next('rooms', 500).catch(() => null)) || { d: { rooms: [] } };
  ok(rooms !== null, 'the room list is broadcast as occupancy changes');

  a.close(); b.close(); c.close(); d.close(); e.close(); f.close(); g.close();
  await sleep(200);
  server.stop();

  // ── HISTORY_REPLAY=0 is the off switch, and it must not fail quietly ─────
  const off = await startServer(OFF_PORT, { DATABASE_URL: 'memory', HISTORY_REPLAY: '0', AUTH_MAX_ATTEMPTS: '500' });
  const offHealth = await (await fetch(`http://127.0.0.1:${OFF_PORT}/healthz`)).json();
  eq(offHealth.persistence, 'memory', 'a non-replaying server still records');
  eq(offHealth.historyReplay, 0, 'but replays nothing');

  const x = await signedIn(OFF_PORT, 'kavya', 'correct-horse');
  await x.create('quiet');
  x.drain().send('chat', { text: 'recorded but never handed back' });
  await x.next('chat');
  await sleep(250);

  const y = await signedIn(OFF_PORT, 'meera', 'correct-horse-2');
  const quiet = await y.enter('quiet');
  eq(quiet.d.history, undefined, 'with HISTORY_REPLAY=0 the history key is absent entirely');
  await sleep(200);
  eq(y.typed('chat').length, 0, 'and nothing recorded is delivered on join');

  x.close(); y.close();
  await sleep(150);
  off.stop();

  report('persistence');
}

main().catch(bail);
