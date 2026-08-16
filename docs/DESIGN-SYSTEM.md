# ChatFat — the design system

**Phase 10a/10b of `docs/ROADMAP.md`.** One hand-written stylesheet, no build step, no framework,
no external request. Everything below lives in `public/style.css`; the faces live in `public/fonts/`.

The short version of what changed: the product used to be set in `system-ui` — a neutral grotesque,
the opposite of organic — with a `--serif` token it barely used; and its accent colours did double
duty as brand *and* as security signal. Both are fixed. Type is now three real faces on one 1.2-ratio
scale. Colour keeps the brand (cream, terracotta, sage, plum-for-encryption) but gains a separate
security scale, a dark theme that shifts hue rather than merely lightness, a four-step elevation
scale, a radius scale and a motion scale. Every text pairing is audited at ≥ 4.5:1 in **both** themes,
with the numbers in §7.

---

## 1 · Typography

### 1.1 What shipped

**Real font binaries, self-hosted.** No CDN link, no fallback-only path. Six `.woff2` files in
`public/fonts/`, all same-origin, so the CSP planned in P8 needs only `font-src 'self'`.
`src/transport/http.js` already carried the `.woff2` MIME entry — it was anticipated.

| Role | Face | Why this one |
|---|---|---|
| **Display** | **Fraunces** — variable, 4 axes | `opsz 9–144`, `wght`, **`SOFT 0–100`**, **`WONK 0–1`**. The `SOFT` and `WONK` axes exist precisely to make letterforms less mechanical, which is the whole brief. Set at `"SOFT" 38, "WONK" 1` with `font-optical-sizing: auto`. |
| **Text** | **Source Sans 3** — variable, roman + true italic | Humanist, not geometric: open apertures and calligraphic stroke contrast are what let a sans read *warm* at 15.5 px in a dense log. Real italics rather than a synthesised oblique, because `/me` actions, tombstones and the typing indicator all use them. |
| **Mono** | **IBM Plex Mono** 400 + 600 | Warmer than JetBrains Mono, and it carries key fingerprints and safety numbers. |

**The mono needed one non-obvious fix.** Google's web subset of IBM Plex Mono has the `zero` feature
*stripped* — so a slashed zero is unavailable and `0` versus `O` is a guess. The files here are
subset from the **upstream OFL build** (`google/fonts` → `ofl/ibmplexmono`) with `zero` retained, and
every mono surface sets `font-feature-settings: "zero" 1`. A safety number that cannot distinguish
`0` from `O` is not a safety number. `1`/`l`/`I` are already unambiguous in Plex Mono by default.

### 1.2 Byte budget — honest numbers

| File | On disk | Fetched when |
|---|---|---|
| `fraunces-latin-var.woff2` | 120.8 KB | immediately (wordmark is above the fold) |
| `source-sans-3-latin-var.woff2` | 28.8 KB | immediately (all body copy) |
| `ibm-plex-mono-latin-400.woff2` | 13.5 KB | immediately (status URL on the join screen) |
| `source-sans-3-latin-italic-var.woff2` | 28.5 KB | only when italic text renders |
| `source-sans-3-latin-ext-var.woff2` | 60.0 KB | only when a `latin-ext` codepoint appears (`unicode-range` gated) |
| `ibm-plex-mono-latin-600.woff2` | 14.5 KB | only when 600-weight mono renders |
| **Total on disk** | **266 KB** | **first paint, English session: ~163 KB** |

The roadmap's target was "~120 KB total". **We are over it, deliberately, and the overage is
Fraunces.** A four-axis high-contrast variable serif is simply a large binary — `pyftsubset` with the
`wght` axis pinned to 300–700 and the charset cut to latin-basic only saved 11 KB (120.8 → 109.9 KB),
which is not worth losing the axis range for. The two levers if the budget must be met later:

- `fonttools varLib.instancer fraunces-latin-var.woff2 opsz=24 -o …` — pinning the optical-size axis
  is the big win, at the cost of Fraunces auto-adjusting between 20.5 px and 42.5 px.
- Swap Fraunces for **Newsreader**, the roadmap's named calmer alternative, which has no `SOFT`/`WONK`.

Everything except the three first-paint files is lazy, so the number that matters to a user on the lab
LAN is ~163 KB, not 266 KB. All faces use `font-display: swap`.

### 1.3 The scale

One 1.2 ratio, declared as tokens. **`public/style.css` contains no `font-size` outside this scale** —
verified mechanically (§8).

