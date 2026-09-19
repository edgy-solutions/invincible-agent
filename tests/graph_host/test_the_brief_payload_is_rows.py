"""The BRIEF payload is ROWS with a declared DISPOSITION — R-073.

The brief rendered live on NP-MERIDIAN and three rows came back, of which one was a finding:

    cost and schedule variance: reported (see artifact)   [fin_variance_analysis]
    cash burn against the phased plan: Spend above plan since FY26-04
    funding position: reported (see artifact)             [fin_funding_status]

**The pipe worked and the water was placeholder.** "Reported" is the graph saying the verb ran.

WHY A NAME IS NOT ENOUGH, and this is the part that decided the shape. cortex-ui-60 raised it
BEFORE the payload existed rather than reading it off the wire afterwards: a row carrying only
a hole name leaves the card choosing among three states with three different repairs and three
different readers, and the honest guess is **no render at all**. The producer's contract
(``presentation_agent/main.py:527``) already distinguishes ``unentitled`` to NAMED_HOLE,
``unavailable`` to a whole-board refusal, and ``empty`` to the panel's own rowless card.

**The brief's stub rows were none of those.** The caller is entitled, the verbs ran, the hop
artifacts exist. Rendering them as a hole would tell a reader they lack an entitlement they
have — hence the fourth disposition, ``unsummarised``: content exists, verdict absent, drawn as
a FINDING row with its artifact.

Run: uv run --frozen pytest tests/graph_host/test_the_brief_payload_is_rows.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

from tests.graph_host._engine_deps import needs_langgraph

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_IDENT = {"authorization": "Bearer caller-token"}


def _brief():
    from agent_fleet.graph_host.graphs import fin_program_brief as b

    return b


class _Resp:
    def __init__(self, status: int, payload: dict | None = None):
        self.status_code = status
        self._p = payload or {}

    def json(self) -> dict:
        return self._p


def _run(monkeypatch, *, status=200, payload=None, raises=None, ident=None) -> dict:
    """Drive ONE fetch node to one outcome and return the state update it produced."""
    b = _brief()

    def _post(*_a, **_k):
        if raises is not None:
            raise raises
        return _Resp(status, payload)

    monkeypatch.setattr(b.httpx, "post", _post)
    node = b._fetch("fin_variance_analysis", "cost and schedule variance")
    return node({"program_id": "NP-MERIDIAN", "identity": ident if ident is not None else _IDENT})


# -- the shape -----------------------------------------------------------------------------

@needs_langgraph
def test_EVERY_outcome_emits_exactly_one_row(monkeypatch):
    """A row per source whatever happened to it — otherwise a card cannot tell "three sources,
    one unsummarised" from "two sources", which is the silently-narrowed answer again."""
    import httpx

    outcomes = [
        dict(status=200, payload={"verdict": "Spend above plan", "artifact_id": "a-1"}),
        dict(status=200, payload={"artifact_id": "a-2"}),
        dict(status=403),
        dict(status=500),
        dict(raises=httpx.ConnectError("down")),
        dict(ident={}),
    ]
    for kw in outcomes:
        out = _run(monkeypatch, **kw)
        assert len(out.get("rows", [])) == 1, f"{kw} produced {out.get('rows')}"


@needs_langgraph
def test_the_artifact_is_a_FIELD_on_every_row_even_when_absent(monkeypatch):
    """Absent-versus-empty, the same rule as ``disposal`` and ``failure_cause``. A refused verb
    HAS no artifact; saying so is a different statement from not mentioning it, and a consumer
    left to guess which draws the wrong thing confidently."""
    for kw in (dict(status=403), dict(status=500), dict(status=200, payload={})):
        row = _run(monkeypatch, **kw)["rows"][0]
        assert "artifact" in row, f"the artifact field is missing entirely: {row}"


@needs_langgraph
def test_the_FOUR_dispositions_are_each_REACHABLE(monkeypatch):
    """PARTITION, derived from the outcomes rather than asserted as a list. A declared
    vocabulary with an unreachable member is a name nobody can produce; one with an unlisted
    outcome is a row the card has no rule for."""
    import httpx

    b = _brief()
    seen = {
        _run(monkeypatch, status=200,
             payload={"verdict": "v", "artifact_id": "a"})["rows"][0]["disposition"],
        _run(monkeypatch, status=200, payload={"artifact_id": "a"})["rows"][0]["disposition"],
        _run(monkeypatch, status=403)["rows"][0]["disposition"],
        _run(monkeypatch, raises=httpx.ConnectError("x"))["rows"][0]["disposition"],
    }
    assert seen == set(b.ROW_DISPOSITIONS), (
        f"declared {set(b.ROW_DISPOSITIONS)} but the fetch node reaches {seen}. A member of "
        f"neither set is the defect: unreachable means nobody can produce it, unlisted means "
        f"the card has no rule for it."
    )


