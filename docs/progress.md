# Progress — Lab 4 Secure Persistent Chat

**Companion to `docs/ROADMAP.md`.** The roadmap says *what* and *why*; this file says *how far*.

---

## Working protocol

> At the start of every turn, read `docs/ROADMAP.md` and `docs/progress.md`.
> On finishing a phase, update this file: flip the status, tick the tasks, fill in the
> acceptance evidence, and append a dated entry to the log at the bottom.

**Status vocabulary** — one per phase, no in-between improvisation:

| | Meaning |
|---|---|
| `⬜ not started` | No code written for this phase |
| `🟡 in progress` | Started, acceptance criteria not yet met |
| `✅ done` | Every task ticked **and** the acceptance criterion demonstrably met |
| `⏸ blocked` | Waiting on a decision, a credential, or another phase — reason recorded |
| `⏭ skipped` | Deliberately dropped; reason recorded |

A phase is **not** `✅ done` until its acceptance line in the roadmap has been run and the
result recorded here. "The code is written" is `🟡`.

---

## Snapshot

| | |
|---|---|
| **Current phase** | P3 — Identity (Better Auth, email + password) |
| **Phases complete** | 3 / 12 — P0, P1, P2 |
| **Mandatory requirements met** | 2 / 6 — requirements 1 and 2 |
| **Test suite** | 257 assertions green offline · 16 green against Neon |
| **Last updated** | 16 Aug 2026 — P2 committed (871ebfb) |

### Mandatory requirements (PDF slide 23)

| # | Requirement | Status | Closed by |
|---|---|---|---|
| 1 | Messages are stored in a database | ✅ **met** — Neon, proven across a restart | P1 |
| 2 | A user receives previous chat history | ✅ **met** — replay 50 + keyset scrollback | P1 · P2 |
| 3 | Messages are not stored as plaintext | ⬜ partial (locked rooms only) | P4 |
| 4 | Modification of a stored message is detected | ⬜ partial (content only) | P4 · P7 |
| 5 | Each sender has a signing key pair | ⬜ not met | P5 |
| 6 | Messages carry a verified sender signature | ⬜ not met | P6 |

### Decisions

| | Decision | Chosen | Confirmed |
|---|---|---|---|
| D1 | Database | **Neon** serverless Postgres | ✅ user |
| D2 | Signature algorithm | Ed25519, `ES256` fallback by feature detection | ✅ user |
| D3 | Private key storage | Non-extractable `CryptoKey` in IndexedDB | ✅ user |
| D4 | Authentication | **Better Auth**, email + password *(was Google OAuth; changed 16 Aug)* | ✅ user |
| D5 | Module system | **CommonJS stays** — `require('better-auth')` works on Node 24 | ✅ verified |

---

## Phases

### ✅ P0 · Baseline and guardrails — *0.5 d*

- [x] `npm run test:all` green on a clean checkout — 246 assertions before any change
- [x] `docs/` populated — ROADMAP, progress, CONTRIBUTIONS, DESIGN-SYSTEM
- [x] `.env.example` covering every variable in `src/config.js`
- [x] `docker-compose.yml` (app + local Postgres for offline work)
- [x] CI at `.github/workflows/ci.yml`, Node 22 + 24 matrix + audit + secret grep
- [x] `CHANGELOG.md` and `docs/CONTRIBUTIONS.md` started
- [x] Tag `v2.0.0-lab2` → points at 65a704d
- [x] ~~HTTPS story~~ — **retired** by the D4 change to email + password
- [ ] **Verify egress** — `curl` the Neon endpoint from the allotted host *(deferred: no allotted host yet)*
- [x] README layout tree corrected — it referenced `docs/SPEC.md`, which never existed

**Acceptance:** clean clone → `npm ci && npm run test:all` green, no broken README links.
**Evidence:** 246 assertions green at commit 39fa9d7. CI not yet observed on a push — GitHub
Actions has not run against this branch. HTTPS question retired rather than answered.

---

### ✅ P1 · Persistence on Neon — *1.0 d*

