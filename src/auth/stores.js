// src/auth/stores.js — MemoryStore | PgStore behind one interface.
//
// Both must pass test/auth.js unchanged: pointing DATABASE_URL at a real
// Postgres runs the same 22 assertions as `DATABASE_URL=memory`.
'use strict';

const config = require('../config');
const pool = require('../db/pool');

// — memory —

class MemoryStore {
  constructor() {
    this.users = new Map(); // name_lower -> { id, name, pass }
    this.byId = new Map();
    this.sessions = new Map(); // token -> { userId, expiresAt }
    this.seq = 1;
  }

  async init() {}

  async findByName(name) {
    return this.users.get(String(name).toLowerCase()) || null;
  }

  async findById(id) {
    return this.byId.get(id) || null;
  }

  async createUser(name, pass) {
    const key = name.toLowerCase();
    if (this.users.has(key)) return null;
    const user = { id: this.seq++, name, pass };
    this.users.set(key, user);
    this.byId.set(user.id, user);
    return user;
  }

  async renameUser(id, name) {
    const user = this.byId.get(id);
    if (!user) return false;
    const key = name.toLowerCase();
    const clash = this.users.get(key);
    if (clash && clash.id !== id) return false;
    this.users.delete(user.name.toLowerCase());
    user.name = name;
    this.users.set(key, user);
    return true;
  }

  async createSession(token, userId, expiresAt) {
    this.sessions.set(token, { userId, expiresAt });
  }

  async findSession(token) {
    const s = this.sessions.get(token);
    if (!s) return null;
    if (s.expiresAt <= Date.now()) {
      this.sessions.delete(token); // expired tokens are deleted lazily on lookup
      return null;
    }
    return this.byId.get(s.userId) || null;
  }

  async revokeSession(token) {
    this.sessions.delete(token);
  }

  async close() {}
}

// — postgres —

class PgStore {
  async init() {}

  async findByName(name) {
    const r = await pool.query('select id, name, pass from users where name_lower = $1', [String(name).toLowerCase()]);
    return r.rows[0] || null;
  }

  async findById(id) {
    const r = await pool.query('select id, name, pass from users where id = $1', [id]);
    return r.rows[0] || null;
  }

  async createUser(name, pass) {
    try {
      const r = await pool.query(
        'insert into users (name, name_lower, pass) values ($1, $2, $3) returning id, name, pass',
        [name, name.toLowerCase(), pass],
      );
      return r.rows[0];
    } catch (err) {
      if (err && err.code === '23505') return null; // unique violation
      throw err;
    }
  }

  async renameUser(id, name) {
    try {
      const r = await pool.query('update users set name = $1, name_lower = $2 where id = $3', [
        name,
        name.toLowerCase(),
        id,
      ]);
      return r.rowCount > 0;
    } catch (err) {
      if (err && err.code === '23505') return false;
      throw err;
    }
  }

  async createSession(token, userId, expiresAt) {
    await pool.query('insert into sessions (token, user_id, expires_at) values ($1, $2, to_timestamp($3 / 1000.0))', [
      token,
      userId,
      expiresAt,
    ]);
  }

  async findSession(token) {
    // Filtered by expiry in SQL, so an expired row can never authenticate.
    const r = await pool.query(
      `select u.id, u.name, u.pass from sessions s
         join users u on u.id = s.user_id
        where s.token = $1 and s.expires_at > now()`,
      [token],
    );
    return r.rows[0] || null;
  }

  async revokeSession(token) {
    await pool.query('delete from sessions where token = $1', [token]);
  }

  async close() {}
}

function createStore() {
  return config.USE_POSTGRES ? new PgStore() : new MemoryStore();
}

module.exports = { createStore, MemoryStore, PgStore };