@needs_langgraph
def test_an_ENTITLED_caller_with_no_verdict_is_UNSUMMARISED_and_NOT_a_hole(monkeypatch):
    """THE LOAD-BEARING ROW. Drawing this as a hole would tell an entitled reader they lack an
    entitlement they have — the thing R-073 exists to prevent."""
    out = _run(monkeypatch, status=200, payload={"artifact_id": "hop-7", "rows": [1, 2]})
    row = out["rows"][0]
    assert row["disposition"] == "unsummarised"
    assert row["artifact"] == "hop-7", "the row cannot link the content it says exists"
    assert row["verdict"] is None
    assert not out.get("holes"), (
        f"an entitled caller's answered verb produced a HOLE: {out.get('holes')}"
    )


@needs_langgraph
def test_an_UNENTITLED_caller_still_produces_a_HOLE(monkeypatch):
    """THE CONTROL for the row above. Without it, "never a hole" passes against a graph that
    stopped producing holes at all — which would silently retire ADR-0049 Ruling 2."""
    out = _run(monkeypatch, status=403)
    assert out["rows"][0]["disposition"] == "unentitled"
    assert out.get("holes"), "the named-hole contract stopped producing holes"


# -- the JOIN, which is the half that usually goes unasserted -------------------------------

@needs_langgraph
def test_no_BUILT_IN_verb_the_brief_CALLS_can_fail_to_emit_a_verdict():
    """R-073's retirement clause: ``unsummarised`` retires by TEST, not by someone remembering
    it was temporary.

    DERIVED ON BOTH SIDES — the brief's own source list against engine-fin's verdict registry —
    so adding a fourth source to the brief, or removing a registry entry, goes red.

    WHAT THIS DOES NOT CLAIM, stated because the honest scope is narrower than the ruling's
    headline: a verdict function returns ``Optional[str]`` and may legitimately return None for
    particular rows ("a card with no verdict shows the chart and no caption"). So
    ``unsummarised`` stays REACHABLE on data, and that is correct — content exists, verdict
    absent. What is now impossible is a verb that STRUCTURALLY cannot emit one.
    """
    from agent_fleet.finance_agent import measures as fin

    b = _brief()
    called = {fn for fn, _label in b._SOURCES}
    missing = sorted(called - set(fin.VERDICT))
    assert not missing, (
        f"{missing} are called by the brief and have no verdict emitter in engine-fin's "
        f"registry, so they can only ever produce `unsummarised`."
    )


@needs_langgraph
def test_the_key_the_BRIEF_READS_is_the_key_engine_fin_WRITES():
    """BOTH ENDS WERE ALREADY CORRECT AND THE RELATION BETWEEN THEM WAS ASSERTED NOWHERE.

    engine-fin merges its verdict into the response under one key; the brief looks for a verdict
    under ``VERDICT_KEYS``. Rename either and every per-side test stays green while every brief
    row silently becomes ``unsummarised`` — a defect that reads as "the verbs stopped emitting".
    """
    b = _brief()
    main_src = (_ROOT / "agent_fleet" / "finance_agent" / "main.py").read_text(encoding="utf-8")
    assert '{"verdict": _v}' in main_src, (
        "engine-fin no longer merges its verdict under the key this brief reads — find the new "
        "key and add it to VERDICT_KEYS in the same change."
    )
    assert "verdict" in b.VERDICT_KEYS


# -- synthesise stops at prose --------------------------------------------------------------

@needs_langgraph
def test_synthesise_does_NOT_build_or_amend_rows():
    """Structure recovered from prose is a parser guessing at a sentence this node wrote. The
    rows are emitted where the payload is in hand and travel untouched."""
    b = _brief()
    rows = [{"row": "fin_burn_rate", "label": "cash burn", "disposition": "finding",
             "artifact": "a-9", "verdict": "Spend above plan", "reason": None}]
    out = b.synthesise({"program_id": "NP-MERIDIAN", "rows": rows,
                        "findings": [], "holes": []})
    assert set(out) == {"summary"}, (
        f"synthesise returned {sorted(out)} — it must stop at prose and never re-derive rows"
    )


@needs_langgraph
def test_the_prose_and_the_ROW_read_the_verdict_THE_SAME_WAY():
    """These had two copies of the key list. They would agree today and diverge the first time
    one gained a key — the row saying ``finding`` while the prose said "reported (see
    artifact)", with nothing able to see it."""
    b = _brief()
    payload = {"artifact_id": "a-1"}
    assert b._verdict_of(payload) is None
    assert b._headline(payload) == "reported (see artifact)"
    payload2 = {"verdict": "Spend above plan"}
    assert b._verdict_of(payload2) == "Spend above plan"
    assert b._headline(payload2) == "Spend above plan"
