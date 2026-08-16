// test/postgres.js — the suite that needs a real database.
//
// Everything else runs offline against `memory`, deliberately: a suite that
// needs network is a suite that stops being run. This one is the exception,
// because two things cannot be proved without durable storage —
//
//   1. that messages survive a server restart, which is Lab 4 requirement 1
//      and the direct answer to slide 2's "what happens if the server
//      restarts?"
//   2. that the migration runner is idempotent across boots.
//
// Set TEST_DATABASE_URL to run it. Skipped, loudly, when it is absent.
//
//   docker compose up -d db
//   TEST_DATABASE_URL=postgresql://chatfat:chatfat@localhost:5432/chatfat npm run test:pg
//
// In CI, point it at a Neon branch created for the run.
'use strict';

const { ok, eq, bail, report, startServer, client, sleep, post } = require('./harness');

const PORT = 8087;
const URL = process.env.TEST_DATABASE_URL;

async function signedIn(port, name, password) {
  const reg = await post(port, '/auth/register', { username: name, password });
  const c = await client(port);
  await c.next('hello');
  await c.joinToken(reg.body.token);
  return c;
}

// Every run starts from an empty schema, so a previous run's rows cannot make
// this one pass or fail for the wrong reason.
async function reset() {
  const { Client } = require('pg');
  const c = new Client({ connectionString: URL });
  await c.connect();
  await c.query(`
    drop table if exists messages cascade;
    drop table if exists rooms cascade;
    drop table if exists sessions cascade;
    drop table if exists users cascade;
    drop table if exists schema_version cascade;
  `);
  await c.end();
}

async function main() {
  if (!URL) {
    console.log('postgres: SKIPPED — set TEST_DATABASE_URL to run this suite');
    console.log('  docker compose up -d db');
    console.log('  TEST_DATABASE_URL=postgresql://chatfat:chatfat@localhost:5432/chatfat npm run test:pg');
    return;
  }

  await reset();

  // ── first boot: migrations apply from empty ──────────────────────────────
  const first = await startServer(PORT, {
    DATABASE_URL: URL,
    HISTORY_REPLAY: '50',
    AUTH_MAX_ATTEMPTS: '500',
  });

  ok(first.out().includes('migration applied — 001_init'), 'migrations apply on an empty database');

  const health = await (await fetch(`http://127.0.0.1:${PORT}/healthz`)).json();
  eq(health.persistence, 'postgres', '/healthz reports postgres');

  const a = await signedIn(PORT, 'kavya', 'correct-horse');
  await a.create('durable');

  a.drain().send('chat', { text: 'written before the restart' });
  const before = (await a.next('chat')).d;
  await sleep(400); // the write is detached from the hot path

  a.close();
  await sleep(200);
  first.stop();
  await sleep(600); // let the port free up

  // ── second boot: the messages are still there ────────────────────────────
  // This is the assertion the whole phase exists for.
  const second = await startServer(PORT, {
    DATABASE_URL: URL,
    HISTORY_REPLAY: '50',
    AUTH_MAX_ATTEMPTS: '500',
  });

  ok(!second.out().includes('migration applied'), 'a second boot applies no migrations');
  ok(second.out().includes('schema already at version'), 'and says the schema is already current');

  const b = await signedIn(PORT, 'meera', 'correct-horse-2');
  const joined = await b.enter('durable');

  ok(Array.isArray(joined.d.history), 'history is replayed after a restart');
  const survivor = joined.d.history.find((m) => m.id === before.id);
  ok(survivor, 'the message written before the restart is still there');
  eq(survivor && survivor.text, 'written before the restart', 'with its text intact');
  eq(survivor && survivor.from, 'kavya', 'and its sender');

  // ── the room survived too ────────────────────────────────────────────────
  // Losing the directory while keeping the messages would orphan every row.
  eq(joined.d.room.id, 'durable', 'the room created before the restart still exists');

  b.close();
  await sleep(200);
  second.stop();

  report('postgres');
}

main().catch(bail);
