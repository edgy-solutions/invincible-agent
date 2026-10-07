"""Two engine-cost defects lane/fin found while fixing the same two in engine-fin.

1. EVERY COST FINDING CITED `artifact: null`. The costing review
   (`graph_host/graphs/cost_lot_costing_review.py`) cites `payload.get("artifact_id")` off each
   `/measure` envelope, and engine-cost wrote no such key anywhere. The review's line fell back
   to the verb's NAME, which is a citation of a function, not of an answer. engine-cost now mints
   a CONTENT-ADDRESSED `cost:<fn>:<sha256[:16]>` on every ANSWERED envelope -- the form engine-fin
   mints -- and never on a refusal, which is not an artifact.

2. `package_export` LET A BUILDER'S `SystemExit` ESCAPE. The builders are scripts and refuse by
   exiting: an unpinned Pyodide loader, a dirty `pricing.py`, a lot set the dataset builder will
   not package. `SystemExit` is a `BaseException`, so the route's `except` ladder never saw it
   and the caller got a bare 500 with the reason thrown away. It is now `SourceUnavailable`,
   which the route already answers as `outcome: "unavailable"` -- the same named refusal this
   verb gives for a missing runtime or a missing duckdb.

THE ARMS DRIVE THE REAL ROUTE AND THE REAL GRAPH NODE. Where a builder refuses for real (the
loader check, the dirty-tree check) the arm makes the real builder refuse; only the dataset
builder, whose real refusal is unreachable through this verb (a canvas's lots are refused as
Unentitled before it runs), is replaced by one that exits.
"""
from __future__ import annotations

import functools
import re
import subprocess
import sys
import types

import pytest
from fastapi.testclient import TestClient

from agent_fleet.cost_agent import measures as m
from agent_fleet.cost_agent.entities import SourceUnavailable
from agent_fleet.cost_agent.main import STATE, app
from agent_fleet.graph_host.graphs import cost_lot_costing_review as review_graph
from tests.cost.test_the_export_survives_the_image_layout import (  # noqa: F401 (fixture)
    _SHA_POD, _stage_fake_pod_root, real_builder,
)

_LOT, _VINTAGE = 3, "2021-02-01"
_SCOPE = "notional-customer-alpha"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _measure(client, fn, params):
    r = client.post(f"/measure/{fn}", json={"params": params})
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. an answer cites itself ───────────────────────────────────────────────────────────

def _cites(fn: str) -> re.Pattern:
    return re.compile(rf"cost:{re.escape(fn)}:[0-9a-f]{{16}}")


@pytest.mark.parametrize("fn", [fn for fn, _ in review_graph._VIEWS])
def test_A_EVERY_VERB_THE_REVIEW_CITES_WRITES_THE_KEY_THE_REVIEW_READS(client, fn):
    body = _measure(client, fn, {"lot": _LOT, "rate_vintage": _VINTAGE})
    assert body["refused"] is False, body
    assert _cites(fn).fullmatch(str(body.get("artifact_id"))), (
        f"{fn}'s answer carries artifact_id={body.get('artifact_id')!r}; the review reads that key "
        "and cites `artifact: null` without it")


def test_B_THE_REVIEW_DRAWN_THROUGH_THE_REAL_ENGINE_CITES_AN_ARTIFACT_ON_EVERY_LINE(
        client, monkeypatch):
    """The JOIN: the graph's own fetch node, its httpx call routed to the real engine-cost app.
    A key the engine writes and a key the graph reads are two declarations; this is the one
    place they meet."""
    def via_app(url, *, json, headers, timeout):
        assert url.startswith(review_graph.ENGINE_COST_URL), url
        return client.post(url[len(review_graph.ENGINE_COST_URL):], json=json)

    monkeypatch.setattr(review_graph.httpx, "post", via_app)
    state = {"lot": _LOT, "rate_vintage": _VINTAGE,
             "identity": {"authorization": "Bearer person"}}
    views = []
    for fn, label in review_graph._VIEWS:
        out = review_graph._fetch(fn, label)(state)
        views += out["views"]
        assert out["rows"], fn

    for v in views:
        assert _cites(v["source"]).fullmatch(str(v["artifact"])), (
            f"{v['source']} cites {v['artifact']!r}")
    summary = review_graph.review({**state, "views": views})["summary"]
    for v in views:
        assert f"[{v['artifact']}]" in summary, (v["source"], summary)
    assert not any(f"[{fn}]" in summary for fn, _ in review_graph._VIEWS), (
        "a line fell back to citing the verb's name instead of the answer")


def test_C_THE_ID_IS_THE_ANSWERS_SAME_ANSWER_SAME_ID_OTHER_ANSWER_OTHER_ID(client):
    fn = "cost_lot_breakdown"
    one = _measure(client, fn, {"lot": _LOT, "rate_vintage": _VINTAGE})
    again = _measure(client, fn, {"lot": _LOT, "rate_vintage": _VINTAGE})
    other_vintage = _measure(client, fn, {"lot": _LOT, "rate_vintage": "2021-08-01"})
    other_verb = _measure(client, "cost_price_composition",
                          {"lot": _LOT, "rate_vintage": _VINTAGE})
    assert one["artifact_id"] == again["artifact_id"], "re-running must reproduce the citation"
    assert one["artifact_id"] != other_vintage["artifact_id"], (
        "another vintage is another answer and must not share its citation")
    assert other_verb["artifact_id"].split(":")[:2] == ["cost", "cost_price_composition"]


