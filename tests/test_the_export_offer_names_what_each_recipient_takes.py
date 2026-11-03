"""The exporter says up front which answers each recipient takes (architect, 2026-10-28).

`POST /export/package/recipients` takes the board and answers, per recipient the caller may
export to, which of its answers that recipient's export would take (`exports`) and which it
would refuse (`refused`, with the export's own reason codes). A board no recipient takes is
greyed in the picker, not refused after Export is pressed.

THE JOIN THIS ROUTE EXISTS TO KEEP is `test_the_offer_agrees_with_the_real_export`: for each
board and each recipient, the real `POST /export/package` is run with engine-cost answering
through its real app and the real `measures.package_export`, and what it exported and refused
must equal what the offer said. See `real_cost_engine` for the three things it patches.
"""
from __future__ import annotations

import json
import pathlib
import sys
from urllib.parse import urlsplit

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.cost_agent import canvas as C  # noqa: E402
from agent_fleet.cost_agent import entities as E  # noqa: E402
from agent_fleet.cost_agent import measures as M  # noqa: E402
from agent_fleet.cost_agent import seed  # noqa: E402
from tests.recipient_rail_double import Rail, install as install_rail, serve_no_plan_profiles  # noqa: E402
from agent_fleet.finance_agent.main import VERB_TO_FN  # noqa: E402
from src.iagent import gateway  # noqa: E402
from tests.test_a_mixed_board_exports_per_engine import _Driver, _store_row  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ALICE = "alice@example.com"
SCOPES = sorted(seed.RECIPIENT_SCOPES)
URL = "/export/package/recipients"
PLANNING = ["planSchedule", "planCostCurve", "planSiteLoad", "planFundingGap", "planMaturityGrid"]
FIN_VERB = sorted(VERB_TO_FN)[0]
PROGRAM_VERB = "mesh:costUnitPriceTrend"  # spans the program: needs no lot on the card


def _card(aid, verb, subject=None):
    return {"id": aid, "verb_iri": verb, "subject": "" if subject is None else str(subject)}


def _pair():
    """(A, B, lot): a lot entitled to A and not to B, DERIVED from the seed."""
    for a in SCOPES:
        for b in SCOPES:
            diff = sorted(set(seed.lots_for_recipient(a)) - set(seed.lots_for_recipient(b)))
            if a != b and diff:
                return a, b, diff[0]
    pytest.fail("the seed has no lot entitled to one recipient and not to another")


A_SCOPE, B_SCOPE, A_ONLY_LOT = _pair()

BOARDS = {
    "portfolio": [_card(f"p{i}", None) for i in range(5)],
    "planning": [_card(f"v{i}", f"mesh:{v}") for i, v in enumerate(PLANNING)],
    "entitlement": [_card("e1", "mesh:costLotBreakdown", A_ONLY_LOT)],
    "mixed": [_card("m1", PROGRAM_VERB), _card("m2", FIN_VERB)],
    "fin_only": [_card("f1", FIN_VERB), _card("f2", FIN_VERB)],
    "partial_cost": [
        _card("x1", PROGRAM_VERB), _card("x2", None), _card("x3", "mesh:costLotBreakdown"),
        _card("x4", "mesh:planSchedule"),
    ],
    # canvas.resolve refuses it for NO LOT, naming only the no-verb answer
    "lotless": [_card("l1", "mesh:costRateAssumptions"), _card("l2", None)],
    # one answer sent twice: resolve raises "appears twice" with nothing named
    "duplicate": [_card("d1", PROGRAM_VERB)],
}
#: The ids a board is SENT with, where that differs from its cards (a duplicate is one id).
SENT = {"duplicate": ["d1", "d1"]}


