// test/feed.js — the Lab 6 routes, /message and /feed.
//
// This suite exists because of a specific and expensive failure. /feed keeps an
// append-only cache and proved an append was sound by checking that the cached
// row count plus the rows that had arrived equalled the current count. Read as
// two separate queries — count, then fetch — that check compares two different
// database snapshots, so any message committed between them broke the equality.
// Under write load that is almost every cycle, and every failure fell back to
// refetching and decrypting the whole table: at 35 000 messages that query ran
// for 25 seconds while holding a connection, and the writes queued behind it hit
// the pool's acquisition timeout. In the graded run it showed up as mass client
// timeouts and a final GET /feed that returned 504.
//
// So the assertions that matter here are not just "the feed is correct" but
// "reads taken during writes do not rebuild". Correct-but-rebuilding is the bug.
//
// Needs a real database, so it follows test/postgres.js: set TEST_DATABASE_URL
// to run it, and it skips loudly when that is absent.
//
//   TEST_DATABASE_URL=postgresql://chatfat:chatfat@localhost:5432/chatfat node test/feed.js
'use strict';

const { ok, eq, bail, report, startServer, sleep } = require('./harness');
const http = require('http');
const zlib = require('zlib');

const PORT = 8093;
const URL = process.env.TEST_DATABASE_URL;

async function feed(port, query = '', headers = {}) {
  const res = await fetch(`http://127.0.0.1:${port}/feed${query}`, { headers });
  const text = await res.text();
  return {
    status: res.status,
    headers: res.headers,
    text,
    items: res.ok ? JSON.parse(text) : null,
  };
}

// fetch() offers gzip and decompresses the reply before returning it, which
// hides the bytes actually sent. These assertions are about those bytes, so
// they go through http directly.
function rawFeed(port, headers) {
  return new Promise((resolve, reject) => {
    const req = http.get({ port, host: '127.0.0.1', path: '/feed', headers }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({ headers: res.headers, raw: Buffer.concat(chunks) }));
    });
    req.on('error', reject);
  });
}

