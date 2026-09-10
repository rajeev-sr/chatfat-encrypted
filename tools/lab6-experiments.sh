#!/usr/bin/env bash
# tools/lab6-experiments.sh — the measured runs behind the Lab 6 report.
#
# Four runs in a 2x2: two selection strategies against two states of the
# cluster. The comparison only means something if everything except the one
# variable is held fixed, so every run uses the same client count, duration,
# message-length range and think-time range, and the load generator is seeded
# identically — so the two strategies see the same sequence of messages at the
# same offered rate, and the only difference is where the balancer sends them.
#
#   balanced-*   all three backends idle. Round-robin is near-optimal here, so
#                this run exists to show that load-aware routing costs nothing
#                when there is nothing to route around.
#   degraded-*   one backend (Sys4) is externally loaded, the way a shared
#                machine gets busy with someone else's work. This is where a
#                fixed rotation keeps posting into a queue it can see is
#                growing, and where switching is worth something.
#
# Usage:  tools/lab6-experiments.sh [duration] [users]
set -uo pipefail

HOST=10.1.75.53
LB_PUB="https://$HOST:3273"
BACKENDS_PUB="http://$HOST:3274,http://$HOST:3275,http://$HOST:3276"
SSH1=(ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p 2273 "student@$HOST")
SSH4=(ssh -o BatchMode=yes -o StrictHostKeyChecking=no -p 2276 "student@$HOST")

DURATION="${1:-45s}"
USERS="${2:-60}"
SEED=424242
OUT="$(cd "$(dirname "$0")/.." && pwd)/results/lab6"
BIN="$(cd "$(dirname "$0")/.." && pwd)/bin/chatload"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()  { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }

# The balancer is restarted rather than reconfigured: -strategy is read once at
# startup, and a run that changed strategy midway would be neither one thing
# nor the other.
restart_lb() {
  local strategy="$1" threshold="$2"
  "${SSH1[@]}" "
    tmux kill-session -t lb 2>/dev/null
    tmux new -d -s lb
    tmux send-keys -t lb 'cd ~/chatfat-encrypted && ./bin/lb -listen 0.0.0.0:3000 \
      -backends http://172.17.0.75:3000,http://172.17.0.76:3000,http://172.17.0.77:3000 \
      -strategy $strategy -load-threshold $threshold \
      -health-timeout 5s -backend-timeout 15s \
      -tls-cert ./tls-cert.pem -tls-key ./tls-key.pem' C-m
    sleep 4" >/dev/null 2>&1
  local healthy
  healthy=$(curl -sk -m 8 "$LB_PUB/lb/status" | python3 -c 'import sys,json;print(json.load(sys.stdin)["healthy"])' 2>/dev/null || echo 0)
  ok "load balancer restarted: strategy=$strategy threshold=${threshold}ms healthy=$healthy"
  [ "$healthy" = "3" ] || { echo "  !! expected 3 healthy backends, got $healthy" >&2; return 1; }
}

# Competing work on Sys4, applied from Sys4 itself so it does not consume the
# link the measurement runs over. Occupies the backend's event loop the way a
# co-tenant process would, rather than pausing or killing it — a stopped
# backend tests health checking, which is a different requirement.
start_hog() {
  "${SSH4[@]}" "
    tmux kill-session -t hog 2>/dev/null
    tmux new -d -s hog
    tmux send-keys -t hog 'while true; do seq 1 16 | xargs -P 16 -I{} curl -s -o /dev/null -m 10 \"http://127.0.0.1:3000/bench?work=4000\"; done' C-m" >/dev/null 2>&1
  sleep 6
  ok "competing load running on Sys4"
}
stop_hog() {
  "${SSH4[@]}" 'tmux kill-session -t hog 2>/dev/null; true' >/dev/null 2>&1
  sleep 4
  ok "competing load stopped"
}

run() {
  local name="$1"
  say "run: $name  ($USERS users, $DURATION)"
  "$BIN" -url "$LB_PUB" -insecure -users "$USERS" -duration "$DURATION" \
    -backends "$BACKENDS_PUB" -seed "$SEED" \
    -experiment "$name" -out "$OUT" 2>&1 | grep -vE '^wrote|^seed|^generating|^  for '
  curl -sk -m 8 "$LB_PUB/lb/metrics" > "$OUT/$name.lb-metrics.json" 2>/dev/null
  curl -sk -m 8 "$LB_PUB/lb/status"  > "$OUT/$name.lb-status.json"  2>/dev/null
  sleep 6   # let queues drain so one run's backlog is not the next run's latency
}

mkdir -p "$OUT"

say "EXPERIMENT SET 1 — all three backends healthy and idle"
stop_hog
restart_lb round-robin 0   || exit 1
run balanced-round-robin
restart_lb p2c 150         || exit 1
run balanced-p2c

say "EXPERIMENT SET 2 — Sys4 degraded by competing load"
start_hog
restart_lb round-robin 0   || exit 1
run degraded-round-robin
restart_lb p2c 150         || exit 1
run degraded-p2c
stop_hog

say "restoring the production configuration"
restart_lb p2c 150
say "results in $OUT"
ls -1 "$OUT" | sed 's/^/    /'