@pytest.fixture
def offer(monkeypatch):
    """`offer(cards, readers=None, ids=None, body=None)` -> the offer route's response.
    `readers` ({scope: (emails)}) replaces the rail's `cost` rows (who may export to whom); without
    it Topaz is doubled with the SHIPPED policy/recipient_readers.yaml."""
    user = type("U", (), {
        "authz_id": ALICE, "id": "sub-alice", "email": ALICE, "roles": [], "persona": None,
        "entitled_domains": [], "is_authenticated": True,
    })()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user

    def go(cards, readers=None, ids=None, body=None):
        install_rail(monkeypatch, None if readers is None else Rail(
            {("cost", sc): tuple(r) for sc, r in readers.items()}))
        serve_no_plan_profiles(monkeypatch)  # the plan half is answerable (a 503 otherwise) and empty
        monkeypatch.setattr(gateway, "neo4j_driver",
                            _Driver({c["id"]: _store_row(c) for c in cards}, []))
        payload = body if body is not None else {
            "answers": [{"artifact_id": i} for i in (ids or [c["id"] for c in cards])]}
        with TestClient(gateway.app) as client:
            return client.post(URL, json=payload)

    go.user = user
    yield go
    gateway.app.dependency_overrides.clear()


def _everyone_reads():
    return {s: (ALICE,) for s in SCOPES}


def _by_scope(resp):
    assert resp.status_code == 200, resp.text
    return {r["value"]: r for r in resp.json()["recipients"]}


def _every_id_once(rec, cards):
    ids = [c["id"] for c in cards]
    seen = list(rec["exports"]) + [r["answer_id"] for r in rec["refused"]]
    assert sorted(seen) == sorted(ids), (rec, ids)
    assert [r["answer_id"] for r in rec["refused"]] == [i for i in ids if i not in rec["exports"]]


# -- 1, 2: a board no recipient takes ------------------------------------------------------------


def test_the_portfolio_board_is_greyed_for_every_recipient(offer):
    cards = BOARDS["portfolio"]
    resp = offer(cards, readers=_everyone_reads())
    got = _by_scope(resp)
    assert sorted(got) == SCOPES and resp.json()["answers"] == 5
    for rec in got.values():
        assert rec["offered"] is False
        assert rec["reason_code"] == "takes_none_of_these_answers"
        assert rec["exports"] == []
        assert [r["reason_code"] for r in rec["refused"]] == ["no_verb"] * 5
        assert all(r["kind"] is None for r in rec["refused"])
        assert all(r["reason"] == C.REFUSAL_REASONS[C.NO_VERB] for r in rec["refused"])
        _every_id_once(rec, cards)


def test_planning_verbs_are_refused_with_their_kind(offer):
    cards = BOARDS["planning"]
    for rec in _by_scope(offer(cards, readers=_everyone_reads())).values():
        assert rec["offered"] is False and rec["exports"] == []
        assert [r["reason_code"] for r in rec["refused"]] == [C.NOT_AN_EXPORTABLE_COST_VERB] * 5
        assert [r["kind"] for r in rec["refused"]] == PLANNING
        _every_id_once(rec, cards)


# -- 3: entitlement is per recipient -------------------------------------------------------------


def test_a_lot_answer_is_offered_to_the_recipient_entitled_to_it_and_greyed_for_the_other(offer):
    cards = BOARDS["entitlement"]
    got = _by_scope(offer(cards, readers=_everyone_reads()))
    a, b = got[A_SCOPE], got[B_SCOPE]
    assert a["offered"] is True and a["exports"] == ["e1"] and a["refused"] == []
    assert a["reason_code"] is None and a["reason"] is None
    assert b["offered"] is False and b["exports"] == []
    assert b["reason_code"] == "unentitled"
    assert b["reason"] == C.ENTITLEMENT_REFUSAL
    assert [(r["answer_id"], r["reason_code"], r["reason"]) for r in b["refused"]] == [
        ("e1", "unentitled", C.ENTITLEMENT_REFUSAL)]
    # nothing but the constant prose: no recipient, no lot, no answer id in a grey's reason
    for prose in (b["reason"], b["refused"][0]["reason"]):
        for forbidden in (A_SCOPE, B_SCOPE, str(A_ONLY_LOT), "e1"):
            assert forbidden not in prose
    assert json.dumps(b).count(A_SCOPE) == 0


# -- 4, 5: fin answers ---------------------------------------------------------------------------


def test_a_mixed_board_stays_offered_and_names_the_fin_answer_as_refused(offer):
    cards = BOARDS["mixed"]
    for rec in _by_scope(offer(cards, readers=_everyone_reads())).values():
        assert rec["offered"] is True and rec["exports"] == ["m1"]
        assert rec["reason_code"] is None and rec["reason"] is None
        assert rec["refused"] == [{
            "answer_id": "m2", "kind": FIN_VERB.removeprefix("mesh:"),
            "reason_code": "not_a_ratified_template", "reason": "not a ratified template"}]
        _every_id_once(rec, cards)


