// src/db/pool.js — the single Postgres pool, plus schema migration.
//
// `pg` is required LAZILY, inside getPool(). A checkout without pg installed
// must still run in no-database and memory modes, and it does, because nothing
// on those paths ever reaches this line.
'use strict';

const config = require('../config');
const log = require('../logger');

let pool = null;

function getPool() {
  if (pool) return pool;
  if (!config.USE_POSTGRES) throw new Error('Postgres is not configured.');

  let pg;
  try {
    pg = require('pg');
  } catch {
    throw new Error("DATABASE_URL points at Postgres but the 'pg' package is not installed. Run: npm install pg");
  }

  pool = new pg.Pool({
    connectionString: config.DATABASE_URL,
    max: 10,
    idleTimeoutMillis: 30000,
    connectionTimeoutMillis: 8000,
  });

  // Mandatory. An unhandled error on an idle client is fatal to the process.
  pool.on('error', (err) => log.error('postgres idle client error', err.message));

  return pool;
}

const SCHEMA = `
create table if not exists users (
  id          serial primary key,
  name        text not null,
  name_lower  text not null unique,
  pass        text not null,
  created_at  timestamptz not null default now()
);

create table if not exists sessions (
  token      text primary key,
  user_id    integer not null references users(id) on delete cascade,
  expires_at timestamptz not null
);
create index if not exists sessions_user on sessions(user_id);

create table if not exists rooms (
  id         text primary key,
  name       text not null,
  created_at bigint,
  created_by text,
  permanent  boolean not null default false,
  locked     boolean not null default false,
  kdf        jsonb,
  verifier   text,
  key_epoch  integer not null default 0,
  locked_by  text,
  locked_at  bigint
);

create table if not exists messages (
  id         text primary key,
  room_id    text not null,
  ts         bigint not null,
  from_name  text,
  from_id    text,
  colour     integer,
  text       text not null default '',
  action     boolean not null default false,
  reply_to   jsonb,
  mentions   jsonb,
  reactions  jsonb,
  edited_at  bigint,
  unsent     boolean not null default false,
  expires_at bigint,
  enc_alg    text,
  enc_kid    integer,
  enc_n      text,
  enc_iv     text,
  enc_ct     text,
  enc_aadv   integer
);
create index if not exists messages_room_ts on messages(room_id, ts desc);
`;

async function migrate() {
  const p = getPool();
  await p.query(SCHEMA);
  log.info('postgres schema ready');
}

async function query(text, params) {
  return getPool().query(text, params);
}

async function close() {
  if (!pool) return;
  const p = pool;
  pool = null;
  try {
    await p.end();
  } catch (err) {
    log.warn('closing the pool:', err.message);
  }
}

module.exports = { getPool, migrate, query, close };
