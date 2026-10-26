"""Client for the ingest-v1 API: drop a file, follow it, read what was extracted, decide the review.

Read docs/api/ingest-v1.md first. This file is the working example for it.

Configuration (environment):

    IA_BASE_URL=https://<bff-host>
    IA_TOKEN=<bearer>            # or the password grant below
    IA_TOKEN_URL=https://<issuer-host>/realms/<realm>/protocol/openid-connect/token
    IA_CLIENT_ID=cortex-ui  IA_USERNAME=<user>  IA_PASSWORD=<password>
    SSL_CERT_FILE=<CA bundle or pinned certificate for both hosts>

Commands:

    python samples/ingest_client.py drop <file> <content_kind> [--kind pdf|cad|xml]
    python samples/ingest_client.py status <ingest_id>
    python samples/ingest_client.py extraction <ingest_id>
    python samples/ingest_client.py promote <ingest_id>
    python samples/ingest_client.py reject <ingest_id> <code> [note]

Two rules this file follows, and a client of yours should too:

  * Every path is in ROUTES and every HTTP call goes through call(), so there is one place to
    look when a route changes.
  * Every response key the client reads is listed in READS and read through field(), so a key
    that is not in the published contract fails loudly instead of returning None.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import requests

# The only place a path appears. Each entry is (HTTP method, path).
ROUTES: dict[str, tuple[str, str]] = {
    "drop": ("POST", "/ingest"),
    "status": ("GET", "/ingest/{ingest_id}/status"),
    "mine": ("GET", "/ingest/mine"),
    "extraction": ("GET", "/ingest/{ingest_id}/extraction"),
    "tasks": ("GET", "/me/human_tasks"),
    "act": ("POST", "/human_tasks/{task_id}/act"),
}

# The response keys this client reads, per route. "mine" and "tasks" are listed in ROUTES for
# reference; this client does not call them, so it reads nothing from them.
READS: dict[str, frozenset[str]] = {
    "drop": frozenset({"ingest_id"}),
    "status": frozenset({"stage", "detail", "review_task_id", "review_shape"}),
    "mine": frozenset(),
    "extraction": frozenset({"part_count", "rows_without_evidence"}),
    "tasks": frozenset(),
    "act": frozenset({"record_id", "decision", "replayed"}),
}

# Stages that move on their own. Any other stage is waiting for a person or is final.
MOVING_STAGES = ("received", "extracting")

# Reject reasons a steward may give for a document_promotion task (docs section 6.4).
REJECT_CODES = ("not_a_notice", "unreadable", "parts_unusable", "duplicate")


def session() -> tuple[requests.Session, str]:
    """Return (authenticated session, base URL). The only function that reads the environment."""
    env = os.environ.get
    verify = env("SSL_CERT_FILE") or True      # never False: point SSL_CERT_FILE at your certificate
    token = env("IA_TOKEN")
    if not token:
        resp = requests.post(env("IA_TOKEN_URL"), verify=verify, timeout=30, data={
            "grant_type": "password", "client_id": env("IA_CLIENT_ID", "cortex-ui"),
            "username": env("IA_USERNAME"), "password": env("IA_PASSWORD")})
        resp.raise_for_status()
        token = resp.json()["access_token"]
    api = requests.Session()
    api.headers["Authorization"] = f"Bearer {token}"
    api.verify = verify
    return api, env("IA_BASE_URL", "").rstrip("/")


def call(api, base, name, *, expect=(200,), params=None, **kw) -> requests.Response:
    """Send the request for route `name`. `params` fills the {placeholders} in the path; any other
    keyword (json=, data=, files=, timeout=) goes to requests. Raises if the status is not expected."""
    method, path = ROUTES[name]
    url = base + path.format(**(params or {}))
    kw.setdefault("timeout", 60)
    resp = api.request(method, url, **kw)
    if resp.status_code not in expect:
        raise RuntimeError(f"{name}: expected {tuple(expect)}, got {resp.status_code}: {resp.text[:300]}")
    return resp


def field(body, name, key):
    """Read `key` from a response body of route `name`. Fails if the client never declared that key
    in READS. A key that is declared but absent from this particular body reads as None."""
    if key not in READS[name]:
        raise AssertionError(f"{name}: the client reads {key!r} but READS[{name!r}] does not list it")
    return body[key] if key in body else None


def drop(api, base, path, *, kind, content_kind, on_behalf_of="") -> str:
    """Upload one file. Returns its ingest_id. A blank `on_behalf_of` means "myself"; name another
    person only if you are their declared delegate (docs section 3.3)."""
    with open(path, "rb") as f:
        resp = call(api, base, "drop", files={"file": (os.path.basename(path), f)},
                    data={"kind": kind, "content_kind": content_kind, "on_behalf_of": on_behalf_of},
                    timeout=120)
    return field(resp.json(), "drop", "ingest_id")


def poll(api, base, ingest_id, *, timeout_s=900, interval_s=10,
         sleep=time.sleep, clock=time.time, on_status=None) -> dict:
    """Read the status until the stage stops moving on its own or the deadline passes.
    Returns the last status body. `on_status`, if given, is called with each body."""
    deadline = clock() + timeout_s
    while True:
        body = call(api, base, "status", params={"ingest_id": ingest_id}).json()
        if on_status is not None:
            on_status(body)
        if field(body, "status", "stage") not in MOVING_STAGES or clock() > deadline:
            return body
        sleep(interval_s)


def extraction(api, base, ingest_id) -> dict:
    """Read the extraction (rows, counts, evidence). Available once the stage has left received
    and extracting."""
    return call(api, base, "extraction", params={"ingest_id": ingest_id}).json()


def review_task(status_body) -> str | None:
    """The id of the task a steward acts on, from a status row at stage `review`.

    Take the task id from the row, never build one: it changes (a suffix is added) when the leaf
    is changed at review. None at review means the task could not be read just then, so poll
    again (docs 6.2).
    """
    return field(status_body, "status", "review_task_id")


def promote(api, base, task_id) -> dict:
    """Promote the document behind a `document_promotion` task. Returns the act response."""
    return call(api, base, "act", params={"task_id": task_id}, json={"decision": "promoted"}).json()


def reject(api, base, task_id, code, note="") -> dict:
    """Reject a `document_promotion` task. `code` must be one of REJECT_CODES; `note` is optional."""
    if code not in REJECT_CODES:
        raise ValueError(f"reject code must be one of {', '.join(REJECT_CODES)}, not {code!r}")
    comment = f"{code}: {note}" if note else code
    return call(api, base, "act", params={"task_id": task_id},
                json={"decision": "rejected", "comment": comment}).json()


def ledger_entry(act_body) -> dict:
    """What the act response tells you about the recorded decision.

    The decision ledger itself has no read route in ingest-v1 (docs section 2, "not shipped").
    What a client can hold today is the record id the act returns; a repeat of the same decision
    replays the same record (`replayed: true`).
    """
    return {key: field(act_body, "act", key) for key in ("record_id", "decision", "replayed")}


def _decidable_task(api, base, ingest_id) -> str:
    """The promotion task id for a drop, or a SystemExit saying why there is none."""
    body = call(api, base, "status", params={"ingest_id": ingest_id}).json()
    stage, shape = field(body, "status", "stage"), field(body, "status", "review_shape")
    if stage != "review" or shape != "promotion":
        raise SystemExit(f"nothing to decide: stage is {stage!r}, review_shape is {shape!r} "
                         "(need stage 'review' and review_shape 'promotion')")
    task_id = review_task(body)
    if task_id is None:
        raise SystemExit("the review task could not be read just now; try again")
    return task_id


def _print_stage(body) -> None:
    print("stage", field(body, "status", "stage"), field(body, "status", "detail") or "")


def main(argv) -> int:
    ap = argparse.ArgumentParser(prog="ingest_client")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("drop")
    p.add_argument("file")
    p.add_argument("content_kind")
    p.add_argument("--kind", default="pdf", choices=("pdf", "cad", "xml"))
    for name in ("status", "extraction", "promote"):
        sub.add_parser(name).add_argument("ingest_id")
    p = sub.add_parser("reject")
    p.add_argument("ingest_id")
    p.add_argument("code", choices=REJECT_CODES)
    p.add_argument("note", nargs="?", default="")
    args = ap.parse_args(argv)

    api, base = session()
    if args.cmd == "drop":
        ingest_id = drop(api, base, args.file, kind=args.kind, content_kind=args.content_kind)
        print("ingest_id", ingest_id)
        poll(api, base, ingest_id, timeout_s=int(os.environ.get("IA_POLL_SECONDS", "900")),
             on_status=_print_stage)
    elif args.cmd == "status":
        body = call(api, base, "status", params={"ingest_id": args.ingest_id}).json()
        _print_stage(body)
        print("review_task_id", review_task(body))
    elif args.cmd == "extraction":
        body = extraction(api, base, args.ingest_id)
        print("part_count", field(body, "extraction", "part_count"))
        print("rows_without_evidence", field(body, "extraction", "rows_without_evidence"))
    elif args.cmd == "promote":
        print(ledger_entry(promote(api, base, _decidable_task(api, base, args.ingest_id))))
    else:
        task_id = _decidable_task(api, base, args.ingest_id)
        print(ledger_entry(reject(api, base, task_id, args.code, args.note)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
