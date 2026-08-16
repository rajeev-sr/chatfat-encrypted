// src/messages/repository.js — durable storage: Null | Memory | Pg behind one
// interface.
//
// Recording and replaying are separate questions. This module records; whether
// a joining client is handed anything is HISTORY_REPLAY's business, and it is 0
// by default. In a locked room what lands here is ciphertext, `text` is '', and
// nothing in a row is readable by the operator.
'use strict';

const config = require('../config');
const log = require('../logger');
const pool = require('../db/pool');

// Ordering is (ts, id), never ts alone. Two messages can share a millisecond —
// a burst of three from the same client routinely does — and a cursor that
// cannot break that tie will either skip a row or hand it back twice on the
// next page. `id` is monotonic within a millisecond because newId appends a
// counter, so it is a valid tie-break.
function byTsThenId(a, b) {
  return a.ts - b.ts || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

function olderThan(m, cursor) {
  return m.ts < cursor.ts || (m.ts === cursor.ts && m.id < cursor.id);
}

function encColumns(m) {
  const e = m.enc;
  return e
    ? [e.alg, e.kid, e.n, e.iv, e.ct, e.aadv]
    : [null, null, null, null, null, null];
}

function rowToMessage(row) {
  const enc = row.enc_alg
    ? { alg: row.enc_alg, kid: row.enc_kid, n: row.enc_n, iv: row.enc_iv, ct: row.enc_ct, aadv: row.enc_aadv }
    : null;
  return {
    kind: 'chat',
    id: row.id,
    ts: Number(row.ts),
    from: row.from_name,
    fromId: row.from_id,
    colour: row.colour,
    text: row.text || '',
    action: !!row.action,
    replyTo: row.reply_to || null,
    mentions: row.mentions || [],
    reactions: row.reactions || {},
    editedAt: row.edited_at === null || row.edited_at === undefined ? null : Number(row.edited_at),
    unsent: !!row.unsent,
    ...(row.expires_at ? { expiresAt: Number(row.expires_at) } : {}),
    enc,
  };
}

// — null: nothing is stored, nothing is replayed —

class NullRepo {
  constructor() {
    this.kind = 'nothing';
  }
  async init() {}
  async save() {}
  async update() {}
  async remove() {}
  async recent() {
    return [];
  }
  async before() {
    return [];
  }
  async close() {}
}

// — memory —

class MemoryRepo {
  constructor() {
    this.kind = 'memory';
    this.rows = new Map(); // messageId -> message copy
  }
  async init() {}

  async save(roomId, m) {
    this.rows.set(m.id, { roomId, m: JSON.parse(JSON.stringify(m)) });
  }

  async update(id, patch) {
    const hit = this.rows.get(id);
    if (hit) Object.assign(hit.m, JSON.parse(JSON.stringify(patch)));
  }

  async remove(id) {
    this.rows.delete(id);
  }

  async recent(roomId, limit) {
    if (limit <= 0) return [];
    const out = [];
    for (const { roomId: rid, m } of this.rows.values()) {
      if (rid === roomId && !m.unsent) out.push(m); // unsent rows are excluded from replay
    }
    out.sort(byTsThenId);
    return out.slice(-limit).map((m) => JSON.parse(JSON.stringify(m)));
  }

  // The page strictly older than the cursor. Same ordering rule as recent(),
  // and the same tie-break on id — see the comment on byTsThenId.
  async before(roomId, cursor, limit) {
    if (limit <= 0) return [];
    const out = [];
    for (const { roomId: rid, m } of this.rows.values()) {
      if (rid !== roomId || m.unsent) continue;
      if (cursor && !olderThan(m, cursor)) continue;
      out.push(m);
    }
    out.sort(byTsThenId);
    return out.slice(-limit).map((m) => JSON.parse(JSON.stringify(m)));
  }

  async close() {
    this.rows.clear();
  }
}

// — postgres —

class PgRepo {
  constructor() {
    this.kind = 'postgres';
  }
  async init() {}

  async save(roomId, m) {
    await pool.query(
      `insert into messages
         (id, room_id, ts, from_name, from_id, colour, text, action, reply_to, mentions,
          reactions, edited_at, unsent, expires_at, enc_alg, enc_kid, enc_n, enc_iv, enc_ct, enc_aadv)
       values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)
       on conflict (id) do nothing`,
      [
        m.id,
        roomId,
        m.ts,
        m.from,
        m.fromId,
        m.colour,
        m.text || '',
        !!m.action,
        m.replyTo ? JSON.stringify(m.replyTo) : null,
        JSON.stringify(m.mentions || []),
        JSON.stringify(m.reactions || {}),
        m.editedAt ?? null,
        !!m.unsent,
        m.expiresAt ?? null,
        ...encColumns(m),
      ],
    );
  }

  async update(id, patch) {
    const sets = [];
    const vals = [];
    const put = (col, v) => {
      vals.push(v);
      sets.push(`${col} = $${vals.length}`);
    };
    if ('text' in patch) put('text', patch.text || '');
    if ('editedAt' in patch) put('edited_at', patch.editedAt);
    if ('mentions' in patch) put('mentions', JSON.stringify(patch.mentions || []));
    if ('reactions' in patch) put('reactions', JSON.stringify(patch.reactions || {}));
    if ('unsent' in patch) put('unsent', !!patch.unsent);
    if ('enc' in patch) {
      const e = patch.enc;
      put('enc_alg', e ? e.alg : null);
      put('enc_kid', e ? e.kid : null);
      put('enc_n', e ? e.n : null);
      put('enc_iv', e ? e.iv : null);
      put('enc_ct', e ? e.ct : null);
      put('enc_aadv', e ? e.aadv : null);
    }
    if (!sets.length) return;
    vals.push(id);
    await pool.query(`update messages set ${sets.join(', ')} where id = $${vals.length}`, vals);
  }

  async remove(id) {
    await pool.query('delete from messages where id = $1', [id]);
  }

  async recent(roomId, limit) {
    if (limit <= 0) return [];
    const res = await pool.query(
      `select * from (
         select * from messages where room_id = $1 and unsent = false
         order by ts desc, id desc limit $2
       ) t order by ts asc, id asc`,
      [roomId, limit],
    );
    return res.rows.map(rowToMessage);
  }

  // Keyset pagination, never OFFSET. On Neon every page is a network round
  // trip, and OFFSET makes the database walk and discard every row it skips —
  // so page 20 costs twenty times page 1, for identical output. The row
  // comparison `(ts, id) < ($2, $3)` matches the messages_room_ts index
  // exactly, so each page is one index seek regardless of depth.
  async before(roomId, cursor, limit) {
    if (limit <= 0) return [];
    if (!cursor) return this.recent(roomId, limit);
    const res = await pool.query(
      `select * from (
         select * from messages
         where room_id = $1 and unsent = false and (ts, id) < ($2, $3)
         order by ts desc, id desc limit $4
       ) t order by ts asc, id asc`,
      [roomId, cursor.ts, cursor.id, limit],
    );
    return res.rows.map(rowToMessage);
  }

  async close() {}
}

function createRepository() {
  if (!config.PERSISTENCE_ENABLED) return new NullRepo();
  return config.USE_POSTGRES ? new PgRepo() : new MemoryRepo();
}

const repository = createRepository();

// Writes are fire-and-forget: logged and dropped, never awaited on the hot
// path. A slow database must not delay the room.
function detach(promise, what) {
  if (promise && typeof promise.catch === 'function') {
    promise.catch((err) => log.error(`persisting ${what} failed:`, err.message));
  }
}

module.exports = { repository, detach, createRepository, NullRepo, MemoryRepo, PgRepo };
