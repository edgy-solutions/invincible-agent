"""The review card's walk, as personas, against the sandbox (architect 193 item 4).

    alice  POST /ingest                         drop the notice through the door
    alice  GET  /ingest/{id}/status             watch it to `review` (or `failed`)
    bob    GET  /me/human_tasks                 the document_promotion task, titled by the notice id
    bob    GET  /ingest/{id}/extraction         the rows; every row carries an evidence_ref
    bob    GET  /ingest/{id}/source             the PDF bytes, whose sha256 is the ingest id
    bob    POST /human_tasks/{task}/act         promoted; the body records the origin
    alice  GET  /ingest/{id}/status             the row is `promoted`
    bob    GET  /ingest/{id}/source             403 now: the task is no longer open

Usage (one PDF per argument; content_kind from its filename, PDN -> pdn, else pcn):
    python tests/e2e/walk_document_promotion.py TI_PCN_20210316000.pdf IDT_PDN_OV-19-05.pdf

Credentials come from the environment only, never from a file in the cluster or the repo:
ALICE_USER, ALICE_PASS, BOB_USER, BOB_PASS. BFF_URL, KEYCLOAK_URL and KC_CLIENT_ID are read by
`tests/sandbox_e2e/mesh_client.py`. TLS is verified (SSL_CERT_FILE for the pinned leaf).

Prints one PASS/FAIL line per step and per document, and exits 0 only if every step passed. A
step that cannot run because an earlier one failed is printed SKIP and counts as a failure.
Not a pytest module (no `test_` prefix): it acts on the live sandbox and must be run on purpose.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sandbox_e2e"))
import mesh_client as mc  # noqa: E402

PAYLOAD_KEYS = ("ingest_id", "notice_id", "content_kind", "mfr", "notice_date",
                "part_count", "dropped_by", "attempt")
REVIEW_TIMEOUT_S = int(os.getenv("WALK_REVIEW_TIMEOUT_S", "1200"))
POLL_S = 15


def _env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        sys.exit(f"{name} is not set; this script reads credentials from the environment only")
    return v


def _token(c: httpx.Client, user: str, pw: str) -> str:
    r = c.post(f"{mc.KEYCLOAK_URL}/protocol/openid-connect/token", timeout=15.0,
               data={"client_id": mc.CLIENT_ID, "grant_type": "password",
                     "username": user, "password": pw})
    r.raise_for_status()
    return r.json()["access_token"]


def _email(tok: str) -> str:
    part = tok.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))["email"]


class Walk:
    def __init__(self, label: str):
        self.label, self.results, self.blocked = label, [], False

    def step(self, name: str, ok: bool, detail: str = "") -> bool:
        verdict = "SKIP" if self.blocked else ("PASS" if ok else "FAIL")
        self.results.append(verdict == "PASS")
        print(f"  [{verdict}] {name}" + (f" -- {detail}" if detail else ""), flush=True)
        return verdict == "PASS"

    def gate(self, name: str, ok: bool, detail: str = "") -> bool:
        """A step the rest depend on: a failure marks every later step SKIP."""
        passed = self.step(name, ok, detail)
        if not passed:
            self.blocked = True
        return passed


def walk_one(c: httpx.Client, pdf: Path, al: str, bo: str) -> bool:
    A, B = {"Authorization": f"Bearer {al}"}, {"Authorization": f"Bearer {bo}"}
    data = pdf.read_bytes()
    ingest_id = "sha256:" + hashlib.sha256(data).hexdigest()
    content_kind = "pdn" if "PDN" in pdf.name.upper() else "pcn"
    w = Walk(pdf.name)
    print(f"\n=== {pdf.name} ({len(data)} bytes, {ingest_id[:15]}..., content_kind={content_kind}) ===")

    # 1. alice drops through the door.
    r = c.post(f"{mc.BFF_URL}/ingest", headers=A, timeout=120.0,
               files={"file": (pdf.name, data, "application/pdf")},
               data={"kind": "pdf", "on_behalf_of": _email(al), "content_kind": content_kind})
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    dup = body.get("duplicate")
    w.gate("1 alice drops via POST /ingest", r.status_code == 200 and body.get("ingest_id") == ingest_id,
           f"{r.status_code} stage={body.get('stage')} duplicate={bool(dup)}"
           + ("" if r.status_code == 200 else f" body={r.text[:300]}"))
    if dup:
        print("  note: these bytes were dropped before; the walk continues on the existing row")

    # 2. watch it to review.
    stage, deadline, seen = None, time.monotonic() + REVIEW_TIMEOUT_S, []
    while not w.blocked and time.monotonic() < deadline:
        s = c.get(f"{mc.BFF_URL}/ingest/{ingest_id}/status", headers=A, timeout=30.0)
        st = s.json() if s.status_code == 200 else {}
        stage = st.get("stage")
        if not seen or seen[-1] != stage:
            seen.append(stage)
        if stage in ("review", "failed", "promoted", "rejected"):
            break
        time.sleep(POLL_S)
    w.gate("2 alice watches it to review", stage == "review",
           f"stages seen {seen}" + (f" failure={st.get('failure')}" if stage == "failed" else ""))

    # 3. bob sees the task, titled by the notice id, with the full payload.
    task, tasks = None, []
    if not w.blocked:
        t = c.get(f"{mc.BFF_URL}/me/human_tasks", headers=B, timeout=30.0)
        tasks = t.json().get("tasks", []) if t.status_code == 200 else []
        task = next((x for x in tasks if x.get("task_id") == f"document_promotion:{ingest_id}"), None)
    payload = (task or {}).get("payload") or {}
    missing = [k for k in PAYLOAD_KEYS if k not in payload]
    w.gate("3a bob holds the document_promotion task", task is not None,
           f"{len(tasks)} tasks visible to bob" if task is None else task["task_id"][:40])
    w.step("3b payload carries the eight keys", not missing,
           f"missing {missing}" if missing else
           f"notice_id={payload.get('notice_id')} mfr={payload.get('mfr')} "
           f"notice_date={payload.get('notice_date')} part_count={payload.get('part_count')} "
           f"attempt={payload.get('attempt')}")
    w.step("3c title is the notice id, not the sha",
           bool(payload.get("notice_id")) and (task or {}).get("title") == payload.get("notice_id"),
           f"title={(task or {}).get('title')!r}")

    # 4. bob reads the extraction rows.
    rows, n_bad = [], None
    if not w.blocked:
        e = c.get(f"{mc.BFF_URL}/ingest/{ingest_id}/extraction", headers=B, timeout=60.0)
        ext = e.json() if e.status_code == 200 else {}
        rows, n_bad = ext.get("rows") or [], ext.get("rows_without_evidence")
        w.gate("4a bob GET /ingest/{id}/extraction", e.status_code == 200 and bool(rows),
               f"{e.status_code} rows={len(rows)}" + ("" if e.status_code == 200 else f" body={e.text[:300]}"))
    else:
        w.step("4a bob GET /ingest/{id}/extraction", False)
    w.step("4b every row carries evidence_ref {page, bbox}",
           bool(rows) and n_bad == 0 and all((x.get("evidence_ref") or {}).get("bbox") for x in rows),
           f"rows_without_evidence={n_bad} of {len(rows)}")
    if rows:
        print(f"  first row: mpn={rows[0].get('mpn')} field={rows[0].get('field')} "
              f"value={rows[0].get('extracted_value')!r} via={rows[0].get('obtained_via')} "
              f"evidence={rows[0].get('evidence_ref')}")

    # 5. bob reads the source bytes.
    if not w.blocked:
        src = c.get(f"{mc.BFF_URL}/ingest/{ingest_id}/source", headers=B, timeout=120.0)
        got = "sha256:" + hashlib.sha256(src.content).hexdigest() if src.status_code == 200 else None
        w.step("5 bob GET /ingest/{id}/source: the bytes are the drop's",
               src.status_code == 200 and got == ingest_id
               and src.headers.get("content-type", "").startswith("application/pdf"),
               f"{src.status_code} {src.headers.get('content-type')} {len(src.content)} bytes "
               f"sha-match={got == ingest_id}")
    else:
        w.step("5 bob GET /ingest/{id}/source", False)

    # 6. bob promotes; the body records the origin.
    done = {}
    if not w.blocked:
        p = c.post(f"{mc.BFF_URL}/human_tasks/{task['task_id']}/act", headers=B, timeout=120.0,
                   json={"decision": "promoted", "comment": "e2e walk: rows confirmed against the crops"})
        done = p.json() if p.status_code == 200 else {}
        w.gate("6a bob promotes", p.status_code == 200 and done.get("decision") == "promoted",
               f"{p.status_code}" + ("" if p.status_code == 200 else f" body={p.text[:300]}"))
    else:
        w.step("6a bob promotes", False)
    w.step("6b origin recorded", done.get("origin") in ("written", "kept_record", "kept_steward"),
           f"origin={done.get('origin')!r} record_id={str(done.get('record_id'))[:12]}")

    # 7. alice sees promoted; bob's source access closed with the task.
    if not w.blocked:
        s = c.get(f"{mc.BFF_URL}/ingest/{ingest_id}/status", headers=A, timeout=30.0)
        w.step("7a alice reads stage promoted", s.status_code == 200 and s.json().get("stage") == "promoted",
               f"{s.status_code} stage={s.json().get('stage') if s.status_code == 200 else None}")
        src2 = c.get(f"{mc.BFF_URL}/ingest/{ingest_id}/source", headers=B, timeout=30.0)
        w.step("7b bob's source read is 403 once the task is closed", src2.status_code == 403,
               f"{src2.status_code}")
    else:
        w.step("7a alice reads stage promoted", False)
        w.step("7b bob's source read is 403 once the task is closed", False)

    ok = all(w.results)
    print(f"  => {pdf.name}: {'PASS' if ok else 'FAIL'} ({sum(w.results)}/{len(w.results)} steps)")
    return ok


def main(argv: list[str]) -> int:
    if not argv:
        sys.exit(__doc__)
    pdfs = [Path(a) for a in argv]
    for p in pdfs:
        if not p.is_file():
            sys.exit(f"no such file: {p}")
    with httpx.Client() as c:
        al = _token(c, _env("ALICE_USER"), _env("ALICE_PASS"))
        bo = _token(c, _env("BOB_USER"), _env("BOB_PASS"))
        results = [walk_one(c, p, al, bo) for p in pdfs]
    print(f"\nWALK: {'PASS' if all(results) else 'FAIL'} ({sum(results)}/{len(results)} documents)")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
