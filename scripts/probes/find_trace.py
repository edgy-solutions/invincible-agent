import os, sys, json
import requests
from requests.auth import HTTPBasicAuth
HOST = os.environ["LANGFUSE_HOST"].rstrip("/")
AUTH = HTTPBasicAuth(os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
prefix = sys.argv[1]
found = []
for page in range(1, 12):
    r = requests.get(f"{HOST}/api/public/traces", auth=AUTH,
                     params={"limit": 100, "page": page}, timeout=30)
    if r.status_code != 200:
        print("http", r.status_code); break
    data = r.json().get("data", [])
    if not data: break
    for t in data:
        if str(t.get("id", "")).startswith(prefix):
            found.append({"id": t["id"], "name": t.get("name"),
                          "timestamp": t.get("timestamp"), "tags": t.get("tags")})
    if found: break
print(json.dumps(found, indent=1) if found else f"no trace with prefix {prefix} in the last {page*100}")
