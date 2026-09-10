#!/usr/bin/env bash
# tools/lab6-deploy.sh — deploy the Lab 6 stack to the four lab systems FROM GIT.
#
# Everything the systems run comes from a pushed commit, so what is deployed is
# always something a reader can check out. That is the point of this script:
# copying a working tree over SSH is faster and leaves nobody able to reproduce
# the deployment, including you.
#
# Each system is reset hard to the remote branch rather than merged. A lab box
# is not somewhere to resolve conflicts, and a `git pull` onto a tree that has
# been poked at by hand fails in the least helpful way possible — half applied,
# with the service down.
#
# Secrets are never committed. They are read from tools/lab6.env, which is
# gitignored; see lab6.env.example.
#
#   tools/lab6-deploy.sh              deploy the current branch and restart
#   tools/lab6-deploy.sh --status     show what each system is running
#   tools/lab6-deploy.sh --stop       stop every service
set -uo pipefail

HOST=10.1.75.53
BRANCH="${BRANCH:-load-bal}"
REPO_DIR=chatfat-encrypted

# Bridge addresses. Not the host's published ports: traffic from one container
# out to the host IP and back into a sibling has to hairpin through the same
# bridge, which Docker drops.
BRIDGE=(x 172.17.0.74 172.17.0.75 172.17.0.76 172.17.0.77)
APP_PORT=3000        # what the host publishes as 3273-3276
LB_PUBLIC="https://$HOST:3273"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/tools/lab6.env"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[1;31m✗\033[0m %s\n' "$*"; }
warn() { printf '  \033[1;33m!\033[0m %s\n' "$*"; }

ssh_sys() { local n=$1; shift; ssh -o BatchMode=yes -o StrictHostKeyChecking=no \
              -o ConnectTimeout=10 -p $((2272 + n)) "student@$HOST" "$@"; }

# ---------------------------------------------------------------- status ----
if [ "${1:-}" = "--status" ]; then
  for n in 1 2 3 4; do
    say "sys$n"
    ssh_sys "$n" "cd ~/$REPO_DIR 2>/dev/null || { echo '  repo missing'; exit; }
      echo \"  commit:  \$(git rev-parse --short HEAD) on \$(git rev-parse --abbrev-ref HEAD)\"
      echo \"  clean:   \$(test -z \"\$(git status --porcelain)\" && echo yes || echo \"NO — \$(git status --porcelain | wc -l) files differ\")\"
      echo \"  tmux:    \$(tmux ls 2>/dev/null | cut -d: -f1 | tr '\n' ' ')\"
      echo \"  :$APP_PORT:   \$(ss -ltn 2>/dev/null | grep -c \":$APP_PORT \") listener\""
  done
  say "load balancer"
  curl -sk -m 8 "$LB_PUBLIC/lb/status" 2>/dev/null \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);print("  strategy %s | threshold %s ms | healthy %d/%d"%(d["strategy"],d["load_threshold_ms"],d["healthy"],len(d["backends"])))' \
    || bad "not answering on $LB_PUBLIC"
  exit 0
fi

# ------------------------------------------------------------------ stop ----
if [ "${1:-}" = "--stop" ]; then
  for n in 1 2 3 4; do
    ssh_sys "$n" 'tmux kill-session -t lb 2>/dev/null; tmux kill-session -t backend 2>/dev/null; true' >/dev/null 2>&1
    ok "sys$n stopped"
  done
  warn "PostgreSQL on sys1 left running — stop it with: ~/pgsql/bin/pg_ctl -D ~/pgdata stop"
  exit 0
fi

# ---------------------------------------------------------------- deploy ----
[ -f "$ENV_FILE" ] || { bad "missing $ENV_FILE — copy tools/lab6.env.example and fill it in"; exit 1; }
# shellcheck disable=SC1090
source "$ENV_FILE"
: "${DATABASE_URL:?set DATABASE_URL in tools/lab6.env}"
: "${MASTER_KEY:?set MASTER_KEY in tools/lab6.env}"
DB_POOL_MAX="${DB_POOL_MAX:-40}"
STRATEGY="${STRATEGY:-p2c}"
LOAD_THRESHOLD="${LOAD_THRESHOLD:-50}"

# Two checks, and the second one is the one that matters.
#
# Comparing HEAD to origin alone is not enough, and getting that wrong is
# destructive rather than merely unhelpful: with uncommitted work in the tree,
# HEAD already equals origin, the check passes, and the script then resets every
# system to the last *commit* — deleting the very files it was asked to deploy.
# That happened. So a dirty tree is refused before anything remote is touched.
say "checking the working tree is committed and pushed"

DIRTY=$(git -C "$ROOT" status --porcelain -- src lb tools server.js package.json 2>/dev/null | grep -v '^?? tools/lab6.env' || true)
if [ -n "$DIRTY" ]; then
  bad "the working tree has uncommitted changes to deployable files:"
  echo "$DIRTY" | sed 's/^/      /'
  bad "commit and push first — deploying now would reset the systems to the last"
  bad "commit and delete exactly the work you are trying to ship"
  exit 1
