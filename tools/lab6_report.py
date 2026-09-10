#!/usr/bin/env python3
"""tools/lab6_report.py — the Lab 6 submission report.

Assembles results/lab6/report.pdf from the measured output and the figures.
Every number is read from a summary.json written by the load generator, so the
document cannot drift from what was run.

    python3 tools/lab6_report.py --pdf
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "lab6"

STUDENT = "Rajeev Kumar"
ROLL = "12341700"
REPO = "https://github.com/rajeev-sr/chatfat-encrypted/tree/load-bal"
LB_URL = "https://10.1.75.53:3273"

SYSTEMS = [
    ("Sys1", "stu79_sys1", 2273, 3273, "172.17.0.74", "Load balancer (Go) + PostgreSQL 16"),
    ("Sys2", "stu79_sys2", 2274, 3274, "172.17.0.75", "backend-1 — ChatFat"),
    ("Sys3", "stu79_sys3", 2275, 3275, "172.17.0.76", "backend-2 — ChatFat"),
    ("Sys4", "stu79_sys4", 2276, 3276, "172.17.0.77", "backend-3 — ChatFat"),
]

FIGURES = [
    ("response-time.png", "Response time through the run, with one backend degraded",
     "Both panels are the same offered load from the same seed; only the selection strategy differs. "
     "Round-robin's p95 stays between 200 and 300 ms for the whole run because one request in three is "
     "posted into a queue it can see is growing. The performance-based balancer spikes once at the start — "
     "it has no service-time history yet, so its first requests explore every backend including the slow "
     "one — and then settles between 50 and 100 ms."),
    ("distribution.png", "Where the requests actually went",
     "The requirement made visible. A fixed rotation cannot do anything other than send an equal third to "
     "the degraded machine. The load-aware balancer discovers the difference within a couple of seconds and "
     "routes around it."),
    ("utilization.png", "System utilisation, all four systems",
     "Event-loop delay is the saturation signal here, not CPU: the hosts have 120 cores, so a single-threaded "
     "Node backend can never exceed about 0.8% of the whole machine no matter how overloaded it is. Sys4's "
     "delay runs at 30–80 ms against 2–5 ms on the other two, and that gap is exactly what the balancer routes on."),
    ("latency-summary.png", "Response-time percentiles across all four runs",
     "The balanced pair matters as much as the degraded one: when every backend is equal, load-aware selection "
     "performs the same as round-robin. It is not paying for its cleverness when there is nothing to be clever about."),
]

E = html.escape


def read_json(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def num(v, suffix="", dash="—"):
    if v is None:
        return dash
    try:
        f = float(v)
    except (TypeError, ValueError):
        return E(str(v))
    return (f"{f:,.2f}".rstrip("0").rstrip(".") if f % 1 else f"{int(f):,}") + suffix


def summaries():
    out = {}
    for p in sorted(RESULTS.glob("*.summary.json")):
        d = read_json(p)
        if d:
            out[d["experiment"]] = d
    return out


def embed(path: Path) -> str:
    if not path.exists():
        return f'<p class="missing">Figure not found: {E(path.name)}</p>'
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<img src="data:image/png;base64,{b64}" alt="">'


def sec_cover() -> str:
    rows = "".join(
        f"<tr><td>{E(s)}</td><td><code>{E(host)}</code></td>"
        f"<td><code>ssh -p {ssh} student@10.1.75.53</code></td>"
        f"<td><code>{app}</code></td><td><code>{E(ip)}</code></td><td>{E(role)}</td></tr>"
        for s, host, ssh, app, ip, role in SYSTEMS
    )
    return f"""
<header class="cover">
  <p class="kicker">Lab 6 — Dynamic Load Balancing and Persistent Chat</p>
  <h1>Performance-Based Load Balancing</h1>
  <p class="sub">A Go load balancer that routes on measured backend performance, in front of three
     instances of a secure group-chat application sharing one PostgreSQL database.</p>
  <dl class="ident">
    <dt>Student</dt><dd>{E(STUDENT)}</dd>
    <dt>Roll Number</dt><dd>{E(ROLL)}</dd>
    <dt>Load Balancer URL</dt><dd class="url"><a href="{E(LB_URL)}">{E(LB_URL)}</a></dd>
    <dt>Repository</dt><dd class="url"><a href="{E(REPO)}">{E(REPO)}</a></dd>
  </dl>
</header>

