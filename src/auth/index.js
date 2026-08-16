// src/auth/index.js — scrypt hashing, credential validation, register/login.
//
// Accounts are off by default and turn on with DATABASE_URL. Both modes must work.
'use strict';

const crypto = require('node:crypto');
const config = require('../config');
const { createStore } = require('./stores');

const N = 16384;
const r = 8;
const p = 1;
const KEYLEN = 64;

const store = createStore();

function scrypt(password, salt) {
  return new Promise((resolve, reject) => {
    crypto.scrypt(password, salt, KEYLEN, { N, r, p, maxmem: 64 * 1024 * 1024 }, (err, key) =>
      err ? reject(err) : resolve(key),
    );
  });
}

// Self-describing, so the cost can be raised later without breaking old hashes.
async function hash(password) {
  const salt = crypto.randomBytes(16);
  const key = await scrypt(password, salt);
  return `scrypt$${N}$${r}$${p}$${salt.toString('base64')}$${key.toString('base64')}`;
}

async function verify(password, stored) {
  try {
    const parts = String(stored).split('$');
    if (parts.length !== 6 || parts[0] !== 'scrypt') return false;
    const [, sn, sr, sp, saltB64, keyB64] = parts;
    const salt = Buffer.from(saltB64, 'base64');
    const expected = Buffer.from(keyB64, 'base64');
    const got = await new Promise((resolve, reject) => {
      crypto.scrypt(
        password,
        salt,
        expected.length,
        { N: Number(sn), r: Number(sr), p: Number(sp), maxmem: 64 * 1024 * 1024 },
        (err, key) => (err ? reject(err) : resolve(key)),
      );
    });
    if (got.length !== expected.length) return false;
    return crypto.timingSafeEqual(got, expected);
  } catch {
    return false; // anything malformed is a failed login, never a throw
  }
}

// An unknown username burns one real hash before answering, so response time
// cannot be used to enumerate the account list.
const DUMMY = '$'.repeat(0) + 'chatfat-timing-parity-filler';
async function wasteTime() {
  await scrypt(DUMMY, Buffer.alloc(16, 7));
}

function checkCredentials(username, password) {
  if (typeof username !== 'string' || !config.NAME_RE.test(username.trim())) {
    return { code: 'NAME_INVALID', message: 'Names are 2–16 letters, numbers, spaces, _ . or -' };
  }
  if (typeof password !== 'string' || password.length < config.MIN_PASSWORD || password.length > config.MAX_PASSWORD) {
    return {
      code: 'WEAK_PASSWORD',
      message: `Passwords are ${config.MIN_PASSWORD}–${config.MAX_PASSWORD} characters.`,
    };
  }
  return null;
}

function newToken() {
  return crypto.randomBytes(32).toString('base64url');
}

async function register(username, password) {
  const bad = checkCredentials(username, password);
  if (bad) return { error: bad };

  const name = username.trim();
  const existing = await store.findByName(name);
  if (existing) return { error: { code: 'NAME_TAKEN', message: 'That name is already registered.' } };

  const user = await store.createUser(name, await hash(password));
  if (!user) return { error: { code: 'NAME_TAKEN', message: 'That name is already registered.' } };

  const token = newToken();
  await store.createSession(token, user.id, Date.now() + config.SESSION_TTL_MS);
  return { token, user: { id: user.id, name: user.name } };
}

async function login(username, password) {
  const bad = checkCredentials(username, password);
  if (bad) return { error: bad };

  const user = await store.findByName(String(username).trim());
  if (!user) {
    await wasteTime(); // timing parity with a wrong password
    return { error: { code: 'BAD_LOGIN', message: 'That name and password do not match.' } };
  }
  if (!(await verify(password, user.pass))) {
    return { error: { code: 'BAD_LOGIN', message: 'That name and password do not match.' } };
  }

  const token = newToken();
  await store.createSession(token, user.id, Date.now() + config.SESSION_TTL_MS);
  return { token, user: { id: user.id, name: user.name } };
}

async function logout(token) {
  if (typeof token === 'string' && token) await store.revokeSession(token);
  return { ok: true }; // always ok, even for an unknown token
}

async function resolveToken(token) {
  if (typeof token !== 'string' || !token) return null;
  return store.findSession(token);
}

module.exports = { store, hash, verify, register, login, logout, resolveToken, checkCredentials, newToken };