```css
--fs-1:12px    --fs-2:14px    --fs-3:15.5px  --fs-4:17px    --fs-5:20.5px
--fs-6:24.5px  --fs-7:29.5px  --fs-8:35.5px  --fs-9:42.5px
```

The old stylesheet had 15 off-scale sizes (10, 10.5, 11, 11.5, 12.5, 13, 13.5, 14.5, 18, 20, 23, 26,
27, 34, 36, 44). Everything below 12 px moved **up** to `--fs-1`, which is an accessibility gain as
well as a consistency one — badges, the `away` tag, RTT and the group-hover ministamp were all at
10–11 px. To pay for the extra bulk, those chips lost a little vertical padding and gained tighter
tracking.

| Line height | Value | Used for |
|---|---|---|
| `--lh-display` | 1.08 | 29.5 px and up |
| `--lh-head` | 1.2 | 20.5–24.5 px |
| `--lh-log` | **1.45** | the message log (roadmap-specified) |
| `--lh-ui` | 1.35 | single-line chrome |
| `--lh-prose` | 1.6 | paragraphs, body default |

`--ls-display: -.022em` closes up display sizes; `--ls-caps: .12em` opens out uppercase micro-labels.
`--measure: 65ch` caps every prose block (`.cf-blurb`, `.cf-tagline`, `.cf-hint`, `.lede`, `.cf-text`).

### 1.4 The rules that follow from the scale

- **The display face never appears below 20.5 px.** That forced two real changes: `.cf-btn` moved from
  `--serif` at 14 px to `--sans` at 600 weight, and `.cf-poll h4` went 18 px → 20.5 px. `.cf-brand`
  sits at 20.5 px in the top bar in every breakpoint, with its `/ room-name` half in the sans at 12–14 px.
- **`text-wrap: balance`** on `.cf-wordmark`, `.cf-h`, `.cf-spotlight h3`, `.cf-modal h3`,
  `.cf-room h4`, `.cf-poll h4`, `.cf-brand`; **`text-wrap: pretty`** on the prose blocks.
- **`font-variant-numeric: tabular-nums`** on timestamps, the group ministamp, RTT (roster and the
  spark meter), poll tallies, the composer counter, the burn fuse, the roster count and every
  fingerprint.
  *Caveat worth knowing:* Source Sans 3's web subset has no `tnum` feature, so the declaration alone
  would be a no-op there. Every one of those surfaces is therefore routed through `--mono`, which is
  monospaced by construction and so tabular whether or not the feature survives subsetting. The
  declaration stays because it is correct intent and it does work in the fallback stack.
- **`.cf-fp`** is a new utility for P5's safety numbers: mono, tabular, slashed zero, `.06em` tracking
  and `.5em` word-spacing, so five groups of five read as five groups.

---

## 2 · Colour

### 2.1 The brand is unchanged; the vocabulary around it is new

Cream ground, terracotta (`--brass`), sage (`--jack`), plum-for-encryption (`--seal`). What changed is
that these no longer have to mean two things at once.

**Three token families, and they do not overlap:**

| Family | Tokens | Means |
|---|---|---|
| **Brand** | `--brass` `--jack` `--seal` `--good` | identity, affordance, encryption. **Never** a security verdict. |
| **Semantic** | `--alert` | "your input is wrong", "the server said no". **Never** a security verdict. |
| **Security** | `--verified` `--pending` `--tamper` (+ `--seal`) | authenticity and integrity. **Never** decoration. |

`--seal` sits in both the brand and the security column because encryption is the one place where the
brand *is* the security story — a locked room reads as a different kind of place. It means encryption
and nothing else; it never signals verification.

The concrete fix the roadmap asked for: **`.cf-fail`** — a message that could not be decrypted or
verified — used `--alert`, the same red as an invalid form field. It now uses `--tamper` plus a 1.5 px
ring, so it can never be mistaken for a typo in a password box.

### 2.2 Light palette