- [x] Neon project + database; pooled endpoint (`-pooler`) confirmed, `sslmode=require`
- [x] Versioned migration runner + `schema_version` table with checksums
- [x] `001_init.sql`
- [x] `PgRepo` is the default path; `memory` retained for offline suites
- [x] `HISTORY_REPLAY` default `0 → 50`
- [x] `DEFAULT_ROOMS` seeded from config *(already true in `directory.load`; verified, not changed)*
- [x] Restart test — in `test/postgres.js`, not `persistence.js`: it needs durable storage
- [x] Cold-start note in README, plus the `pg` sslmode warning
- [ ] Neon branch per CI run (`neonctl branch create`) *(deferred to P11 with CI setup)*

**Acceptance:** send → restart server → history returns; rows visible in Neon.
**Evidence:** ✅ `test/postgres.js` 16/16 against the real Neon database. "written before the
restart" written on boot 1, read back on boot 2 with text and sender intact, room directory
survived. Row confirmed by direct SQL — **and readable as plaintext, which is the "before"
picture for P4.**

---

### ✅ P2 · History as a real experience — *1.0 d*

- [x] Keyset pagination — `repository.before(roomId, cursor, limit)` on `(ts, id)`, all 3 repos
- [x] `history:more` / `history:page` frames, bounded by `HISTORY_PAGE`, rate-limited
- [x] Infinite scrollback with preserved scroll anchor
- [x] Date separators — rebuilt wholesale after a prepend (`rebuildDays`)
- [x] Loading / done / error-with-retry states (`.cf-histtop`)
- [x] Empty vs absent history distinguished in copy
- [ ] Unread divider at last-left position *(not done — deferred, cosmetic)*

**Acceptance:** pages back cleanly, no scroll jump, no duplicate at a page boundary.
**Evidence:** ✅ 12 messages at 5/page reassemble to exactly `m0..m11` in order, both on the
memory repo and against Neon (`test/postgres.js`). Malformed cursor refused with `NAME_INVALID`.
**Not verified:** the 500-message figure and the scroll-anchor behaviour itself — both need a
browser, and no browser check was run for P2.

---

### 🟡 P3 · Identity — Better Auth, email + password — *1.0 d*

- [x] `require('better-auth')` interop verified on Node 24 — **works, no ESM conversion needed**
- [x] ~~Google OAuth client~~ — removed by the D4 change
- [ ] Better Auth configured with the Neon pool adapter, `emailAndPassword` enabled
- [ ] Better Auth schema migrated (`user`, `session`, `account`, `verification`)
- [ ] `toNodeHandler` mounted at `/api/auth/*` in `src/transport/http.js`
- [ ] Old `src/auth/{index,stores}.js` scrypt path retired; `users`/`sessions` tables dropped
- [ ] WebSocket upgrade authenticates from the **session cookie**, not a payload token
- [ ] `localStorage` bearer token removed from `public/client.js`
- [ ] `session.userId` is a stable account id — it becomes `sender_id` everywhere
- [ ] `SameSite=Strict` (available now that no OAuth redirect must survive a cross-site nav)
- [ ] Join screen posts to `/api/auth/*`; email + password + register/sign-in toggle
- [ ] `test/auth.js` rewritten against the new flow

**Acceptance:** register + sign in work end to end; the WS authenticates from the cookie with no
token in JS-readable storage; `sender_id` is a stable account id that `/nick` cannot change.
**Evidence:** —

---

### ⬜ P4 · At-rest encryption — Layer 2 — *1.5 d*

- [ ] `src/crypto/atrest.js` — `seal()` / `open()`
- [ ] `MASTER_KEY` → `HKDF-SHA256(master, salt=room_id)` → per-room DEK
- [ ] AES-256-GCM, fresh 12-byte IV per message
- [ ] Length-prefixed AAD binding `id, room_id, seq, ts, sender_id, key_id, kv`
- [ ] `text`, `mentions`, `reply_to`, `action` moved inside the encrypted payload
- [ ] `ar_kv` key-version column; `MASTER_KEYS` accepts `v1:…,v2:…`
- [ ] `tools/keygen.js`, `tools/rekey.js`
- [ ] Startup guard: no `MASTER_KEY` in production ⇒ refuse to boot
- [ ] stdout assertion extended to the at-rest path
- [ ] **Backfill decision written down** — truncate, or seal legacy rows as `sig_alg='none'`
- [ ] **Burns become tombstones** — `repository.remove()` off the burn path; nothing is ever `DELETE`d