def test_a_fin_only_board_is_greyed_with_only_fin_rows(offer):
    cards = BOARDS["fin_only"]
    for rec in _by_scope(offer(cards, readers=_everyone_reads())).values():
        assert rec["offered"] is False and rec["exports"] == []
        assert rec["reason_code"] == "takes_none_of_these_answers"
        assert [r["reason_code"] for r in rec["refused"]] == ["not_a_ratified_template"] * 2
        _every_id_once(rec, cards)


# -- 6: the picker never widens ------------------------------------------------------------------


def test_the_offer_lists_exactly_the_recipients_the_caller_may_export_to(offer):
    cards = BOARDS["portfolio"]
    resp = offer(cards)  # the seed's own readers: alice reads alpha only
    want = gateway._export_recipients_for(offer.user)
    assert want and len(want) < len(SCOPES), "control: the caller reads some recipient, not all"
    got = [r["value"] for r in resp.json()["recipients"]]
    assert got == want
    assert not (set(SCOPES) - set(want)) & set(got)


# -- 7: the export's own gates -------------------------------------------------------------------


def test_an_empty_board_is_a_400_and_an_unknown_id_a_404(offer):
    r = offer([], body={"answers": []})
    assert r.status_code == 400 and r.json()["detail"] == {"reason": "no_answers"}
    r = offer([], body={})
    assert r.status_code == 400 and r.json()["detail"] == {"reason": "no_answers"}
    r = offer([_card("known", None)], ids=["known", "unknown"])
    assert r.status_code == 404
    assert r.json()["detail"] == {"reason": "answer_not_found", "artifact_id": "unknown"}


# -- 9: one module object ------------------------------------------------------------------------


def test_the_exceptions_resolve_raises_are_the_ones_the_offer_catches():
    """canvas.py falls back from `from entities import ...` to the package path; the offer
    catches `canvas.Unentitled`, so what must hold is that these are ONE class each."""
    assert C.Unentitled is E.Unentitled and C.NotInModel is E.NotInModel
    lots = seed.lots_for_recipient(B_SCOPE)
    with pytest.raises(E.Unentitled):
        C.resolve({"answers": [{"id": "e1", "verb_iri": "mesh:costLotBreakdown",
                                "subject_instance_id": A_ONLY_LOT}]},
                  recipient_scope=B_SCOPE, entitled_lots=lots)
    with pytest.raises(E.NotInModel):
        C.resolve({"answers": [{"id": "p", "verb_iri": None}]}, recipient_scope=B_SCOPE,
                  entitled_lots=lots)


def test_an_answer_the_engine_does_not_name_is_still_refused_once(offer):
    """Defends: when canvas.resolve refuses the board for NO LOT with a non-empty `refused`,
    the good-but-lotless answers are not in that list; each must still appear once."""
    cards = [_card("s1", "mesh:seedCanvas", 1), _card("r1", "mesh:costRateAssumptions")]
    for rec in _by_scope(offer(cards, readers=_everyone_reads())).values():
        assert rec["offered"] is False and rec["exports"] == []
        assert [r["reason_code"] for r in rec["refused"]] == [
            C.NOT_AN_EXPORTABLE_COST_VERB, "not_in_model"]
        _every_id_once(rec, cards)


# -- 8: the agreement arm ------------------------------------------------------------------------