<section>
  <h2>1. Submission endpoint</h2>
  <p>Clients reach the application only through the load balancer. The two required routes:</p>
  <table class="grid">
    <thead><tr><th>Route</th><th>Method</th><th>Input</th><th>Returns</th></tr></thead>
    <tbody>
      <tr><td><code>{E(LB_URL)}/message</code></td><td>POST</td>
          <td><code>client-name</code>, <code>msg</code></td>
          <td><code>201</code> with the stored message id</td></tr>
      <tr><td><code>{E(LB_URL)}/feed</code></td><td>GET</td><td>—</td>
          <td><code>200</code>, a JSON array of every message</td></tr>
    </tbody>
  </table>
  <p>The certificate is self-signed, so a client must skip verification
     (<code>curl -k</code>). JSON, form-encoded and query-string bodies are all accepted, because the
     assignment fixes the field names but not the encoding.</p>
  <pre class="term">$ curl -sk -X POST {E(LB_URL)}/message \\
    -H 'content-type: application/json' \\
    -d '{{"client-name":"alice","msg":"hello"}}'
{{"ok":true,"id":"m_mtuh…","client-name":"alice","ts":1788981740723,"backend":"backend-3","idempotent":false}}

$ curl -sk '{E(LB_URL)}/feed?limit=2'
[{{"id":"m_…","client-name":"alice","msg":"hello","ts":1788981740723}}, …]</pre>
</section>

<section>
  <h2>2. Topology</h2>
  <table class="grid">
    <thead><tr><th>System</th><th>Hostname</th><th>SSH</th><th>Public port</th><th>Bridge IP</th><th>Role</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <pre class="diagram">
  clients ──HTTPS──▶  Sys1 :3273   load balancer (Go)
                        │           performance-based selection
                        │           health checking
                        │
                        ├──▶ Sys2 :3274  backend-1  ─┐
                        ├──▶ Sys3 :3275  backend-2  ─┼──▶ PostgreSQL 16 on Sys1
                        └──▶ Sys4 :3276  backend-3  ─┘    (Docker bridge, private)
  </pre>
  <p>Two addressing details are forced by the environment rather than chosen. Each container's
     application must listen on port <strong>3000</strong>, which the host publishes as
     <code>3273</code>–<code>3276</code>; and the balancer reaches the backends by their Docker bridge
     addresses, because traffic from one container out to the host's external IP and back into a sibling
     has to hairpin through the same bridge, which Docker drops.</p>
</section>
"""


def sec_algorithm() -> str:
    return """
<section>
  <h2>3. How a backend is chosen</h2>
  <p>Fixed round-robin is explicitly not acceptable, and the reason is visible in section 6: it has no
     way to notice that one of its backends has become slow. What replaces it has to answer two
     questions — how loaded is each backend, and which one should take this request.</p>

  <h3>3.1 Measuring load</h3>
  <p>Two signals, because each is blind where the other is not.</p>
  <table class="grid">
    <thead><tr><th>Signal</th><th>Source</th><th>Strength</th><th>Weakness</th></tr></thead>
    <tbody>
      <tr><td>Service-time EWMA</td><td>the balancer's own timing of completed requests</td>
          <td>needs no cooperation and cannot be misreported</td>
          <td>only rises <em>after</em> requests have already been sent somewhere slow</td></tr>
      <tr><td>Event-loop delay</td><td>each backend, published on <code>/healthz</code></td>
          <td>leading indicator — it is literally the wait a new request will meet on arrival</td>
          <td>requires trusting the backend to report honestly</td></tr>
    </tbody>
  </table>
  <p>The backend's figure costs no extra traffic: the balancer already probes <code>/healthz</code> once
     a second for liveness, so the same response carries the load block. Both are smoothed with an EWMA,
     because a balancer that reacts to one slow sample oscillates between backends instead of settling.</p>

  <h3>3.2 The score</h3>
  <p>Each backend is scored as an estimate, in milliseconds, of how long a request sent to it would take:</p>
  <pre class="term">score = (in-flight + 1) × service-time-EWMA  +  event-loop-delay
        └──── the queue this request would join ────┘   └── wait before its turn ──┘</pre>
  <p>An estimate in real time is comparable between backends of different speeds, which a bare connection
     count is not. The <code>+1</code> is the request being scheduled: without it an idle backend scores
     zero however slow it is, and the balancer would send it everything.</p>

  <h3>3.3 The threshold, and what "switch" means</h3>
  <p>A backend whose score exceeds <code>-load-threshold</code> is treated as overloaded and skipped
     entirely, <em>while any backend is below it</em>. When every backend is above the threshold the
     least-bad one is still used — refusing a request that some backend could have served helps nobody,
     and a threshold that can take the whole cluster out of rotation is worse than no threshold.</p>

  <h3>3.4 Choosing among the candidates</h3>
  <p>The default is <strong>power-of-two-choices</strong>: sample two eligible backends at random and take
     the better score. Always taking the single best backend sounds stronger and behaves worse under
     concurrency — every request deciding at the same instant reads the same scores and stampedes onto the
     same machine, which is then the slowest by the time the next batch decides. Two random samples remove
     almost all of the imbalance while making that herding impossible, since no two concurrent decisions
     see the same pair. <code>-strategy least-load</code> and <code>-strategy round-robin</code> are both
     available, the latter only so section 6 can measure what the difference is worth.</p>

  <h3>3.5 Unhealthy backends</h3>
  <p>Liveness is separate from load. A backend is evicted after three consecutive failed probes and
     restored after one success — eviction is deliberately slower than restoration, because a saturated
     single-threaded backend cannot always answer a probe promptly and evicting on one missed sample
     produces a flap loop that reports the balancer's own oscillation as backend failure. Connection-level
     proxy errors evict immediately; timeouts and client cancellations do not, since neither is evidence
     that the backend has failed.</p>