fi
ok "working tree clean"

LOCAL=$(git -C "$ROOT" rev-parse HEAD)
git -C "$ROOT" fetch --quiet origin "$BRANCH" 2>/dev/null || true
REMOTE=$(git -C "$ROOT" rev-parse "origin/$BRANCH" 2>/dev/null || echo none)
if [ "$LOCAL" != "$REMOTE" ]; then
  bad "HEAD ($(git -C "$ROOT" rev-parse --short HEAD)) is not origin/$BRANCH ($(echo "$REMOTE" | cut -c1-7))"
  bad "push first — this script deliberately refuses to deploy an unpushed commit"
  exit 1
fi
ok "origin/$BRANCH is $(git -C "$ROOT" rev-parse --short HEAD)"

say "1/4  pulling on all four systems"
for n in 1 2 3 4; do
  ssh_sys "$n" "
    set -e
    cd ~/$REPO_DIR
    git fetch --quiet origin $BRANCH
    git checkout --quiet -B $BRANCH origin/$BRANCH
    # Hard reset, not merge: see the header. bin/ is excluded from the clean so
    # a compiled binary is not deleted out from under a running process.
    git reset --hard --quiet origin/$BRANCH
    git clean -qfd -e bin -e node_modules
    echo \"  sys$n now at \$(git rev-parse --short HEAD)\"" 2>&1 | tail -1
done

say "2/4  dependencies"
for n in 2 3 4; do
  ssh_sys "$n" "cd ~/$REPO_DIR && (npm install --omit=dev --silent >/dev/null 2>&1 || npm install --silent >/dev/null 2>&1); node -e 'require(\"ws\")' 2>/dev/null && echo '  sys$n deps ok' || echo '  sys$n deps MISSING'" 2>&1 | tail -1
done
ssh_sys 1 "cd ~/$REPO_DIR && export PATH=\$HOME/goroot/bin:\$PATH && go build -C lb -o ../bin/lb ./cmd/lb && echo '  sys1 load balancer built'" 2>&1 | tail -1

say "3/4  starting backends (container port $APP_PORT -> public 3274-3276)"
for n in 2 3 4; do
  name="backend-$((n - 1))"
  ssh_sys "$n" "
    tmux kill-session -t backend 2>/dev/null
    tmux new -d -s backend
    tmux send-keys -t backend 'cd ~/$REPO_DIR && PORT=$APP_PORT BACKEND_NAME=$name \
      DATABASE_URL=\"$DATABASE_URL\" MASTER_KEY=\"$MASTER_KEY\" DB_POOL_MAX=$DB_POOL_MAX \
      BENCH_ENABLED=1 TLS_CERT_FILE= TLS_KEY_FILE= node server.js' C-m
    sleep 6" >/dev/null 2>&1
  if out=$(curl -s -m 8 "http://$HOST:$((3272 + n))/statz" 2>/dev/null); then
    ok "sys$n $(echo "$out" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["backend"],"up")' 2>/dev/null || echo up)"
  else
    bad "sys$n backend not answering — ssh -p $((2272+n)) student@$HOST 'tmux capture-pane -pt backend | tail -20'"
  fi
done

say "4/4  starting the load balancer on sys1"
BACKENDS="http://${BRIDGE[2]}:$APP_PORT,http://${BRIDGE[3]}:$APP_PORT,http://${BRIDGE[4]}:$APP_PORT"
ssh_sys 1 "
  tmux kill-session -t lb 2>/dev/null
  tmux new -d -s lb
  tmux send-keys -t lb 'cd ~/$REPO_DIR && ./bin/lb -listen 0.0.0.0:$APP_PORT \
    -backends $BACKENDS \
    -strategy $STRATEGY -load-threshold $LOAD_THRESHOLD \
    -health-timeout 5s -backend-timeout 15s \
    -tls-cert ./tls-cert.pem -tls-key ./tls-key.pem' C-m
  sleep 5" >/dev/null 2>&1

if st=$(curl -sk -m 10 "$LB_PUBLIC/lb/status" 2>/dev/null); then
  echo "$st" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("  strategy %s | threshold %s ms | healthy %d/%d"%(d["strategy"],d["load_threshold_ms"],d["healthy"],len(d["backends"])))'
else
  bad "load balancer not answering on $LB_PUBLIC"; exit 1
fi

say "verifying the required routes end to end"
curl -sk -m 10 -X POST "$LB_PUBLIC/message" -H 'content-type: application/json' \
  -d '{"client-name":"deploy-check","msg":"deployed from git"}' \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print("  POST /message -> ok=%s via %s"%(d["ok"],d["backend"]))' 2>/dev/null \
  || bad "POST /message failed"
curl -sk -m 20 "$LB_PUBLIC/feed?limit=1" \
  | python3 -c 'import sys,json;print("  GET  /feed    -> %d message(s)"%len(json.load(sys.stdin)))' 2>/dev/null \
  || bad "GET /feed failed"

say "deployed from $(git -C "$ROOT" rev-parse --short HEAD) — submit $LB_PUBLIC"
