# ChatFat

Real-time group chat on **raw WebSockets** — no Socket.IO, no framework, no build step.
One Node process serves the browser client over HTTP and relays every message over a
WebSocket on the same port. Rooms can be **locked**: end-to-end encrypted in the browser,
with the server reduced to a blind relay that stores and forwards ciphertext it cannot read.

```bash
npm install
npm start                              # port 3000, no accounts, nothing stored
```

Open the printed **lan** link on each machine. If one cannot connect, the firewall is the
first suspect: `sudo ufw allow 3000/tcp`.

---

## One switch

`DATABASE_URL` is the only thing that changes what this server is.

| `DATABASE_URL` | Accounts | Messages |
| --- | --- | --- |
| *(unset)* | off — a username is a claim, not an identity | nothing stored, nothing replayed |
| `memory` | on, in-process | stored in the heap, lost on restart |
| `postgres://…` | on, durable | stored in Postgres |

```bash
PORT=9000 npm start
DATABASE_URL=memory npm start
DATABASE_URL='postgres://user:pass@host/db' npm start
npm run dev                            # node --watch
```

**Recording and replaying are separate questions.** With a database configured, messages
*are* written — but `HISTORY_REPLAY` governs how many a joining client is handed, and it is
`0` by default. You see what is said while you are in a room, and nothing else.

---

## Commands

```
/help                       list every command
/rooms                      list the rooms on this server
/join <room>                switch to another room
/leave                      leave this room, back to the lobby
/users                      who is in the room right now
/w <user> <message>         private message (aliases: /whisper, /msg)
/me <action>                emote
/poll Question? a | b | c   open a live poll
/burn <seconds> <message>   self-destructing message
/nick <name>                change your display name
/ping                       show round-trip time
/clear                      clear your own view of the log
/theme                      switch light / dark / system
/quit                       leave

/lock <passphrase>          turn this room into an encrypted room
/unlock <passphrase>        supply the key for an encrypted room you are in
/key                        show the key fingerprint for this room
/forget                     drop the stored key for this room from this browser
/seal                       toggle sealed (E2E encrypted) whispers
```

A message beginning with `//` escapes the parser and is sent as literal text starting
with a single `/`.

---

## Encrypted rooms

The server relays over plain `ws://` on a LAN. Anyone on that network — and the operator,
and anyone who reads the Postgres table — can read every message. A locked room fixes that:
the key is derived in the browser from a passphrase that is never transmitted, and the
server has no code path that could decrypt.

```
salt  = SHA-256("ChatFat-room-v1|" + roomId)          deterministic, so a member who
K     = PBKDF2-HMAC-SHA-256(passphrase, salt,         joins later derives the key from
                            250 000 iterations, 256)  the passphrase alone
```

Messages are **AES-256-GCM** with a fresh 96-bit IV, and the AAD binds each ciphertext to
its room and key epoch so it cannot be replayed elsewhere. Whispers get their own scheme —
ephemeral **ECDH P-256** + HKDF, encrypted twice so your own log stays readable.

### What it protects, and what it does not

| Protected | **Not** protected |
| --- | --- |
| A passive listener on the LAN reading message text | Traffic analysis: who is in which room, when, how often |
| The operator reading stored message text | Metadata: sender names, timestamps, sizes, reactions, poll tallies, typing, presence |
| A database dump leaking conversation content | A member of the room — anyone with the passphrase reads everything |
| Someone joining later reading the backlog | An offline dictionary attack on a **weak** passphrase (hence the ≥ 10 character rule) |
| | A compromised browser, a keylogger, or a screenshot |
| | The server tampering with *delivery* — it can drop or reorder frames, it just cannot read them |

A locked room can never be unlocked back to plaintext. That would be a downgrade attack:
someone silently turns encryption off and everybody keeps typing.

Rotating the passphrase (`/lock` again) protects **new** messages. Anyone who already had
the old one can still read older ones — rotation does not re-encrypt history.

---

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `PORT` | `3000` | Listen port |
| `HOST` | `0.0.0.0` | Bind interface. `127.0.0.1` keeps it local |
| `ALLOWED_ORIGINS` | *(empty)* | Comma-separated origins allowed to open a socket. Empty ⇒ the browser's `Origin` host must equal the `Host` it dialled |
| `DATABASE_URL` | *(empty)* | The one switch — see above |
| `DATA_DIR` | `./data` | Where `rooms.json` is written, when there is no database |
| `HISTORY_REPLAY` | `0` | How many stored messages a joining client receives. `0` replays nothing |
| `HISTORY_CAP` | `200` | Per-room in-memory buffer. Bounds how far back an edit/react/reply can reach; **not** a browsable window |
| `MAX_ROOMS` | `24` | Ceiling on rooms |
| `HEARTBEAT_MS` | `15000` | Heartbeat sweep interval |
| `AUTH_MAX_ATTEMPTS` | `10` | Failed sign-ins per minute per IP before HTTP 429 |
| `ENCRYPTION_ENABLED` | `1` | Set to `0` to forbid locking rooms on this server |
| `MAX_CIPHERTEXT` | `12288` | Byte cap on one ciphertext envelope |
| `ChatFat_ENV_FILE` | *(unset)* | Set to `off` to skip reading `.env` entirely. The test suites set this |

A `.env` in the repo root is read at startup. **The real environment always wins.**

---

## Layout

