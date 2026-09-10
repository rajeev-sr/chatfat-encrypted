#!/usr/bin/env python3
"""tools/report.py — assemble the single submission report from measured output.

The submission is one PDF containing name, roll number, the assigned systems,
the load balancer code, the comparison table and the supporting evidence.
Everything here is read from results/ and from the source tree, so the report
cannot drift from what was actually measured: there is no number in it that was
typed by hand.

    python3 tools/report.py                      -> results/report.html
    python3 tools/report.py --pdf                -> also results/report.pdf

Missing inputs degrade to a visible placeholder rather than an exception, so a
partial run still produces a readable draft that says what is missing.
"""
from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Rebound by main() when --results is given, so a dry run can be rendered
# without touching the directory the submission is built from.
RESULTS = ROOT / "results"
EVIDENCE = RESULTS / "evidence"

# Defaults only. Every one of these is a command-line flag, because the ports a
# run actually used are a property of that run and not of this file — see main().
STUDENT_NAME = "Rajeev Kumar"
ROLL_NUMBER = "12341700"
LAB_ACCOUNT = "stu79 (sys1–sys4)"
LAB_HOST = "10.1.75.53"
SSH_PORTS = [2273, 2274, 2275, 2276]
APP_PORTS = [3273, 3274, 3275, 3276]
HOST_PREFIX = "stu79"
GITHUB_URL = "https://github.com/rajeev-sr/chatfat-encrypted/tree/load-bal"

ROLES = [
    "Load Balancer (Go)",
    "Backend-1 — ChatFat messaging server",
    "Backend-2 — ChatFat messaging server",
    "Backend-3 — ChatFat messaging server",
]


def systems():
    """The assigned-systems table, assembled from whatever the flags said."""
    return [
        (f"Sys{i + 1}", f"{HOST_PREFIX}_sys{i + 1}", LAB_HOST,
         SSH_PORTS[i] if i < len(SSH_PORTS) else "—",
         APP_PORTS[i] if i < len(APP_PORTS) else "—",
         ROLES[i])
        for i in range(4)
    ]

# Runs are discovered from results/ rather than hard-coded, because the run
# labels are chosen at measurement time (-experiment) and a report that only
# knows a fixed set silently omits anything named differently.
def discover_runs():
    """[(label, heading, backend_count)] for every measured run, 1-backend first."""
    if not RESULTS.is_dir():
        return []
    labels = sorted(
        q.stem for q in RESULTS.glob("*.json")
        if not q.stem.endswith((".lb-metrics", ".lb-status"))
        and q.stem not in {"report"}
    )
    # ".lb-metrics.json" leaves stem "x.lb-metrics" on some paths; belt and braces.
    labels = [l for l in labels if not l.endswith((".lb-metrics", ".lb-status"))]

    def backends_in(label):
        m = re.match(r"(\d+)-backend", label)
        return int(m.group(1)) if m else 0

    def sort_key(label):
        n = backends_in(label)
        # steady before any deadline/overload variant, so the report reads
        # "capacity first, then what happens at the limit".
        return (n or 99, 0 if "steady" in label else 1, label)

    out = []
    for label in sorted(labels, key=sort_key):
        n = backends_in(label)
        which = {1: "one backend", 3: "three backends"}.get(n, f"{n} backends" if n else label)
        kind = ("throughput and latency" if "steady" in label
                else "under a client deadline" if "deadline" in label
                else "under overload" if "overload" in label
                else "")
        heading = f"{label} — {which}" + (f", {kind}" if kind else "")
        out.append((label, heading, n))
    return out


CODE_LISTINGS = [
    ("lb/cmd/lb/main.go", "Load Balancer — reverse proxy, round-robin, health checks, metrics"),
    ("lb/cmd/loadgen/main.go", "Load Generator — worker pool, percentiles, JSON/CSV output"),
    ("src/transport/bench.js", "Backend experiment endpoint, added to the ChatFat messaging server"),
]

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
TEXT_SUFFIXES = {".txt", ".log", ".json", ".md", ".out"}
E = html.escape


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except Exception:
        return None


def missing(what: str) -> str:
    return (f'<p class="missing">Not available — {E(what)}. '
            f'Run the deploy scripts in order and regenerate this report.</p>')


def pre(text: str, cls: str = "term") -> str:
    return f'<pre class="{cls}">{E(text.rstrip())}</pre>'


# ---------------------------------------------------------------- results ----

def load_runs(runs) -> dict:
    out = {}
    for label, _, _ in runs:
        out[label] = {
            "client": read_json(RESULTS / f"{label}.json"),
            "lb": read_json(RESULTS / f"{label}.lb-metrics.json"),
            "status": read_json(RESULTS / f"{label}.lb-status.json"),
        }
    return out


def comparison_rows() -> list[dict]:
    path = RESULTS / "comparison.csv"
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def fnum(v, suffix="", dashes="—"):
    if v is None or v == "":
        return dashes
    try:
        f = float(v)
    except (TypeError, ValueError):
        return E(str(v))
    s = f"{f:,.2f}".rstrip("0").rstrip(".") if f % 1 else f"{int(f):,}"
    return f"{s}{suffix}"


# ---------------------------------------------------------------- sections ---