| Token | Value | Role |
|---|---|---|
| `--ground` | `#f6ecda` | page canvas |
| `--surface` | `#efe1c9` | level-1 panels: sidebar, log, cards, modal, join card |
| `--panel` | `#e7d6b9` | sunken wells: chips, badges, bar tracks, the facts box, the spark canvas |
| `--raised` | `#fdf9f1` | floating: composer, poll, rail, toast, autocomplete, inputs |
| `--ink` | `#1e1c19` | body |
| `--muted` | `#544d42` | secondary |
| `--faint` | `#6a6254` | tertiary |
| `--brass` / `--brass-w` | `#96481b` / `#ffe1d0` | terracotta |
| `--jack` / `--jack-w` | `#4f6136` / `#dfeac7` | sage |
| `--seal` / `--seal-w` | `#7a5480` / `#f0e4f0` | plum · encryption |
| `--alert` / `--alert-w` | `#a4392c` / `#f8ded6` | input and protocol errors |
| `--verified` / `-w` | `#2f6b45` / `#d8ecdd` | signature verified |
| `--pending` / `-w` | `#7a5808` / `#f7e7c2` | not yet checked (TOFU) |
| `--tamper` / `-w` | `#6f2230` / `#f2d8d9` | forged or altered |
| `--bubble-me` | `#ffeee2` | own-message bubble |
| `--scrim` | `#2a2418` @ 58 % | modal backdrop |

Two brand values moved, and both moves were forced by the audit, not by taste:

- **`--brass` `#b2622d` → `#96481b`.** The old terracotta measured **3.50:1** on `--surface`. It is
  used both as text (`.cf-eyebrow`, `.cf-btn-ghost`, `.cf-room .go`, links) *and* as a fill carrying
  `--ground` text (`.cf-btn-primary`, `.cf-spotlight`, `.cf-jump`), so it had to clear 4.5:1 in both
  directions. `#96481b` gives 5.03:1 on surface and 5.53:1 as a fill.
- **`--jack` `#728157` → `#4f6136`.** The old sage measured **3.51:1** on its own `--jack-w` wash —
  the exact pairing used by `.cf-pill` and `.cf-badge.pv`. Now 5.40:1.

`--faint` `#82796a` → `#6a6254` is the "cream-on-cream secondary text" the roadmap flagged first. It
measured **3.56:1** on `--ground`. Now 5.14:1.

### 2.3 Dark palette — a theme, not a darkening

The old dark tokens were the light hues at lower lightness, which is why they read muddy. The grounds
now shift **hue** to a warm charcoal with a green-brown undertone (~78° at very low chroma), and every
accent is **desaturated as it is lightened** rather than merely lightened.

| Token | Value | Note |
|---|---|---|
| `--ground` | `#161711` | green-brown charcoal |
| `--panel` | `#1a1c15` | |
| `--surface` | `#1f211a` | |
| `--raised` | `#292c23` | |
| `--ink` | `#f2ece0` | warm off-white |
| `--muted` | `#a39f8d` | |
| `--faint` | `#999583` | |
| `--brass` / `-w` | `#dd9d78` / `#452b18` | was `#f6a06b` — desaturated, not just lightened |
| `--jack` / `-w` | `#a3b092` / `#2e3a22` | was `#aebf92` |
| `--seal` / `-w` | `#cbb0d2` / `#372a3d` | was `#d5aede` |
| `--alert` / `-w` | `#f0a18a` / `#4a231a` | was `#f09580` |
| `--verified` / `-w` | `#93c1a2` / `#22392b` | |
| `--pending` / `-w` | `#d4b784` / `#40331b` | |
| `--tamper` / `-w` | `#d98c95` / `#3d2226` | |
| `--bubble-me` | `#33291c` | |
| `--scrim` | `#080905` @ 72 % | |

**One asymmetry, deliberate and documented.** In light, the shell panels are *recessed* into the
ground (`--surface` is darker than `--ground`) and floating things are near-white; in dark, panels are
*lifted* (`--surface` is lighter than `--ground`). This is not an oversight — a dark UI cannot put a
panel below its own ground and still read a shadow, so dark elevation has to be carried by lightness
where light elevation is carried by shadow. Both directions produce the same message: "this panel is
not the page." Light reads as paper; dark reads as emission.

**`--alert` versus `--tamper` in dark deserves a note.** In light they separate easily — bright brick
`#a4392c` against deep oxblood `#6f2230`. In dark both must lighten, so they converge in hue. They are
separated by **saturation** (alert is a bright salmon, tamper a muted dusty rose) **and by treatment**:
every tamper surface ships a 1.5 px ring and an icon, `.cf-alert` ships a flat wash. Colour is never
the only channel carrying the difference. That is the accessible answer regardless of theme.

### 2.4 Per-user colour

`--uc` is a hue set inline by `client.js`; the stylesheet supplies the saturation and lightness. The
light lightness dropped **30 % → 26 %** because at 30 % the worst hue (60°, yellow-green) measured
3.81:1 on `--surface`. The whole 360° wheel is swept in the audit; the worst hue is reported.

