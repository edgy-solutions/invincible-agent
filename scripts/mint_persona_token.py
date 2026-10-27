"""Mint a sandbox demo persona's access token and write it to a file. The token is never printed.

    python -I scripts/mint_persona_token.py <persona> --out <dir> [--keycloak <base url>]

The password is the sandbox DEMO user's, read from this repo's chart template
(helm/invincible-agent/templates/keycloak-configmap.yaml, the realm import). It is never printed,
logged or written anywhere. The token goes to `<dir>/token-<persona>.txt`, and that path plus
the token's length and the first 8 hex of its sha256 are the only things printed (CLAUDE.md:
"print a length and a hash prefix, never a secret value").

`--out` is required on purpose: the token belongs in a session scratchpad, never in the tree.
`--keycloak` defaults to the sandbox_e2e README's port-forward (svc/iagent-keycloak 18083:8080).
Plain HTTP over that port-forward; this script does no TLS of its own.

Architect, 2026-10-17: "Put the minting in a committed script ... demo passwords from the keycloak
configmap, token to the scratchpad", so that an allow rule names this script literally.

Exit codes: 0 minted; 2 the persona or its password is not in the template; 3 the token endpoint
refused the grant (its `error` code is printed, never the request); 4 the endpoint was unreachable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_TEMPLATE = (Path(__file__).resolve().parents[1]
             / "helm" / "invincible-agent" / "templates" / "keycloak-configmap.yaml")
_REALM = "invincible-agent"
_CLIENT = "cortex-ui"


def _demo_password(persona: str) -> str | None:
    """The `password` credential of the user block whose username is `persona`, or None.

    A user block runs from its `"username": "<persona>"` to the next `"username"`; inside it the
    first `"type": "password"` credential's `"value"` is taken. A templated value (`{{ ... }}`) is
    refused, since it is not the literal the realm import seeds."""
    text = _TEMPLATE.read_text(encoding="utf-8")
    start = text.find(f'"username": "{persona}"')
    if start < 0:
        return None
    end = text.find('"username":', start + 1)
    block = text[start:end if end > 0 else len(text)]
    cred = block.find('"type": "password"')
    if cred < 0:
        return None
    m = re.search(r'"value":\s*"([^"]*)"', block[cred:])
    if not m or "{{" in m.group(1) or not m.group(1):
        return None
    return m.group(1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("persona", help="a demo username in the realm import, e.g. alice, bob, erin")
    ap.add_argument("--out", required=True, type=Path, help="directory the token file goes in")
    ap.add_argument("--keycloak", default="http://localhost:18083",
                    help="keycloak base URL (default: the README's port-forward)")
    args = ap.parse_args(argv)

    if not re.fullmatch(r"[a-z][a-z0-9_.-]*", args.persona):
        print(f"persona {args.persona!r} is not a username", file=sys.stderr)
        return 2
    pw = _demo_password(args.persona)
    if pw is None:
        print(f"no literal password credential for {args.persona!r} in {_TEMPLATE.name}",
              file=sys.stderr)
        return 2

    url = f"{args.keycloak.rstrip('/')}/realms/{_REALM}/protocol/openid-connect/token"
    body = urllib.parse.urlencode({"client_id": _CLIENT, "grant_type": "password",
                                   "username": args.persona, "password": pw}).encode()
    del pw
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=15) as r:
            answer = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            code = json.loads(exc.read()).get("error", "?")
        except Exception:  # noqa: BLE001 -- a non-JSON refusal still reports its status
            code = "?"
        print(f"{args.persona}: token endpoint refused, HTTP {exc.code} error={code}",
              file=sys.stderr)
        return 3
    except (urllib.error.URLError, OSError) as exc:
        print(f"{args.persona}: token endpoint unreachable ({type(exc).__name__})", file=sys.stderr)
        return 4

    token = answer.get("access_token") or ""
    if not token:
        print(f"{args.persona}: the answer carried no access_token", file=sys.stderr)
        return 3
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"token-{args.persona}.txt"
    path.write_text(token, encoding="utf-8")
    digest = hashlib.sha256(token.encode()).hexdigest()[:8]
    print(f"{args.persona}: token len={len(token)} sha256={digest} "
          f"expires_in={answer.get('expires_in')} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
