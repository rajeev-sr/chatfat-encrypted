# Lab 4 — Persistent and Secure WebSocket Chat · Phase Roadmap

**Course:** CS559 Computer Systems Design, IIT Bhilai
**Repo:** `4.GroupChat-Encypted` (ChatFat v2 → v3)
**Written:** 16 Aug 2026 · **Revised:** 16 Aug 2026 (Neon, Better Auth, design system)
**Scope source:** `Lab-Pdfs/Lab 4.pdf` (24 slides) · **Progress tracker:** `docs/progress.md`

---

## 0 · What the lab actually asks for

Six mandatory requirements (slide 23), plus one closing provocation (slide 24: *"IS IT REALLY SECURED?"*) which is where the difference between a pass and full marks lives.

| # | Mandatory requirement | Status today | Phase that closes it |
|---|---|---|---|
| 1 | Messages are stored in a database | ⚠️ **Partial** — a repository exists, but `DATABASE_URL` is unset by default, so the running server uses `NullRepo` and stores *nothing* | **P1** |
| 2 | A user receives previous chat history | ❌ **No** — `HISTORY_REPLAY=0` by default; no scrollback, no pagination | **P1 + P2** |
| 3 | Messages are not stored as plaintext | ⚠️ **Partial** — only inside `/lock`-ed rooms. An ordinary room writes `messages.text` in the clear | **P4** |
| 4 | The system detects modification of a stored message | ⚠️ **Partial** — AES-GCM tag protects locked-room *content* only. `sender_id`, `ts`, `room_id` are unprotected columns | **P4 + P7** |
| 5 | Each sender has a signing key pair | ❌ **Missing** — the only keypair in the codebase is an *ephemeral ECDH* pair for whispers. ECDH is key agreement, not signing | **P5** |
| 6 | Messages carry a sender signature and it is verified | ❌ **Missing** | **P6** |

Non-code deliverables the PDF also grades — these lose marks silently if left to the last night, so they are **Phase 11**, not an afterthought:

- Source code + **PDF report** + **per-member contribution report**
- **Working client URL** hosted on the allotted system
- **Public GitHub repo** with all members added as collaborators
- **Screenshots or a short demo video** proving *persistence*, *tamper detection*, and *signature verification*

---

## 0.1 · Compliance matrix

Verified against the PDF on 16 Aug 2026, before execution. **Reproduce this table verbatim in
`REPORT.md`** — it makes the grader's job trivial, and every row is a mark you have already earned
if the evidence column is honest.

| # | PDF requirement (slide 23) | Phase | Implemented by | Proved by |
|---|---|---|---|---|
| 1 | Messages are stored in a database | P1 | `PgRepo` on Neon; `001_init.sql` | `test/persistence.js` restart test; rows in the Neon console |
| 2 | A user receives previous chat history | P1 · P2 | `HISTORY_REPLAY=50`; `history:more` keyset pagination | `test/persistence.js` replay assertions; 500-message scrollback |
| 3 | Messages are not stored as plaintext | P4 | `src/crypto/atrest.js` — AES-256-GCM per row | `select * from messages` shows only ciphertext; stdout assertion in `test/crypto.js` |
| 4 | Modification of a stored message is detected | P4 · P6 · P7 | GCM tag + AAD binding · signature re-verified on read · per-room hash chain | `test/tamper.js`; `tools/audit.js` non-zero exit |
| 5 | Each sender has a signing key pair | P5 | `public/js/identity.js`; `device_keys` table | `test/signature.js`; fingerprints visible in the Security Center |
| 6 | Messages carry a signature and it is verified | P6 | Canonical `sigdata`; verified at ingress, on read, on render | `test/signature.js` — forged, wrong-key, replayed, revoked |

| Submission item (slide 23) | Phase | Where |
|---|---|---|
| Source code | — | The repo |
| PDF report | P11 | `docs/REPORT.md` → rendered |
| Contribution report per member | P0 → P11 | `docs/CONTRIBUTIONS.md`, written as you go |
| Working client URL on the allotted system | P11 | Deployment — **see Risk 4, HTTPS is a hard blocker** |
| Public GitHub, all members as collaborators | P0 → P11 | Repo settings |
| Screenshots / demo of persistence, tamper detection, signature verification | P11 | `docs/DEMO.md` steps 1, 3–5, 6 · `docs/screenshots/` |

### Where we deliberately exceed the brief

Say all four of these in the report; each is a direct answer to slide 24.

| Slide teaches | We also do | Why it matters |
|---|---|---|
| One server-side encryption layer | Two layers — at-rest **and** optional E2EE | Slide 6's model protects against a database thief but not against the operator |
| A signature detects a modified row | A per-room **hash chain** | A signature says nothing about a row that was **deleted** or **reordered** — it can only speak about rows still present |
| `sender` is a stored string | `sender_id` is a **Google-verified account**, bound into the AAD | Signing a self-declared username proves only that someone signed a string |
| Verify on read | Verify at **ingress, on read, and on render** | Verifying only server-side means trusting the server, which the E2EE layer explicitly refuses to do |

### Compliance with the crypto instructions (slides 7 and 17)

The PDF says twice: *"Do not write your own encryption algorithm — use a standard cryptographic
implementation."* State the compliance explicitly in the report:

- **Browser:** WebCrypto (`SubtleCrypto`) for PBKDF2, HKDF, AES-GCM, ECDH and signing.
- **Server:** `node:crypto` for HKDF, AES-256-GCM, scrypt and signature verification.
- **No hand-rolled primitive anywhere.** What *is* hand-written is the *composition* — key
  hierarchy, AAD construction, the canonical signing encoder, the chain — which is the part a
  lab is meant to teach, and every one of those is a documented, tested design decision rather
  than an invented algorithm.

### One naming note

Slide 20 lists the stored record as `sender · ciphertext · nonce · signature · timestamp`. Our
columns are `sender_id · ar_ct · ar_iv · sig · ts`. **`ar_iv` *is* the nonce** — GCM calls it an
IV, the slides call it a nonce, they are the same 12 bytes. Add one line to the report mapping
the two vocabularies so nobody hunts for a missing column.

---

## 1 · Where the code stands today

The starting point is unusually strong for a lab — this is not a rewrite, it is an extension. What already exists and should be **kept**:

| Asset | Verdict |
|---|---|
| Clean module graph: `config` is the only reader of `process.env`; transport depends on everything, nothing depends on transport | Keep. This is the discipline that makes the rest of the roadmap cheap. |
| `src/messages/repository.js` — `Null │ Memory │ Pg` behind one interface | Keep the seam; `PgRepo` becomes the primary path on Neon. |
| `public/crypto.js` — WebCrypto PBKDF2 + AES-256-GCM, AAD-bound, key store, fingerprints | Keep. This is **E2EE (Layer 1)** and it is genuinely good. |
| `src/crypto/envelope.js` — shape/size validation of ciphertext without ever interpreting it | Keep and extend for signature envelopes. |
| Four real integration suites that spawn actual servers and drive real sockets | Keep. Extend, don't replace. |
| Design-token stylesheet with correct dual-declaration dark mode, three-screen shell | Keep the *structure*; **P10** re-derives the type and colour on top of it. |