Avatars used to need two duplicated dark-mode rules with hard-coded HSL. They are now four tokens —
`--uc-av-s`, `--uc-av-bg-l`, `--uc-av-fg-s`, `--uc-av-fg-l` — and **one** rule, which deleted the
`.cf-av` block from inside the `prefers-color-scheme` media query.

### 2.5 Lines, hovers, scrims

| Token | Light | Dark | Role |
|---|---|---|---|
| `--line-soft` | ink 7 % | ink 8 % | decorative separators |
| `--line` | ink 15 % | ink 17 % | ordinary borders |
| `--line-firm` | ink **54 %** | ink **46 %** | 3:1 component boundaries |
| `--hover` | `--raised` 60 % | `--raised` 60 % | hovered rows |
| `--hover-firm` | ink 8 % | ink 8 % | hovered controls already on `--raised` |

`--line-firm` is new and it is the WCAG **1.4.11** token. A `.cf-input` sitting on a `.cf-join-card`
differs from its card by only 1.24:1 in fill, so the *border* is the only thing identifying the
control; the same is true of an unchecked `.cf-box` and an off `.cf-toggle`. Those three get
`--line-firm` (≥ 3.45:1 everywhere); everything decorative keeps the hairlines.

**Hover became a lift, not a darkening.** `.cf-msg:hover` used `ink 4%`, which pushed the timestamp to
**4.33:1**. Mixing toward `--raised` instead raises contrast in both themes and reads as the row
coming forward — which is also the more organic gesture.

---

## 3 · Elevation

Four steps, each a **ring plus a two-part shadow** (a tight contact shadow and a wide ambient one), so
a card, a popover and a modal are distinguishable without reading their contents. `--e0` is flat on
purpose. Light shadows are warm brown (`rgba(74,59,34,…)`), never black; dark shadows are black at
higher alpha.

| Step | Ring | Used by |
|---|---|---|
| `--e1` | `--line-soft` | resting cards: `.cf-create`, `.cf-empty`, `.cf-replybar`, `.cf-btn-primary`, the toggle knob, a closed poll |
| `--e2` | `--line-soft` | lifted: `.cf-join-card`, `.cf-room:hover`, `.cf-spotlight`, `.cf-poll`, `.cf-composer` |
| `--e3` | `--line` | popovers: `.cf-rail`, `.cf-ac`, `.cf-toast`, `.cf-jump`, `.cf-composer:focus-within`, `.cf-spotlight:hover` |
| `--e4` | `--line` | overlays: `.cf-modal`, the mobile roster drawer, `.cf-jump:hover` |

`--shadow` and `--shadow-lift` survive as aliases of `--e2` and `--e4`.

## 4 · Radius

Organic means *consistently* soft, not randomly rounded. The old file used 6, 16, 18, 20, 22, 24, 26,
28 and 32 px more or less ad hoc.

```css
--r-1:8px  --r-2:12px  --r-3:18px  --r-4:24px  --r-5:32px  --r-pill:999px  --r-circle:50%
```

`--r-pill` stays the workhorse — it is what makes the product feel soft — and `--r-5` is the shell
radius (cards, modals, the sidebar and log corners). The dead `--r:16px` token was removed.

## 5 · Space

A 4 px spine: `--s-1:4 --s-2:8 --s-3:12 --s-4:16 --s-5:24 --s-6:32 --s-7:40 --s-8:56`. Applied to the
layout rhythm — padding, gaps, section margins. A handful of structural values stay literal (the 34 px
avatar, the 40 px message gutter, the 64 px spark canvas) because they are measurements, not rhythm.

The message gutter went **36 px → 40 px** so a `hh:mm` ministamp at 12 px mono fits without clipping;
`.cf-sys` padding-left followed it, 46 → 54 px, to keep system lines aligned with message text.

## 6 · Motion

**One curve, four durations.**

```css
--ease: cubic-bezier(.2,.75,.25,1)
--dur-1:120ms   hover, colour
--dur-2:200ms   entrance, toggle
--dur-3:320ms   modal, drawer
--dur-4:520ms   burn, decay
```

What moves: message entrance, toast rise, modal scrim fade + card lift, mobile bottom-sheet slide,
button/card hover lift with an active press, input focus ring, roster and rail hovers, poll bar fill,
reaction pop, skeleton shimmer, the scrollback spinner, and a 35° rotation of the theme icon on hover.