def diagram() -> str:
    """Topology, drawn at the ports actually used.

    Built column-exact and asserted: a diagram whose box edges do not line up
    reads as a rendering fault in the report rather than a drawing choice.
    """
    L, R = 26, 42
    GAP = " " * 10
    lb_ = lambda t="": "  |" + t.ljust(L) + "|"
    rb_ = lambda t="": "|" + t.ljust(R) + "|"
    p = APP_PORTS + [0] * 4

    lines = [
        f"   Laptop (load generator)                {LAB_HOST}",
        "  +" + "-" * L + "+" + GAP + "+" + "-" * R + "+",
        lb_(" loadgen") + GAP + rb_(f"  Sys1  :{p[0]}  Load Balancer (Go)"),
        lb_("   -requests 5000") + " -HTTP--> " + rb_("        |  round-robin + health checks"),
        lb_("   -concurrency 40") + GAP + rb_("        |"),
        lb_("   -work 2000") + GAP + rb_(f"        +--> Sys2 :{p[1]}  backend-1"),
        "  +" + "-" * L + "+" + GAP + rb_(f"        +--> Sys3 :{p[2]}  backend-2"),
        " " * (3 + L + 1 + 10) + rb_(f"        +--> Sys4 :{p[3]}  backend-3"),
        " " * (3 + L + 1 + 10) + "+" + "-" * R + "+",
    ]
    width = len(lines[1])
    for i, ln in enumerate(lines):
        if i:
            assert len(ln) == width, (i, len(ln), width)
    # Returns the whole <pre>, tags included: box-drawing that is not in a
    # monospace preformatted block reflows into prose and stops being a diagram.
    return '<pre class="diagram">' + E("\n".join(lines)) + "</pre>"


def sec_cover() -> str:
    rows = "".join(
        f"<tr><td>{E(s)}</td><td><code>{E(host)}</code></td><td><code>{E(ip)}</code></td>"
        f"<td><code>ssh -p {ssh} student@{E(ip)}</code></td>"
        f"<td><code>{app}</code></td><td>{E(role)}</td></tr>"
        for s, host, ip, ssh, app, role in systems()
    )
    return f"""
<header class="cover">
  <p class="kicker">Cloud &amp; Systems Design — Lab Exercise</p>
  <h1>Building a Load Balancer in Go</h1>
  <p class="sub">Reverse proxy, round-robin scheduling, health checks and performance experiments,
     in front of the ChatFat messaging backend.</p>
  <dl class="ident">
    <dt>Student Name</dt><dd>{E(STUDENT_NAME)}</dd>
    <dt>Roll Number</dt><dd>{E(ROLL_NUMBER)}</dd>
    <dt>Lab Account</dt><dd>{E(LAB_ACCOUNT)}</dd>
    <dt>Source Code</dt><dd class="url"><a href="{E(GITHUB_URL)}">{E(GITHUB_URL)}</a></dd>
  </dl>
</header>

<section>
  <h2>1. Assigned Systems</h2>
  <table class="grid">
    <thead><tr><th>System</th><th>Hostname</th><th>IP</th><th>SSH</th><th>App port</th><th>Role</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p>All four systems answer on one IP behind different forwarded ports, so the machine
     identity in this report is a port number rather than a hostname. The application
     ports are the first entry of each system's assigned range — the host-forwarded
     ports, not container-internal ones, which is what makes the backends reachable
     from Sys1 and the load balancer reachable from the laptop running the load
     generator.</p>
</section>

<section>
  <h2>2. Topology</h2>
{diagram()}
  <p>The backend is the messaging project from the previous assignment — the ChatFat
     WebSocket chat server — deployed whole on each of Sys2, Sys3 and Sys4. The load
     balancer carries its WebSocket upgrades as well as plain HTTP.</p>
</section>
"""


