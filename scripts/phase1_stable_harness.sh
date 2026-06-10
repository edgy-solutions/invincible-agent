#!/usr/bin/env bash
# Phase 1 stable harness: ONE port-forward, ONE engine-o, 5 sequential runs.
# Engine-O has 0 restarts in production; rolling it between runs was the
# instability source, not the wedge. WinError 10061 / RemoteDisconnected in
# the alternating-wedge pattern was kubectl pf dying under rollout churn on
# a flaky wifi link, not BAML/OPENROUTER timeout.
set -u

PROJECT=c:/Users/cnogr/git/invincible-agent
PYTEST=$PROJECT/.venv/Scripts/pytest.exe
LOG_DIR=c:/tmp

# Kill any leaked PFs from earlier scripts before starting fresh.
pkill -f 'port-forward.*engine-o' 2>/dev/null
sleep 2

kubectl -n sandbox port-forward svc/iagent-engine-o 18084:8084 >/dev/null 2>&1 &
PF_PID=$!
sleep 2

# Wait for /health.
i=0
while ! curl -sf http://localhost:18084/health >/dev/null 2>&1; do
  sleep 1; i=$((i+1))
  if [ $i -gt 20 ]; then
    echo "ERROR: engine-o /health never came up"
    kill $PF_PID 2>/dev/null
    exit 1
  fi
done
echo "PF stable; /health OK; starting 5 runs."

# Warm-up.
curl -s --max-time 60 -X POST http://localhost:18084/resolve \
  -H 'Content-Type: application/json' \
  -d '{"query":"warm","domain":"MAINTENANCE"}' >/dev/null 2>&1

for i in 1 2 3 4 5; do
  echo ""
  echo "===== Phase 1 stable Run $i ====="
  ROUTING_TEST_BASE_URL=http://localhost:18084 \
    PYTHONIOENCODING=utf-8 \
    "$PYTEST" "$PROJECT/tests/routing/test_classify_route.py" \
      --tb=line -q --no-header -s 2>&1 \
    | tee "$LOG_DIR/phase1_stable_run$i.log" \
    | tail -3
done

kill $PF_PID 2>/dev/null
echo ""
echo "===== Phase 1 stable done ====="
for i in 1 2 3 4 5; do
  last=$(tail -1 "$LOG_DIR/phase1_stable_run$i.log" 2>/dev/null)
  echo "Run $i: $last"
done