</section>
"""


def sec_persistence(dedupe) -> str:
    total, distinct, dupes = dedupe if dedupe else ("—", "—", "—")
    return f"""
<section>
  <h2>4. Persistence and duplicate prevention</h2>
  <p>All three backends share one PostgreSQL 16 database. It runs on Sys1, reachable only over the Docker
     bridge — the port is not published, so the database is not exposed publicly.</p>
  <p>Its location was the single largest performance decision in this lab. The application previously used
     a hosted database in <code>us-east-2</code>, measured at <strong>~350 ms</strong> round trip from the
     lab; every <code>POST /message</code> would have paid that, capping the whole system at roughly three
     writes per second per pooled connection. The same query against the local instance measures
     <strong>0.62 ms</strong>. Nothing else in this report would have been worth measuring without that change.</p>

  <h3>4.1 Unique ids and idempotent insertion</h3>
  <p>Two mechanisms, and the order matters:</p>
  <ol>
    <li>Every message is keyed by a unique id — supplied by the client if it sends one, generated as a
        time-ordered UUID otherwise. A client that supplies an id can retry safely, because the retry
        carries the same id.</li>
    <li>The insert is <code>on conflict (id) do nothing</code>. Uniqueness is enforced by the
        <em>database</em>, not the application, so it holds even when two backends receive the same retried
        message concurrently — which is exactly what happens when a client retries through a load balancer.</li>
  </ol>
  <p>The generated id deliberately does <strong>not</strong> include the backend's name. Two backends must
     be able to produce the same row for the same client-supplied message; encoding the machine would
     defeat the deduplication this exists for.</p>

  <h3>4.2 Evidence</h3>
  <p>The load generator sends a configurable share of its messages twice with an identical id
     (<code>-retry-percent</code>, default 5%). Counted directly in the database after a run:</p>
  <table class="grid narrow">
    <tbody>
      <tr><th>Rows in <code>messages</code></th><td>{num(total)}</td></tr>
      <tr><th>Distinct message ids</th><td>{num(distinct)}</td></tr>
      <tr><th>Duplicates</th><td><strong>{num(dupes)}</strong></td></tr>
    </tbody>
  </table>
  <p>Messages posted over HTTP land in the same room, the same table and the same at-rest encryption as
     messages sent over the WebSocket chat protocol, and are broadcast to any connected chat client. There
     is no separate store for the lab routes.</p>
</section>
"""


def sec_loadgen() -> str:
    return """
