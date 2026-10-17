"""RULED 2026-10-16 (Q1): a cost canvas exports its good answers and names the refused ones.

One refused question does not withhold a document. The engine exports the exportable answers
and returns the refused ones by id with a reason_code; the gateway only passes the list
through. Nothing refused ever reaches the customer page: a board with refused members builds
the SAME package, and the same sha, as the board of its good answers alone.
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

from agent_fleet.cost_agent import canvas as C
from agent_fleet.cost_agent import measures as M
from tests.cost.test_a_canvas_exports_the_alpha_document import (  # noqa: F401  (fixtures)
    ALPHA, ALPHA_CANVAS, ROOT, _a, _dataset_package, _resolve, state,
)
from tests.test_a_mixed_board_exports_per_engine import (  # noqa: F401  (fixtures + doubles)
    COST1, COST2, FIN1, _Resp, world,
)

GOOD = ALPHA_CANVAS["answers"]
NOVERB = {"id": "q-noverb", "verb_iri": None, "subject_instance_id": 1}
SEED = _a("q-seed", "seedCanvas", 1)
NOLOT = _a("q-nolot", "costLotBreakdown")
REFUSED = [NOVERB, SEED, NOLOT]
CODES = [C.NO_VERB, C.NOT_AN_EXPORTABLE_COST_VERB, C.LOT_NOT_NAMED]


def _mixed():
    """The good answers with one of each refused kind interleaved, in a known board order."""
    return {"answers": [NOVERB, *GOOD[:1], SEED, *GOOD[1:], NOLOT]}


def _items():
    return [{"answer_id": a["id"], "reason_code": c, "reason": C.REFUSAL_REASONS[c]}
            for a, c in zip(REFUSED, CODES)]


def test_resolve_names_the_refused_and_composes_the_good_ones():
    """Defends: refused answers are named in board order with their codes, and answers, lots
    and sections are those of the good-only canvas."""
    got, good = _resolve(_mixed()), _resolve({"answers": GOOD})
    assert got["answers"] == [a["id"] for a in GOOD]
    assert [r["answer_id"] for r in got["refused"]] == [a["id"] for a in REFUSED]
    assert [r["reason_code"] for r in got["refused"]] == CODES
    assert got["refused"] == _items()
    assert got["lots"] == good["lots"] and got["sections"] == good["sections"]
    assert good["refused"] == []


def test_resolve_with_every_answer_refused_is_NOT_IN_MODEL_and_carries_them():
    """Defends: no exportable answer is still a whole refusal, with one item per answer and
    today's message."""
    with pytest.raises(C.NotInModel, match="not cost answers") as ei:
        _resolve({"answers": REFUSED})
    assert ei.value.refused == _items()
    with pytest.raises(C.NotInModel, match="name none") as ei:
        _resolve({"answers": [NOLOT]})
    assert [r["reason_code"] for r in ei.value.refused] == [C.LOT_NOT_NAMED]
    with pytest.raises(C.NotInModel, match="verify nothing") as ei:
        _resolve({"answers": [SEED, _a("r", "costRateAssumptions")]})
    assert [r["answer_id"] for r in ei.value.refused] == ["q-seed"]


def test_entitlement_is_still_decided_for_the_whole_canvas():
    """Defends: an unentitled lot refuses the whole canvas even beside a good and a refused
    answer; entitlement is never demoted to a refused item."""
    canvas = {"answers": [SEED, GOOD[0], _a("theirs", "costLotBreakdown", 8)]}
    with pytest.raises(C.Unentitled):
        _resolve(canvas)


def _needs_the_runtime():
    pytest.importorskip("duckdb", reason="duckdb is not installed in this venv: the mixed-versus-good-only package sha is NOT verified (uv sync --extra agent-fleet)")
    if not (ROOT / ".pyodide-cache" / "pyodide.js").exists():
        pytest.skip("the pinned Pyodide runtime is not fetched here")


def test_the_verb_builds_the_same_package_with_or_without_the_refused(state, isolated_dist):
    """Defends: M.package_export on the mixed canvas has the good-only canvas's sha, and names
    the refused answers in refused_answers."""
    _needs_the_runtime()
    mixed = M.package_export(state, recipient_scope=ALPHA, canvas=_mixed(), as_of="2026-01-02")
    only = M.package_export(state, recipient_scope=ALPHA, canvas={"answers": GOOD},
                            as_of="2026-01-02")
    assert mixed["artifact_sha256"] == only["artifact_sha256"]
    assert mixed["refused_answers"] == _items()
    assert only["refused_answers"] == []
    html = (isolated_dist / mixed["artifact_filename"]).read_text(encoding="utf-8")
    for a in REFUSED:
        assert a["id"] not in html
    for c in CODES:
        assert c not in html


def test_the_customer_page_carries_nothing_refused(state):
    """Defends: the package body (build_dataset_package, JSON-dumped) of the mixed canvas
    names no refused id and no reason_code and equals the good-only body. The built HTML page
    is checked in the verb test above, which needs the Pyodide runtime; this one does not."""
    mixed = _dataset_package(state, _resolve(_mixed()))
    only = _dataset_package(state, _resolve({"answers": GOOD}))
    text = json.dumps(mixed, default=str, sort_keys=True)
    for a in REFUSED:
        assert a["id"] not in text
    for c in CODES:
        assert c not in text
    assert text == json.dumps(only, default=str, sort_keys=True)


def test_the_route_carries_refused_answers_when_every_answer_is_refused():
    """Defends: the cost route's not_in_model refusal names the refused answers."""
    from fastapi.testclient import TestClient
    from agent_fleet.cost_agent import main as cost_main

    with TestClient(cost_main.app) as c:
        r = c.post("/measure/package_export", json={"params": {
            "recipient_scope": ALPHA, "canvas": {"answers": REFUSED}}})
    body = r.json()
    assert body.get("refused") is True and body.get("outcome") == "not_in_model", body
    assert body["refused_answers"] == _items()


# -- the gateway only passes the list through --------------------------------------------------


def test_gateway_passes_refused_answers_through_on_a_cost_only_board(world):
    """Defends: a refused_answers list in the engine's response reaches a single-engine cost
    board's response; a response without the key gains none."""
    items = _items()
    body = dict(_Resp()._body, refused_answers=items)
    world.reply = _Resp(200, body)
    r = world.post([COST1, COST2])
    assert r.status_code == 200, r.text
    assert r.json()["refused_answers"] == items
    world.reply = _Resp()
    r = world.post([COST1, COST2])
    assert "refused_answers" not in r.json()


def test_gateway_passes_an_in_band_refusal_list_through(world):
    """Defends: an in-band engine refusal's refused_answers is on the refusal body."""
    items = _items()
    world.reply = _Resp(200, {"refused": True, "outcome": "not_in_model", "reason": "x",
                              "refused_answers": items})
    r = world.post([COST1])
    assert r.json()["refused_answers"] == items


def test_gateway_cost_section_of_a_mixed_board_carries_refused_answers(world):
    """Defends: on the mixed path the cost section carries the engine's refused_answers."""
    items = _items()
    world.reply = _Resp(200, dict(_Resp()._body, refused_answers=items))
    body = world.post([COST1, FIN1]).json()
    cost = [d for d in body["documents"] if d["engine"] == "cost"][0]
    assert cost["refused_answers"] == items
