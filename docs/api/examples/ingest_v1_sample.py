"""ingest-v1 sample: drop a file, poll its stage, read its extraction. See docs/api/ingest-v1.md.

    IA_BASE_URL=https://<bff-host>  IA_TOKEN_URL=https://<issuer>/realms/<realm>/protocol/openid-connect/token
    IA_CLIENT_ID=cortex-ui  IA_USERNAME=<user>  IA_PASSWORD=<password>   (or IA_TOKEN=<bearer>)
    SSL_CERT_FILE=<ca or pinned leaf .pem>   python ingest_v1_sample.py <file> <content_kind> [pdf|cad|xml]
"""
import os, sys, time
import requests

env = os.environ.get
verify = env("SSL_CERT_FILE", True)
token = env("IA_TOKEN") or requests.post(env("IA_TOKEN_URL"), verify=verify, timeout=30, data={
    "grant_type": "password", "client_id": env("IA_CLIENT_ID", "cortex-ui"),
    "username": env("IA_USERNAME"), "password": env("IA_PASSWORD")}).json()["access_token"]
api = requests.Session()
api.headers["Authorization"] = f"Bearer {token}"
api.verify = verify
base = env("IA_BASE_URL").rstrip("/")
path, content_kind = sys.argv[1], sys.argv[2]
kind = sys.argv[3] if len(sys.argv) > 3 else "pdf"

with open(path, "rb") as f:   # on_behalf_of is required; blank means "myself"
    r = api.post(f"{base}/ingest", files={"file": (os.path.basename(path), f)},
                 data={"kind": kind, "content_kind": content_kind, "on_behalf_of": ""}, timeout=120)
print("drop", r.status_code, r.json())
r.raise_for_status()
ingest_id = r.json()["ingest_id"]

deadline = time.time() + int(env("IA_POLL_SECONDS", "900"))
while True:   # received and extracting are the only stages that move on their own
    st = api.get(f"{base}/ingest/{ingest_id}/status", timeout=30).json()
    print("stage", st["stage"], st.get("detail") or "")
    if st["stage"] not in ("received", "extracting") or time.time() > deadline:
        break
    time.sleep(10)

r = api.get(f"{base}/ingest/{ingest_id}/extraction", timeout=60)
body = r.json()
print("extraction", r.status_code,
      {k: body[k] for k in ("part_count", "rows_without_evidence")} if r.ok else body)