**`prefers-reduced-motion` is honoured twice.** Every keyframe animation lives inside
`@media (prefers-reduced-motion: no-preference)`, and a blanket
`@media (prefers-reduced-motion: reduce){ *,*::before,*::after{ animation:none!important;
transition:none!important; scroll-behavior:auto!important } }` closes the file as a backstop against
future edits. With motion reduced, the scrollback spinner degrades to a static ring with one brass
edge — it still reads as "working".

### History must not cascade — how that is guaranteed without touching JS

The entrance animation is scoped to `.cf-log > .cf-msg:last-child` (and the same for `.cf-sys`,
`.cf-poll`, `.cf-encbanner`). Two independent facts make a 50-message backfill impossible to animate:

1. `paintHistoryTop()` inserts older pages **after `#cf-histtop`**, i.e. *prepended* at the top of the
   log. A prepended row is never the last child, so it never matches.
2. Even for an append-style batch, the whole loop runs inside one synchronous task, so only the final
   row is the last child when the browser next paints.

A live message is always the last child at the moment it lands, so it always animates. There is one
known cosmetic edge: two live messages arriving less than 200 ms apart cancel the first animation
mid-flight and it snaps to its finished state. See the handoff in §9 for the precise fix if that ever
becomes visible.

---

## 7 · Contrast audit

Measured, not estimated. `scripts` used: a WCAG 2.1 relative-luminance calculator that **parses the
token values straight out of `public/style.css`**, resolves the `color-mix` washes by alpha
compositing, and sweeps all 360° of the per-user hue wheel reporting the worst case.

**146 pairings across both themes. 0 failing.** Text floor 4.5:1; non-text component boundaries
(WCAG 1.4.11) floor 3:1.

