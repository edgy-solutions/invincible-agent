#!/usr/bin/env bash
# Roll litany — one service at a time, six legs, stop at the first failure.
#
#   usage: scripts/roll-litany.sh iagent-engine-w [iagent-engine-o ...]
#
# WHY STOP-AT-FIRST-FAILURE. A defect found at population size one costs nothing: Kubernetes'
# rolling update keeps the old ready pod serving while the new ReplicaSet crashloops, so the
# failing roll is free. Rolling twelve first means any failure arrives as fleet noise — twelve
# pods' symptoms against N candidate causes. This is why narrow-first is mandatory, not
# cautious.
#
# PODS ARE ADDRESSED BY NAME, NEVER BY LIST POSITION. During a roll the list always contains a
# corpse, and `items[0]` returned the terminating pod once already — reporting a stale digest
# and a missing module as if they were the new pod's, which read as a defect in the change
# under test. The instrument's own view of "which pod" is part of the measurement.
set -uo pipefail
NS="${NS:-sandbox}"

# LEG 5 PROBES A NON-EXEMPT PATH, and this map is why the leg exists at all.
#
# It used to probe /health. Then /health became EXEMPT (SDK v0.2.2), so the leg read zero gauge
# lines for every service and COULD NO LONGER FAIL — the instrument built to catch
# guard-gone-quiet, silenced by its own project's fix. A leg that cannot go red is not a check.
#
# So each service names a route that is real, cheap, and NOT exempt. `_EXPECT` is the status
# that means "the dependency ran": under OBSERVE a gated route serves normally (200) or rejects
# on its own terms (422 for a missing body) — either way the gauge line is what we assert on,
# not the status.
probe_path() {
  case "$1" in
    iagent-mesh-registrar) echo "/v1/register" ;;
    iagent-domain-broker)  echo "/api/v1/internal/resolve" ;;
    iagent-projector)      echo "/projector/watermark" ;;
    iagent-engine-w)       echo "/query_knowledge" ;;
    iagent-engine-o)       echo "/personas" ;;
    iagent-engine-d)       echo "/query_metadata" ;;
    iagent-engine-e)       echo "/query_proxy" ;;
    iagent-engine-f)       echo "/render_ui" ;;
    iagent-engine-a)       echo "/analyze" ;;
    iagent-data-analyst)   echo "/analyze_data" ;;
    *)                     echo "" ;;
  esac
}

fail=0
for DEP in "$@"; do
  echo "=================== $DEP ==================="

  kubectl -n "$NS" rollout restart "deploy/$DEP" >/dev/null 2>&1
  if ! kubectl -n "$NS" rollout status "deploy/$DEP" --timeout=300s >/tmp/rs.$$ 2>&1; then
    echo "  LEG1 rollout   : FAIL — $(tail -1 /tmp/rs.$$)"; rm -f /tmp/rs.$$
    echo "  STOPPING at $DEP (fleet stays unrolled behind a defect at population size one)"
    exit 1
  fi
  rm -f /tmp/rs.$$
  echo "  LEG1 rollout   : ok"

  POD=$(kubectl -n "$NS" get pods --field-selector=status.phase=Running \
        -o jsonpath="{range .items[*]}{.metadata.name}{' '}{.metadata.creationTimestamp}{'\n'}{end}" \
        | grep "^${DEP}-" | sort -k2 | tail -1 | cut -d' ' -f1)
  [ -z "$POD" ] && { echo "  no running pod"; exit 1; }
  echo "  pod            : $POD"
  echo "  LEG2 digest    : $(kubectl -n "$NS" get pod "$POD" -o jsonpath='{.status.containerStatuses[0].imageID}' | sed 's/.*@sha256://' | cut -c1-16)"

  V=$(kubectl -n "$NS" exec "$POD" -- python -c "import importlib.metadata as m;print(m.version('iagent-mesh'))" 2>/dev/null | tr -d '\r')
  echo "  LEG3 sdk in img: ${V:-ABSENT}"
  [ -z "$V" ] && { echo "  STOPPING: image does not carry the SDK"; exit 1; }

  ANN=$(kubectl -n "$NS" logs "$POD" 2>/dev/null | grep -m1 "transport auth:")
  echo "  LEG4 announce  : ${ANN:-MISSING}"
  [ -z "$ANN" ] && { echo "  STOPPING: no posture announcement"; exit 1; }

  # LEG 5 — non-exempt probe, then a HAS-SUBJECTS assertion on the gauge.
  PP=$(probe_path "$DEP")
  if [ -z "$PP" ]; then
    echo "  LEG5 gauge     : NO PROBE PATH MAPPED for $DEP — leg 5 cannot run, and an"
    echo "                   unmapped service is an UNCHECKED one. Add it to probe_path()."
    fail=1
  else
    BEFORE=$(kubectl -n "$NS" logs "$POD" 2>/dev/null | grep -c "caller:")
    PORT=$(kubectl -n "$NS" get deploy "$DEP" -o jsonpath='{.spec.template.spec.containers[0].ports[0].containerPort}' 2>/dev/null)
    kubectl -n "$NS" exec "$POD" -- python -c "
import urllib.request
r=urllib.request.Request('http://127.0.0.1:${PORT}${PP}', data=b'{}', headers={'Content-Type':'application/json'})
try: urllib.request.urlopen(r, timeout=25)
except Exception: pass
" >/dev/null 2>&1
    sleep 3
    AFTER=$(kubectl -n "$NS" logs "$POD" 2>/dev/null | grep -c "caller:")
    DELTA=$((AFTER - BEFORE))
    if [ "$DELTA" -ge 1 ]; then
      echo "  LEG5 gauge     : ok — probe on ${PP} produced ${DELTA} new line(s)"
      kubectl -n "$NS" logs "$POD" 2>/dev/null | grep "caller:" | tail -1 | sed 's/^/                   /'
    else
      # THE HAS-SUBJECTS ASSERTION. Zero new lines means the probe path is exempt, the
      # dependency is not applied, or the gauge is dark — all three are failures, and all
      # three previously looked identical to "clean".
      echo "  LEG5 gauge     : FAIL — probe on ${PP} produced NO gauge line."
      echo "                   Either that path became exempt, the dependency is unapplied,"
      echo "                   or the gauge is dark. A zero here is not 'clean'."
      fail=1
    fi
  fi
done

echo "=================== litany complete (fail=$fail) ==================="
exit "$fail"