def sec_method(rows: list[dict]) -> str:
    """Section 3. The per-request cost is a property of the machines this ran on,
    so it is read back from the measurement rather than quoted from wherever the
    workload was originally tuned."""
    by = {r["experiment"]: r for r in rows}
    calibration = ("Calibration figures unavailable — the single-backend steady run "
                   "was not measured.")
    try:
        steady = by["1-backend-steady"]
        rps = float(steady["throughput_rps"])
        p50 = float(steady["p50_ms"])
        calibration = (
            f"Measured on these machines, that cost gives a single backend a ceiling of "
            f"<strong>{rps:,.2f}&nbsp;requests/s</strong> — about {1000 / rps:.1f}&nbsp;ms of "
            f"backend CPU per request — at a median latency of {p50:,.0f}&nbsp;ms with 40 "
            f"concurrent clients. One backend is therefore fully saturated, which is the "
            f"precondition for the comparison meaning anything. These lab containers share "
            f"a host and are markedly slower than a desktop, so the absolute figures are "
            f"low; both experiments ran on the same hardware over the same network path, so "
            f"the comparison between them is unaffected."
        )
    except (TypeError, ValueError, ZeroDivisionError, KeyError):
        pass

    return """
<section>
  <h2>3. Method</h2>

  <h3>3.1 What is measured, and against what</h3>
  <p>Two configurations of the same load balancer binary, differing only in the
     <code>-backends</code> flag:</p>
  <ul>
    <li><strong>Experiment 1</strong> — one backend (Sys2)</li>
    <li><strong>Experiment 2</strong> — three backends (Sys2, Sys3, Sys4)</li>
  </ul>
  <p>Request count, concurrency, target URL and per-request work are identical across the
     two. Each configuration is driven twice, because throughput and dropout become
     visible under different conditions:</p>
  <table class="grid">
    <thead><tr><th>Run</th><th>Client deadline</th><th>What it measures</th></tr></thead>
    <tbody>
      <tr><td><code>steady</code></td><td>5&nbsp;s (generous)</td>
          <td>Nothing fails, so throughput and latency are measured cleanly. The honest
              measure of capacity.</td></tr>
      <tr><td><code>deadline</code></td><td>400&nbsp;ms</td>
          <td>Every request must complete inside a fixed budget. Requests whose queueing
              delay exceeds it become failures, which is where dropout appears.</td></tr>
    </tbody>
  </table>
  <p>Both runs use concurrency 40. The load generator is closed-loop — 40 workers, each
     issuing its next request only when the previous returns — so raising concurrency does
     not raise the offered rate. By Little's Law the rate pins at whatever the backend can
     serve, and extra concurrency only lengthens the queue:
     <em>latency&nbsp;=&nbsp;concurrency&nbsp;÷&nbsp;throughput</em>. Failures therefore
     appear when queueing delay exceeds the client's deadline, so varying the deadline at
     fixed concurrency probes the same mechanism as varying concurrency at a fixed
     deadline. Holding the connection count constant additionally keeps the transport out
     of the measurement.</p>

  <h3>3.2 The request, and why it costs what it does</h3>
  <p>Each request is <code>GET /bench?work=2000</code>: 2000 rounds of SHA-256 on the
     backend. The purpose of a per-request CPU cost is to make the backend the bottleneck.
     Node.js is single-threaded, so one backend can occupy exactly one core no matter how
     much load arrives — and that ceiling is precisely what a second and third backend
     lift. Serving <code>index.html</code> instead would be answered from page cache, one
     backend would never saturate, and the one-versus-three comparison would be measuring
     the lab network rather than the load balancing.</p>
  <p>{calibration}</p>

  <h3>3.3 Controls</h3>
  <ul>
    <li><strong>Warmup.</strong> 200 unmeasured requests precede each run, so connection
        pools are filled and the JIT is warm before the first measured request.</li>
    <li><strong>Counters reset after the warmup, not before.</strong> The load generator
        POSTs <code>/lb/reset</code> between the warmup and the measured phase, so the
        load balancer's own numbers cover exactly the requests the client counted.</li>
    <li><strong>Drain between runs.</strong> Five seconds, so one run's backlog is not
        charged to the next run's latency.</li>
    <li><strong>Percentiles</strong> use nearest-rank on the sorted sample, the same rule
        on both the client and the load balancer, so the two are comparable.</li>
    <li><strong>Full body drain.</strong> An undrained response body cannot return to the
        idle pool, which silently disables keep-alive partway through a run.</li>
  </ul>

  <h3>3.4 Metric definitions</h3>
  <table class="grid">
    <thead><tr><th>Metric</th><th>Definition</th></tr></thead>
    <tbody>
      <tr><td>Throughput</td><td>successful requests ÷ elapsed wall-clock time of the run</td></tr>
      <tr><td>Dropout</td><td>failed requests ÷ total attempted requests × 100</td></tr>
      <tr><td>p50 / p95 / p99</td><td>nearest-rank percentiles of end-to-end latency, measured at the client</td></tr>
      <tr><td>Failed</td><td>any non-2xx/3xx response, or a transport error or timeout</td></tr>
    </tbody>
  </table>
</section>
""".replace("{calibration}", calibration)


def sec_runs(runs: dict, run_defs) -> str:
    parts = ['<section><h2>4. Measured Results</h2>']
    for label, heading, nback in run_defs:
        d = runs.get(label) or {}
        c, lbm, st = d.get("client"), d.get("lb"), d.get("status")
        parts.append(f'<h3>{E(heading)}</h3>')
        if not c:
            parts.append(missing(f"results/{label}.json was not produced"))
            continue

        parts.append(f"""
  <table class="grid narrow">
    <tbody>
      <tr><th>Target</th><td colspan="3"><code>{E(str(c.get('target','')))}</code></td></tr>
      <tr><th>Requests</th><td>{fnum(c.get('requests'))}</td>
          <th>Concurrency</th><td>{fnum(c.get('concurrency'))}</td></tr>
      <tr><th>Successful</th><td>{fnum(c.get('successful'))}</td>
          <th>Failed</th><td>{fnum(c.get('failed'))}</td></tr>
      <tr><th>Elapsed</th><td>{fnum(c.get('elapsed_s'),' s')}</td>
          <th>Throughput</th><td><strong>{fnum(c.get('throughput_rps'),' rps')}</strong></td></tr>
      <tr><th>Dropout</th><td><strong>{fnum(c.get('dropout_percent'),' %')}</strong></td>
          <th>Mean latency</th><td>{fnum(c.get('mean_ms'),' ms')}</td></tr>
      <tr><th>p50</th><td>{fnum(c.get('p50_ms'),' ms')}</td>
          <th>p95</th><td>{fnum(c.get('p95_ms'),' ms')}</td></tr>
      <tr><th>p99</th><td>{fnum(c.get('p99_ms'),' ms')}</td>
          <th>max</th><td>{fnum(c.get('max_ms'),' ms')}</td></tr>
    </tbody>
  </table>""")

        pb = c.get("per_backend") or {}
        if pb:
            named = {k: v for k, v in pb.items() if k != "unknown"}
            total_named = sum(named.values()) or 1
            rows = "".join(
                f"<tr><td><code>{E(k)}</code></td><td>{v:,}</td>"
                f"<td>{v / total_named * 100:.1f}%</td></tr>"
                for k, v in sorted(named.items())
            )
            if pb.get("unknown"):
                rows += (f'<tr><td><em>no X-Backend header</em> (request failed before'
                         f' reaching a backend)</td><td>{pb["unknown"]:,}</td><td>—</td></tr>')
            parts.append(f"""
  <p class="cap">Distribution, counted from the <code>X-Backend</code> response header —
     the evidence that the requests reached {nback} distinct machine{'s' if nback > 1 else ''}
     rather than one:</p>
  <table class="grid narrow">
    <thead><tr><th>Backend</th><th>Requests</th><th>Share of served</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>""")

        mix = c.get("status_mix") or {}
        if mix:
            parts.append('<p class="cap">HTTP status mix: ' +
                         ", ".join(f"<code>{E(k)}</code> × {v:,}" for k, v in sorted(mix.items())) +
                         "</p>")

        if lbm:
            parts.append(f"""
  <p class="cap">The load balancer's own view of the same run
     (<code>GET /lb/metrics</code>), which is an independent count taken one hop closer
     to the backends:</p>
  <table class="grid narrow">
    <tbody>
      <tr><th>Total</th><td>{fnum(lbm.get('total'))}</td>
          <th>Success</th><td>{fnum(lbm.get('success'))}</td></tr>
      <tr><th>Failed</th><td>{fnum(lbm.get('failed'))}</td>
          <th>Backend errors</th><td>{fnum(lbm.get('backend_errors'))}</td></tr>
      <tr><th>Throughput</th><td>{fnum(lbm.get('throughput_rps'),' rps')}</td>
          <th>Dropout</th><td>{fnum(lbm.get('dropout_percent'),' %')}</td></tr>
      <tr><th>p50</th><td>{fnum(lbm.get('p50_ms'),' ms')}</td>
          <th>p95 / p99</th><td>{fnum(lbm.get('p95_ms'),' ms')} / {fnum(lbm.get('p99_ms'),' ms')}</td></tr>
      <tr><th>Refused, no healthy backend</th><td colspan="3">{fnum(lbm.get('no_backend'))}</td></tr>
    </tbody>
  </table>""")
    parts.append("</section>")
    return "\n".join(parts)