| Pairing | Light | Dark | Floor |
|---|---|---|---|
| `--ink on --ground` | 14.51:1 | 15.32:1 | 4.5:1 |
| `--muted on --ground` | 7.12:1 | 6.78:1 | 4.5:1 |
| `--ink on --surface` | 13.18:1 | 13.83:1 | 4.5:1 |
| `--muted on --surface` | 6.47:1 | 6.12:1 | 4.5:1 |
| `--ink on --panel` | 11.91:1 | 14.62:1 | 4.5:1 |
| `--muted on --panel` | 5.85:1 | 6.47:1 | 4.5:1 |
| `--ink on --raised` | 16.19:1 | 12.07:1 | 4.5:1 |
| `--muted on --raised` | 7.94:1 | 5.34:1 | 4.5:1 |
| `--faint on --ground` | 5.14:1 | 5.99:1 | 4.5:1 |
| `--faint on --surface` | 4.67:1 | 5.41:1 | 4.5:1 |
| `--faint on --raised` | 5.73:1 | 4.72:1 | 4.5:1 |
| `--brass on --ground` | 5.53:1 | 7.87:1 | 4.5:1 |
| `--brass on --surface` | 5.03:1 | 7.10:1 | 4.5:1 |
| `--brass on --raised` | 6.17:1 | 6.20:1 | 4.5:1 |
| `--brass on --brass-w` | 5.23:1 | 5.69:1 | 4.5:1 |
| `--jack on --ground` | 5.79:1 | 7.88:1 | 4.5:1 |
| `--jack on --surface` | 5.26:1 | 7.11:1 | 4.5:1 |
| `--jack on --raised` | 6.46:1 | 6.21:1 | 4.5:1 |
| `--jack on --jack-w` | 5.40:1 | 5.26:1 | 4.5:1 |
| `--seal on --ground` | 5.26:1 | 9.17:1 | 4.5:1 |
| `--seal on --surface` | 4.78:1 | 8.27:1 | 4.5:1 |
| `--seal on --raised` | 5.87:1 | 7.22:1 | 4.5:1 |
| `--seal on --seal-w` | 5.01:1 | 6.84:1 | 4.5:1 |
| `--alert on --ground` | 5.60:1 | 8.73:1 | 4.5:1 |
| `--alert on --surface` | 5.09:1 | 7.88:1 | 4.5:1 |
| `--alert on --raised` | 6.25:1 | 6.88:1 | 4.5:1 |
| `--alert on --alert-w` | 5.13:1 | 6.58:1 | 4.5:1 |
| `--verified on --surface` | 4.92:1 | 8.05:1 | 4.5:1 |
| `--verified on --raised` | 6.04:1 | 7.03:1 | 4.5:1 |
| `--verified on --verified-w` | 5.12:1 | 6.15:1 | 4.5:1 |
| `--pending on --surface` | 5.05:1 | 8.45:1 | 4.5:1 |
| `--pending on --raised` | 6.20:1 | 7.37:1 | 4.5:1 |
| `--pending on --pending-w` | 5.32:1 | 6.39:1 | 4.5:1 |
| `--tamper on --surface` | 8.36:1 | 6.30:1 | 4.5:1 |
| `--tamper on --raised` | 10.27:1 | 5.50:1 | 4.5:1 |
| `--tamper on --tamper-w` | 8.01:1 | 5.59:1 | 4.5:1 |
| `--ground on --brass fill` (btn-primary, spotlight, jump) | 5.53:1 | 7.87:1 | 4.5:1 |
| `--ground on --seal fill` (unlock, sealed send) | 5.26:1 | 9.17:1 | 4.5:1 |
| spotlight `.k` / `p` (ground 88 % over brass) | 4.68:1 | 6.43:1 | 4.5:1 |
| `--ink on --bubble-me` | 15.04:1 | 12.10:1 | 4.5:1 |
| `--brass` link on `--bubble-me` | 5.74:1 | 6.22:1 | 4.5:1 |
| `--ink` on hovered row (`.cf-msg` / `.cf-user`) | 14.94:1 | 12.78:1 | 4.5:1 |
| `--muted` on hovered row | 7.33:1 | 5.66:1 | 4.5:1 |
| `--faint` on hovered row (timestamp) | 5.29:1 | 5.00:1 | 4.5:1 |
| `--ink` on hovered control (`--hover-firm` on raised) | 13.82:1 | 9.63:1 | 4.5:1 |
| `--muted on --brass-w` (`.cf-ac-row.sel`) | 6.73:1 | 4.90:1 | 4.5:1 |
| `--muted` on `.cf-msg.flash` (brass 15 % over surface) | 5.28:1 | 4.64:1 | 4.5:1 |
| `--ink` on `.cf-msg.flash` | 10.76:1 | 10.48:1 | 4.5:1 |
| `--muted` on `.cf-msg.mine-mention` | 5.66:1 | 5.12:1 | 4.5:1 |
| `--ink` on `.cf-msg.mine-mention` | 11.53:1 | 11.58:1 | 4.5:1 |
| `--muted on --seal-w` (`.cf-lockbar .cf-hint`) | 6.78:1 | 5.06:1 | 4.5:1 |
| `--ink on --seal-w` | 13.81:1 | 11.43:1 | 4.5:1 |
| `--jack` "Yes" on `--panel` | 4.75:1 | 7.52:1 | 4.5:1 |
| `--alert` "No" on `--panel` | 4.60:1 | 8.33:1 | 4.5:1 |
| `--ink` on toast code chip (ink 8 % over raised) | 13.82:1 | 9.63:1 | 4.5:1 |
| `--alert` on bad-toast code chip (edge, no fill) | 5.13:1 | 6.58:1 | 4.5:1 |
| `--faint on --surface` (`.cf-histtop.done`) | 4.67:1 | 5.41:1 | 4.5:1 |
| `--alert on --alert-w` (`.cf-histtop.error` button) | 5.13:1 | 6.58:1 | 4.5:1 |
| user colour on `--surface` (worst hue: 60° light, 240° dark) | 4.76:1 | 6.11:1 | 4.5:1 |
| user colour on `--raised` (worst hue) | 5.84:1 | 5.33:1 | 4.5:1 |
| avatar initials on avatar (worst hue) | 5.30:1 | 5.67:1 | 4.5:1 |
| `--line-firm` border on `--surface` | 3.45:1 | 4.01:1 | 3.0:1 |
| `--line-firm` border on `--ground` | 3.55:1 | 4.13:1 | 3.0:1 |
| `--line-firm` border on `--raised` | 3.66:1 | 3.79:1 | 3.0:1 |
| `--line-firm` border on `--seal-w` | 3.50:1 | 3.68:1 | 3.0:1 |
| `--raised` knob on `--line-firm` toggle track | 4.24:1 | 3.50:1 | 3.0:1 |
| `--seal` toggle-on vs `--surface` | 4.78:1 | 8.27:1 | 3.0:1 |
| `--brass` focus ring on `--ground` | 5.53:1 | 7.87:1 | 3.0:1 |
| `--brass` focus ring on `--surface` | 5.03:1 | 7.10:1 | 3.0:1 |
| `--brass` focus ring on `--raised` | 6.17:1 | 6.20:1 | 3.0:1 |
| `--good` dot on `--surface` | 5.26:1 | 7.11:1 | 3.0:1 |
| `--jack` bar fill on `--panel` track | 4.75:1 | 7.52:1 | 3.0:1 |
| `--tamper` ring on `--tamper-w` | 8.01:1 | 5.59:1 | 3.0:1 |