@pytest.fixture
def real_cost_engine(monkeypatch, tmp_path):
    """engine-cost answers the gateway through its REAL app (ASGI) and the REAL
    `measures.package_export`, `canvas.resolve` and dataset builder.

    PATCHED (and only this): where the build lives and what it renders. (1) `_repo_root` and
    `_dist_dir` point at a tmp dir holding empty stand-ins for the pinned Pyodide runtime
    files, which are not fetched in this venv; (2) `build_cost_package.build_html`, the page
    renderer that needs that runtime, returns a one-line page; (3) `IAGENT_GIT_SHA` stands in
    for git. Everything that DECIDES (`canvas.resolve`, entitlement, the engine route's
    envelopes, the gateway's partition and documents[]) is real; the file write is real, to
    tmp. `canvas.resolve` is never patched.
    """
    pytest.importorskip("duckdb", reason="the dataset half of a canvas export needs duckdb")
    from agent_fleet.cost_agent import main as cost_main
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    import build_cost_package as builder

    root = tmp_path / "root"
    runtime = root / ".pyodide-cache"
    runtime.mkdir(parents=True)
    for name in builder.RUNTIME_FILES + ("pyodide.js",):
        (runtime / name).write_bytes(b"")
    monkeypatch.setattr(M, "_repo_root", lambda: root)
    monkeypatch.setattr(M, "_dist_dir", lambda r: tmp_path / "dist")
    monkeypatch.setenv("IAGENT_GIT_SHA", "a" * 40)
    monkeypatch.setattr(builder, "build_html", lambda *a, **k: "<html>stub</html>\n")

    real = httpx.AsyncClient

    class _Asgi:
        def __init__(self, *a, **k):
            self._c = real(transport=httpx.ASGITransport(app=cost_main.app),
                           base_url="http://engine-cost", timeout=120.0)

        async def __aenter__(self):
            await self._c.__aenter__()
            return self

        async def __aexit__(self, *a):
            return await self._c.__aexit__(*a)

        async def post(self, url, json=None, headers=None, **k):
            return await self._c.post(urlsplit(url).path, json=json, headers=headers)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Asgi)


def _what_the_export_did(body, ids):
    """(exported ids in board order, {refused id: (reason_code, reason)}) from either shape
    of `POST /export/package` response: `documents[]`, or the single section."""
    if "documents" in body:
        exported = [a for d in body["documents"] if d["status"] == "exists" for a in d["answers"]]
        refused = {a: (d["reason_code"], d["reason"])
                   for d in body["documents"] if d["status"] != "exists" for a in d["answers"]}
    elif body["status"] == "exists":
        exported, refused = list(ids), {}
    else:
        exported = []
        refused = {a: (body["outcome"], body["reason"]) for a in ids}
    return exported, refused


@pytest.mark.parametrize("name", list(BOARDS))
def test_the_offer_agrees_with_the_real_export(offer, real_cost_engine, name):
    """THE JOIN. For each board and each recipient: what `POST /export/package` exported and
    refused (ids, reason_codes, prose) equals what the offer said it would."""
    cards = BOARDS[name]
    ids = SENT.get(name) or [c["id"] for c in cards]
    offered = _by_scope(offer(cards, ids=ids, readers=_everyone_reads()))
    assert sorted(offered) == SCOPES
    for scope in SCOPES:
        rec = offered[scope]
        with TestClient(gateway.app) as client:
            r = client.post("/export/package", json={
                "answers": [{"artifact_id": i} for i in ids], "recipient_scope": scope})
        assert r.status_code == 200, r.text
        exported, refused = _what_the_export_did(r.json(), ids)
        assert exported == rec["exports"], (scope, r.json())
        assert refused == {x["answer_id"]: (x["reason_code"], x["reason"])
                           for x in rec["refused"]}, (scope, r.json())
        assert (r.json()["status"] != "failed") == rec["offered"], (scope, r.json())
        # an id sent twice is ONE answer in the offer's accounting (rows are keyed by id)
        assert set(exported) | set(refused) == set(ids), (scope, r.json())


@pytest.mark.parametrize("name", ["lotless", "portfolio", "mixed", "partial_cost"])
def test_every_board_answer_is_in_exactly_one_document(offer, real_cost_engine, name):
    """Defends: the export accounts for every answer once (a duplicated id is the single-section shape, covered by the agreement arm),
    and the refused count is the sum of the failed documents' answers."""
    cards = BOARDS[name]
    ids = SENT.get(name) or [c["id"] for c in cards]
    offer(cards, ids=ids, readers=_everyone_reads())  # stands up the store
    with TestClient(gateway.app) as client:
        r = client.post("/export/package", json={
            "answers": [{"artifact_id": i} for i in ids], "recipient_scope": A_SCOPE})
    body = r.json()
    assert r.status_code == 200 and "documents" in body, r.text
    seen = [a for d in body["documents"] for a in d["answers"]]
    assert sorted(seen) == sorted(ids), body
    failed = sum(len(d["answers"]) for d in body["documents"] if d["status"] != "exists")
    assert body["reason"] == f"{failed} of {len(ids)} answers refused", body
