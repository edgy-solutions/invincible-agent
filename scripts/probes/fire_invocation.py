"""Fire a one-way Restate invocation so the pod can be killed mid-flight.

`/send` returns an invocation id immediately instead of blocking for the agent
loop, which is what lets us manufacture the replay rather than wait for one.
Usage: fire_invocation.py <SERVICE/handler> <trace_seed> <query>
"""
import json, sys
import requests

INGRESS = "http://iagent-restate:8080"
service, seed, query = sys.argv[1], sys.argv[2], " ".join(sys.argv[3:])

payload = {
    "user_query": query,
    "task_description": query,
    "trace_id": seed,
    "session_id": f"session-{seed}",
    "user_id": "alice@edgy-solutions.com",
    "domain": "MAINTENANCE" if "Engine" in service or "Expert" in service else None,
}
payload = {k: v for k, v in payload.items() if v is not None}

r = requests.post(f"{INGRESS}/{service}/send", json=payload, timeout=60)
print(f"http={r.status_code} body={r.text[:300]}")

from langfuse import get_client
print("langfuse_trace_id=" + get_client().create_trace_id(seed=seed))
