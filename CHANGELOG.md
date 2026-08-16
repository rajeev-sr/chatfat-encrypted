# Changelog

Lab 4 turns the Lab 2 chat into a persistent and secure messaging system.
`v2.0.0-lab2` is the tag to diff against — everything below it is Lab 2.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `docs/ROADMAP.md` — the twelve-phase plan, with a compliance matrix mapping
  each of the six mandatory requirements to a phase, an implementing file and
  a proving test.
- `docs/progress.md` — per-phase checklists and the working protocol.
- `.env.example` — every variable the system reads, with placeholder values
  and the reasoning behind each default.
- `docker-compose.yml` — app plus a local Postgres, so the database path is
  testable with no network.
- `.github/workflows/ci.yml` — test matrix on Node 22 and 24, a dependency
  audit, and a grep that fails the build if a Neon or Google credential is
  ever committed.

### Changed
- `README.md` — the layout tree now lists the files that actually exist. It
  previously referenced `docs/SPEC.md`, which never did.

---

## [2.0.0-lab2] — 14 Aug 2026

The Lab 2 submission. Real-time group chat on raw WebSockets: rooms,
whispers, polls, reactions, edits, self-destructing messages, presence and
typing, optional accounts on Postgres, and end-to-end encrypted rooms with
the server reduced to a blind relay.
