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
  # METHOD and PATH, both. Carrying only the path was a real defect: the probe POSTed to
  # engine-o's GET-only /personas, FastAPI returned 405 BEFORE running app dependencies, and
  # leg 5 reported "no gauge line" — correctly, but for a reason that was the instrument's
  # fault rather than the fleet's. A 405 short-circuits the dependency exactly like a 404 does.
  #
  # Paths verified by enumerating each app's live routes, not from the README: engine-e serves
  # /query_graph, NOT the /query_proxy this map used to claim.
  case "$1" in
    iagent-mesh-registrar) echo "POST /v1/register" ;;
    iagent-domain-broker)  echo "POST /api/v1/internal/resolve" ;;
    iagent-engine-w)       echo "POST /query_knowledge" ;;
    iagent-engine-o)       echo "GET /personas" ;;
    # engine-p had NO mapping, so leg 5 could not run for it at all — the exact
    # silence this map exists to prevent. /resolve_instance is real, cheap, and
    # non-exempt; an empty body is rejected 422 on the route's own terms, which
    # is a gauge line either way. NOT /measure/<fn>: those run a measure.
    iagent-engine-p)       echo "POST /resolve_instance" ;;
    # engine-cost was the THIRD unmapped service and it surfaced the only way an unmapped
    # service ever does: leg 5 said "NO PROBE PATH MAPPED" on the 2026-09-11 roll, after
    # engine-cost had been serving for nine days. The map is not self-maintaining -- a
    # service added to the fleet is UNCHECKED by this litany until someone adds a row, and
    # the leg reporting that honestly is the only thing that makes the gap visible.
    #
    # Routes verified off the LIVE app object in the serving pod, per this map's own rule:
    #   GET /version · POST /resolve_instance · POST /enumerate_instances
    #   POST /measure/{fn_name} · GET /verbs · GET /health (exempt)
    # /resolve_instance for the same reason as engine-p and engine-fin: real, cheap,
    # non-exempt, and an empty body is refused 422 on the route's own terms -- a gauge line
    # either way. NOT /measure/{fn}, which would RUN a measure.
    iagent-engine-cost)    echo "POST /resolve_instance" ;;
    # engine-fin was the OTHER unmapped service, and the only one besides engine-p:
    # diffing sandbox deployments against this map found 15 unmapped, of which
    # exactly ONE announces a posture (leg 4's criterion, and so the litany's real
    # population). The other 14 -- redis, topaz, the dagster trio, cortex-ui,
    # electric, projector, the broker pairs -- would stop at leg 4 regardless.
    #
    # Routes verified off the live app object, per this map's own rule. engine-fin
    # serves /health (exempt), /verbs, /measure/{fn}, /resolve_instance and
    # /enumerate_instances -- the same shape as engine-p.
    #
    # NOTE ON A KNOWN BUG THAT DOES NOT INVALIDATE THIS PROBE: engine-fin's
    # /resolve_instance has a contract mismatch on its field names. Leg 5 asserts a
    # GAUGE LINE, not a correct answer, and the empty {} body this script sends is
    # rejected 422 on the route's own terms either way. The probe measures transport,
    # which is what it claims to measure.
    iagent-engine-fin)     echo "POST /resolve_instance" ;;
    iagent-engine-d)       echo "POST /query_metadata" ;;
    iagent-engine-e)       echo "POST /query_graph" ;;
    iagent-engine-f)       echo "POST /render_ui" ;;
    iagent-engine-a)       echo "POST /analyze" ;;
    iagent-data-analyst)   echo "POST /analyze_data" ;;
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

  # THE POD THAT SERVES TRAFFIC, not the newest one that lists. A partially-rolled
  # deployment gives a TRUE answer from a pod nobody is routed to — every leg below then
  # reports on an image no user reaches. Endpoints are the authority; newest-Running is the
  # fallback, and it SAYS so rather than pretending.
  POD=$(kubectl -n "$NS" get endpoints "$DEP" -o jsonpath='{.subsets[0].addresses[0].targetRef.name}' 2>/dev/null)
  if [ -n "$POD" ]; then
    POD_SRC="serving"
  else
    POD=$(kubectl -n "$NS" get pods --field-selector=status.phase=Running -o jsonpath="{range .items[*]}{.metadata.name}{' '}{.metadata.creationTimestamp}{'\n'}{end}" | grep "^${DEP}-" | sort -k2 | tail -1 | cut -d' ' -f1)
    POD_SRC="newest-running (NO SERVICE ENDPOINT - may serve nobody)"
  fi
  [ -z "$POD" ] && { echo "  no running pod"; exit 1; }
  echo "  pod            : $POD  [$POD_SRC]"

  # ── LEG 2 — A CHOSEN COMMIT, not whatever :latest happened to resolve to ──────────────
  #
  # MEASURED 2026-09-06: another lane rolled engine-o onto an image built BEFORE `2ff0acf`,
  # and that fix silently regressed OUT of the deployment. Nobody did anything wrong —
  # `:latest` plus independent rolls means one lane can roll BACK another lane's change and
  # neither notices, because both pulled "the newest image" at different moments.
  #
  # A digest change is not a landed commit. A `:latest` pull is not even a CHOSEN commit.
  IMG=$(kubectl -n "$NS" get pod "$POD" -o jsonpath='{.status.containerStatuses[0].image}')
  DIG=$(kubectl -n "$NS" get pod "$POD" -o jsonpath='{.status.containerStatuses[0].imageID}' | sed 's/.*@sha256://' | cut -c1-16)
  echo "  LEG2 image     : ${IMG##*/}  digest ${DIG}"
  case "${IMG}" in
    *:latest)
      echo "  LEG2 tag       : UNPINNED (:latest) - cannot say WHICH commit ran."
      echo "                   Ruled 2026-09-06: rolls reference the commit-tagged image."
      echo "                   The chart still publishes :latest; until that migrates this"
      echo "                   leg REPORTS rather than enforces. REQUIRE_PINNED_IMAGE=1"
      echo "                   makes it a stop."
      if [ "${REQUIRE_PINNED_IMAGE:-}" = "1" ]; then
        echo "  STOPPING: REQUIRE_PINNED_IMAGE=1 and the image is :latest"
        exit 1
      fi
      ;;
    *)
      echo "  LEG2 tag       : ${IMG##*:}"
      if [ -n "${EXPECT_COMMIT:-}" ]; then
        case "${IMG}" in
          *"${EXPECT_COMMIT}"*)
            echo "  LEG2 commit    : ok (matches EXPECT_COMMIT)"
            ;;
          *)
            echo "  STOPPING: tag ${IMG##*:} does not carry EXPECT_COMMIT=${EXPECT_COMMIT}"
            echo "            The roll landed a different commit than intended."
            exit 1
            ;;
        esac
      fi
      ;;
  esac

  V=$(kubectl -n "$NS" exec "$POD" -- python -c "import importlib.metadata as m;print(m.version('iagent-mesh'))" 2>/dev/null | tr -d '\r')
  echo "  LEG3 sdk in img: ${V:-ABSENT}"
  [ -z "$V" ] && { echo "  STOPPING: image does not carry the SDK"; exit 1; }

  ANN=$(kubectl -n "$NS" logs "$POD" 2>/dev/null | grep -m1 "transport auth:")
  echo "  LEG4 announce  : ${ANN:-MISSING}"
  [ -z "$ANN" ] && { echo "  STOPPING: no posture announcement"; exit 1; }

  # LEG 5 — non-exempt probe, then a HAS-SUBJECTS assertion on the gauge.
  PM=$(probe_path "$DEP"); PV=${PM%% *}; PP=${PM#* }
  if [ -z "$PM" ]; then
    echo "  LEG5 gauge     : NO PROBE PATH MAPPED for $DEP — leg 5 cannot run, and an"
    echo "                   unmapped service is an UNCHECKED one. Add it to probe_path()."
    fail=1
  else
    BEFORE=$(kubectl -n "$NS" logs "$POD" 2>/dev/null | grep -c "caller:")
    PORT=$(kubectl -n "$NS" get deploy "$DEP" -o jsonpath='{.spec.template.spec.containers[0].ports[0].containerPort}' 2>/dev/null)
    kubectl -n "$NS" exec "$POD" -- python -c "
import urllib.request
r=urllib.request.Request('http://127.0.0.1:${PORT}${PP}', data=(b'{}' if '${PV}'=='POST' else None), headers={'Content-Type':'application/json'}, method='${PV}')
try: urllib.request.urlopen(r, timeout=25)
except Exception: pass
" >/dev/null 2>&1
    sleep 3
    AFTER=$(kubectl -n "$NS" logs "$POD" 2>/dev/null | grep -c "caller:")
    DELTA=$((AFTER - BEFORE))
    if [ "$DELTA" -ge 1 ]; then
      echo "  LEG5 gauge     : ok — probe on ${PV} ${PP} produced ${DELTA} new line(s)"
      kubectl -n "$NS" logs "$POD" 2>/dev/null | grep "caller:" | tail -1 | sed 's/^/                   /'
    else
      # THE HAS-SUBJECTS ASSERTION. Zero new lines means the probe path is exempt, the
      # dependency is not applied, or the gauge is dark — all three are failures, and all
      # three previously looked identical to "clean".
      echo "  LEG5 gauge     : FAIL — probe on ${PV} ${PP} produced NO gauge line."
      echo "                   Either that path became exempt, the dependency is unapplied,"
      echo "                   or the gauge is dark. A zero here is not 'clean'."
      fail=1
    fi
  fi

  # LEG 6 — DID THE ENGINE ACTUALLY JOIN THE MESH, or only start serving?
  #
  # ADDED 2026-09-01, AFTER A ROLL PASSED ALL FIVE LEGS WITH THE ENGINE UNREGISTERED.
  # engine-p rolled into a window where Keycloak was mid realm-import, every mint retry got
  # connection-refused, and registration ended UNREGISTERED. Legs 1-5 were all green: the
  # pod rolled, the digest changed, the SDK was present, the posture announced, and the
  # gauge produced a line. Every one of those tests that the pod SERVES. None tests that it
  # JOINED. The verb edges from the PREVIOUS registration were still in the graph, so the
  # measurement taken afterwards looked entirely plausible and was stale.
  #
  # THAT IS THE WHOLE CASE FOR THIS LEG: the failure mode is not a missing answer, it is a
  # believable one. A roll is exactly when stale-versus-fresh stops being distinguishable
  # by looking.
  #
  # FAILS ON THE PRESENCE OF THE ALARM, never on the absence of a success line.
  # mesh-registrar and the other non-registrants emit neither and must keep passing;
  # demanding a success line would make this fail for the wrong population, which is the
  # defect leg 5 already had to be rescued from once.
  #
  # The alarm names its own postcondition test
  # (tests/routing/test_resolve_instance_probes.py), and that test was never part of a
  # roll. This leg is the roll half of it.
  UNREG=$(kubectl -n "$NS" logs "$POD" 2>/dev/null | grep -c "mesh registration: UNREGISTERED")
  if [ "${UNREG:-0}" -ge 1 ]; then
    echo "  LEG6 registered: FAIL — ${UNREG} UNREGISTERED alarm(s) in this pod log."
    echo "                   The engine is SERVING but its verbs will not route. Any edge"
    echo "                   still in the graph is STALE, left by an earlier registration —"
    echo "                   which is why this fails loudly rather than reading as clean."
    kubectl -n "$NS" logs "$POD" 2>/dev/null | grep -m1 "mesh registration: UNREGISTERED" | cut -c1-150 | sed "s/^/                   /"
    fail=1
  else
    OKN=$(kubectl -n "$NS" logs "$POD" 2>/dev/null | grep -c "mesh registration: OK")
    echo "  LEG6 registered: ok — 0 alarms, ${OKN} registration(s) confirmed"
  fi
done

echo "=================== litany complete (fail=$fail) ==================="
exit "$fail"