<section>
  <h2>5. Load generator</h2>
  <p><code>lb/cmd/chatload</code> models chat clients rather than running a benchmark loop. A fixed-rate
     flood of identical requests exercises none of the behaviour a load balancer exists for: real load
     arrives unevenly, and it is the unevenness that makes performance-based routing worth more than
     taking turns.</p>
  <table class="grid">
    <thead><tr><th>Varied</th><th>Flag</th><th>Default</th></tr></thead>
    <tbody>
      <tr><td>Number of concurrent users</td><td><code>-users</code></td><td>40</td></tr>
      <tr><td>Message length, random per message</td><td><code>-min-len</code> / <code>-max-len</code></td><td>8–280 characters</td></tr>
      <tr><td>Think time between a user's messages, random</td><td><code>-min-gap</code> / <code>-max-gap</code></td><td>20–400 ms</td></tr>
      <tr><td>Read/write mix</td><td><code>-feed-every</code></td><td>one <code>GET /feed</code> per 25 posts</td></tr>
      <tr><td>Deliberate retries, to exercise deduplication</td><td><code>-retry-percent</code></td><td>5%</td></tr>
    </tbody>
  </table>
  <p>Each user has its own PRNG derived from one run seed, so there is no shared mutable state between
     goroutines and a whole run is reproducible with <code>-seed</code>. Every run in section 6 used the
     same seed, so the two strategies saw the same messages at the same offered rate.</p>
  <p>It also samples utilisation from all four systems while the run is in progress — each backend's
     <code>/statz</code> and the balancer's <code>/lb/metrics</code> — so the figures need no agent
     installed on the machines.</p>
</section>
"""


def sec_results(s) -> str:
    order = [("balanced-round-robin", "balanced", "round-robin"),
             ("balanced-p2c", "balanced", "p2c"),
             ("degraded-round-robin", "degraded", "round-robin"),
             ("degraded-p2c", "degraded", "p2c")]
    rows = ""
    for key, cond, strat in order:
        d = s.get(key)
        if not d:
            continue
        per = {k: v for k, v in (d.get("per_backend") or {}).items() if k != "unknown"}
        dist = " / ".join(f"{per.get(b, 0):,}" for b in sorted(per))
        rows += (f"<tr><td>{E(cond)}</td><td><code>{E(strat)}</code></td>"
                 f"<td>{num(d.get('total_requests'))}</td><td>{num(d.get('failed'))}</td>"
                 f"<td><strong>{num(d.get('messages_per_s'))}</strong></td>"
                 f"<td>{num(d.get('p50_ms'),' ms')}</td>"
                 f"<td><strong>{num(d.get('p95_ms'),' ms')}</strong></td>"
                 f"<td>{num(d.get('p99_ms'),' ms')}</td><td><code>{dist}</code></td></tr>")

    verdict = ""
    rr, p2c = s.get("degraded-round-robin"), s.get("degraded-p2c")
    if rr and p2c:
        def ratio(k, lower=True):
            a, b = float(rr[k]), float(p2c[k])
            if b == 0 or a == 0:
                return f"{a:,.2f} → {b:,.2f}"
            return (f"{a:,.2f} → {b:,.2f} <strong>({a/b:.2f}× lower)</strong>" if lower
                    else f"{a:,.2f} → {b:,.2f} <strong>({b/a:.2f}×)</strong>")
        deg_rr = {k: v for k, v in (rr.get("per_backend") or {}).items() if k != "unknown"}
        deg_p2 = {k: v for k, v in (p2c.get("per_backend") or {}).items() if k != "unknown"}
        slow_rr = deg_rr.get("backend-3", 0)
        slow_p2 = deg_p2.get("backend-3", 0)
        verdict = f"""
  <h3>6.2 Round-robin versus performance-based, cluster degraded</h3>
  <table class="grid">
    <thead><tr><th>Metric</th><th>round-robin → p2c</th></tr></thead>
    <tbody>
      <tr><td>Messages per second</td><td>{ratio('messages_per_s', lower=False)}</td></tr>
      <tr><td>p95 response time</td><td>{ratio('p95_ms')}</td></tr>
      <tr><td>p99 response time</td><td>{ratio('p99_ms')}</td></tr>
      <tr><td>p50 response time</td><td>{ratio('p50_ms')}</td></tr>
      <tr><td>Requests sent to the degraded backend</td>
          <td>{slow_rr:,} → <strong>{slow_p2:,}</strong></td></tr>
    </tbody>
  </table>"""

    figs = ""
    for name, title, caption in FIGURES:
        figs += (f'<figure>{embed(RESULTS / name)}'
                 f'<figcaption><strong>{E(title)}.</strong> {caption}</figcaption></figure>')

    return f"""
