"""A stateful stand-in for `curl` against the Keycloak admin API (test double, no network).

Invoked as `python fake_keycloak_curl.py <curl args>`. State is one realm-export-shaped JSON file
(FAKE_KC_STATE); every call appends a JSON line {"m": method, "p": path} to FAKE_KC_LOG.
FAKE_KC_REFUSE_DELETE=1 makes DELETE answer 403.

Supported (the paths realm-reconcile-job.yaml's broker / retired-user segments use):
  GET    authentication/flows | authentication/flows/{alias}/executions
         identity-provider/instances/{alias} | .../mappers
         users?username=&exact= | users/{id} | users/{id}/federated-identity | users/{id}/credentials
  POST   authentication/flows/{alias}/copy | identity-provider/import-config
         identity-provider/instances | identity-provider/instances/{alias}/mappers
  PUT    authentication/flows/{alias}/executions | identity-provider/instances/{alias}
  DELETE users/{id}
Anything else is logged as "UNHANDLED" and fails (curl exit 22).

ASSUMED (not verified against a live Keycloak): a copied flow's sub-flows are renamed
"<newName> <oldAlias>" and the executions API reports the ORIGINAL alias as displayName.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import uuid

NS = uuid.UUID("12345678-1234-5678-1234-567812345678")
PREFIX = "http://kc/admin/realms/r"


def _id(*parts: str) -> str:
    return str(uuid.uuid5(NS, "/".join(parts)))


def _load() -> dict:
    with open(os.environ["FAKE_KC_STATE"], encoding="utf-8") as fh:
        return json.load(fh)


def _save(st: dict) -> None:
    with open(os.environ["FAKE_KC_STATE"], "w", encoding="utf-8") as fh:
        json.dump(st, fh, indent=1, sort_keys=True)


def _flow(st: dict, alias: str) -> dict | None:
    return next((f for f in st["authenticationFlows"] if f["alias"] == alias), None)


def _display(alias: str, top: str) -> str:
    pre = top + " "
    return alias[len(pre):] if alias.startswith(pre) and top != alias else alias


def _flatten(st: dict, alias: str, top: str, level: int = 0) -> list[dict]:
    out: list[dict] = []
    f = _flow(st, alias)
    for idx, ex in enumerate(f["authenticationExecutions"]):
        base = {"id": f"{alias}#{idx}", "requirement": ex["requirement"], "level": level, "index": idx}
        if ex.get("authenticatorFlow"):
            out.append({**base, "displayName": _display(ex["flowAlias"], top), "authenticationFlow": True,
                        "flowId": _id("flow", ex["flowAlias"])})
            out.extend(_flatten(st, ex["flowAlias"], top, level + 1))
        else:
            out.append({**base, "displayName": ex["authenticator"], "providerId": ex["authenticator"],
                        "authenticationFlow": False})
    return out


def _copy(st: dict, src: str, new: str) -> None:
    def clone(alias: str, newalias: str, top: bool) -> None:
        f = json.loads(json.dumps(_flow(st, alias)))
        f["alias"], f["builtIn"], f["topLevel"] = newalias, False, top
        for ex in f["authenticationExecutions"]:
            if ex.get("authenticatorFlow"):
                sub = f"{new} {ex['flowAlias']}"
                clone(ex["flowAlias"], sub, False)
                ex["flowAlias"] = sub
        st["authenticationFlows"].append(f)
    clone(src, new, True)


def _find_exec(st: dict, ident: str) -> dict | None:
    alias, _, idx = ident.rpartition("#")
    f = _flow(st, alias)
    if f is None or not idx.isdigit() or int(idx) >= len(f["authenticationExecutions"]):
        return None
    return f["authenticationExecutions"][int(idx)]


def _mask(idp: dict) -> dict:
    out = json.loads(json.dumps(idp))
    if "clientSecret" in out.get("config", {}):
        out["config"]["clientSecret"] = "**********"
    return out


def handle(method: str, path: str, query: dict, body: object) -> tuple[int, object]:
    st = _load()
    seg = [urllib.parse.unquote(p) for p in path.strip("/").split("/")]
    if method == "GET":
        if seg == ["authentication", "flows"]:
            return 200, [{"alias": f["alias"], "id": _id("flow", f["alias"]), "builtIn": f["builtIn"], "topLevel": True}
                         for f in st["authenticationFlows"] if f["topLevel"]]
        if seg[:2] == ["authentication", "flows"] and len(seg) == 4 and seg[3] == "executions":
            f = _flow(st, seg[2])
            return (200, _flatten(st, seg[2], seg[2])) if f else (404, None)
        if seg[:2] == ["identity-provider", "instances"] and len(seg) == 3:
            idp = next((i for i in st["identityProviders"] if i["alias"] == seg[2]), None)
            return (200, _mask(idp)) if idp else (404, None)
        if seg[:2] == ["identity-provider", "instances"] and len(seg) == 4 and seg[3] == "mappers":
            return 200, [m for m in st["identityProviderMappers"] if m["identityProviderAlias"] == seg[2]]
        if seg == ["users"]:
            want = query.get("username", [""])[0]
            exact = query.get("exact", ["false"])[0] == "true"
            hits = [u for u in st["users"] if (u["username"] == want if exact else want in u["username"])]
            return 200, hits
        if seg[0] == "users" and len(seg) == 3 and seg[2] == "federated-identity":
            u = next((u for u in st["users"] if u["id"] == seg[1]), None)
            return (200, u.get("federatedIdentities", [])) if u else (404, None)
        if seg[0] == "users" and len(seg) == 3 and seg[2] == "credentials":
            return 200, []
        if seg[0] == "users" and len(seg) == 2:
            u = next((u for u in st["users"] if u["id"] == seg[1]), None)
            return (200, u) if u else (404, None)
    elif method == "POST":
        if seg[:2] == ["authentication", "flows"] and len(seg) == 4 and seg[3] == "copy":
            if _flow(st, seg[2]) is None:
                return 404, None
            if _flow(st, body["newName"]):
                return 409, None
            _copy(st, seg[2], body["newName"])
            _save(st)
            return 201, None
        if seg == ["identity-provider", "import-config"]:
            iss = body["fromUrl"].rsplit("/.well-known/", 1)[0]
            return 200, {"issuer": iss, "authorizationUrl": iss + "/protocol/openid-connect/auth",
                         "tokenUrl": iss + "/protocol/openid-connect/token", "useJwksUrl": "true"}
        if seg == ["identity-provider", "instances"]:
            if any(i["alias"] == body["alias"] for i in st["identityProviders"]):
                return 409, None
            st["identityProviders"].append({**body, "internalId": _id("idp", body["alias"])})
            _save(st)
            return 201, None
        if seg[:2] == ["identity-provider", "instances"] and len(seg) == 4 and seg[3] == "mappers":
            if any(m["name"] == body["name"] and m["identityProviderAlias"] == seg[2]
                   for m in st["identityProviderMappers"]):
                return 409, None
            st["identityProviderMappers"].append({**body, "id": _id("mapper", seg[2], body["name"])})
            _save(st)
            return 201, None
    elif method == "PUT":
        if seg[:2] == ["authentication", "flows"] and len(seg) == 4 and seg[3] == "executions":
            ex = _find_exec(st, body["id"])
            if ex is None:
                return 404, None
            ex["requirement"] = body["requirement"]
            _save(st)
            return 204, None
        if seg[:2] == ["identity-provider", "instances"] and len(seg) == 3:
            for i, idp in enumerate(st["identityProviders"]):
                if idp["alias"] == seg[2]:
                    st["identityProviders"][i] = {**body, "internalId": idp.get("internalId")}
                    _save(st)
                    return 204, None
            return 404, None
    elif method == "DELETE":
        if seg[0] == "users" and len(seg) == 2:
            if os.environ.get("FAKE_KC_REFUSE_DELETE") == "1":
                return 403, None
            before = len(st["users"])
            st["users"] = [u for u in st["users"] if u["id"] != seg[1]]
            _save(st)
            return (204, None) if len(st["users"]) < before else (404, None)
    return -1, None


def main(argv: list[str]) -> int:
    method = body = url = outfile = wfmt = None
    fail = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "-X":
            method = argv[i + 1]; i += 2
        elif a == "-d":
            body = argv[i + 1]; i += 2
        elif a == "-o":
            outfile = argv[i + 1]; i += 2
        elif a == "-w":
            wfmt = argv[i + 1]; i += 2
        elif a in ("-H", "--data-urlencode"):
            i += 2
        elif a.startswith("-") and not a.startswith("--"):
            fail = fail or "f" in a[1:]; i += 1
        else:
            url = a; i += 1
    method = method or ("POST" if body is not None else "GET")
    assert url and url.startswith(PREFIX), f"fake curl: unexpected URL {url!r}"
    parsed = urllib.parse.urlsplit(url[len(PREFIX):])
    query = urllib.parse.parse_qs(parsed.query)
    try:
        payload = json.loads(body) if body not in (None, "") else None
    except ValueError:
        code, resp = 400, None
    else:
        code, resp = handle(method, parsed.path, query, payload)
    with open(os.environ["FAKE_KC_LOG"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"m": method if code != -1 else "UNHANDLED " + method,
                             "p": parsed.path + ("?" + parsed.query if parsed.query else ""), "c": code}) + "\n")
    if code == -1:
        return 22
    if code >= 400 and fail:
        return 22
    if resp is not None and outfile is None:
        sys.stdout.write(json.dumps(resp, separators=(",", ":")))
    if wfmt:
        sys.stdout.write(wfmt.replace("%{http_code}", str(code)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
