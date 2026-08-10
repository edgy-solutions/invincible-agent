"""REQUIRE-posture witness, run INSIDE the throwaway pod.

Five legs. The pair that makes the others mean anything is (exempt /health -> 200) and
(non-exempt route -> 401): together they show the gate is ON and the exemption is NARROW.
A run where everything 200s proves nothing; a run where everything 401s proves nothing.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8088"


def call(label, path, headers=None, expect=None):
    req = urllib.request.Request(BASE + path, headers=headers or {})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        code, body = r.status, r.read()[:120]
    except urllib.error.HTTPError as e:
        code, body = e.code, e.read()[:160]
    except Exception as e:  # noqa: BLE001
        code, body = f"ERR {type(e).__name__}", str(e)[:120].encode()
    ok = "OK " if (expect is None or code == expect) else "!! "
    print(f"  {ok}{label:<42} -> {code}  {body.decode(errors='replace').strip()[:110]}")
    return code


def mint():
    """A REAL client-credentials token for svc:supervisor — not a hand-rolled JWT.

    The point of the 200 leg is that a legitimately minted, RS256-signed, Keycloak-issued
    token is ADMITTED. Signing something locally would test the test.
    """
    import os
    realm = os.environ["KEYCLOAK_REALM_URL"].rstrip("/")
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["SUPERVISOR_CLIENT_ID"],
        "client_secret": os.environ["SUPERVISOR_CLIENT_SECRET"],
    }).encode()
    req = urllib.request.Request(
        realm + "/protocol/openid-connect/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    return json.load(urllib.request.urlopen(req, timeout=30))["access_token"]


print("== REQUIRE posture matrix ==")
call("exempt /health, NO token", "/health", expect=200)
call("gated /query_knowledge, NO token", "/query_knowledge", expect=401)
call("gated /query_knowledge, garbage bearer", "/query_knowledge",
     {"Authorization": "Bearer not-a-real-token"}, expect=403)

try:
    tok = mint()
    import base64
    claims = json.loads(base64.urlsafe_b64decode(tok.split(".")[1] + "=="))
    # THE MINT'S WITNESS IS THE DECODED SUBJECT, NOT THE 200.
    print(f"  -- minted subject: {claims.get('email') or claims.get('sub')}")
    call("gated /query_knowledge, MINTED token", "/query_knowledge",
         {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}, expect=405)
except Exception as e:  # noqa: BLE001
    print(f"  !! mint leg failed: {type(e).__name__}: {str(e)[:200]}")
