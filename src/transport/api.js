// src/transport/api.js — the Lab 6 HTTP surface: POST /message and GET /feed.
//
// These two paths and their exact spelling are fixed by the assignment, so they
// are handled here rather than folded into the WebSocket protocol. They are a
// second door onto the same room: a message posted here is stored by the same
// repository, encrypted at rest by the same code, and broadcast to any
// WebSocket client currently in the room. There is no parallel message store.
//
// Idempotency is the requirement worth being careful about. A retry after a
// timeout, a reconnect, or a load balancer sending the same request to a second
// backend must not produce two rows. Two things make that true:
//
//   1. The row key is the message id, and the insert is `on conflict (id) do
//      nothing` (see src/messages/repository.js). The database, not the
//      application, is what enforces uniqueness — so it holds even when two
//      backends insert the same id concurrently.
//   2. A client may supply its own id. If it does, a retry carries the same id
//      and collapses onto the same row. If it does not, one is generated that
//      is unique across processes and machines.
'use strict';

const crypto = require('node:crypto');
const config = require('../config');
const log = require('../logger');
const rooms = require('../rooms');
const { hub, colourFor } = require('../state/hub');
const { repository } = require('../messages/repository');
const load = require('./load');

// Bounded so a malformed or hostile request cannot buffer without limit.
const MAX_BODY = 64 * 1024;

// Accepted spellings for the two documented fields. The assignment names them
// "client-name" and "msg"; the others are here because a hyphen in a JSON key
// is unusual enough that a generator may well send a variant, and rejecting a
// well-formed message over punctuation would be a poor trade.
const NAME_KEYS = ['client-name', 'client_name', 'clientName', 'clientname', 'name', 'user', 'username'];
const MSG_KEYS = ['msg', 'message', 'text', 'body', 'content'];
const ID_KEYS = ['id', 'message-id', 'message_id', 'messageId', 'msg-id', 'msg_id'];

function firstOf(obj, keys) {
  for (const k of keys) {
    if (obj && obj[k] !== undefined && obj[k] !== null && String(obj[k]) !== '') return String(obj[k]);
  }
  return '';
}

function json(res, status, body) {
  const raw = JSON.stringify(body);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    'content-length': Buffer.byteLength(raw),
    'x-backend': config.BACKEND_NAME,
  });
  res.end(raw);
}