Being replaced:

| Asset | Why |
|---|---|
| `src/auth/index.js` — hand-rolled scrypt hashing, register/login | Superseded by **Better Auth + Google OAuth** in P3. The scrypt work was correct; it is simply no longer the identity model. |
| `src/auth/stores.js` — `MemoryStore \| PgStore` | Better Auth owns its own `user` / `session` / `account` tables. |
| `localStorage` bearer tokens in `public/client.js` | Replaced by Better Auth's `HttpOnly; Secure; SameSite` session cookies. |

Honest weaknesses to fix along the way:

- **`public/client.js` is 1,938 lines in one IIFE.** Fine for Lab 2; not "production grade code structure" for a graded submission. → **P9**
- **`docs/` did not exist** in this checkout while `README.md` linked to `docs/SPEC.md` and `docs/design.html`. → **P0**
- **No `.env.example`, no `docker-compose.yml`, no CI** (Lab 2's copy has all three). → **P0**
- **The type and colour are underspecified.** The stylesheet declares a `--serif` token it barely uses, sets body copy in `system-ui` (a neutral grotesque, the opposite of organic), and uses the same `--alert` red for a form error and for a security failure. → **P10**

---

## 2 · Target architecture: three independent security layers

The single most important design idea in this roadmap, and the thing to lead the report with. The slides teach *one* encryption layer (server-side, before `INSERT`). The repo already has a *different* one (client-side E2EE). **They defend against different adversaries and must be layered, not swapped.**

```
                  ┌─────────────────────────────────────────────┐
   Layer 3        │  SIGNATURE      Ed25519 / ECDSA-P256        │
   authenticity   │  "who created this?"                        │
                  │  verified 3×: ingress, on-read, on-render   │
                  └─────────────────────────────────────────────┘
                  ┌─────────────────────────────────────────────┐
   Layer 1        │  E2EE (optional, per room)  AES-256-GCM      │
   confidentiality│  key = PBKDF2(passphrase) — never on wire    │
   vs. the server │  defends against: the operator, a DB dump    │
                  └─────────────────────────────────────────────┘
                  ┌─────────────────────────────────────────────┐
   Layer 2        │  AT-REST (always on)        AES-256-GCM      │
   confidentiality│  key = HKDF(MASTER_KEY, room_id)             │
   vs. the DB     │  defends against: a Neon dump, a leaked      │
                  │  connection string, a backup on a laptop     │
                  └─────────────────────────────────────────────┘
                  ┌─────────────────────────────────────────────┐
   Layer 0        │  APPEND-ONLY TABLE + PER-ROOM HASH CHAIN     │
   ordering       │  detects deletion and reordering, which      │
                  │  neither GCM nor a signature can catch       │
                  └─────────────────────────────────────────────┘
```

**Layer 2 is the new mandatory work.** Every message row is encrypted with a server-held key before it reaches Neon, whether or not the room is locked. In a locked room, Layer 2 wraps ciphertext that is *already* ciphertext — defence in depth, and the honest answer to "is it really secured?" is that Layer 2 alone is *not*, because the server holds the key; only Layer 1 removes the operator from the trust boundary.

**Neon sharpens the argument.** The database is now a managed third party reachable over the public internet with a connection string. Layer 2 is what makes that acceptable: a leaked `DATABASE_URL` yields ciphertext and metadata, never message text. Say exactly this in the report — it turns a deployment convenience into a defensible security position.

### The design rule that drives the schema

> **A column outside the AAD is a column an attacker can rewrite.**

AES-GCM protects the bytes it encrypts. It does *not* protect `sender_id`, `ts`, or `room_id` sitting in adjacent columns. So:

1. Everything that does not need to be queried moves **inside** the encrypted payload (`text`, `mentions`, `reply_to`, `action`).
2. Everything that must stay a column is bound into the **AAD** *and* into the **signature payload**. Rewriting `sender_id` then breaks decryption **and** verification.

### The second rule

> **The `messages` table is append-only. The application never issues an `UPDATE`. Therefore any row that differs from its signature is, by definition, tampering.**

This is what makes the tamper demo unambiguous. Edits become a new row with `supersedes = <old id>`; unsends become a tombstone row; reactions move to their own table with their own per-reaction signature. No mutable state means no ambiguity about whether a diff is legitimate.

---

## 3 · Decisions

D1 and D4 are settled by the team. D2, D3 and D5 are still open — recommendations below.

**D1 · Which database?** — ✅ **Settled: Neon serverless Postgres.**
The existing `PgRepo` and `src/db/pool.js` already speak Postgres, so the code cost is a connection string and a migration runner, not a rewrite. What Neon changes in practice:

- **Connect with `pg` over TCP** using the **pooled** endpoint (the host containing `-pooler`), `sslmode=require`. The `@neondatabase/serverless` HTTP driver exists for edge runtimes; a long-lived Node process wants the ordinary pool, so keep `pg`.
- **The free tier scales to zero** after a few minutes idle, so the first query after a quiet period pays a cold start of roughly half a second. Harmless in use, *visible in a live demo* — warm it with a `/healthz` hit before recording.
- **Branching is the real win.** `neonctl branch create` gives every CI run an isolated copy-on-write database, so the integration suites can run against real Postgres instead of fixtures.
- **Offline still works.** `DATABASE_URL=memory` keeps the existing `MemoryRepo` path alive for local work and for suites that must not need network. The one suite that genuinely needs durability — the restart test in P1 — runs against a Neon branch in CI.
- **The connection string is a secret.** It goes in `.env` (gitignored), in GitHub Actions secrets, and nowhere else. It must never appear in `/healthz`, a log line, or an error message.

**D4 · Authentication?** — ✅ **Settled: Better Auth with Google OAuth.**
This replaces the hand-rolled scrypt path in `src/auth/`. Three things it buys, beyond convenience:

1. **`sender_id` becomes a verified identity.** Today a username is a claim. After P3 it is a Google account id, which is what makes a signature over `sender_id` mean something. This is why **P3 is sequenced before P4** — the AAD and the signature payload both bind `sender_id`, and binding a value whose meaning is about to change is wasted work.
2. **Session cookies replace `localStorage` bearer tokens** — `HttpOnly; Secure; SameSite`, so an XSS can no longer read the session. That was a P8 hardening item; Better Auth absorbs it.
3. **No password storage at all.** The best way to not leak passwords is to not have any. Note in the report that this *moves* trust to Google rather than eliminating it — an honest framing beats a triumphant one.

Practical friction to plan for:
- Better Auth is **ESM-first**. Node 24 can `require()` an ESM graph with no top-level await, so plain `require('better-auth')` may just work — **verify this in the first hour of P3**. If it does not, see D5.
- It brings its own schema (`user`, `session`, `account`, `verification`) and its own migration command. The old `users` and `sessions` tables get dropped.
- It mounts as a request handler; `better-auth/node`'s `toNodeHandler` fits the project's raw `node:http` server at `/api/auth/*`.
- **Google OAuth needs registered redirect URIs.** Add `http://localhost:3000/api/auth/callback/google` now and the deployed origin in P11. Google permits `localhost` over plain HTTP; every other origin must be HTTPS, which couples P3's completion to P8's TLS work for the hosted demo.
- **The WebSocket upgrade must authenticate from the cookie.** `src/transport/websocket.js` currently lets any socket connect and waits for a `join` frame carrying a token. After P3 the upgrade handler parses the session cookie and rejects unauthenticated upgrades before the socket ever opens.

**D2 · Which signature algorithm?** — ⬜ *Recommended:* Ed25519 when the browser's WebCrypto supports it, ECDSA P-256 + SHA-256 (`ES256`) as the fallback, chosen by feature detection at key-generation time. Node verifies both (confirmed locally). The envelope carries `sig_alg`, so the choice is per-key rather than per-server. `ES256` alone is the zero-risk option — universally supported, and already the curve `public/crypto.js` uses for whisper ECDH.

**D3 · Where does the private signing key live?** — ⬜ *Recommended:* a non-extractable `CryptoKey` in IndexedDB. The private key bytes never become a JS value, so an XSS can *use* the key while the page is open but can never *exfiltrate* it. Do **not** put key material in `localStorage` — that is what the room-key store does, and it is opt-in and warned about precisely because it is the weaker option.

**D5 · Module system?** — ⬜ *Recommended:* if `require('better-auth')` fails on Node 24, convert `src/` to ESM (`"type": "module"`) rather than scattering dynamic `import()` calls. The codebase is ~1,800 server lines with a clean dependency graph, P9 is already converting the client to ES modules, and one module system across the project is a better story in the report than two. The escape hatch, if time is tight, is a single `src/auth/betterauth.mjs` loaded by dynamic import — a contained ugliness rather than a spreading one.

---

## 4 · The phases

Twelve phases. **P0, P1, P3, P4, P5, P6 and P11 are the critical path to full mandatory marks.** P2, P7, P8, P9 and P10 are the differentiators — and of those, **P7 is the highest marks-per-hour**, because it is the direct answer to slide 24.

Estimates assume one person; §7 has the three-way split.

---

### Phase 0 · Baseline and guardrails
**~0.5 day · Blocks everything · No security work**

The point is that every later phase is *verifiable*. Do not skip this to "save time"; a broken baseline costs more later.

| Task | Detail |
|---|---|
| Green the existing suites | `npm run test:all` must pass on a clean checkout before anything changes |
| Populate `docs/` | Port `SPEC.md` and `design.html` from Lab 2 so `README.md`'s links resolve |
| `.env.example` | Every variable in `src/config.js`, documented, with safe defaults and **placeholder** secrets |
| `docker-compose.yml` | App + a local Postgres, so the database path is workable with no network |
| CI: `.github/workflows/ci.yml` | Node 22 + 24 matrix, `npm ci`, `npm run test:all`. A green badge in the README is free professionalism |
| `CHANGELOG.md`, `docs/CONTRIBUTIONS.md` | Start both now; they become half of P11 |
| Tag `v2.0.0-lab2` | So the diff you present in the report is exactly "what Lab 4 added" |
| **Establish the demo host's HTTPS story** | Google OAuth is unusable without it (Risk 4). Find out *now* whether the allotted system has a hostname, can use `<ip>.sslip.io`, can run a Cloudflare Tunnel, or none of the above. This single answer decides whether P3 is straightforward or needs a fallback path, and finding out in P11 is too late |
| **Verify egress from the allotted host** | `curl` Neon and `accounts.google.com` from the machine that will serve the demo. If either is blocked (Risk 5), self-host Postgres via `docker-compose.yml` and keep an email/password provider alongside Google |

**Acceptance:** clean clone → `npm ci && npm run test:all` green, CI green on a pushed branch, no broken links in `README.md`.

---

### Phase 1 · Persistence on Neon
**~1 day · Closes requirement 1, opens requirement 2**

| Task | Detail |
|---|---|
| Neon project | Create the project and database; copy the **pooled** connection string with `sslmode=require` into `.env` |
| Pool tuning | `src/db/pool.js` already caps at 10 with sensible timeouts. Against a pooled Neon endpoint, keep `max` modest and let PgBouncer do the multiplexing |
| Versioned migrations | `src/db/migrations/001_init.sql`, `002_atrest.sql`… plus a `schema_version` table and a runner. Not a single `CREATE TABLE IF NOT EXISTS` blob — a grader can *see* schema evolution |
| `PgRepo` becomes the default | `DATABASE_URL` unset now means "you have not configured Neon yet", and the server says so loudly instead of silently storing nothing |
| `memory` retained | Offline development and the suites that must not need network keep working, unchanged |
| `HISTORY_REPLAY` default `0 → 50` | Keep the README's "recording and replaying are separate questions" distinction; it is a good one |
| Seed rooms from config | `DEFAULT_ROOMS` creates rows on first boot; stop depending on a git-ignored `data/rooms.json` |
| CI database branches | `neonctl branch create` per run, dropped after. Real Postgres in CI, isolated per build |
| Restart test | `test/persistence.js` restarts the server mid-suite and asserts history survives — this *is* the "what happens if the server restarts?" slide |
| Cold-start note | Document the scale-to-zero behaviour in the README so nobody mistakes it for a bug during the demo |

**Acceptance:** `npm start` → send messages → `Ctrl-C` → `npm start` → history is there, and the rows are visible in the Neon SQL editor.

---

### Phase 2 · History as a real experience
**~1 day · Closes requirement 2 properly**

Requirement 2 is satisfied by a `SELECT`, but the marks for UX are not. Slide 5's flow (*connect → query → chat history → socket stays open*) deserves a real interface.

| Task | Detail |
|---|---|
| Cursor pagination | `repository.before(roomId, cursor, limit)` — keyset on `(ts, id)`, never `OFFSET`. Matters more on Neon than on a local disk: every page is a network round trip |
| `history:more` frame | Client asks, server answers. Bounded page size, rate-limited like everything else |
| Infinite scrollback | Scroll to top → fetch previous page → **preserve scroll anchor** (measure `scrollHeight` before insert, restore after). Getting this wrong is the classic chat-app bug |
| Date separators | "Today", "Yesterday", "Mon 12 Aug" between day boundaries |
| Unread divider | "12 new messages" line at the point you last left the room |
| Skeleton + empty + error states | Three states, not one. A history fetch that fails must say so, not silently show an empty room |

**Acceptance:** a room with 500 stored messages scrolls back smoothly in pages of 50, scroll position never jumps, day separators are correct across a midnight boundary.

---

### Phase 3 · Identity — Better Auth + Google OAuth
**~1 day · Prerequisite for P4, P5 and P6**

Sequenced here deliberately: `sender_id` is bound into the at-rest AAD (P4) and into the signature payload (P6). Settle what `sender_id` *means* before either of those is written.

| Task | Detail |
|---|---|
| Interop check *(do this first)* | Try `require('better-auth')` on Node 24. If it throws, take D5 and convert `src/` to ESM before writing any auth code — that ordering matters, because converting afterwards means touching every file you just wrote |
| Google Cloud OAuth client | Consent screen, client id + secret. Redirect URIs: `http://localhost:3000/api/auth/callback/google` now, the deployed origin added in P11 |
| Better Auth config | Google as the social provider, Neon pool as the database adapter, session lifetime, cookie flags `HttpOnly; Secure; SameSite=Lax` (Lax, not Strict — Strict breaks the OAuth redirect) |
| Schema migration | Better Auth generates `user`, `session`, `account`, `verification`. Fold it into the P1 migration runner as `003_betterauth.sql` so there is one migration story, not two |
| Mount the handler | `toNodeHandler` from `better-auth/node` at `/api/auth/*` in `src/transport/http.js`, above the static-file branch |
| Retire the old path | Delete `src/auth/index.js` and `src/auth/stores.js`; drop the old `users` and `sessions` tables in a migration. Keep the *timing-parity* comment somewhere in the report — it was a good idea and it is worth showing you understood why |
| **Authenticate the upgrade** | `src/transport/websocket.js` parses the session cookie in the `upgrade` handler and rejects unauthenticated sockets with `401` before the connection opens. The `join` frame stops carrying a token entirely |
| Client rework | The join screen becomes "Continue with Google". Remove `LS.token`, the `/auth/*` fetches, and the token-resume path from `public/client.js` |
| Identity in the hub | `session.userId` is the Better Auth user id and becomes the canonical `sender_id`. Display name and avatar come off the Google profile; `/nick` becomes a display-name preference, never an identity change |
| `test/auth.js` rewritten | Sign-in, session resume, expired session, unauthenticated upgrade rejected, and — still — impersonation refused |

**Acceptance:** Google sign-in works end to end; the WebSocket authenticates with no token in JS-readable storage; `sender_id` is a verified Google account id.

---

### Phase 4 · At-rest encryption (Layer 2)
**~1.5 days · Closes requirement 3, half of requirement 4 · The core of the lab**

| Task | Detail |
|---|---|
| `src/crypto/atrest.js` | The whole layer in one module. `seal(row) → {kv, iv, ct}` and `open(row) → payload \| TAMPERED` |
| Key hierarchy | `MASTER_KEY` (32 B, base64, from env or a `0600` key file) → `HKDF-SHA256(master, salt=room_id, info="chatfat-room-dek-v1")` → per-room DEK → AES-256-GCM per message with a fresh random 12-byte IV |
| **AAD binding** | `aad = "chatfat-atrest-v1" ‖ len(id)‖id ‖ len(room_id)‖room_id ‖ seq ‖ ts ‖ sender_id ‖ key_id ‖ kv` — length-prefixed, so no field-boundary confusion. **This is the line that makes column tampering detectable.** |
| Payload moves inside | `text`, `mentions`, `reply_to`, `action` leave the schema and become fields of the encrypted JSON |
| Key versioning | `ar_kv` column; `MASTER_KEYS` accepts `v1:…,v2:…` so rotation never orphans old rows |
| `tools/keygen.js` | Generates a master key, prints the `.env` line, refuses to overwrite an existing one |
| `tools/rekey.js` | Re-encrypts every row from `kv=n` to `kv=n+1`. Rotation you can actually demonstrate |
| Startup guard | No `MASTER_KEY` in production mode ⇒ **refuse to boot**, do not silently fall back to plaintext. In dev, generate an ephemeral one and log a loud warning |
| Never log plaintext | Extend the existing stdout assertion in `test/crypto.js` to the at-rest path |
| **Backfill the rows from P1–P3** | Everything written before this phase is plaintext with no `seq`, no signature and no chain link. Decide *and write down* which: **(a)** truncate — legitimate, it is development data, and the migration says so; or **(b)** a one-shot `tools/migrate-plaintext.js` that seals each row under a reserved `key_id = 'legacy'` and marks it `sig_alg = 'none'`, which the verifier then renders as *unverified* rather than *forged*. **(b) is the better demo** — it shows you thought about deployed data — but (a) is defensible if said out loud. Silently leaving mixed rows is the only wrong answer |

**Burn messages break the append-only rule — fix it here, not in P7.** `onChat` currently arms a
timer that calls `repository.remove(id)`, a real `DELETE`. Once P7 chains rows, a legitimate burn
would snap the chain and `audit.js` would report tampering on correct behaviour. So from this phase
on, a burn **overwrites the payload in place and keeps the row**: `ar_ct` is replaced with a sealed
empty payload, `unsent`-style tombstone semantics apply, and the chain is untouched because
`row_hash` was computed over the *original* insert and the tombstone appends a superseding row. The
same already-planned treatment covers `/unsend`. **Nothing in the message table is ever `DELETE`d.**

**Acceptance:** `select * from messages limit 5` in the Neon console shows **no readable text anywhere** — for locked *and* unlocked rooms. This is the screenshot for slide 6, and it is more persuasive on a hosted database than on a local file.

---

### Phase 5 · Sender signing keys
**~1.5 days · Closes requirement 5**

The requirement is one sentence; doing it *correctly* is where most submissions fall down, because a public key nobody verified proves nothing. Google has authenticated the *account*; nothing yet authenticates the *device*.

| Task | Detail |
|---|---|
| `public/js/identity.js` | Generate a non-extractable keypair (Ed25519, else ES256 — D2), store the `CryptoKey` in IndexedDB (D3) |
| `key_id` | `base64url(SHA-256(spki))`, truncated to 16 chars for display |
| **Proof of possession** | Registration is not "here is my public key". Server issues a 32-byte challenge bound to the Better Auth session; client returns `sign("chatfat-key-reg-v1" ‖ user_id ‖ key_id ‖ challenge)`; server verifies **before** storing. Without this, any authenticated user can plant a key under any account |
| `device_keys` table | `(key_id PK, user_id → user.id, alg, spki, label, created_at, revoked_at)`. One Google account, many browsers — a real system does not assume one device |
| `GET /keys/:user` | Public key lookup, cached client-side |
| **Safety numbers** | Render the fingerprint as five groups of five digits, plus a QR. Two members compare out of band. Worth saying in the report that TOFU is a *choice*, not an oversight |
| Key-change warning | If a sender's `key_id` differs from the one this client saw before → a **loud** banner, not a subtle badge. This is the attack that matters |
| Revocation | `POST /keys/:key_id/revoke` (authenticated). Messages signed before `revoked_at` stay valid; after, they do not |

**Acceptance:** two browsers signed into two Google accounts show matching fingerprints under manual comparison; a key planted by `curl` with a valid session but no valid proof of possession is rejected with `403`.

---

### Phase 6 · Signatures on the wire and at rest
**~1.5 days · Closes requirement 6, completes requirement 4**

| Task | Detail |
|---|---|
| **Canonical signing payload** | `sigdata = "chatfat-msg-v1" ‖ len-prefixed(id, room_id, seq, ts, sender_id, sender_name, key_id, content_hash)`. **Never `JSON.stringify` an object** — key order is not guaranteed and the signature becomes unreproducible |
| `content_hash` | `SHA-256(canonical_payload)` for an unlocked room; `SHA-256(e2ee_envelope_bytes)` for a locked one |
| **Verify #1 — ingress** | Server verifies before storing or broadcasting. Invalid ⇒ `SIG_INVALID`, message never enters the room. A forged frame does not reach a single other client |
| **Verify #2 — on read** | History replay re-verifies every row against `device_keys`. A row that fails is returned with `integrity: 'FAILED'` and its content withheld |
| **Verify #3 — on render** | The client verifies independently against its own cached copy of the sender's key. Server-side verification alone would mean trusting the server, which is precisely what Layer 1 refuses to do |
| **Inner signature (E2EE rooms)** | The outer signature proves *"this account transmitted these bytes"*. It does **not** prove *"this account wrote this text"* — the server never sees the text. So in locked rooms also sign the plaintext and put `{text, sig, key_id}` *inside* the ciphertext, verified by room members after decryption. Explaining this distinction in the report is a full-marks answer |
| Five rendered states | `verified` ✓ · `unverified` (TOFU pending) · `key-changed` ⚠ · `forged` ✗ · `tampered-at-rest` ✗. A message that fails **must never render as ordinary text** |
| `test/signature.js` | Valid, wrong key, mutated ciphertext, mutated `sender_id`, replayed frame, revoked key, cross-room replay |

**Build the canonical encoder first, with its round-trip test, before anything else in this phase.** Everything downstream depends on it producing byte-identical output in the browser and in Node.

#### The ordering question — answer it in the report before a grader asks

Slide 22 writes the flow as *Message → Authenticate → **Encrypt → Sign** → Store → Broadcast*. Our
unlocked-room path signs the **plaintext** and encrypts afterwards, which is the opposite order. That
is deliberate, and it is not a deviation from the PDF — it is a deviation from one line of prose that
**the PDF's own code contradicts**: slide 20 signs `message.encode()`, the plaintext, and stores the
signature alongside the ciphertext. Our design follows the code.

The substantive reasons, worth three sentences in the report:

- **Signing must happen where the private key is.** Slide 12 draws *Sign* inside the server box, but
  slide 20 also says *"the sender's private key must never be shared"*. Both cannot hold — a server
  that signs on your behalf holds your key. We resolve it by signing in the **client**, which is the
  only place that satisfies slide 20.
- **Signing plaintext proves authorship; signing ciphertext proves transmission.** Only the first
  answers slide 10's question, *"can we prove Alice actually created the message?"*
- **We do both, and the split is principled.** In a locked room the server cannot see plaintext, so it
  gets an **outer** signature over the ciphertext envelope (encrypt-then-sign, server-verifiable) while
  room members additionally verify an **inner** signature over the plaintext (sign-then-encrypt,
  end-to-end). Unlocked rooms need only the plaintext signature. Present this as a table of *which
  ordering, which room type, which adversary* and it reads as mastery rather than deviation.

**Acceptance:** a hand-crafted WebSocket client that sends a message with someone else's `sender_id` is rejected at ingress; a valid message whose `sender_id` is rewritten in Neon afterwards renders as a red tamper card on the next history load.

---

### Phase 7 · Tamper detection, audit, and the hash chain
**~1 day · This is the "IS IT REALLY SECURED?" phase**

Slide 19 explicitly asks for the demo: *"Change a ciphertext value directly in the database and try to read the message again."* Build the tooling so the demo is one command, not a manual SQL session under exam pressure. Neon's web SQL editor makes this demo *better* — you can tamper in a browser tab, on screen, and watch the client react.

| Task | Detail |
|---|---|
| `tools/tamper.js` | `--flip-ciphertext <id>` · `--rewrite-sender <id> <name>` · `--swap-signature <a> <b>` · `--delete <id>` · `--reorder <a> <b>`. Refuses to run unless `ALLOW_TAMPER=1`, so it can ship in the repo safely |
| `tools/audit.js` | Walks every row in every room: decrypts, verifies the signature, verifies the chain. Prints a per-room table and exits non-zero on any failure. **This is your best screenshot.** |
| **Per-room hash chain** | `row_hash = SHA-256("chatfat-chain-v1" ‖ prev_hash ‖ id ‖ room_id ‖ seq ‖ ts ‖ sender_id ‖ key_id ‖ sig ‖ ar_ct)`, head kept in `room_chain(room_id, head_seq, head_hash)`. Signatures and GCM cannot detect a **deleted** or **reordered** message. A chain can |
| Replay protection | Message `id` uniqueness + per-sender monotonic `seq` per room. A captured frame re-injected later is rejected, not stored twice |
| **`seq` allocation** | One in-memory counter per room, the single writer being the single Node process. On boot, restore each counter from `room_chain.head_seq` — **not** from `max(seq)` in `messages`, because a deleted tail row would silently let `seq` be reused. `UNIQUE(room_id, seq)` is the backstop that turns a bug into an error instead of a corrupt chain |
| **Chain head restoration** | `room_chain(room_id, head_seq, head_hash)` is written in the *same transaction* as the message insert. A crash between the two would otherwise leave a chain that audits as broken on the next boot |
| **Burns and unsends do not break the chain** | Already handled in P4: nothing is ever `DELETE`d, so a legitimate expiry is a superseding tombstone, not a gap. Verify this explicitly here — `audit.js` must report **intact** on a room where messages have burned |
| Tamper UI | A failed row renders as a bordered alert card: *"This message failed verification — it may have been altered in storage."* Plus a room-level banner when any row in the loaded window fails |
| `test/tamper.js` | Automated: seed → tamper via the tool → assert `audit.js` exits non-zero and the client renders the alert state. **Plus the inverse:** burn a message, let it expire, assert `audit.js` still exits **zero** — a tamper detector that fires on correct behaviour is worse than none |

**Acceptance:** `node tools/tamper.js --flip-ciphertext m_abc && node tools/audit.js` → non-zero exit, one clearly-identified failing row, and the running client shows the tamper card without a restart.

---

### Phase 8 · Hardening the rest of the stack
**~1 day · The gap between "the crypto is right" and "the system is secure"**

Better Auth already took the cookie and CSRF work off this list in P3. What remains:

| Task | Detail |
|---|---|
| **TLS / `wss://`** | Caddy or nginx in front, Let's Encrypt on the allotted host. Required, not optional: Google OAuth refuses non-HTTPS redirect URIs for anything but `localhost`. The client already derives `wss://` from `location.protocol` |
| **CSP** | `default-src 'self'; script-src 'self'; connect-src 'self' wss:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`. The inline theme script in `index.html` needs a nonce or a move to an external file; self-hosted fonts in `public/fonts/` need `font-src 'self'` |
| Security headers | HSTS, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy` |
| Rate limiting | Extend the existing token bucket to `history:more`, key registration, and key lookups |
| Secret hygiene | `MASTER_KEY`, `DATABASE_URL` and the Google client secret never logged, never in `/healthz`, never in an error message. A pre-commit grep in CI |
| Dependency audit | `npm audit` in CI; pin `ws`, `pg` and `better-auth`; `npm ci --omit=dev` in the Dockerfile (already correct) |
| `docs/THREAT-MODEL.md` | Adversaries (passive network, malicious operator, **Neon compromise or a leaked connection string**, compromised member, XSS, a malicious Google), what each layer stops, **and what none of them stop**. The README's "what it protects / what it does not" table is already the right shape — extend it |

**Acceptance:** `https://` + `wss://` end to end, a header check with no criticals, and a threat-model doc that names at least one thing the system genuinely does not protect against.

---

### Phase 9 · Code structure and engineering quality
**~1 day · "Production grade code structure"**

Sequenced after P6 on purpose: a refactor must not be able to quietly break a security property that nothing yet tests.

| Task | Detail |
|---|---|
| **Split `public/client.js`** | 1,938 lines → ES modules under `public/js/`, loaded with `<script type="module">`. **No build step** — that stays a virtue of this project. Boundaries the file already suggests via its own section banners: `socket.js` · `state.js` · `render/messages.js` · `render/roster.js` · `screens/{join,lobby,chat}.js` · `crypto/{room,identity,verify}.js` · `commands.js` · `ui/{toast,modal,theme}.js` |
| ESM on the server | If D5 was taken in P3, this is already done; otherwise finish the conversion here so both halves of the codebase agree |
| ESLint + Prettier | Flat config, run in CI |
| `checkJs` | `jsconfig.json` with `"checkJs": true` + JSDoc on every exported function. Types without TypeScript, no build step |
| Error taxonomy | One `src/protocol/codes.js`: every `fail()` code defined once, with its close-code mapping and its user-facing string. Currently those strings live inline across `handlers.js` |
| Structured logging | `src/logger.js` → JSON lines with `level`, `event`, `roomId`, `sessionId`. Never message content, never key material, never a connection string |
| Migrate to `node:test` | Keep the real-server harness; swap the bespoke assertion loop for the built-in runner so output is standard and CI-parseable. Add `--experimental-test-coverage` |
| ADRs | `docs/adr/0001-two-encryption-layers.md`, `0002-append-only-messages.md`, `0003-neon-and-better-auth.md`. Three short ADRs communicate design maturity faster than any amount of prose |

**Acceptance:** no source file over ~400 lines, `npm run lint` and `npm run typecheck` clean in CI, coverage reported.

---

### Phase 10 · UI/UX and the organic design system
**~2 days · The largest non-security phase, and the most visible**

Two jobs. First, **re-derive the type and colour** so the product reads as one deliberate organic system rather than a set of defaults. Second, **make security legible** — which is an information-design problem, not a cryptographic one.

#### 10a · Typography

The current stylesheet declares `--serif: Georgia…` and then sets body copy in `system-ui` — a neutral grotesque, which is the opposite of organic. Fix it properly.

| Task | Detail |
|---|---|
| **Self-host, do not link** | Fonts go in `public/fonts/` as subset `.woff2`. Same-origin, so no CSP exception beyond `font-src 'self'`, no external dependency, no build step. `src/transport/http.js` already has a `.woff2` MIME entry — it was anticipated |
| **Display face** | A variable serif with an organic axis. **Fraunces** is the recommendation: its `SOFT` and `WONK` axes literally exist to make letterforms less mechanical. **Newsreader** is the calmer alternative. Used for the wordmark, screen headings and the lobby's question — nowhere below 20 px |
| **Text face** | A humanist sans for message bodies and UI: **Source Sans 3** or **Instrument Sans**. Humanist, not geometric — open apertures and calligraphic stroke contrast are what make a sans read warm at 15 px in a dense log |
| **Mono face** | **IBM Plex Mono** — warmer than JetBrains Mono, and it is carrying key fingerprints and safety numbers, so it needs unambiguous `0/O` and `1/l/I` |
| Subset and budget | Latin + punctuation + the digits the safety numbers need. Two variable faces plus one mono, ~120 KB total, `font-display: swap`, `<link rel="preload">` on the two above-the-fold faces |
| **Type scale** | One 1.2 ratio scale — `12 · 14 · 15.5 · 17 · 20.5 · 24.5 · 29.5 · 35.5 · 42.5` — declared as tokens. No off-scale sizes anywhere; the current stylesheet has several |
| Measure and rhythm | Body copy capped near 65 characters, line height 1.55–1.65 for prose and 1.45 in the message log, `text-wrap: balance` on headings, letter-spacing tightened on display sizes and opened on uppercase labels |
| Numerals | `font-variant-numeric: tabular-nums` on timestamps, RTT, poll tallies and every fingerprint |

#### 10b · Colour

The existing palette — cream ground, terracotta, sage, plum-for-encryption — is a good *start* and should be kept as the brand. Three things are wrong with how it is used.

| Problem | Fix |
|---|---|
| **Semantic and brand colours collide.** `--alert` is both "your form input is invalid" and, after P6, "this message may have been forged". Those must not look the same | Introduce a **separate security scale**: `--verified` (deepened sage), `--pending` (ochre), `--tamper` (oxblood, distinct from `--alert`), `--seal` (plum, unchanged — encryption). Brand accents never carry security meaning and security colours never carry brand meaning |
| **Dark mode is a darkening, not a theme.** The dark tokens keep the same hues at lower lightness, which is why it reads muddy | Shift hue as well as lightness: warm charcoal with a green-brown undertone for grounds, and accents *desaturated and lightened* rather than merely lightened. Re-audit every pairing — an accent tuned for cream rarely survives on charcoal untouched |
| **Elevation is implied, not defined.** Four surface tokens exist with one shadow | A four-step elevation scale pairing each surface with its own shadow and border treatment, so a modal, a card and a toast are distinguishable without reading their contents |

Also in this pass: a radius scale (organic means *consistently* soft, not randomly rounded), a motion token set (one easing curve, one duration scale), and a **contrast audit at ≥ 4.5:1 in both themes** — the current cream-on-cream secondary text is the first thing to check.

#### 10c · Making security legible

| Task | Detail |
|---|---|
| **Security Center** | One panel answering, live, for the current room: at-rest `on · kv2` · E2EE `on` + fingerprint · signatures `142 verified, 0 failed` · chain `intact to seq 142` · your device key and safety number. **This is the screen you demo and screenshot** |
| Per-message verification badge | Quiet when verified, unmissable when not. On hover or focus: "Signed by Rahul · key 3f9a…c1 · verified in your browser" |
| Identity & devices screen | Your Google account, your device keys, last used, revoke. Plus a "verify a contact" safety-number comparison flow |
| Accessibility | Full keyboard path through every flow, visible focus rings, `aria-live` extended to verification-state changes, `prefers-reduced-motion` honoured, contrast audited in both themes |
| Responsive | The roster already collapses; audit 360 px, and make modals bottom-sheets under 640 px |
| Every state designed | loading · empty · error · offline · reconnecting · rate-limited · tampered. The reconnect path exists in `client.js`; give it a real interface |
| Onboarding | First run: three steps explaining what is encrypted, what is signed, and what is still visible. Honesty as a feature |

**Acceptance:** Lighthouse accessibility ≥ 95; a keyboard-only walkthrough from Google sign-in to a verified contact in a locked room; no off-scale type sizes or unlisted colours anywhere in `style.css`; and a security state a non-technical grader can read at a glance.

---

### Phase 11 · Deploy, demo, and the graded paperwork
**~1 day · Do not compress this**

| Deliverable | Detail |
|---|---|
| **Verify the deliverables are tracked** | `git ls-files docs/` must list `REPORT`, `CONTRIBUTIONS`, `DEMO`, `THREAT-MODEL`, the ADRs and the screenshots. If `docs/` is ignored at that point, narrow the rule to `docs/ROADMAP.md` and `docs/progress.md` only. **This is a marks-losing detail if forgotten** |
| **Hosted client URL** | Deploy to the allotted system. `docker-compose up -d` behind Caddy with TLS, health check, restart policy, log rotation. `DATABASE_URL` points at Neon; `MASTER_KEY` from the host's environment, never the image |
| **Google OAuth production redirect** | Add the deployed origin to the OAuth client before the demo, not during it |
| **`docs/DEMO.md`** | A 6-minute script with exact commands, so the recording is one take: **(1)** send messages, restart the server, history returns · **(2)** open the Neon SQL editor, show ciphertext where the text should be · **(3)** `tools/tamper.js --flip-ciphertext`, reload, tamper card appears · **(4)** `--rewrite-sender`, signature fails even though the ciphertext is untouched · **(5)** `tools/audit.js` exiting non-zero · **(6)** two Google accounts comparing safety numbers |
| **Screenshots / video** | The three the PDF names — persistence, tamper detection, signature verification — plus the Security Center. In `docs/screenshots/` |
| **PDF report** | Write `docs/REPORT.md`, render via the `docs/report.html` pattern from Lab 2. **Open with the compliance matrix from §0.1** — requirement, phase, implementing file, proving test — so the grader can tick six boxes on page one. Then: problem · threat model · the three layers and why one is not enough · why identity had to come before encryption · schema and the AAD rule · **the sign/encrypt ordering answer from P6** · signature payload construction and why not `JSON.stringify` · verification at three points · **the standard-library compliance statement (slides 7 and 17)** · the `nonce`/`ar_iv` vocabulary note · what we do **not** protect against · results and load figures |
| **Contribution report** | `docs/CONTRIBUTIONS.md` — per member, with commit ranges. Write it as you go; `git shortlog -sne` is evidence |
| **GitHub** | Public repo, **every member added as a collaborator** (asked for explicitly), protected `main`, CI badge, `LICENSE`, a README opening with a screenshot |
| Load figures | `npm run loadtest` before and after the crypto work. "Signing added 1.8 ms p95 at 64 clients" is a sentence that earns marks. Note that Neon adds network latency to the *write* path, not the broadcast path — the fan-out numbers should be unchanged, and saying so shows you understood your own architecture |

**Acceptance:** a stranger can open the URL, sign in with Google, read the README, and reproduce the tamper demo in under five minutes.

---

## 5 · Schema at the end of Phase 7

```sql
-- Better Auth owns user / session / account / verification.
-- Everything below is ours.

-- append-only. the application issues no UPDATE. any diff is tampering.
CREATE TABLE messages (
  id            TEXT PRIMARY KEY,      -- 'm_...' — client-visible id
  room_id       TEXT NOT NULL,
  seq           BIGINT NOT NULL,       -- per-room monotonic; ordering + gap detection
  ts            BIGINT NOT NULL,
  sender_id     TEXT NOT NULL REFERENCES "user"(id),  -- verified Google account
  sender_name   TEXT NOT NULL,         -- display name at send time (inside the signature)
  key_id        TEXT NOT NULL,         -- device key that signed this
  supersedes    TEXT,                  -- edits append; they never mutate
  kind          TEXT NOT NULL,         -- 'chat' | 'tombstone'
                                       -- polls stay in-memory room state: they are
                                       -- not a lab requirement, and persisting them
                                       -- would add signing + encryption surface for
                                       -- no marks. Say this in the report; a scope
                                       -- boundary you can defend beats one you missed.

  ar_alg        TEXT NOT NULL,         -- 'A256GCM'          ─┐ layer 2
  ar_kv         INTEGER NOT NULL,      -- master key version  │ at-rest
  ar_iv         BYTEA NOT NULL,        -- 12 bytes            │
  ar_ct         BYTEA NOT NULL,        -- ct+tag of payload  ─┘

  sig_alg       TEXT NOT NULL,         -- 'Ed25519' | 'ES256' ─┐ layer 3
  sig           BYTEA NOT NULL,        --                      │ authenticity
  content_hash  BYTEA NOT NULL,        --                     ─┘

  prev_hash     BYTEA,                 --                     ─┐ layer 0
  row_hash      BYTEA NOT NULL,        --                     ─┘ chain

  expires_at    BIGINT,
  UNIQUE (room_id, seq)
);
CREATE INDEX messages_room_ts ON messages(room_id, ts DESC, id DESC);

CREATE TABLE device_keys (
  key_id     TEXT PRIMARY KEY,         -- base64url(SHA-256(spki))
  user_id    TEXT NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
  alg        TEXT NOT NULL,
  spki       BYTEA NOT NULL,
  label      TEXT,                     -- "Chrome on rahul-mac"
  created_at BIGINT NOT NULL,
  revoked_at BIGINT
);

CREATE TABLE room_chain (
  room_id   TEXT PRIMARY KEY,
  head_seq  BIGINT NOT NULL,
  head_hash BYTEA NOT NULL
);

-- reactions are mutable, so they cannot live inside an immutable signed blob.
-- each reaction is its own signed row instead.
CREATE TABLE reactions (
  message_id TEXT NOT NULL REFERENCES messages(id),
  user_id    TEXT NOT NULL,
  emoji      TEXT NOT NULL,
  ts         BIGINT NOT NULL,
  key_id     TEXT NOT NULL,
  sig        BYTEA NOT NULL,
  PRIMARY KEY (message_id, user_id, emoji)
);
```

---

## 6 · Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Signature payload not byte-reproducible across browser and Node | **High** | The canonical length-prefixed encoder is written **once**, shared verbatim between `public/js/` and `src/crypto/`, and has its own round-trip test as the first thing built in P6 |
| Crypto work lands but the paperwork does not | **High** | P11 is a phase with an estimate, not a "we'll do it Sunday". `CHANGELOG.md` and `CONTRIBUTIONS.md` start in P0 |
| **Better Auth ESM/CJS interop bites mid-phase** | **High** | The interop check is the *first* task in P3, before any auth code is written. If it fails, convert to ESM immediately (D5) rather than working around it |
| **The allotted system has no domain name, so Google OAuth cannot work** | **High** | Google refuses non-HTTPS redirect URIs for every origin except `localhost`, and Let's Encrypt will not issue for a bare IP. **Resolve this in P0, not P11** — establish which of these you have: a real hostname; a wildcard-DNS name such as `<ip>.sslip.io` (publicly resolvable, so an HTTP-01 challenge succeeds if port 80 is reachable); a free DuckDNS subdomain; or a Cloudflare Tunnel, which terminates TLS for you and needs no inbound ports. If none is possible, fall back to the local-account path (below) for the hosted demo and show Google sign-in on `localhost` in the video |
| **The lab network blocks egress, so Neon and Google are both unreachable** | **High** | The architecture now has two hard external dependencies where Lab 2 had none — a firewalled lab LAN takes the whole app down, not one feature. **Keep an offline path alive and test it weekly:** `DATABASE_URL=memory` plus a retained email/password provider in Better Auth. Verify egress from the allotted host in P0; if it is blocked, self-host Postgres via the P0 `docker-compose.yml` and make local accounts the primary path |
| A legitimate burn or unsend breaks the hash chain and `audit.js` reports false tampering | Medium | Resolved by design in P4 — nothing in `messages` is ever `DELETE`d. P7 carries the inverse test: burn a message, assert the audit still exits **zero** |
| Rows written in P1–P3 are plaintext and unsigned, leaving a mixed table | Medium | Explicit backfill decision in P4 — truncate, or seal legacy rows under `sig_alg = 'none'` so they render *unverified* rather than *forged*. Writing it down is the requirement; either choice is defensible |
| **Graded deliverables live in `docs/` and never reach the public repo** | Medium | `git ls-files docs/` is the first checklist item in P11; the ignore rule carries a comment pointing at it |
| Google OAuth redirect misconfigured at demo time | Medium | Register the production URI in P11 as a named task, and rehearse sign-in on the deployed host before recording |
| Neon cold start makes the demo look broken | Medium | Free tier scales to zero. Hit `/healthz` before recording; document the behaviour in the README |
| Neon connection string leaks into a log or a commit | Medium | `.env` gitignored, secrets in GitHub Actions, pre-commit grep in P8, and `/healthz` audited for it |
| WebCrypto Ed25519 missing on a lab machine | Medium | Feature-detect at key generation, fall back to `ES256`, carry `sig_alg` per key |
| Scroll-anchor bug makes history feel broken | Medium | Budgeted explicitly in P2; test at 500 messages, not 20 |
| Self-hosted fonts blocked by the CSP | Low | `font-src 'self'` added in the same commit as the CSP in P8; fonts are same-origin by construction |
| Losing `MASTER_KEY` makes all history unreadable | Low | Documented as intended behaviour; `tools/keygen.js` prints a backup reminder. This is a *feature* — say so in the report |

---

## 7 · Suggested three-way split

Phases 0–2 are shared groundwork; after that the work parallelises cleanly along the layer boundaries, which is not a coincidence — it is what the module graph was for.

| Member | Owns | Phases |
|---|---|---|
| **A — storage & at-rest** | Neon, migrations, `src/db/*`, `src/messages/*`, `src/crypto/atrest.js`, `tools/{keygen,rekey,audit}.js` | P1, P4, P7 |
| **B — identity & signatures** | Better Auth, Google OAuth, `src/crypto/sign.js`, `public/js/{identity,verify}.js`, `device_keys` | P3, P5, P6, P8 |
| **C — client & experience** | `public/js/**`, the design system, history UX, Security Center, accessibility | P2, P9, P10 |

**Shared, and worth doing together in one sitting:** the canonical encoder (P6) — both server and client depend on it being byte-identical, so pair on it rather than integrating two versions later.
**Everyone:** their own section of `REPORT.md` and `CONTRIBUTIONS.md`, written in the same week as the code.

---

## 8 · Timeline

| | Phases | Days | State at the end |
|---|---|---|---|
| **Week 1** | P0 · P1 · P2 · P3 | 3.5 | Persistence on Neon, real history, Google sign-in. Requirements 1–2 done |
| **Week 2** | P4 · P5 · P6 · P7 | 5.5 | **All six mandatory requirements done.** Ciphertext at rest, signatures verified three times, tamper demo working |
| **Week 3** | P8 · P9 · P10 · P11 | 5.0 | Hardened, restructured, redesigned, deployed, submitted |

**~14 person-days solo; roughly 6 calendar days for a team of three with the split above.**

**If time collapses:** P0 → P1 → P3 → P4 → P5 → P6 → P11 is the minimum path to all six mandatory requirements plus a submittable demo. P2, P7, P8, P9, P10 are what you add back as time allows — and **P7 first**, because it is the direct answer to slide 24 and the highest marks-per-hour in the roadmap.

---

## 9 · The one-paragraph answer to "IS IT REALLY SECURED?"

Worth drafting now, because it shapes what you build:

> No system is secure in the abstract — only against a named adversary. This one **encrypts at rest**, so a leaked Neon connection string yields ciphertext and metadata but never message text; it **signs every message** with a per-device key, so a forged or altered row is detectable; it **chains rows per room**, so a deletion or a reordering is detectable too; it **authenticates senders through Google**, so `sender_id` is a verified identity rather than a claim; and for rooms that opt in, it **encrypts end to end**, so the operator sits outside the trust boundary. It does **not** protect metadata — who is in which room, when, and how often is visible to the server in every mode. It does not protect against a member of the room, who has the key by definition. It does not protect against a compromised browser. It moves password trust to Google rather than eliminating it. And the honest weak point is key distribution: the first time you see someone's device key, you trust it, and only an out-of-band comparison of safety numbers turns that trust into verification. Each of those is a deliberate boundary, documented in `docs/THREAT-MODEL.md` — and naming them is what makes the rest of the claims credible.