### 7.1 What the audit forced

Five pairings failed on the first pass and were fixed at the point of use rather than by weakening
the palette:

| Failure | Was | Fix |
|---|---|---|
| Spotlight kicker/lede on the terracotta fill | 3.92:1 light | Hierarchy from size and tracking, not `opacity`. The dim is now `color-mix(ground 88%, brass)` → 4.68:1. |
| Timestamp on `.cf-msg.flash` and `.cf-msg.mine-mention` | 3.81 / 4.08:1 | An emphasised row promotes its metadata with it: `--faint` → `--muted`. |
| `.code` chip inside a `.cf-toast.bad` | 4.40:1 light | The ink-8 % wash stacked on `--alert-w`. The chip is now drawn with an edge and no fill → 5.13:1. |
| `.cf-lockbar .cf-hint` | 4.47:1 dark | Long-form safety copy on the plum wash takes `--muted` → 5.06:1. |

### 7.2 Known exemptions, stated rather than hidden

WCAG 1.4.3 exempts disabled controls and purely decorative text. These use `opacity` and are **not**
in the table:

- `.cf-btn[disabled] { opacity:.45 }` — disabled.
- `.cf-composer.locked { opacity:.72 }` — disabled composer in a room you have no key for.
- `.cf-msg.burning { opacity:.25 }` — a transient burn animation, not readable state.
- `.cf-msg .ministamp { opacity:0 }` — revealed on hover/focus; the accessible time is in `.cf-head time`.

One `opacity` was **removed** because it was not exempt: `.cf-user.away { opacity:.55 }` dropped an
away user's name to roughly 2.2:1. Away is now carried by `--muted` on the name plus the existing
`away` tag, with the dimming confined to the avatar.

---

## 8 · Mechanical verification

Everything in this document is checkable, and all of it currently passes:

| Check | Result |
|---|---|
| Every class in `index.html` + `client.js` has a rule in `style.css` | **146 referenced, 0 unstyled** |
| `font-size` values outside the 1.2 scale | **0** |
| Colour literals outside the token blocks | **0** (only `hsl(var(--uc) …)`, the inline per-user hue) |
| `var(--x)` used but never declared | **0**, apart from `--uc`, which `client.js` sets inline — correct |
| Dark declared twice, byte-identical | **42 tokens + 42 tokens, 0 mismatches** |
| Any colour defined *only* inside a media query | **0** |
| Keyframe animations outside a `no-preference` guard | **0**; blanket `reduce` override present |

**No class was dropped.** Every selector that existed before still exists; the DOM contract is
untouched. `.cf-histtop` (+ `.loading` / `.done` / `.error`) was **added** for the P2 scrollback bar,
which had no styling at all before this pass, and a handful of forward-looking security classes were
added for P5–P7 (see §9.3).

### Visual verification actually performed

`npm start` on port 3000, driven in Chrome. Both themes confirmed rendering correctly on: the join
screen (including the `.cf-alert` error state), the lobby (spotlight, room grid, create bar), the chat
shell (roster, log, message grouping, own-message bubbles, hover rail, poll card, composer, spark
meter, connection pill), both modals, the toast stack including the bad variant, and the 360 px
breakpoint with the roster drawer and the bottom-sheet modal. Computed styles were read back to
confirm the tokens resolve to the intended values and that all three faces load with their variable
axes applied (`font-variation-settings: "SOFT" 38, "WONK" 1` confirmed live on the wordmark). No
console errors. The server was stopped afterwards.

**Not verified:** `prefers-reduced-motion: reduce` was checked structurally (every animation is inside
a guard, plus the blanket override) but not by emulating the OS setting in the browser. Lighthouse was
not run — the roadmap's ≥ 95 accessibility target belongs to 10c, which is not in this pass.

---

## 9 · Handoff: changes needed in `index.html` / `client.js`

None of these are required for the design system to work — everything above is live as it stands. They
are the remaining rough edges I could not reach from `public/style.css`.

### 9.1 `index.html` — preload the two above-the-fold faces

The roadmap asks for `<link rel="preload">` on the first-paint faces. Add inside `<head>`, **above**
the `style.css` link:

```html
<link rel="preload" href="fonts/fraunces-latin-var.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="fonts/source-sans-3-latin-var.woff2" as="font" type="font/woff2" crossorigin>
```

`crossorigin` is required even same-origin — fonts are always fetched in CORS mode.

### 9.2 `index.html` — three inline styles that bypass the type scale

`style.css` contains no off-scale sizes, but three inline attributes in the markup still do. Each has
a replacement class already defined.

**a) `#share` — line 127.** Replace the inline sizing with the new `.cf-btn-sm` class:

```html
<!-- was: <button class="cf-btn cf-btn-secondary" type="button" id="share" style="padding:7px 14px;font-size:13px"> -->
<button class="cf-btn cf-btn-secondary cf-btn-sm" type="button" id="share">
```

**b) `#me-av` — line 162.** The `font-size:10px` is below the scale floor. `.cf-side-foot .cf-av`
already sizes it; drop the inline attribute entirely:

```html
<!-- was: <span class="cf-av" id="me-av" style="width:24px;height:24px;font-size:10px">··</span> -->
<span class="cf-av" id="me-av">··</span>
```

If you want it smaller than the 28 px default, say so and I will add a `.cf-av-sm` modifier rather
than restoring the inline style.

**c) `#km-error` / `#lm-error` — lines 214 and 247.** `style="margin-top:9px"` is off the space
spine. Safe to drop; if the gap matters I will add it to the `.cf-field .cf-alert` rule instead.

Two other inline styles are **fine and should stay**: `style="width:100%"` on `#join-submit`, and
`style="background:var(--seal)"` / `style="color:var(--seal)"` on the modal buttons and lock glyphs —
those reference live tokens and both are audited (`--ground` on a `--seal` fill is 5.26:1 light,
9.17:1 dark).

### 9.3 `client.js` — classes that now exist and are ready to use

Added for P5–P7 so the security work has somewhere to land. All are styled, contrast-audited and
currently unused:

| Class | Renders as |
|---|---|
| `.cf-badge.verified` / `.pending` / `.tamper` | signature-state pills on `--verified` / `--pending` / `--tamper`, the tamper one ringed |
| `.cf-msg.tampered`, `.cf-msg.forged` | the whole row as a bordered oxblood alert card, text in `--tamper` |
| `.cf-tamperbanner` | the room-level "a row in this window failed verification" banner |
| `.cf-sig` + `.ok` / `.pending` / `.bad` | the per-message verification badge — quiet when it passes, bold when it does not |
| `.cf-fp` | safety numbers: mono, tabular, slashed zero, tracked and word-spaced for five groups of five |
| `.cf-btn-sm` | the small button shape (§9.2a) |
| `.cf-user.self` | the roster row for yourself, underlined — was referenced by `client.js` but never styled |

Note `.cf-fail` now renders in `--tamper`, not `--alert`. If any code path is using `.cf-fail` for a
*non*-security failure, move it to `.cf-alert`.

### 9.4 `client.js` — two optional refinements

**a) Modal exit animation.** Modals fade and lift in, but there is no exit: the dialog is removed with
`hidden`, and CSS cannot animate an element out of `display:none`. If you want a symmetric close, set
a class first and remove `hidden` a beat later:

```js
// closing a modal
modal.classList.add('closing');
setTimeout(function () { modal.hidden = true; modal.classList.remove('closing'); }, 200);
```

Tell me if you add it and I will supply the `.cf-backdrop.closing` keyframes; I did not add dead CSS
for a hook that does not exist yet.

**b) A precise "is this message live?" hook.** The entrance animation is scoped to `:last-child`,
which is correct for both the prepend-style scrollback and a synchronous batch (§6). The one cosmetic
edge is two live messages under 200 ms apart: the first snaps to its finished state. If that ever
shows, add one line in the append path:

```js
// in place(), for live messages only — never in the atTop / scrollback branch
node.classList.add('cf-fresh');
setTimeout(function () { node.classList.remove('cf-fresh'); }, 400);
```

Then I will re-scope the keyframe from `.cf-log > .cf-msg:last-child` to `.cf-msg.cf-fresh`. Until
that hook exists the `:last-child` scoping is the correct CSS-only answer, so no change is needed.

### 9.5 P8 reminder

The CSP will need `font-src 'self'`. Nothing in `style.css` requests an external origin, so that one
directive is sufficient — no `unsafe-inline` is needed for the stylesheet, though the inline theme
script in `index.html` still needs its nonce or a move to an external file, as the roadmap notes.