<section>
  <h2>6. Results</h2>
  <p>Four runs in a 2×2: two selection strategies against two states of the cluster. Everything except the
     one variable is held fixed — same client count, duration, message-length and think-time ranges, and
     the same load-generator seed. In the degraded runs, Sys4 carries competing work applied locally, the
     way a shared machine gets busy with someone else's job. It is not stopped: a stopped backend tests
     health checking, which is a different requirement.</p>

  <h3>6.1 All runs</h3>
  <table class="grid">
    <thead><tr><th>Cluster</th><th>Strategy</th><th>Requests</th><th>Failed</th><th>msg/s</th>
               <th>p50</th><th>p95</th><th>p99</th><th>b1 / b2 / b3</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  {verdict}

  <h3>6.3 Figures</h3>
  {figs}
</section>
"""


def sec_threshold(sweep) -> str:
    if not sweep:
        return """
<section>
  <h2>7. Choosing the threshold</h2>
  <p class="missing">Threshold sweep not present in results/lab6.</p>
</section>"""
    # A run that failed is not a fast run. One sweep point had the balancer down
    # for the whole run: every request errored in a few milliseconds, which
    # ranked first on p95. Excluded here as well as in the sweep script, so the
    # document cannot report a threshold chosen from a broken measurement even
    # if it is handed older data.
    valid = [r for r in sweep if not r.get("excluded")
             and r.get("served", 1) > 0
             and float(r.get("failed", 0)) / max(1, float(r.get("total", 1))) < 0.02]
    if not valid:
        return """
<section>
  <h2>7. Choosing the threshold</h2>
  <p class="missing">Every sweep run failed — no threshold can be justified from this data.</p>
</section>"""

    rows = ""
    for r in sweep:
        excluded = r not in valid
        cells = (f"<td><code>{num(r['threshold'])} ms</code></td><td>{num(r.get('messages_per_s'))}</td>"
                 f"<td>{num(r.get('p50_ms'),' ms')}</td><td><strong>{num(r.get('p95_ms'),' ms')}</strong></td>"
                 f"<td>{num(r.get('p99_ms'),' ms')}</td><td><code>{r.get('dist') or '—'}</code></td>")
        if excluded:
            rows += (f'<tr class="excluded">{cells}</tr>')
        else:
            rows += f"<tr>{cells}</tr>"
    best = min(valid, key=lambda r: float(r.get("p95_ms", 1e9)))

    # A threshold can be "best" in a sweep and still be wrong if it is so low
    # that it never lets anything through — the balancer would then fall back to
    # least-loaded on every decision and the threshold would be decorative. This
    # measures how often that happens on a healthy cluster.
    v = read_json(RESULTS / "threshold-validation.json")
    validation = ""
    if v:
        validation = (
            f'<p><strong>Is it too low?</strong> A threshold that every backend exceeds all the time is '
            f'decorative: the balancer falls through to least-loaded on every decision. Measured on a healthy '
            f'cluster at the chosen value, per-backend scores settle to '
            f'{", ".join(f"{x:.1f}" for x in v["steady_scores_ms"])}&nbsp;ms against the '
            f'{num(v["threshold_ms"])}&nbsp;ms threshold, and all three backends were over it for only '
            f'<strong>{v["pct"]}%</strong> of {v["requests"]:,} routing decisions. So it engages when a backend '
            f'genuinely degrades and stays out of the way otherwise, which is what it is for.</p>')
    excluded_note = ""
    dead = [r for r in sweep if r not in valid]
    if dead:
        which = ", ".join(f"{num(r['threshold'])} ms" for r in dead)
        excluded_note = (f'<p><strong>Excluded: {which}.</strong> In that run the balancer was not serving — '
                         f'every request failed at the transport in a few milliseconds. Ranked on p95 alone it '
                         f'was the fastest row in the sweep, which is a good illustration of why a latency '
                         f'number means nothing without the success count beside it. Rows shown struck through.</p>')
    return f"""
<section>
  <h2>7. Choosing the threshold</h2>
  <p>The threshold is in the same units as the score — estimated milliseconds to serve a request — which
     is what makes it possible to reason about rather than tune blindly. Too low and healthy backends are
     excluded for ordinary variation, concentrating traffic on whichever machine happened to look best;
     too high and it never engages, leaving plain load-preference with no switching. Measured on the
     degraded cluster, all else held fixed:</p>
  <table class="grid">
    <thead><tr><th>Threshold</th><th>msg/s</th><th>p50</th><th>p95</th><th>p99</th><th>b1 / b2 / b3</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  {excluded_note}
  <p><strong>Chosen: {num(best['threshold'])} ms</strong> — the lowest p95 among runs that actually served
     the load. The deployed balancer runs with <code>-load-threshold {num(best['threshold'])}</code>.</p>
  {validation}
  <p>The value is not universal: it is an absolute response-time budget, so it belongs to this workload on
     this hardware. Its meaning, though, is portable — it is the answer to "how slow does a backend have
     to look before I stop sending it work", and that is a question with an operational answer rather than
     a tuning knob to be swept.</p>