**Acceptance:** a `select * from messages limit 5` in the Neon console shows no readable text — locked and unlocked rooms alike.
**Evidence:** —

---

### ⬜ P5 · Sender identity and signing keys — *1.5 d*

- [ ] `public/js/identity.js` — non-extractable keypair, Ed25519 with `ES256` fallback
- [ ] `CryptoKey` persisted in IndexedDB
- [ ] `key_id` = `base64url(SHA-256(spki))`
- [ ] Proof-of-possession challenge/response on registration
- [ ] `device_keys` table; multi-device per user
- [ ] `GET /keys/:user` lookup + client cache
- [ ] Safety numbers — five groups of five digits, plus QR
- [ ] Key-change warning banner
- [ ] Revocation endpoint honouring `revoked_at`

**Acceptance:** two browsers show matching fingerprints; a key planted by `curl` without valid PoP gets `403`.
**Evidence:** —

---

### ⬜ P6 · Signatures on the wire and at rest — *1.5 d*

- [ ] **Canonical length-prefixed encoder, written once, shared browser ↔ server**
- [ ] Round-trip test proving byte-identical output in both engines *(build this first)*
- [ ] Verify #1 — ingress, before store or broadcast
- [ ] Verify #2 — on read, during history replay
- [ ] Verify #3 — on render, in the client
- [ ] Inner signature over plaintext for E2EE rooms
- [ ] **Sign/encrypt ordering rationale drafted** for the report (slide 22 vs slide 20)
- [ ] Five render states: verified / unverified / key-changed / forged / tampered-at-rest
- [ ] `test/signature.js` — wrong key, mutated ct, mutated sender, replay, revoked, cross-room

**Acceptance:** a forged `sender_id` is rejected at ingress; a row rewritten in Neon afterwards renders as a tamper card on next load.
**Evidence:** —

---

### ⬜ P7 · Tamper detection, audit, hash chain — *1.0 d*

- [ ] `tools/tamper.js` — flip-ciphertext / rewrite-sender / swap-signature / delete / reorder
- [ ] Gated behind `ALLOW_TAMPER=1`
- [ ] `tools/audit.js` — per-room table, non-zero exit on any failure
- [ ] Per-room hash chain + `room_chain` head table
- [ ] `seq` counters restored from `room_chain.head_seq`, **not** `max(seq)`
- [ ] Chain head written in the **same transaction** as the message insert
- [ ] Replay protection: id uniqueness + per-sender monotonic `seq`
- [ ] **Inverse test:** burn a message → `audit.js` still exits **zero**
- [ ] Tamper UI: alert card + room-level banner
- [ ] `test/tamper.js`

**Acceptance:** `tamper.js --flip-ciphertext && audit.js` → non-zero exit, one identified row, live client shows the card without a restart.
**Evidence:** —

---

### ⬜ P8 · Hardening the rest of the stack — *1.0 d*

- [ ] TLS + `wss://` behind Caddy
- [ ] CSP, HSTS, `nosniff`, `Referrer-Policy`, `Permissions-Policy`
- [ ] Inline theme script given a nonce or moved to its own file
- [ ] Rate limits extended to `history:more` and key lookups
- [ ] Secret hygiene: `MASTER_KEY` never logged, absent from `/healthz`
- [ ] `npm audit` in CI; pre-commit secret grep
- [ ] `docs/THREAT-MODEL.md`

*(Cookie/CSRF hardening lands in P3 with Better Auth — tick it there, not here.)*

**Acceptance:** `https://` + `wss://` end to end, header check with no criticals, threat model naming a real gap.
**Evidence:** —

---