def test_C2_THE_SAME_QUESTION_ANSWERED_DIFFERENTLY_IS_ANOTHER_ARTIFACT(client, monkeypatch):
    """Params alone would make C pass: the id must move when the ANSWER moves under the same
    question (another seed, a corrected rate), or a citation would vouch for figures it never
    saw."""
    fn = "cost_lot_breakdown"
    params = {"lot": _LOT, "rate_vintage": _VINTAGE}
    real = m.VERBS[fn]
    before = _measure(client, fn, params)
    @functools.wraps(real)  # the route reads the verb's declared slots off its signature
    def answered_differently(state, **kw):
        return {**real(state, **kw), "rows": []}

    monkeypatch.setitem(m.VERBS, fn, answered_differently)
    after = _measure(client, fn, params)
    assert after["rows"] == [] and before["rows"], "the patched verb did not reach the route"
    assert before["artifact_id"] != after["artifact_id"]


def test_D_AN_UNDECLARED_PARAM_IS_DROPPED_SO_IT_DOES_NOT_CHANGE_THE_ID(client):
    """The id is over the ACCEPTED params: a dropped one changed nothing that was answered."""
    fn = "cost_lot_breakdown"
    plain = _measure(client, fn, {"lot": _LOT, "rate_vintage": _VINTAGE})
    noisy = _measure(client, fn, {"lot": _LOT, "rate_vintage": _VINTAGE, "not_a_slot": 1})
    assert noisy.get("ignored_params") == ["not_a_slot"], noisy
    assert noisy["artifact_id"] == plain["artifact_id"]


def test_E_A_REFUSAL_CARRIES_NO_ARTIFACT(client):
    body = _measure(client, "cost_rate_comparison", {"lot": _LOT})
    assert body["refused"] is True, body
    assert "artifact_id" not in body, (
        "a refusal is not an artifact; an id on it lets a consumer cite a figure never produced")


# ── 2. a builder's exit is a named refusal ──────────────────────────────────────────────

def _export(client, **params):
    try:
        return _measure(client, "package_export", {"recipient_scope": _SCOPE, **params})
    except SystemExit as exc:  # a BaseException: no `except Exception` on the route sees it
        raise AssertionError(f"a builder exit escaped the route as a bare 500: {exc}") from None


def _assert_named(body, reason_fragment):
    assert body.get("refused") is True and body.get("outcome") == "unavailable", body
    assert reason_fragment in body["reason"], (
        f"the builder's own reason was not carried: {body['reason']!r}")


def test_F_AN_UNPINNED_RUNTIME_IS_UNAVAILABLE_BY_NAME_NOT_A_BARE_500(
        client, tmp_path, monkeypatch, real_builder):
    """The REAL `build_html` against a runtime whose files exist and whose loader is not the
    pinned one: the loader check refuses with `SystemExit`, as it would in a pod whose cache
    was filled with the wrong release."""
    root = _stage_fake_pod_root(tmp_path, real_builder, with_git=False)
    monkeypatch.setattr(m, "_repo_root", lambda: root)
    monkeypatch.setenv("IAGENT_GIT_SHA", _SHA_POD)
    _assert_named(_export(client), "dynamic-import branch was not found")
    assert not (root / "dist").exists()


def test_G_A_DIRTY_ALGORITHM_IS_UNAVAILABLE_BY_NAME(client, tmp_path, monkeypatch, real_builder):
    """The REAL `algorithm_sha` in a checkout whose `pricing.py` has uncommitted edits."""
    root = _stage_fake_pod_root(tmp_path, real_builder, with_git=True)
    monkeypatch.setattr(m, "_repo_root", lambda: root)

    def dirty_git(argv, **_kw):
        assert argv[:2] == ["git", "status"], argv
        return subprocess.CompletedProcess(argv, 0, " M agent_fleet/cost_agent/pricing.py\n", "")

    monkeypatch.setattr(subprocess, "run", dirty_git)
    _assert_named(_export(client), "pricing.py has uncommitted changes")


def test_H_A_DATASET_BUILDER_EXIT_IS_UNAVAILABLE_BY_NAME(
        client, tmp_path, monkeypatch, real_builder):
    root = _stage_fake_pod_root(tmp_path, real_builder, with_git=False)
    monkeypatch.setattr(m, "_repo_root", lambda: root)
    monkeypatch.setenv("IAGENT_GIT_SHA", _SHA_POD)
    # The guard only asks that duckdb IMPORTS; the builder that would use it is replaced.
    monkeypatch.setitem(sys.modules, "duckdb",
                        sys.modules.get("duckdb") or types.ModuleType("duckdb"))
    import build_cost_dataset

    def exits(*_a, **_k):
        raise SystemExit("REFUSING TO BUILD: the dataset builder said no")

    monkeypatch.setattr(build_cost_dataset, "build", exits)
    _assert_named(_export(client, include_dataset=True), "the dataset builder said no")


def test_I_AT_THE_VERB_THE_EXIT_IS_THE_TYPE_THE_ROUTE_ALREADY_NAMES(
        tmp_path, monkeypatch, real_builder):
    """At the verb, not only the route: the exit becomes `SourceUnavailable`, the one type the
    route's ladder maps to `unavailable`, and not a SystemExit the ladder cannot see."""
    root = _stage_fake_pod_root(tmp_path, real_builder, with_git=False)
    monkeypatch.setattr(m, "_repo_root", lambda: root)
    monkeypatch.setenv("IAGENT_GIT_SHA", _SHA_POD)
    try:
        m.package_export(STATE, recipient_scope=_SCOPE)
    except SourceUnavailable as exc:
        assert "the package builder refused" in str(exc), str(exc)
    except SystemExit as exc:
        raise AssertionError(f"the verb let a builder exit through: {exc}") from None
    else:
        raise AssertionError("a runtime with no pinned loader produced a package")