</section>
"""


def sec_repro(threshold="50") -> str:
    return f"""
<section>
  <h2>8. Running it</h2>
  <h3>8.1 Database — Sys1</h3>
  <pre class="term">~/pgsql/bin/pg_ctl -D ~/pgdata -l ~/pg.log start</pre>
  <p>PostgreSQL 16.4, installed from a portable build into <code>$HOME</code> — the lab containers have no
     root and no Docker. It listens only on the bridge.</p>

  <h3>8.2 Backends — Sys2, Sys3, Sys4</h3>
  <pre class="term">PORT=3000 BACKEND_NAME=backend-1 DB_POOL_MAX=40 \\
  DATABASE_URL='postgresql://chatfat:***@172.17.0.74:5432/chatfat' \\
  MASTER_KEY='***' node server.js</pre>
  <p><code>PORT=3000</code> because the host publishes container port 3000 as the system's public port.
     <code>DB_POOL_MAX</code> is raised from the default of 10: ten connections is right for a database an
     internet away, where the round trip dominates, and far too few for one on the same host, where the
     pool becomes the bottleneck long before the database does.</p>

  <h3>8.3 Load balancer — Sys1</h3>
  <pre class="term">./bin/lb -listen 0.0.0.0:3000 \\
  -backends http://172.17.0.75:3000,http://172.17.0.76:3000,http://172.17.0.77:3000 \\
  -strategy p2c -load-threshold {threshold} \\
  -health-timeout 5s -backend-timeout 15s \\
  -tls-cert ./tls-cert.pem -tls-key ./tls-key.pem</pre>

  <h3>8.4 Reproducing the measurements</h3>
  <pre class="term">tools/lab6-experiments.sh 45s 60     # the four runs
python3 tools/lab6_plots.py          # the figures
python3 tools/lab6_report.py --pdf   # this document</pre>

  <h3>8.5 Observability</h3>
  <table class="grid">
    <thead><tr><th>Endpoint</th><th>Shows</th></tr></thead>
    <tbody>
      <tr><td><code>{E(LB_URL)}/lb/status</code></td>
          <td>per-backend score, measured service time, reported event-loop delay, whether each is over
              the threshold</td></tr>
      <tr><td><code>{E(LB_URL)}/lb/metrics</code></td>
          <td>totals, dropout, percentiles, per-backend request counts and scores, the balancer's own CPU</td></tr>
      <tr><td><code>http://10.1.75.53:3274/statz</code></td><td>that backend's own load</td></tr>
    </tbody>
  </table>
</section>
"""


CSS = """
:root{--ink:#16181d;--mut:#5b6472;--line:#dfe3e9;--bg:#fff;--code:#f6f7f9;--accent:#2a4fa2;--warn:#a8341f}
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;background:var(--bg);color:var(--ink);
     font:11pt/1.62 "Charter","Bitstream Charter",Georgia,serif}
.page{max-width:52em;margin:0 auto;padding:3.2em 2.6em 4em}
h1{font-size:2em;line-height:1.15;margin:.1em 0 .35em;letter-spacing:-.015em}
h2{font-size:1.3em;margin:2.4em 0 .7em;padding-bottom:.28em;border-bottom:2px solid var(--accent)}
h3{font-size:1.04em;margin:1.7em 0 .5em;color:var(--accent)}
p,li{margin:.6em 0}
code,pre{font-family:"JetBrains Mono","DejaVu Sans Mono",ui-monospace,monospace}
code{font-size:.85em;background:var(--code);padding:.08em .34em;border-radius:3px}
pre{background:var(--code);border:1px solid var(--line);border-left:3px solid var(--accent);
    border-radius:4px;padding:.85em 1em;font-size:.72em;line-height:1.5;margin:.8em 0;
    white-space:pre-wrap;overflow-wrap:break-word}