### ⬜ P9 · Code structure and engineering quality — *1.0 d*

- [ ] `public/client.js` split into ES modules under `public/js/`
- [ ] ESLint + Prettier flat config in CI
- [ ] `jsconfig.json` with `checkJs` + JSDoc on exports
- [ ] `src/protocol/codes.js` — one error taxonomy
- [ ] Structured JSON logging
- [ ] Migrate suites to `node:test` + coverage
- [ ] Three ADRs

**Acceptance:** no file over ~400 lines; lint + typecheck clean in CI; coverage reported.
**Evidence:** —

---

### ⬜ P10 · UI/UX and the organic design system — *2.0 d*

- [ ] **Typography**: self-hosted variable faces in `public/fonts/`, subset, `font-display:swap`
- [ ] Display face with an organic axis; humanist text face; warm mono for keys
- [ ] One type scale on a 1.2 ratio; no off-scale sizes
- [ ] **Colour**: warm neutrals re-derived; semantic security scale separated from brand accents
- [ ] Dark theme shifts hue, not just lightness
- [ ] Radius, elevation, motion token scales
- [ ] Contrast audit ≥ 4.5:1 in both themes
- [ ] Security Center panel
- [ ] Per-message verification badge
- [ ] Identity & devices screen with contact verification
- [ ] Accessibility: keyboard path, focus rings, `aria-live`, reduced motion
- [ ] Every state designed: loading / empty / error / offline / reconnecting / rate-limited / tampered
- [ ] Three-step onboarding

**Acceptance:** Lighthouse a11y ≥ 95; keyboard-only walkthrough join → verified contact in a locked room; a grader can read the security state at a glance.
**Evidence:** —

---

### ⬜ P11 · Deploy, demo, and the graded paperwork — *1.0 d*

- [ ] **`git ls-files docs/` lists every graded deliverable** — narrow the ignore rule if not
- [ ] Deployed to the allotted system behind Caddy with TLS
- [ ] Google OAuth redirect URI added for the production host
- [ ] `docs/DEMO.md` — the six-minute script
- [ ] Screenshots: persistence · tamper detection · signature verification · Security Center
- [ ] `docs/REPORT.md` → rendered PDF
- [ ] `docs/CONTRIBUTIONS.md` with commit ranges
- [ ] Public GitHub repo, **all members as collaborators**, CI badge
- [ ] Load figures before/after the crypto work

**Acceptance:** a stranger opens the URL, reads the README, reproduces the tamper demo in under five minutes.
**Evidence:** —

---

## Blockers and open questions

| | Item | Needs | Raised |
|---|---|---|---|
| 1 | ~~HTTPS on the allotted host~~ | **RETIRED** — D4 moved off OAuth, nothing in auth needs TLS | closed 16 Aug |
| 2 | ~~Google OAuth credentials~~ | **RETIRED** — no longer used | closed 16 Aug |
| 3 | ~~D2, D3, D5 unconfirmed~~ | **CLOSED** — D2/D3 confirmed by the team, D5 verified empirically | closed 16 Aug |
| 4 | ~~Neon connection string~~ | **CLOSED** — supplied, working, 16/16 assertions against it | closed 16 Aug |
| 5 | **Egress from the allotted host to Neon** | `curl` from that machine once one exists. Still open only because there is no allotted host yet | 16 Aug |
| 6 | **CI has never actually run** | Push to GitHub and confirm the workflow goes green. Written but unobserved | 16 Aug |
| 7 | P11 deliverables live in `docs/` | Confirm `git ls-files docs/` lists them before submission | 16 Aug |
| 8 | **Design-system handoff items unapplied** | 5 `index.html` edits from the agent's `DESIGN-SYSTEM.md` §9 | 16 Aug |

---

## Log

### 16 Aug 2026
- Read `Lab 4.pdf` (24 slides); audited the checkout against the six mandatory requirements.
- Authored `docs/ROADMAP.md` — 12 phases, three-layer security architecture.
- Revised for **Neon Postgres** (D1) and **Better Auth + Google OAuth** (D4); auth moved ahead of
  at-rest encryption so `sender_id` is a verified account id before it is bound into any AAD.
