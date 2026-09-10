#!/usr/bin/env python3
"""tools/lab6_plots.py — the report's figures, drawn from the measured CSVs.

Reads what tools/lab6-experiments.sh produced in results/lab6/ and writes PNGs
next to it. Nothing here is hand-entered: every number on every axis comes from
a samples.csv or utilization.csv written by the load generator.

    python3 tools/lab6_plots.py [--results results/lab6]

Four figures:

    1  response-time.png     latency over the run, both strategies, degraded cluster
    2  utilization.png       CPU and event-loop delay for all four systems
    3  distribution.png      where each strategy actually sent the requests
    4  latency-summary.png   p50/p95/p99 across all four runs
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

# Validated categorical palette (light surface). Slots are assigned in fixed
# order and never cycled; see the project's data-visualisation notes.
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
SYSTEM_COLORS = {"sys1": BLUE, "sys2": ORANGE, "sys3": AQUA, "sys4": YELLOW}
# Strategy identity is fixed across every figure so a reader never has to
# re-learn which colour means what between plots.
STRATEGY_COLORS = {"p2c": BLUE, "round-robin": ORANGE}

INK = "#16181d"
MUTED = "#5b6472"
GRID = "#e3e6ea"
SURFACE = "#ffffff"

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": GRID,
    "axes.labelcolor": MUTED,
    "axes.titlecolor": INK,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "font.size": 9,
    "axes.titlesize": 11,
    "axes.titleweight": "bold",
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.7,
    "legend.frameon": False,
    "figure.dpi": 130,
})


def style(ax, title="", xlabel="", ylabel=""):
    """Recessive frame: the data should be the darkest thing in the figure."""
    ax.set_title(title, loc="left", pad=10)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.set_axisbelow(True)


def read_samples(path: Path):
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return [
            {"t": float(r["t_s"]), "route": r["route"], "ms": float(r["latency_ms"]),
             "backend": r["backend"], "ok": r["ok"] == "true"}
            for r in csv.DictReader(fh)
        ]


def read_util(path: Path):
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        out = []
        for r in csv.DictReader(fh):
            try:
                out.append({"t": float(r["t_s"]), "system": r["system"], "role": r["role"],
                            "cpu": float(r["cpu_percent"]),
                            # Falls back to the whole-machine figure for CSVs
                            # written before the per-core column existed.
                            "cpu_core": float(r.get("cpu_core_percent") or r["cpu_percent"]),
                            "lag": float(r["lag_ms"])})
            except ValueError:
                continue
        return out


def read_summary(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def buckets(rows, width=2.0):
    """Group samples into fixed time bins, returning (centre, p50, p95) per bin.

    Binned rather than plotted per request: 6000 scattered points hide the trend
    they are supposed to show, and a rolling percentile is what the eye is
    actually looking for."""
    by = defaultdict(list)
    for r in rows:
        by[int(r["t"] // width)].append(r["ms"])
    xs, p50s, p95s = [], [], []
    for b in sorted(by):
        v = sorted(by[b])
        if not v:
            continue
        xs.append(b * width + width / 2)
        p50s.append(v[len(v) // 2])
        p95s.append(v[min(len(v) - 1, int(len(v) * 0.95))])
    return xs, p50s, p95s


def fig_response_time(res: Path, out: Path):
    """Latency through the run, both strategies, on the degraded cluster."""
    runs = [("degraded-round-robin", "round-robin"), ("degraded-p2c", "p2c")]
    data = {label: read_samples(res / f"{name}.samples.csv") for name, label in runs}
    if not any(data.values()):
        return None

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
    for ax, (key, rows) in zip((ax1, ax2), data.items()):
        colour = STRATEGY_COLORS[key]
        xs, p50, p95 = buckets(rows)
        if not xs:
            continue
        ax.plot(xs, p95, color=colour, linewidth=2, label="p95")
        ax.plot(xs, p50, color=colour, linewidth=2, linestyle=(0, (4, 3)), alpha=0.75, label="p50")
        ax.fill_between(xs, p50, p95, color=colour, alpha=0.10, linewidth=0)
        style(ax, f"{key}", "time into run (s)", "response time (ms)" if ax is ax1 else "")
        # Direct labels: the contrast check obliges visible labelling rather
        # than relying on the line colour alone.
        ax.annotate("p95", (xs[-1], p95[-1]), xytext=(6, 0), textcoords="offset points",
                    color=MUTED, va="center", fontsize=8)
        ax.annotate("p50", (xs[-1], p50[-1]), xytext=(6, 0), textcoords="offset points",
                    color=MUTED, va="center", fontsize=8)
        ax.margins(x=0.10)

    fig.suptitle("Response time with one backend degraded", x=0.078, ha="left",
                 fontsize=13, fontweight="bold", color=INK)
    fig.text(0.078, 0.90, "Same offered load and seed; only the selection strategy differs. Lower is better.",
             fontsize=9, color=MUTED, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.87])
    p = out / "response-time.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    return p


def fig_utilization(res: Path, out: Path):
    """CPU and event-loop delay for all four systems — the assignment asks for
    utilisation of every machine, not just the busy one."""
    rows = read_util(res / "degraded-p2c.utilization.csv")
    if not rows:
        return None

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6.6), sharex=True)
    systems = sorted({r["system"] for r in rows})
    for sysname in systems:
        pts = sorted((r for r in rows if r["system"] == sysname), key=lambda r: r["t"])
        if not pts:
            continue
        colour = SYSTEM_COLORS.get(sysname, MUTED)
        role = pts[0]["role"]
        label = f"{sysname} ({role})"
        ax1.plot([p["t"] for p in pts], [p["cpu_core"] for p in pts],
                 color=colour, linewidth=2, label=label)
        if role != "load-balancer":
            ax2.plot([p["t"] for p in pts], [p["lag"] for p in pts],
                     color=colour, linewidth=2, label=label)

    style(ax1, "Process CPU, as a share of one core", "", "% of one core")
    style(ax2, "Event-loop delay — the wait a new request meets on arrival",
          "time into run (s)", "milliseconds")
    # Guarded: a run scraped without -backends has no per-backend rows, and
    # calling legend() on an empty axes warns and leaves a blank panel that
    # looks like a broken figure rather than an absent measurement.
    for ax, note in ((ax1, "no utilisation samples"), (ax2, "no backend samples — was the load generator run with -backends?")):
        if ax.get_legend_handles_labels()[0]:
            ax.legend(loc="upper left", ncol=4, fontsize=8, labelcolor=MUTED)
        else:
            ax.text(0.5, 0.5, note, transform=ax.transAxes, ha="center", va="center",
                    fontsize=9, color=MUTED)

    # Header drawn after tight_layout has reserved the space for it, and saved
    # without a tight bbox: cropping to content moves the figure coordinates the
    # header is positioned in, which is what made the subtitle land on the title.
    fig.tight_layout(rect=[0, 0, 1, 0.86])
    fig.text(0.055, 0.975, "System utilisation, all four systems (degraded run, p2c)",
             ha="left", va="top", fontsize=13, fontweight="bold", color=INK)
    fig.text(0.055, 0.930,
             "Sys4 carries competing load. Hosts have 120 cores, so a single-threaded backend tops out near 100% of ONE core;\n"
             "as a share of the whole machine every figure here is under 1%, which is why event-loop delay is the saturation signal.",
             fontsize=8.5, color=MUTED, ha="left", va="top", linespacing=1.5)
    p = out / "utilization.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def fig_distribution(res: Path, out: Path):
    """Where the requests actually went. This is the requirement made visible:
    a fixed rotation cannot avoid a degraded backend; a load-aware one does."""
    runs = [("degraded-round-robin", "round-robin"), ("degraded-p2c", "p2c")]
    counts = {}
    for name, label in runs:
        s = read_summary(res / f"{name}.summary.json")
        if not s:
            continue
        per = {k: v for k, v in (s.get("per_backend") or {}).items() if k != "unknown"}
        if per:
            counts[label] = per
    if not counts:
        return None

    backends = sorted({b for c in counts.values() for b in c})
    fig, ax = plt.subplots(figsize=(8, 4))
    n = len(counts)
    width = 0.38
    for i, (label, per) in enumerate(counts.items()):
        xs = [j + (i - (n - 1) / 2) * (width + 0.02) for j in range(len(backends))]
        ys = [per.get(b, 0) for b in backends]
        ax.bar(xs, ys, width=width, color=STRATEGY_COLORS[label], label=label,
               edgecolor=SURFACE, linewidth=2)
        for x, y in zip(xs, ys):
            ax.annotate(f"{y:,}", (x, y), xytext=(0, 4), textcoords="offset points",
                        ha="center", fontsize=8, color=MUTED)

    ax.set_xticks(range(len(backends)))
    ax.set_xticklabels([b + ("\n(degraded)" if b.endswith("3") else "") for b in backends])
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v):,}"))
    style(ax, "Requests served per backend, cluster degraded", "", "requests")
    ax.legend(loc="upper right", labelcolor=MUTED)
    fig.text(0.02, -0.04,
             "backend-3 runs on Sys4, which carries competing load throughout both runs.",
             fontsize=9, color=MUTED)
    fig.tight_layout()
    p = out / "distribution.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    return p


def fig_latency_summary(res: Path, out: Path):
    """p50/p95/p99 across all four runs, so the balanced case is visible next to
    the degraded one — the cost of load-aware routing when there is nothing to
    route around is part of the answer."""
    order = [("balanced-round-robin", "balanced\nround-robin", ORANGE),
             ("balanced-p2c", "balanced\np2c", BLUE),
             ("degraded-round-robin", "degraded\nround-robin", ORANGE),
             ("degraded-p2c", "degraded\np2c", BLUE)]
    got = [(lab, col, read_summary(res / f"{n}.summary.json")) for n, lab, col in order]
    got = [(lab, col, s) for lab, col, s in got if s]
    if not got:
        return None

    metrics = [("p50_ms", "p50"), ("p95_ms", "p95"), ("p99_ms", "p99")]
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8))
    for ax, (key, title) in zip(axes, metrics):
        labels = [lab for lab, _, _ in got]
        vals = [s.get(key, 0) for _, _, s in got]
        cols = [c for _, c, _ in got]
        ax.bar(range(len(vals)), vals, color=cols, width=0.62,
               edgecolor=SURFACE, linewidth=2)
        for i, v in enumerate(vals):
            ax.annotate(f"{v:,.0f}", (i, v), xytext=(0, 4), textcoords="offset points",
                        ha="center", fontsize=8, color=MUTED)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, fontsize=8)
        style(ax, f"{title} response time", "", "ms" if ax is axes[0] else "")
        ax.margins(y=0.18)

    fig.suptitle("Response-time percentiles across all four runs", x=0.045, ha="left",
                 fontsize=13, fontweight="bold", color=INK)
    fig.text(0.045, 0.90, "Blue: performance-based (p2c).   Orange: fixed round-robin.   Lower is better.",
             fontsize=9, color=MUTED, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.86])
    p = out / "latency-summary.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default="results/lab6")
    args = ap.parse_args()
    res = Path(args.results).resolve()
    if not res.is_dir():
        print(f"no such directory: {res}", file=sys.stderr)
        return 1

    made = []
    for fn in (fig_response_time, fig_utilization, fig_distribution, fig_latency_summary):
        try:
            p = fn(res, res)
        except Exception as err:  # a missing run should not lose the other figures
            print(f"  {fn.__name__}: {err}", file=sys.stderr)
            continue
        if p:
            made.append(p)
            print(f"wrote {p}")
    if not made:
        print("no figures produced — is results/lab6 populated?", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
