# Contribution report

**CS559 Lab 4 — Persistent and Secure WebSocket Chat**
Required by the lab brief: *"Source code, pdf report and contribution report of each member."*

> **Write this as you go, not the night before.** `git shortlog -sne` and the commit ranges below
> are the evidence; a report assembled from memory at the end reads like one, and the phases were
> split along module boundaries precisely so each member's contribution is separable in the history.

---

## Members

| Member | GitHub | Owns | Phases |
|---|---|---|---|
| Rahul Raj | *(fill in)* | — | — |
| *(fill in)* | `rajeev-sr` | — | — |
| *(fill in)* | *(fill in)* | — | — |

The roadmap's suggested split (`docs/ROADMAP.md` §7) is:

| Role | Owns | Phases |
|---|---|---|
| A — storage & at-rest | Neon, migrations, `src/db/*`, `src/messages/*`, `src/crypto/atrest.js`, `tools/*` | P1 · P4 · P7 |
| B — identity & signatures | Better Auth, Google OAuth, `src/crypto/sign.js`, `public/js/{identity,verify}.js` | P3 · P5 · P6 · P8 |
| C — client & experience | `public/js/**`, the design system, history UX, Security Center, accessibility | P2 · P9 · P10 |

**Assign these before P1 starts** and record the assignment here, so the commit history lines up
with the claim.

---

## Per-member detail

### Rahul Raj

**Phases owned:** *(fill in)*

**Commit range:** `git log --author="Rahul Raj" v2.0.0-lab2..HEAD --oneline`

**Contributions:**
- *(fill in as work lands — one line per meaningful change, not per commit)*

---

### *(Member 2)*

**Phases owned:** *(fill in)*

**Commit range:** *(fill in)*

**Contributions:**
- *(fill in)*

---

### *(Member 3)*

**Phases owned:** *(fill in)*

**Commit range:** *(fill in)*

**Contributions:**
- *(fill in)*

---

## Shared work

Some work was deliberately done together rather than divided, because splitting it would have cost
more than it saved:

- **The canonical signing encoder (P6).** Both the browser and the server must produce byte-identical
  output or every signature fails. Written in one sitting by *(fill in)* rather than integrated from
  two implementations.
- *(add others as they happen)*

---

## Evidence

Regenerate before submission and paste the output here:

```bash
git shortlog -sne v2.0.0-lab2..HEAD
git log v2.0.0-lab2..HEAD --format='%h %an %s' --reverse
```

```
(paste output)
```