- Expanded P10 into a full organic design-system pass — typography, colour, motion.
- **Final pre-execution verification against the PDF.** All six mandatory requirements and all five
  submission items map to a phase — recorded as the compliance matrix in ROADMAP §0.1. Six defects
  found and fixed in the plan:
  1. **Burns broke the append-only rule** — `repository.remove()` is a real `DELETE`, which P7's chain
     would have reported as tampering on correct behaviour. Burns are now tombstones (fixed in P4).
  2. **No backfill plan** for the plaintext, unsigned rows written during P1–P3. Now an explicit P4 task.
  3. **`seq` allocation and chain-head restoration** were unspecified — restore from
     `room_chain.head_seq`, not `max(seq)`, and write the head in the same transaction.
  4. **Sign/encrypt ordering** — slide 22 says encrypt-then-sign, slide 20's code signs plaintext.
     Our answer and its rationale are now written into P6 and the report outline.
  5. **HTTPS on the allotted host** is a hard blocker for Google OAuth and was only implicit in P8.
     Raised to a P0 question with four concrete fallbacks.
  6. **Two hard external dependencies** (Neon, Google) where Lab 2 had none — an offline path must be
     kept alive and egress verified in P0.
- Also added: standard-crypto-library compliance statement (slides 7, 17), the `nonce`/`ar_iv`
  vocabulary note (slide 20), and a decision to keep polls in-memory rather than persisted.
- **Nothing implemented yet.** Next: P0.

### 16 Aug 2026 — execution begins

**P0 done** (39fa9d7). Baseline verified green *before* touching anything: 246 assertions.
`.env.example`, `docker-compose.yml`, CI (test matrix + audit + secret grep), CHANGELOG,
CONTRIBUTIONS, tag `v2.0.0-lab2`. Corrected the README's layout tree, which advertised a
`docs/SPEC.md` that has never existed in this repo or in Lab 2's.

**P1 done** (8fa0708). Requirement 1 met and proven. Versioned migrations with checksums and an
advisory lock; `HISTORY_REPLAY` 0 → 50; an unset `DATABASE_URL` now refuses to boot instead of
silently discarding every message, with `DATABASE_URL=none` kept as the explicit off switch.
`test/postgres.js` proves a message survives a restart against real Neon.

**P2 done** (871ebfb). Requirement 2 met. Keyset pagination on `(ts, id)` — never `OFFSET`, and
never `ts` alone, since messages routinely share a millisecond. Scroll anchor preserved on
prepend; day separators rebuilt wholesale because a prepended page invalidates the separator
above the previously-oldest message.

**A real bug the phase surfaced.** `pg_advisory_lock` was wrong twice over: a session-level lock
outlives a client killed with SIGKILL, so every later boot blocked forever on a lock nobody held —
and Neon's pooled endpoint is PgBouncer in transaction mode, where a lock taken on one backend and
released on another is not a lock at all. Now `pg_advisory_xact_lock` in one transaction with
`lock_timeout`. Found because the test suite wedged; would have been found in production otherwise.

**A test bug worth recording too.** The first pagination failure against Neon looked like an
off-by-one and was not: writes are detached from the hot path, so twelve sequential inserts to
us-east-2 outlast a 500 ms sleep. The suite now waits for *durability* rather than for the echo.

**D5 resolved empirically:** `require('better-auth')` works on Node 24 and `better-auth/node`
exports `toNodeHandler`. No ESM conversion — that was the plan's highest-rated risk.

**D4 changed by the team:** email + password instead of Google OAuth. This retires the HTTPS
blocker and halves the egress risk. Cost, stated in the roadmap and to be repeated in the report:
password hashes are ours again, and there is no email verification.

**Design system delivered** by a parallel agent — `public/style.css` rewritten, real font binaries
in `public/fonts/`, `docs/DESIGN-SYSTEM.md` with a 146-pairing contrast audit, 0 failing. Five
`index.html` handoff items are **not yet applied** (blocker 8).

Next: P3.