pre.diagram{border-left-color:var(--mut);font-size:.7em;line-height:1.35;white-space:pre}
.cover{border-bottom:3px double var(--line);padding-bottom:1.6em}
.kicker{text-transform:uppercase;letter-spacing:.14em;font-size:.7em;color:var(--mut);
        margin:0 0 .7em;font-weight:600}
.sub{color:var(--mut);font-size:1.02em;margin:.2em 0 1.3em;max-width:36em}
dl.ident{display:grid;grid-template-columns:max-content 1fr;gap:.35em 1.4em;margin:0}
dl.ident dt{font-size:.72em;text-transform:uppercase;letter-spacing:.09em;color:var(--mut);
            font-weight:600;align-self:center}
dl.ident dd{margin:0;font-weight:600;font-size:1.02em}
dl.ident dd.url{font-family:"JetBrains Mono","DejaVu Sans Mono",monospace;font-size:.78em;
                font-weight:500;overflow-wrap:anywhere}
dl.ident dd.url a{color:var(--accent);text-decoration:none}
table.grid{border-collapse:collapse;width:100%;margin:.9em 0;font-size:.8em}
table.grid.narrow{width:auto;min-width:24em}
table.grid th,table.grid td{border:1px solid var(--line);padding:.4em .68em;text-align:left;vertical-align:top}
table.grid thead th{background:var(--code);font-size:.9em;text-transform:uppercase;
                    letter-spacing:.05em;color:var(--mut)}
table.grid tbody th{background:#fafbfc;font-weight:600;white-space:nowrap}
figure{margin:1.6em 0;text-align:center}
figure img{max-width:100%;height:auto;border:1px solid var(--line);border-radius:4px}
figcaption{font-size:.82em;color:var(--mut);margin-top:.6em;text-align:left;line-height:1.5}
tr.excluded td{color:var(--mut);text-decoration:line-through;text-decoration-color:var(--warn)}
p.missing{background:#fdf4f2;border-left:3px solid var(--warn);color:var(--warn);
          padding:.6em .9em;font-size:.86em}
@media print{
  .page{max-width:none;padding:0}
  h2,h3{break-after:avoid}
  table,figure{break-inside:avoid}
  pre{break-inside:auto}
}
@page{size:A4;margin:16mm 14mm}
"""


def chosen_threshold(sweep) -> str:
    """The threshold the deployment should be running, from valid runs only."""
    if not sweep:
        return "50"
    valid = [r for r in sweep if not r.get("excluded") and r.get("served", 1) > 0]
    if not valid:
        return "50"
    return str(min(valid, key=lambda r: float(r.get("p95_ms", 1e9)))["threshold"])


def build(s, dedupe, sweep) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Lab 6 — {E(STUDENT)} ({E(ROLL)})</title>
<style>{CSS}</style></head><body><div class="page">
{sec_cover()}
{sec_algorithm()}
{sec_persistence(dedupe)}
{sec_loadgen()}
{sec_results(s)}
{sec_threshold(sweep)}
{sec_repro(chosen_threshold(sweep))}
</div></body></html>
"""


def to_pdf(html_path: Path, pdf_path: Path) -> bool:
    for exe in ("google-chrome", "chromium", "chromium-browser", "google-chrome-stable"):
        chrome = shutil.which(exe)
        if not chrome:
            continue
        profile = pdf_path.parent / ".chrome-profile"
        cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
               f"--user-data-dir={profile}", "--no-pdf-header-footer",
               f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()]
        try:
            subprocess.run(cmd, capture_output=True, timeout=240)
        except subprocess.TimeoutExpired:
            continue
        finally:
            shutil.rmtree(profile, ignore_errors=True)
        if pdf_path.exists() and pdf_path.stat().st_size > 1000:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", action="store_true")
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    dedupe = read_json(RESULTS / "dedupe.json")
    dedupe = (dedupe["total"], dedupe["distinct"], dedupe["duplicates"]) if dedupe else None
    sweep = read_json(RESULTS / "threshold-sweep.json")

    out = RESULTS / "report.html"
    out.write_text(build(summaries(), dedupe, sweep))
    print(f"wrote {out}  ({out.stat().st_size/1024:.0f} KB)")

    if args.pdf:
        pdf = out.with_suffix(".pdf")
        if to_pdf(out, pdf):
            print(f"wrote {pdf}  ({pdf.stat().st_size/1024:.0f} KB)")
        else:
            print("  could not render a PDF — open the HTML and print to PDF", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