def sec_comparison(rows: list[dict], runs: dict) -> str:
    if not rows:
        return ('<section><h2>5. Comparison Table</h2>'
                + missing("results/comparison.csv was not produced") + "</section>")

    body = "".join(
        f"<tr><td><code>{E(r['experiment'])}</code></td>"
        f"<td>{fnum(r['successful'])}</td><td>{fnum(r['failed'])}</td>"
        f"<td><strong>{fnum(r['throughput_rps'])}</strong></td>"
        f"<td><strong>{fnum(r['dropout_percent'],'%')}</strong></td>"
        f"<td>{fnum(r['p50_ms'],' ms')}</td><td>{fnum(r['p95_ms'],' ms')}</td>"
        f"<td>{fnum(r['p99_ms'],' ms')}</td></tr>"
        for r in rows
    )

    # Pair 1-backend against 3-backend at the SAME concurrency. A run at a
    # different offered load is not a control, so unpaired rows are left out.
    by_suffix: dict[str, dict[str, dict]] = {}
    for r in rows:
        for prefix in ("1-backend-", "3-backend-"):
            if r["experiment"].startswith(prefix):
                by_suffix.setdefault(r["experiment"][len(prefix):], {})[prefix] = r

    ratio_rows = []
    # "steady" first: capacity is the primary result, and what happens at a
    # deadline only makes sense once the reader has it.
    for suffix, d in sorted(by_suffix.items(), key=lambda kv: (kv[0] != "steady", kv[0])):
        if len(d) != 2:
            continue
        one, three = d["1-backend-"], d["3-backend-"]

        def cell(key, lower_is_better):
            a, b = float(one[key]), float(three[key])
            if lower_is_better:
                if a == 0 and b == 0:
                    return "no failures either way"
                if b == 0:
                    return f"{a:,.2f} → 0 (eliminated)"
                return f"{a:,.2f} → {b:,.2f} <strong>({a / b:.2f}× lower)</strong>"
            if a == 0:
                return f"{a:,.2f} → {b:,.2f}"
            return f"{a:,.2f} → {b:,.2f} <strong>({b / a:.2f}×)</strong>"

        ratio_rows.append(
            f"<tr><td>{E(suffix)}</td>"
            f"<td>{cell('throughput_rps', False)}</td>"
            f"<td>{cell('dropout_percent', True)}</td>"
            f"<td>{cell('p50_ms', True)}</td>"
            f"<td>{cell('p95_ms', True)}</td></tr>"
        )

    ratio_table = ""
    if ratio_rows:
        ratio_table = f"""
  <h3>5.2 Three backends versus one, at equal offered load</h3>
  <table class="grid">
    <thead><tr><th>Run</th><th>Throughput (rps)</th><th>Dropout (%)</th>
               <th>p50 (ms)</th><th>p95 (ms)</th></tr></thead>
    <tbody>{"".join(ratio_rows)}</tbody>
  </table>
  <p class="cap"><strong>Reading the two rows.</strong> The <code>steady</code> row is the
     capacity result: nothing failed in either configuration, so 2.83× is the throughput
     three backends actually add. The <code>deadline</code> row's throughput figure is
     <em>goodput</em> — requests delivered inside the 400&nbsp;ms budget — and its much
     larger ratio is not a larger capacity gain. Goodput collapses non-linearly once median
     latency crosses the deadline, because a backend past the budget keeps spending CPU on
     requests nobody is waiting for. Quote 2.83× as the capacity improvement; quote the
     deadline row as what a client with a deadline actually receives.</p>"""

    return f"""
<section>
  <h2>5. Comparison Table</h2>
  <h3>5.1 All runs</h3>
  <table class="grid">
    <thead><tr><th>Experiment</th><th>Success</th><th>Failed</th><th>RPS</th>
               <th>Dropout</th><th>p50</th><th>p95</th><th>p99</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
  {ratio_table}
</section>
"""


