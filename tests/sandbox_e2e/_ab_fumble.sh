#!/usr/bin/env bash
# A/B fumble driver: fire N direct /analyze_data calls as alice (granted →
# happy path so the agent runs its full multi-step loop and its <code>-envelope
# fumbles show up in DA_FUMBLE_METRIC). Same query + URN every call so both arms
# see identical inputs. The metric itself is scraped from the DA pod logs
# (tagged structured=True/False) — this script just drives load + prints status.
#
# Usage: N=6 LABEL=baseline bash _ab_fumble.sh
set -u
N="${N:-6}"
LABEL="${LABEL:-arm}"
DA="${DA_URL:-http://localhost:18089}"
KC="${KEYCLOAK_URL:-http://localhost:18083/realms/invincible-agent}/protocol/openid-connect/token"
URN="urn:li:dataset:(urn:li:dataPlatform:dagster,mesh_demo_customers,PROD)"
QUERY="what is the breakdown of mesh_demo_customers by region"

resp=$(curl -s -X POST "$KC" -d "client_id=cortex-ui" -d "grant_type=password" \
  -d "username=alice" -d "password=alice")
TOK=$(echo "$resp" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
if [ -z "$TOK" ]; then echo "NO TOKEN: ${resp:0:120}"; exit 1; fi
SUB=$(echo "$TOK" | cut -d. -f2 | tr '_-' '/+' | base64 -d 2>/dev/null | sed -n 's/.*"sub":"\([^"]*\)".*/\1/p')

echo "== ARM=$LABEL N=$N =="
for i in $(seq 1 "$N"); do
  t0=$(date +%s)
  body=$(curl -s -m 600 -X POST "$DA/analyze_data" \
    -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
    -d "{\"query\": \"$QUERY\", \"resolved_instance_id\": \"$URN\", \"user_email\": \"alice@example.com\", \"user_id\": \"$SUB\"}")
  dt=$(( $(date +%s) - t0 ))
  status=$(echo "$body" | sed -n 's/.*"status":[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
  echo "  [$LABEL $i/$N] ${dt}s status=${status:-<none>} bytes=${#body}"
done
echo "== ARM=$LABEL DONE =="