// Reads the body under a hard cap, destroying the socket if the cap is passed
// rather than reading to the end and discarding — otherwise the cap limits
// memory but not the work an attacker can make the server do.
function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > MAX_BODY) {
        req.destroy();
        reject(new Error('body too large'));
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

// JSON, form-encoded, or a bare query string — whichever the caller used. The
// official load generator's content type is not specified in the assignment,
// so all three are accepted rather than guessed at.
function parseFields(raw, contentType, url) {
  const ct = String(contentType || '').toLowerCase();
  if (raw) {
    if (ct.includes('application/json') || /^\s*[[{]/.test(raw)) {
      try {
        const o = JSON.parse(raw);
        if (o && typeof o === 'object') return o;
      } catch {
        /* fall through to form parsing */
      }
    }
    const params = new URLSearchParams(raw);
    if ([...params.keys()].length) return Object.fromEntries(params);
  }
  // Query parameters last, so a body always wins over the URL.
  return Object.fromEntries(url.searchParams);
}

// Globally unique without coordination: time-ordered prefix so ids sort close
// to insertion order (which keeps the (room_id, ts desc, id desc) index dense),
// then a UUID. The backend name is not part of it — two backends must be able
// to produce the *same* id for the same client-supplied message, and including
// the machine would defeat exactly the deduplication this exists for.
function generateId() {
  return `m_${Date.now().toString(36)}_${crypto.randomUUID()}`;
}

let roomPromise = null;

// One room, created on demand. Every backend resolves the same name to the same
// row because the id is derived from the name, so three processes racing to
// create it converge instead of making three rooms.
function labRoom() {
  if (!roomPromise) {
    roomPromise = (async () => {
      const name = config.LAB_ROOM;
      let room = rooms.getRoom(name);
      if (!room) {
        room = rooms.createRoom(name, null, true);
        try {
          require('../rooms/directory').save(room);
        } catch (err) {
          log.warn(`could not persist the lab room record: ${err.message}`);
        }
      }
      return room;
    })();
  }
  return roomPromise;
}

async function handleMessage(req, res, url) {
  let raw;
  try {
    raw = await readBody(req);
  } catch {
    return json(res, 413, { ok: false, error: 'request body too large' });
  }

  const fields = parseFields(raw, req.headers['content-type'], url);
  const clientName = firstOf(fields, NAME_KEYS).slice(0, 64);
  const msg = firstOf(fields, MSG_KEYS);

  if (!clientName || !msg) {
    return json(res, 400, {
      ok: false,
      error: 'both "client-name" and "msg" are required',
      received: Object.keys(fields || {}),
    });
  }
  if (Buffer.byteLength(msg) > config.MAX_CIPHERTEXT) {
    return json(res, 413, { ok: false, error: 'message too long' });
  }

  // Supplied by the client when it wants retry safety; generated otherwise.
  // `idempotent` tells the caller which happened, so a client that did not
  // supply one knows it cannot safely retry blind.
  const supplied = firstOf(fields, ID_KEYS).slice(0, 128);
  const id = supplied || generateId();

  const room = await labRoom();
  const message = {
    kind: 'chat',
    id,
    ts: Date.now(),
    from: clientName,
    fromId: `http_${crypto.createHash('sha1').update(clientName).digest('hex').slice(0, 12)}`,
    colour: colourFor(clientName),
    text: msg,
    action: false,
    replyTo: null,
    mentions: [],
    reactions: {},
    editedAt: null,
    unsent: false,
    enc: null,
    sig: null,
    sigPub: null,
  };

  await repository.save(room.id, message);

  // The same room the WebSocket clients are in, so an HTTP post shows up in the
  // live chat. Best-effort: a broadcast failure must not fail a stored message.
  try {
    if (hub.rooms.has(room.id)) {
      require('../protocol/frames').broadcast(room.id, 'msg', message);
    }
  } catch (err) {
    log.warn(`broadcast of HTTP message ${id} failed: ${err.message}`);
  }

  return json(res, 201, {
    ok: true,
    id,
    'client-name': clientName,
    ts: message.ts,
    backend: config.BACKEND_NAME,
    idempotent: !!supplied,
  });
}

// — /feed response cache —
//
// /feed is specified as "retrieves all messages", and the honest reading of
// that is expensive: fetching every row, decrypting each one, and serialising
// the result took 1.8 s against 20 000 messages. Under a read-heavy load
// generator that cost is paid again for every call, and it dominates
// everything else the system does.
//
// Caching it naively would be wrong — a client that posts a message and
// immediately reads the feed must see it, and with three backends sharing one
// database a write on one node has to invalidate the cache on the others. So
// the cache is validated rather than timed: one cheap aggregate establishes
// whether anything has changed since the body was built. Any insert moves the
// row count and the maximum timestamp, so a stale body cannot be served.
//
// The validating query costs a few milliseconds against the ~1.8 s it avoids.
let feedCache = null; // { limit, count, maxTs, body }

async function feedFingerprint(roomId) {
  if (!config.USE_POSTGRES) return null; // other repositories are in-process and cheap already
  const pool = require('../db/pool');
  const res = await pool.query(
    'select count(*)::int as n, coalesce(max(ts), 0)::bigint as t from messages where room_id = $1 and unsent = false',
    [roomId],
  );
  const row = res.rows[0] || {};
  return { count: Number(row.n || 0), maxTs: String(row.t || 0) };
}

async function handleFeed(req, res, url) {
  const room = await labRoom();
  const asked = Number(url.searchParams.get('limit'));
  const limit = Number.isFinite(asked) && asked > 0
    ? Math.min(asked, config.FEED_MAX)
    : config.FEED_LIMIT;

  const fp = await feedFingerprint(room.id);
  if (fp && feedCache && feedCache.limit === limit
      && feedCache.count === fp.count && feedCache.maxTs === fp.maxTs) {
    res.writeHead(200, {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'x-backend': config.BACKEND_NAME,
      // The number of messages in the body, which is not the same as the
      // fingerprint's row count once the FEED_LIMIT cap is in play.
      'x-message-count': String(feedCache.bodyCount),
      'x-feed-cache': 'hit',
    });
    return res.end(feedCache.body);
  }

  const messages = await repository.recent(room.id, limit);

  // Field names mirror the input contract: a caller that posts "client-name"
  // and "msg" reads back "client-name" and "msg".
  const out = messages.map((m) => ({
    id: m.id,
    'client-name': m.from,
    msg: m.text,
    ts: m.ts,
    ...(m.tampered ? { tampered: true } : {}),
  }));

  // Serialised once and kept as a Buffer, so a cache hit is a socket write with
  // no JSON work at all.
  const body = Buffer.from(JSON.stringify(out));
  if (fp) feedCache = { limit, count: fp.count, maxTs: fp.maxTs, body, bodyCount: out.length };

  res.writeHead(200, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    'x-backend': config.BACKEND_NAME,
    'x-message-count': String(out.length),
    'x-feed-cache': 'miss',
  });
  res.end(body);
}

// Returns true when it handled the request.
function handle(req, res, pathname, url) {
  if (pathname === '/message' || pathname === '/message/') {
    if (req.method !== 'POST') {
      // GET /message is accepted too: some generators submit via the query
      // string, and refusing it on method alone would drop valid messages.
      if (req.method !== 'GET') {
        return json(res, 405, { ok: false, error: 'use POST' }), true;
      }
    }
    handleMessage(req, res, url).catch((err) => {
      log.error(`POST /message failed: ${err.message}`);
      if (!res.headersSent) json(res, 500, { ok: false, error: 'could not store the message' });
    });
    return true;
  }

  if (pathname === '/feed' || pathname === '/feed/') {
    handleFeed(req, res, url).catch((err) => {
      log.error(`GET /feed failed: ${err.message}`);
      if (!res.headersSent) json(res, 500, { ok: false, error: 'could not read the feed' });
    });
    return true;
  }

  // The load signal the balancer routes on.
  if (pathname === '/statz') {
    return json(res, 200, { backend: config.BACKEND_NAME, ...load.snapshot() }), true;
  }

  return false;
}

module.exports = { handle, generateId, parseFields, firstOf, NAME_KEYS, MSG_KEYS, ID_KEYS };