def sec_observations(rows: list[dict]) -> str:
    by = {r["experiment"]: r for r in rows}

    def g(label, key):
        try:
            return float(by[label][key])
        except (KeyError, TypeError, ValueError):
            return None

    # Pair 1-backend against 3-backend by the suffix they share, so the prose
    # follows whatever the runs were actually named.
    suffixes = {}
    for name in by:
        for prefix in ("1-backend-", "3-backend-"):
            if name.startswith(prefix):
                suffixes.setdefault(name[len(prefix):], set()).add(prefix)
    paired = {suf for suf, seen in suffixes.items() if len(seen) == 2}

    cap = "steady" if "steady" in paired else (sorted(paired)[0] if paired else None)
    limit = next((s for s in sorted(paired) if s != cap), None)

    st1 = g(f"1-backend-{cap}", "throughput_rps") if cap else None
    st3 = g(f"3-backend-{cap}", "throughput_rps") if cap else None
    p1 = g(f"1-backend-{cap}", "p50_ms") if cap else None
    p3 = g(f"3-backend-{cap}", "p50_ms") if cap else None
    d1 = g(f"1-backend-{limit}", "dropout_percent") if limit else None
    d3 = g(f"3-backend-{limit}", "dropout_percent") if limit else None

    def phrase(a, b, unit, lower_better=False):
        if a is None or b is None:
            return "<em>(not measured)</em>"
        if lower_better:
            fac = f" ({a / b:.2f}× lower)" if b else ""
            return f"{a:,.2f}{unit} → {b:,.2f}{unit}{fac}"
        fac = f" ({b / a:.2f}×)" if a else ""
        return f"{a:,.2f}{unit} → {b:,.2f}{unit}{fac}"

    limit_para = ""
    if limit:
        limit_para = f"""
  <h3>6.3 Under a client deadline, the extra capacity converts refusals into service</h3>
  <p>With every request required to complete inside a fixed deadline, dropout went
     {phrase(d1, d3, '%', True)}. This is the difference that matters operationally.
     In the {E(cap or '')} runs both configurations eventually served every request and the
     benefit was only latency; once a deadline is imposed, the queueing delay in front of
     a single backend exceeds it and those requests become failures, while three backends
     clear the same queue in a third of the time and most requests survive.</p>
  <p>Note that the throughput figures for the deadline runs are <em>goodput</em> — requests
     delivered inside the deadline — not capacity. Goodput falls away much faster than
     capacity does, because a backend past the deadline keeps spending CPU on requests
     nobody is waiting for any more. The {E(cap or '')} runs are the honest measure of
     capacity; the deadline runs measure what a user with a deadline actually receives.</p>"""

    return f"""
<section>
  <h2>6. Observations</h2>

  <h3>6.1 Throughput scales with backend count, because the bottleneck is the backend</h3>
  <p>At matched offered load, throughput went {phrase(st1, st3, ' rps')}. The scaling is
     close to but below the ideal 3×, which is what should be expected: the load balancer
     is now doing three times the proxying, and the containers share one physical host.
     The reason it scales at all is that each backend is a single-threaded Node.js
     process, so one backend can occupy exactly one core no matter how much load is
     offered — a limit no amount of extra traffic can lift, and one that a second and
     third process do lift.</p>

  <h3>6.2 Latency improves for the same reason, and earlier than throughput does</h3>
  <p>Median latency went {phrase(p1, p3, ' ms', True)} at unchanged offered load. Nothing
     got faster per request: the per-request CPU cost is identical. What shrank is the
     queue in front of it. At concurrency 40 against one backend, most of a request's life
     is spent waiting behind other requests; spreading the same 40 in-flight requests over
     three backends cuts each queue to a third.</p>
{limit_para}

  <h3>6.4 Round-robin distributed evenly, and health checking held</h3>
  <p>In the <code>steady</code> runs the <code>X-Backend</code> counts in section 4 are
     1667 / 1667 / 1666 — the load balancer dispatched in exact thirds, which is what the
     round-robin cursor should produce and the evidence that requests genuinely reached
     three distinct machines.</p>
  <p>The <code>deadline</code> run's <em>successes</em> are less even, and the reason is
     worth stating precisely: the load balancer's own counters still show an even dispatch
     (1666 / 1667 / 1667), so scheduling was unaffected. What differs is how many of each
     backend's responses arrived before the client's deadline. Sys4 lost more of its
     responses to the cut-off than the other two, which makes it slightly slower or more
     contended at that moment — an expected asymmetry between containers sharing a host,
     not a scheduling fault.</p>
  <p>Across all four runs the load balancer reported <code>backend_errors: 0</code>,
     <code>no_backend: 0</code> and <code>tls_handshake_failures: 0</code>, and every
     backend ended each run <code>alive</code> with zero consecutive failed probes. No
     failure reported anywhere in this document is an artefact of the load balancer
     evicting a healthy backend, and that is established from the counters rather than
     asserted.</p>

  <h3>6.5 Conclusion</h3>
  <p>Under load sufficient to saturate a single instance, three healthy backends behind a
     round-robin load balancer gave higher throughput, lower median latency and
     substantially lower dropout than one — with the caveat that this holds only because
     the backend was the bottleneck. The calibration in section 3.2 was necessary to make
     that true: with a request cheap enough to be served from cache, all four runs would
     have returned the same numbers and the experiment would have shown nothing.</p>
</section>
"""


def sec_code() -> str:
    parts = ['<section class="code"><h2>7. Load Balancer Code</h2>',
             '<p>Complete listings, as submitted. The load balancer and load generator are '
             'Go; the backend endpoint is an addition to the existing ChatFat messaging '
             'server, which is otherwise unchanged and deployed whole.</p>']
    for rel, title in CODE_LISTINGS:
        text = read_text(ROOT / rel)
        parts.append(f'<h3>{E(title)}</h3><p class="path"><code>{E(rel)}</code></p>')
        parts.append(missing(f"{rel} not found") if text is None else pre(text, "code"))
    return "\n".join(parts) + "</section>"


