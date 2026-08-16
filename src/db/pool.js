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

// The schema lives in src/db/migrations/*.sql, applied by src/db/migrate.js.
// `migrate` is required lazily for the same reason `pg` is: nothing on the
// no-database or memory path may reach it.
async function migrate() {
  getPool(); // fail fast with the friendly message if pg is missing
  return require('./migrate').run();
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