async function send(port, name, msg, id) {
  const body = id ? { 'client-name': name, msg, id } : { 'client-name': name, msg };
  const res = await fetch(`http://127.0.0.1:${port}/message`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return { status: res.status, body: await res.json().catch(() => ({})) };
}

// Every message the feed returns, in the shape the route promises.
function wellFormed(items, label) {
  const ids = items.map((m) => m.id);
  eq(new Set(ids).size, ids.length, `${label}: no duplicate ids`);
  ok(items.every((m) => 'id' in m && 'client-name' in m && 'msg' in m && 'ts' in m),
    `${label}: every item carries id, client-name, msg and ts`);
  ok(items.every((m) => typeof m.msg === 'string' && m.msg.length > 0),
    `${label}: every message body is a non-empty string`);
  let ordered = true;
  for (let i = 1; i < items.length; i++) if (items[i].ts < items[i - 1].ts) ordered = false;
  ok(ordered, `${label}: ordered oldest to newest`);
}

(async () => {
  if (!URL) {
    console.log('feed: skipped — set TEST_DATABASE_URL to run (see the header of this file)');
    return;
  }

  // Start from an empty table. Rows left behind by another suite were written
  // under a different MASTER_KEY, so at-rest decryption correctly declines them
  // and every assertion about message text would fail for the wrong reason.
  const { Client } = require('pg');
  const prep = new Client({ connectionString: URL });
  await prep.connect();
  await prep.query('truncate messages');
  await prep.end();

  const srv = await startServer(PORT, { DATABASE_URL: URL, FEED_WARM_MS: '0', FEED_QUIET_MS: '0' });
  // The warmer is off on purpose: it would refresh the cache between the
  // assertions and hide whether the request path itself appends. FEED_QUIET_MS
  // is off for the same reason: with it, a read that lands within the quiet
  // window of a write may be answered from the last snapshot (up to
  // FEED_STALE_MS old) rather than assembled, and these assertions are about
  // what the assembling path itself produces. The snapshot contract has its
  // own section below.

  try {
    // ── a message is readable the instant it is accepted ──────────────────
    const first = await send(PORT, 'alice', 'first message');
    eq(first.status, 201, 'POST /message accepts a message');
    ok(typeof first.body.id === 'string' && first.body.id.length > 0,
      'and answers with the unique id it stored');

    let f = await feed(PORT);
    eq(f.status, 200, 'GET /feed answers 200');
    eq(f.items.length, 1, 'read-your-write: the message is already visible');
    eq(f.items[0].msg, 'first message', 'the text survives encryption at rest');
    eq(f.items[0]['client-name'], 'alice', 'and so does the sender');

    // ── the append path under concurrent writes ───────────────────────────
    await Promise.all(Array.from({ length: 300 }, (_, i) => send(PORT, `u${i % 20}`, `concurrent ${i}`)));
    f = await feed(PORT);
    eq(f.items.length, 301, 'every concurrently posted message is in the feed');
    wellFormed(f.items, 'after 300 concurrent posts');

    // ── reads interleaved with writes must append, not rebuild ────────────
    //     This is the regression. A rebuild is still *correct*, so only the
    //     cache mode distinguishes the fix from the bug.
    const reads = [];
    await Promise.all([
      ...Array.from({ length: 200 }, (_, i) => send(PORT, 'w', `interleaved ${i}`)),
      ...Array.from({ length: 20 }, async () => {
        const r = await feed(PORT);
        reads.push({
          filled: Number(r.headers.get('x-feed-filled')),
          reused: Number(r.headers.get('x-feed-reused')),
        });
      }),
    ]);
    f = await feed(PORT);
    eq(f.items.length, 501, 'nothing is lost when reads and writes interleave');
    wellFormed(f.items, 'interleaved read/write');

    // The regression. Correct-but-expensive is the bug: a read used to refetch
    // and decrypt the entire table whenever a write had landed since the last
    // one, so the work grew with the table and with the number of reads. Total
    // messages decrypted across all 20 reads must stay within the number of
    // messages actually written, not 20 x the table.
    const decrypted = reads.reduce((a, r) => a + r.filled, 0);
    ok(decrypted <= 200,
      `reads decrypt only new messages: ${decrypted} decrypted across 20 reads of a 501-message feed`);
    ok(reads.some((r) => r.reused > 0),
      'and reuse the bytes already assembled rather than re-serialising the feed');

    // ── ?limit= is served from the same cache, newest first ───────────────
    const all = (await feed(PORT)).items;
    for (const k of [1, 10, 137, 501, 900]) {
      const part = await feed(PORT, `?limit=${k}`);
      const want = Math.min(k, all.length);
      eq(part.items.length, want, `limit=${k} returns ${want} messages`);
      eq(JSON.stringify(part.items), JSON.stringify(all.slice(all.length - want)),
        `limit=${k} returns exactly the newest ${want}`);
    }
    const sized = await feed(PORT, '', { 'accept-encoding': 'identity' });
    eq(Number(sized.headers.get('content-length')), Buffer.byteLength(sized.text),
      'content-length matches the body actually sent');

    // ── gzip ──────────────────────────────────────────────────────────────
    // The graded client reads the whole feed over the network and the body
    // grows with every message stored. A 4.8 MB feed was verified and a 15 MB
    // one, on the same deployment minutes later, was still transferring when
    // the balancer gave up at 45 s — so the run could not be checked at all.
    // What matters is that the compressed reply carries the same messages and
    // that Content-Length describes the encoded bytes, not the original: get
    // that wrong and the client truncates the feed or hangs waiting for bytes
    // that never come.
    // Compression is opportunistic, and deliberately so: it is prepared by the
    // warmer when the backend has CPU to spare, never on the request path.
    // Compressing per request cost 100 ms at 20 000 messages and 411 ms at
    // 57 600 on a one-CPU container, which is more compression per second than
    // there are seconds in one. So the guarantee is not "always gzip" — it is
    // that gzip appears once the warmer has had an idle moment, that what it
    // sends is honest, and that it is never sent to a client that did not ask.
    //
    // This needs its own server because the one above runs with the warmer off,
    // which is exactly the condition under which compression never happens.
    const warm = await startServer(PORT + 2, { DATABASE_URL: URL, FEED_WARM_MS: '200' });
    try {
      const plainWarm = await rawFeed(PORT + 2, { 'accept-encoding': 'identity' });
      let gz = null;
      for (let i = 0; i < 40 && !gz; i++) {
        const r = await rawFeed(PORT + 2, { 'accept-encoding': 'gzip' });
        if (r.headers['content-encoding'] === 'gzip') gz = r;
        else await sleep(250);
      }
      ok(gz, 'the warmer prepares a compressed feed when idle');
      if (gz) {
        eq(Number(gz.headers['content-length']), gz.raw.length,
          'content-length counts the encoded bytes, not the original');
        eq(zlib.gunzipSync(gz.raw).toString(), plainWarm.raw.toString(),
          'the compressed feed decompresses to exactly the plain feed');
        ok(gz.raw.length < plainWarm.raw.length,
          'compression reduces the feed');
      }
      const plain = await rawFeed(PORT + 2, { 'accept-encoding': 'identity' });
      ok(!plain.headers['content-encoding'],
        'a client that does not offer gzip is not sent gzip');
      eq(plain.raw.toString(), plainWarm.raw.toString(), 'the uncompressed feed is unchanged');
    } finally {
      warm.stop();
    }

    // The body has been extended in place many times by now. A server that has
    // just started assembles the same feed from scratch, so the two must be
    // byte-identical — that is what says the incremental path is not drifting.
    const cold = await startServer(PORT + 1, { DATABASE_URL: URL, FEED_WARM_MS: '0', FEED_QUIET_MS: '0' });
    try {
      const fresh = await feed(PORT + 1);
      eq(fresh.text, sized.text, 'an incrementally grown body matches one assembled from scratch');
    } finally {
      cold.stop();
    }

    // ── a repeated id is stored once, however many times it arrives ───────
    const dupId = 'retry-me-please';
    const replies = await Promise.all(
      Array.from({ length: 25 }, () => send(PORT, 'flaky-client', 'retried message', dupId)),
    );
    ok(replies.every((r) => r.status >= 200 && r.status < 300),
      'every retry of one id is acknowledged');
    const withId = (await feed(PORT)).items.filter((m) => m.id === dupId);
    eq(withId.length, 1, '25 retries of one id appear once in the feed');
    eq(withId[0].msg, 'retried message', 'and the stored copy is the message that was sent');

    // ── deletion must invalidate, not append onto a stale base ────────────
    //     Emptying the table and re-posting two rows once left the count
    //     coincidentally unchanged, so the deleted rows stayed cached and the
    //     feed grew by two on every cycle. Three rounds, because the first
    //     round passed even when it was broken.
    const db = new Client({ connectionString: URL });
    await db.connect();
    try {
      for (let round = 1; round <= 3; round++) {
        await db.query('truncate messages');
        await send(PORT, 'after-truncate', 'a');
        await send(PORT, 'after-truncate', 'b');
        const g = await feed(PORT);
        eq(g.items.length, 2, `deletion round ${round}: the feed is exactly the two surviving rows`);
        wellFormed(g.items, `deletion round ${round}`);
      }
    } finally {
      await db.end();
    }

    // ── the snapshot contract, on a server with the production settings ───
    //     Under load a read arriving within FEED_QUIET_MS of a write may be
    //     served from the last snapshot; once the room has been quiet for that
    //     long every read is assembled and exact. Both halves are asserted:
    //     the early read must still be a well-formed feed, and the settled
    //     read must contain the write.
    const live = await startServer(PORT + 3, { DATABASE_URL: URL, FEED_WARM_MS: '0' });
    try {
      await feed(PORT + 3); // establishes a snapshot to be stale against
      const posted = await send(PORT + 3, 'quiet-client', 'visible once quiet');
      eq(posted.status, 201, 'the production-configured server accepts a message');
      const early = await feed(PORT + 3);
      eq(early.status, 200, 'a read straight after the write is served');
      wellFormed(early.items, 'read within the quiet window');
      await sleep(900); // FEED_QUIET_MS defaults to 750
      const settled = await feed(PORT + 3);
      ok(settled.items.some((m) => m['client-name'] === 'quiet-client' && m.msg === 'visible once quiet'),
        'a read after the quiet window contains the write');
    } finally {
      live.stop();
    }

    // ── the route contract: form encoding and the documented field names ──
    const form = await fetch(`http://127.0.0.1:${PORT}/message`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ 'client-name': 'form-client', msg: 'sent as a form' }).toString(),
    });
    eq(form.status, 201, 'POST /message also accepts a form-encoded body');
    await sleep(50);
    const withForm = (await feed(PORT)).items.find((m) => m['client-name'] === 'form-client');
    ok(withForm && withForm.msg === 'sent as a form', 'and stores it identically');

    // ── the routes reject what they should ────────────────────────────────
    const empty = await send(PORT, 'nobody', '');
    ok(empty.status >= 400, 'an empty msg is refused');
    const nameless = await fetch(`http://127.0.0.1:${PORT}/message`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ msg: 'no sender' }),
    });
    ok(nameless.status >= 400, 'a message with no client-name is refused');
    // GET /message is deliberately supported, because some generators submit
    // through the query string; with no fields at all it is a bad request, and
    // a verb that carries no message either way is refused on method.
    const bareGet = await fetch(`http://127.0.0.1:${PORT}/message`);
    eq(bareGet.status, 400, 'GET /message with no fields is a bad request');
    const viaQuery = await fetch(
      `http://127.0.0.1:${PORT}/message?client-name=query-client&msg=sent+in+the+query+string`,
    );
    eq(viaQuery.status, 201, 'GET /message with query fields submits the message');
    const queried = (await feed(PORT)).items.find((m) => m['client-name'] === 'query-client');
    ok(queried && queried.msg === 'sent in the query string', 'and stores it identically');
    const wrongVerb = await fetch(`http://127.0.0.1:${PORT}/message`, { method: 'PUT' });
    eq(wrongVerb.status, 405, 'PUT /message is method-not-allowed');
  } catch (err) {
    bail(err);
  } finally {
    srv.stop();
  }

  report('feed');
})().catch(bail);