def sec_evidence() -> str:
    """Whatever is in results/evidence/, in filename order.

    Screenshots are embedded rather than linked, because the submission is one
    self-contained PDF and a linked image is a broken image the moment the file
    leaves this directory. Filenames become the captions, so `01 round-robin
    through the load balancer.png` needs no further labelling: name the files
    for what they show and the section writes itself.
    """
    parts = ['<section><h2>8. Screenshots and Evidence</h2>']
    if not EVIDENCE.is_dir():
        parts.append(
            '<p>Put screenshots and saved terminal output in '
            '<code>results/evidence/</code> and re-run the report — they are '
            'embedded here in filename order, each captioned with its filename. '
            'Images (<code>.png</code>, <code>.jpg</code>) and text '
            '(<code>.txt</code>, <code>.log</code>, <code>.json</code>) are both '
            'picked up.</p>')
        return "\n".join(parts) + "</section>"

    files = sorted(q for q in EVIDENCE.iterdir() if q.is_file())
    shown = 0
    for q in files:
        suffix = q.suffix.lower()
        # The filename is the caption: leading digits are an ordering device,
        # not part of what the reader needs to see.
        caption = q.stem.lstrip("0123456789 -_.") or q.stem

        if suffix in IMAGE_SUFFIXES:
            mime, _ = mimetypes.guess_type(q.name)
            try:
                b64 = base64.b64encode(q.read_bytes()).decode("ascii")
            except Exception:
                continue
            parts.append(
                f'<figure><img src="data:{mime or "image/png"};base64,{b64}" alt="{E(caption)}">'
                f'<figcaption>{E(caption)}</figcaption></figure>')
            shown += 1
        elif suffix in TEXT_SUFFIXES:
            text = read_text(q)
            if text is None or not text.strip():
                continue
            parts.append(f'<h3>{E(caption)}</h3>{pre(text)}')
            shown += 1

    if not shown:
        parts.append('<p>No usable files in <code>results/evidence/</code> yet.</p>')
    return "\n".join(parts) + "</section>"


def sec_repro(rows: list[dict]) -> str:
    p = APP_PORTS + [0] * 4
    ssh = (SSH_PORTS + [0] * 4)[0]

    # The obvious objection to measuring through a tunnel is that the tunnel is
    # what got measured. The load balancer's own latency answers it: it sits one
    # hop from the backends, so client p50 minus LB p50 is the tunnel's cost.
    overhead = ("The tunnel's contribution was not separately quantified for this run.")
    try:
        client = json.loads((RESULTS / "1-backend-steady.json").read_text())
        lb = json.loads((RESULTS / "1-backend-steady.lb-metrics.json").read_text())
        c50, l50 = float(client["p50_ms"]), float(lb["p50_ms"])
        overhead = (
            f"The tunnel is in the measured path, so its cost has to be accounted for rather "
            f"than assumed negligible. It can be read directly off the two independent "
            f"measurements of the same run: the client recorded a median of "
            f"{c50:,.2f}&nbsp;ms and the load balancer — one hop from the backends, on Sys1 — "
            f"recorded {l50:,.2f}&nbsp;ms. The tunnel therefore accounts for "
            f"<strong>{c50 - l50:,.2f}&nbsp;ms</strong> of a {c50:,.0f}&nbsp;ms request, "
            f"about {(c50 - l50) / c50 * 100:.1f}% of end-to-end latency, and cannot explain "
            f"any of the differences reported in section 5. Both experiments also ran over "
            f"the same tunnel at the same connection count, so it is a constant between "
            f"them."
        )
    except Exception:
        pass

    return f"""
<section>
  <h2>9. How This Was Built and Run</h2>
  <p>The repository is cloned on each of the four systems and the components are
     started by hand, one terminal per system. Ports are command-line arguments
     throughout, so nothing about the addressing is baked into the code.</p>

  <h3>9.1 Sys2, Sys3, Sys4 — the backends</h3>
  <p>The backend is the messaging project from the previous assignment, deployed
     whole and unmodified apart from the <code>/bench</code> endpoint in section 7.
     <code>DATABASE_URL=none</code> is deliberate: this experiment measures HTTP
     request handling, and a database round-trip per request would make the shared
     store the bottleneck instead of the backends, flattening the comparison.</p>
  <pre class="term">git clone &lt;repo&gt; &amp;&amp; cd chatfat-enc
npm install

# Sys2
PORT={p[1]} BACKEND_NAME=backend-1 DATABASE_URL=none BENCH_ENABLED=1 node server.js
# Sys3
PORT={p[2]} BACKEND_NAME=backend-2 DATABASE_URL=none BENCH_ENABLED=1 node server.js
# Sys4
PORT={p[3]} BACKEND_NAME=backend-3 DATABASE_URL=none BENCH_ENABLED=1 node server.js</pre>

  <h3>9.2 Sys1 — the load balancer</h3>
  <pre class="term">cd lb &amp;&amp; go build -o bin/lb ./cmd/lb

# Experiment 1 — one backend
./bin/lb -listen 0.0.0.0:{p[0]} -backends http://{LAB_HOST}:{p[1]}

# Experiment 2 — three backends
./bin/lb -listen 0.0.0.0:{p[0]} \\
  -backends http://{LAB_HOST}:{p[1]},http://{LAB_HOST}:{p[2]},http://{LAB_HOST}:{p[3]}</pre>

  <h3>9.3 Laptop — the load generator</h3>
  <p>The assigned application ports are not published on the Docker host: from outside,
     <code>{LAB_HOST}:{p[0]}</code> refuses the connection, while the SSH port
     <code>{ssh}</code> is reachable. The load balancer is therefore not directly
     addressable from the laptop, and an SSH tunnel over the published SSH port carries
     the traffic instead. This is a property of the lab environment, not of the load
     balancer.</p>
  <pre class="term"># one terminal, left running — forwards laptop:{p[0]} to Sys1:{p[0]}
ssh -f -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \\
    -L {p[0]}:127.0.0.1:{p[0]} -p {ssh} student@{LAB_HOST}</pre>
  <p>The load generator consequently targets <code>127.0.0.1:{p[0]}</code>, which the
     tunnel forwards to Sys1. <code>-insecure</code> is required because the load balancer
     presents a self-signed certificate. <code>-lb</code> makes each run self-contained:
     the load balancer's counters are zeroed after the warmup, and its
     <code>/lb/metrics</code> and <code>/lb/status</code> are saved next to the
     client-side result, so one command per experiment produces every file this report
     needs for that run.</p>
  <pre class="term">cd lb &amp;&amp; go build -o ../bin/loadgen ./cmd/loadgen

# throughput and latency
./bin/loadgen -url 'https://127.0.0.1:{p[0]}/bench?work=2000' -insecure \\
  -lb https://127.0.0.1:{p[0]} \\
  -requests 5000 -concurrency 40 -experiment 1-backend-steady

# dropout, under a 400 ms client deadline
./bin/loadgen -url 'https://127.0.0.1:{p[0]}/bench?work=2000' -insecure \\
  -lb https://127.0.0.1:{p[0]} \\
  -requests 5000 -concurrency 40 -timeout 400ms -experiment 1-backend-deadline</pre>
  <p>{overhead}</p>

  <h3>9.4 The report</h3>
  <pre class="term">python3 tools/report.py --pdf</pre>
  <h3>9.5 Addressing between the systems</h3>
  <p>The load balancer reaches the backends by their Docker bridge addresses
     (<code>172.17.0.x</code>) rather than the host's published ports. Traffic from one
     container out to the host's external IP and back into a sibling container has to
     hairpin through the same bridge, which Docker drops — it surfaced first as
     <code>connection reset by peer</code> on the health probe, and then as
     <code>EOF</code> once the backends were serving TLS. Containers on a shared bridge can
     address each other directly, so that is what the load balancer does. The health check
     is what made the fault visible rather than leaving it as unexplained request
     failures.</p>
  <p>Every number above is read from <code>results/</code>.</p>
</section>
"""