```
server.js                  entry point: loads src/app, installs signal handlers, starts
src/
  env.js                   minimal .env loader (Node 18 compatible, real env always wins)
  config.js                every tunable; the ONLY file that reads process.env
  logger.js                one prefixed logger, one seam
  app.js                   composition root: boot order, banner, shutdown
  state/hub.js             all mutable server state + id/colour/session factories
  db/pool.js               the single Postgres pool + schema migration (lazy `pg` require)
  auth/
    index.js               scrypt hashing, credential validation, register/login
    stores.js              MemoryStore | PgStore behind one interface
  rooms/
    index.js               creation, occupancy, roster, typing, lobby/room transitions
    directory.js           room directory persistence: Postgres or debounced JSON file
  messages/
    history.js             per-room in-memory ring buffer + burn timers
    repository.js          durable storage: Null | Memory | Pg behind one interface
    polls.js               poll serialisation (tally computed, never stored)
  protocol/
    frames.js              the wire envelope; send / broadcast / broadcastGlobal / fail
    validation.js          text cleaning, token bucket, server-side mention resolution
  transport/
    http.js                static serving, /healthz, /auth/* routes, login throttle
    websocket.js           upgrade policy, dispatch, lifecycle, heartbeat reaper
    handlers.js            one function per client frame type
  crypto/
    envelope.js            ciphertext envelope validation and size accounting
public/
  index.html               join screen + lobby + chat shell (three screens, one document)
  style.css                design tokens, layout, components, light/dark
  client.js                socket lifecycle, reconnect, state machine, all rendering
  crypto.js                WebCrypto key derivation, encrypt/decrypt, key store
test/
  harness.js               spawned servers and real WebSocket clients
  protocol.js              the main suite — no database
  auth.js                  registration through impersonation
  persistence.js           storage + replay
  crypto.js                encrypted rooms and sealed whispers
tools/
  loadtest.js              broadcast fan-out latency as room size grows
docs/
  SPEC.md                  the full product and engineering specification
  design.html              the design document, linked to the live stylesheet
```

Two rules hold the module graph together: `config.js` is the only module that reads
`process.env`, and transport depends on everything while nothing depends on transport.
`pg` is required **lazily**, so a checkout without it installed still runs in no-database
and `memory` modes.

---

## Tests

```bash
npm test                   # protocol   — no database
npm run test:auth          # accounts
npm run test:persistence   # storage + replay
npm run test:crypto        # encrypted rooms + sealed whispers
npm run test:all
```

Every suite spawns a real server and drives it with real WebSocket clients. There is no
mocked clock anywhere: the heartbeat reaper and the burn fuse are real timers and the
suites wait them out. Each gets `ChatFat_ENV_FILE=off` and an isolated `DATA_DIR`, so a
developer's `.env` cannot reach a suite and fail it for the wrong reason.

The crypto suite reimplements the browser's key derivation independently, so it checks
`public/crypto.js` rather than calling into it — and it captures the server's stdout and
asserts that no message text ever appears there.

```bash
npm run loadtest                                   # 4, 16, 32, 64 clients
node tools/loadtest.js --encrypted                 # the same rungs in a locked room
node tools/loadtest.js --clients 8,64 --duration 12 --out results.json
```

All load clients share one process and one machine, so the figures exclude the network.
They measure the server, not the LAN.

---

## Disconnect handling

"Graceful handling of client disconnections" hides three failure modes, and **only two of
them fire a close event**.

| Failure | What the server sees | How it is caught | Reason |
| --- | --- | --- | --- |
| Tab closed, `/quit` | Close frame, code 1000 | `close` handler, instantly | *left* |
| Browser killed | TCP FIN/RST, code 1006 | Same handler | *lost connection* |
| **Cable pulled, Wi-Fi off** | **Nothing at all** — the socket stays `OPEN` forever | Heartbeat sweep only | *timed out* |

The third row is why the heartbeat is not optional. Worst-case detection is two intervals,
30 s at the default. All three paths converge on one idempotent `removeSession`.

---

## Docker

```bash
docker build -t chatfat .
docker run -p 3000:3000 -v chatfat-data:/data chatfat
```

`node` is PID 1 via the exec-form `CMD`, so it receives `SIGTERM` directly and the shutdown
handler closes every socket with **1001 "server going away"** before exiting. The banner
inside a container lists container-internal addresses — for a LAN demo, hand out the host's IP.

Behind a proxy, set `ALLOWED_ORIGINS` explicitly when the public name differs from the bound
host, and make sure `Upgrade` and `Connection` are forwarded. Under TLS the client dials
`wss://` automatically — it derives the scheme from `location.protocol`.

---

## Known limits

- **Authentication is optional and off by default.** Without `DATABASE_URL` a username is a
  claim, not an identity. With it, identity is real — but rooms are still open: any signed-in
  user can join any room they can see. Encryption is what makes a room actually private.
- **Plaintext `ws://`.** Encrypted rooms protect message content over a plaintext transport,
  but credentials on `/auth/*` are still in the clear without TLS. Use a throwaway password
  on a lab LAN.
- **Single process.** Every room lives in one heap, capped at 24 rooms.
- **One room at a time.** No unread badges for rooms you are not in, because you are not
  receiving them at all.
- **Ephemeral messages are not secure deletion.** They leave every client's DOM and the
  database, but a recipient who screenshots still keeps it.
- **Encryption protects content, not metadata.** See the table above — and the product says
  this in the key modal and the room banner, not only here.
