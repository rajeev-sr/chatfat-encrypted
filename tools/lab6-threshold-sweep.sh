#!/usr/bin/env bash
# tools/lab6-threshold-sweep.sh — pick -load-threshold by measuring it.
#
# The threshold is in the same units as the score the balancer computes:
# estimated milliseconds to serve a request. That makes it something to reason
# about rather than a knob to twiddle, but the right value still depends on the
# workload and the hardware, so it is chosen here by measurement.
#
# Every run is on the degraded cluster, because that is the only condition where
# the threshold does anything — with all backends equal, nothing is ever over it.
# Everything else is held fixed, including the load generator's seed.
set -uo pipefail

HOST=10.1.75.53
LB_PUB="https://$HOST:3273"
BACKENDS_PUB="http://$HOST:3274,http://$HOST:3275,http://$HOST:3276"
SSH1=(ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p 2273 "student@$HOST")
SSH4=(ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p 2276 "student@$HOST")

DURATION="${1:-30s}"
USERS="${2:-60}"
SEED=424242
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/results/lab6"
BIN="$ROOT/bin/chatload"
TMP="$OUT/.sweep"

# 0 disables the threshold entirely, which is the control: it leaves plain
# load-preference with no switching, and shows what the threshold is worth.
THRESHOLDS=(0 25 50 100 150 300 600)

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
mkdir -p "$TMP"

restart_lb() {
  "${SSH1[@]}" "
    tmux kill-session -t lb 2>/dev/null
    tmux new -d -s lb
    tmux send-keys -t lb 'cd ~/chatfat-encrypted && ./bin/lb -listen 0.0.0.0:3000 \
      -backends http://172.17.0.75:3000,http://172.17.0.76:3000,http://172.17.0.77:3000 \
      -strategy p2c -load-threshold $1 \
      -health-timeout 5s -backend-timeout 15s \
      -tls-cert ./tls-cert.pem -tls-key ./tls-key.pem' C-m
    sleep 4" >/dev/null 2>&1
  curl -sk -m 8 "$LB_PUB/lb/status" >/dev/null 2>&1
}

say "starting competing load on Sys4"
"${SSH4[@]}" "
  tmux kill-session -t hog 2>/dev/null
  tmux new -d -s hog
  tmux send-keys -t hog 'while true; do seq 1 16 | xargs -P 16 -I{} curl -s -o /dev/null -m 10 \"http://127.0.0.1:3000/bench?work=4000\"; done' C-m" >/dev/null 2>&1
sleep 6

for t in "${THRESHOLDS[@]}"; do
  say "threshold ${t}ms"
  restart_lb "$t"
  "$BIN" -url "$LB_PUB" -insecure -users "$USERS" -duration "$DURATION" \
    -backends "$BACKENDS_PUB" -seed "$SEED" \
    -experiment "thr-$t" -out "$TMP" 2>&1 | grep -E 'msg/s|throughput|latency all|per backend'
  sleep 5
done

say "stopping competing load"
"${SSH4[@]}" 'tmux kill-session -t hog 2>/dev/null; true' >/dev/null 2>&1

python3 - "$TMP" "$OUT" <<'PY'
import json, sys, glob, os, re
tmp, out = sys.argv[1], sys.argv[2]
rows = []
for f in sorted(glob.glob(os.path.join(tmp, "thr-*.summary.json"))):
    d = json.load(open(f))
    t = int(re.search(r"thr-(\d+)", d["experiment"]).group(1))
    per = {k: v for k, v in (d.get("per_backend") or {}).items() if k != "unknown"}
    rows.append({
        "threshold": t,
        "served": d["successful"],
        "total": d["total_requests"],
        "messages_per_s": d["messages_per_s"],
        "p50_ms": d["p50_ms"], "p95_ms": d["p95_ms"], "p99_ms": d["p99_ms"],
        "failed": d["failed"],
        "dist": " / ".join(f"{per.get(b,0):,}" for b in sorted(per)),
    })
rows.sort(key=lambda r: r["threshold"])
with open(os.path.join(out, "threshold-sweep.json"), "w") as fh:
    json.dump(rows, fh, indent=2)

# A run that failed is not a fast run. Selecting on p95 alone once picked a
# threshold from a run where the balancer had not come back up: every request
# errored in a few milliseconds, which looked like the best latency in the
# sweep. Candidates must have actually served the load before their latency
# means anything.
valid = [r for r in rows if r["served"] > 0 and r["failed"] / max(1, r["total"]) < 0.02]
best = min(valid, key=lambda r: r["p95_ms"]) if valid else None
for r in rows:
    if r not in valid:
        r["excluded"] = "run failed — not a candidate"
with open(os.path.join(out, "threshold-sweep.json"), "w") as fh:
    json.dump(rows, fh, indent=2)
print()
print("  threshold  msg/s     p50        p95        p99        b1 / b2 / b3")
print("  " + "-" * 72)
for r in rows:
    note = ""
    if r.get("excluded"):
        note = "  <- EXCLUDED, " + r["excluded"]
    elif best and r is best:
        note = "  <- lowest p95"
    print(f"  {r['threshold']:>6} ms  {r['messages_per_s']:>7.1f}  {r['p50_ms']:>7.1f}ms  "
          f"{r['p95_ms']:>7.1f}ms  {r['p99_ms']:>7.1f}ms  {r['dist']}{note}")
if best:
    print(f"\n  chosen: -load-threshold {best['threshold']}")
else:
    print("\n  no valid candidate — every run failed")
PY

say "restoring the deployed configuration"
BEST=$(python3 -c "
import json
rows=json.load(open('$OUT/threshold-sweep.json'))
ok=[r for r in rows if not r.get('excluded')]
print(min(ok,key=lambda r:r['p95_ms'])['threshold'] if ok else 50)" 2>/dev/null || echo 50)
restart_lb "$BEST"
say "load balancer running with -load-threshold $BEST"