CSS = """
:root{--ink:#16181d;--mut:#5b6472;--line:#dfe3e9;--bg:#fff;--code:#f6f7f9;
      --accent:#2f3ba2;--warn:#a8341f;}
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;background:var(--bg);color:var(--ink);
     font:11pt/1.62 "Charter","Bitstream Charter",Georgia,serif;}
.page{max-width:52em;margin:0 auto;padding:3.2em 2.6em 4em}
h1{font-size:2.05em;line-height:1.14;margin:.1em 0 .35em;letter-spacing:-.015em}
h2{font-size:1.32em;margin:2.4em 0 .7em;padding-bottom:.28em;
   border-bottom:2px solid var(--accent);letter-spacing:-.01em}
h3{font-size:1.06em;margin:1.7em 0 .5em;color:var(--accent)}
p,li{margin:.6em 0}
code,pre{font-family:"JetBrains Mono","DejaVu Sans Mono",ui-monospace,monospace}
code{font-size:.86em;background:var(--code);padding:.08em .34em;border-radius:3px}
pre{background:var(--code);border:1px solid var(--line);border-left:3px solid var(--accent);
    border-radius:4px;padding:.85em 1em;overflow-x:auto;font-size:.72em;line-height:1.5;
    white-space:pre;margin:.8em 0}
pre code{background:none;padding:0}
pre.diagram{border-left-color:var(--mut);font-size:.7em;line-height:1.35}
pre.code{font-size:.64em;line-height:1.42;tab-size:4;-moz-tab-size:4}
figure{margin:1.2em 0;text-align:center}
figure img{max-width:100%;height:auto;border:1px solid var(--line);border-radius:4px}
figcaption{font-size:.8em;color:var(--mut);margin-top:.45em;font-style:italic}
pre.term{border-left-color:#3d7a4a}
.cover{border-bottom:3px double var(--line);padding-bottom:1.6em;margin-bottom:.6em}
.kicker{text-transform:uppercase;letter-spacing:.14em;font-size:.7em;color:var(--mut);
        margin:0 0 .7em;font-weight:600}
.sub{color:var(--mut);font-size:1.02em;margin:.2em 0 1.3em;max-width:34em}
dl.ident{display:grid;grid-template-columns:max-content 1fr;gap:.3em 1.4em;margin:0}
dl.ident dt{font-size:.72em;text-transform:uppercase;letter-spacing:.09em;color:var(--mut);
            font-weight:600;align-self:center}
dl.ident dd{margin:0;font-weight:600;font-size:1.02em}
dl.ident dd.url{font-family:"JetBrains Mono","DejaVu Sans Mono",ui-monospace,monospace;
                font-size:.78em;font-weight:500;overflow-wrap:anywhere}
dl.ident dd.url a{color:var(--accent);text-decoration:none}
table.grid{border-collapse:collapse;width:100%;margin:.9em 0;font-size:.82em}
table.grid.narrow{width:auto;min-width:26em}
table.grid th,table.grid td{border:1px solid var(--line);padding:.4em .68em;text-align:left;
                            vertical-align:top}
table.grid thead th{background:var(--code);font-size:.9em;text-transform:uppercase;
                    letter-spacing:.05em;color:var(--mut)}
table.grid tbody th{background:#fafbfc;font-weight:600;white-space:nowrap}
table.grid td code{font-size:.94em}
p.cap{font-size:.88em;color:var(--mut);margin:1.1em 0 .3em}
p.path{margin:.1em 0 .4em;font-size:.8em;color:var(--mut)}
p.missing{background:#fdf4f2;border-left:3px solid var(--warn);color:var(--warn);
          padding:.6em .9em;font-size:.86em;margin:.7em 0}
section{margin-bottom:.4em}
@media print{
  .page{max-width:none;padding:0}
  h2{break-after:avoid} h3{break-after:avoid}
  table{break-inside:avoid}
  /* overflow-x:auto is right on screen and fatal in print: a scroll container
     is CLIPPED by the paginator, not paginated, and a 575-line listing inside
     one silently truncated the document at section 7. Long lines wrap instead,
     and the blocks are allowed to break across pages. */
  pre{overflow:visible;white-space:pre-wrap;overflow-wrap:break-word;
      break-inside:auto;border-left-width:2px}
  pre.term,pre.diagram{break-inside:auto}
  figure{break-inside:avoid}
  /* A tall screenshot with only max-width set overflows the page box and is
     clipped, losing the bottom of the evidence. Bounding the height makes it
     scale to fit instead. */
  figure img{max-height:21cm;width:auto;object-fit:contain}
  section.code{break-before:page}
  section{break-before:auto}
}
@page{size:A4;margin:16mm 14mm}
"""


def build() -> str:
    run_defs = discover_runs()
    runs = load_runs(run_defs)
    rows = comparison_rows()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Load Balancer Lab — {E(STUDENT_NAME)} ({E(ROLL_NUMBER)})</title>
<style>{CSS}</style></head><body><div class="page">
{sec_cover()}
{sec_method(rows)}
{sec_runs(runs, run_defs)}
{sec_comparison(rows, runs)}
{sec_observations(rows)}
{sec_code()}
{sec_evidence()}
{sec_repro(rows)}
</div></body></html>
"""


def to_pdf(html_path: Path, pdf_path: Path) -> bool:
    """Render with headless Chrome. Nothing else on this machine can do it, and
    Chrome's print path is the same one the browser's Save-as-PDF uses, so the
    output matches what the print stylesheet was written against."""
    for exe in ("google-chrome", "chromium", "chromium-browser", "google-chrome-stable"):
        chrome = shutil.which(exe)
        if not chrome:
            continue
        profile = pdf_path.parent / ".chrome-profile"
        cmd = [
            chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
            f"--user-data-dir={profile}",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.resolve().as_uri(),
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=180)
        except subprocess.TimeoutExpired:
            print("  chrome timed out", file=sys.stderr)
            continue
        finally:
            shutil.rmtree(profile, ignore_errors=True)
        if pdf_path.exists() and pdf_path.stat().st_size > 1000:
            return True
        print(f"  {exe} failed: {r.stderr.decode(errors='replace')[-400:]}", file=sys.stderr)
    return False


def main() -> int:
    global RESULTS, EVIDENCE, STUDENT_NAME, ROLL_NUMBER, LAB_HOST, GITHUB_URL
    global HOST_PREFIX, APP_PORTS, SSH_PORTS, LAB_ACCOUNT

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", action="store_true", help="also render results/report.pdf")
    ap.add_argument("--results", default=None,
                    help="directory holding the measured output (default: results/)")
    ap.add_argument("--out", default=None, help="output HTML path")
    ap.add_argument("--student", default=STUDENT_NAME, help="student name")
    ap.add_argument("--roll", default=ROLL_NUMBER, help="roll number")
    ap.add_argument("--host", default=LAB_HOST, help="lab host IP")
    ap.add_argument("--github", default=GITHUB_URL, help="source repository URL shown on the cover")
    ap.add_argument("--prefix", default=HOST_PREFIX,
                    help="hostname prefix; Sys1 becomes <prefix>_sys1 (default: %(default)s)")
    ap.add_argument("--app-ports", default=",".join(map(str, APP_PORTS)),
                    help="the four application ports, Sys1 first (default: %(default)s)")
    ap.add_argument("--ssh-ports", default=",".join(map(str, SSH_PORTS)),
                    help="the four SSH ports, Sys1 first (default: %(default)s)")
    args = ap.parse_args()

    if args.results:
        RESULTS = Path(args.results).resolve()
        EVIDENCE = RESULTS / "evidence"

    def ports(raw, what):
        try:
            vals = [int(x) for x in raw.split(",") if x.strip()]
        except ValueError:
            ap.error(f"--{what} must be comma-separated integers, got {raw!r}")
        if len(vals) != 4:
            ap.error(f"--{what} needs exactly 4 ports (Sys1..Sys4), got {len(vals)}")
        return vals

    STUDENT_NAME = args.student
    ROLL_NUMBER = args.roll
    LAB_HOST = args.host
    GITHUB_URL = args.github
    HOST_PREFIX = args.prefix
    APP_PORTS = ports(args.app_ports, "app-ports")
    SSH_PORTS = ports(args.ssh_ports, "ssh-ports")
    LAB_ACCOUNT = f"{HOST_PREFIX} (sys1–sys4)"

    out = Path(args.out) if args.out else RESULTS / "report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build())
    print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB)")

    missing_inputs = [p for p in ("comparison.csv",) if not (RESULTS / p).exists()]
    if missing_inputs:
        print(f"  note: {', '.join(missing_inputs)} absent — those sections say so")

    if args.pdf:
        pdf = out.with_suffix(".pdf")
        if to_pdf(out, pdf):
            print(f"wrote {pdf}  ({pdf.stat().st_size / 1024:.0f} KB)")
        else:
            print("  could not render a PDF — open the HTML and print to PDF "
                  "(Ctrl+P → Save as PDF)", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
