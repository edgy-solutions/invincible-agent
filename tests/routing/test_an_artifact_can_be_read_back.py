"""`/artifacts/{id}` — a headless reader recovers what an artifact WAS, scoped to its owner.

WHY IT EXISTS. Seeding returns artifact IDS and nothing else, so the verb each panel actually
ran is not knowable to anything but a browser. ADR-0050's seal 3 compares the panel set of two
seeds; without this route its live arm recovers verbs by fetching artifacts, and that fetch
404'd — it would have burned ~25 minutes on the first seed and then errored.

THE WORSE VERSION IS WHY THE SHAPE MATTERS. Had verb recovery returned `None` per panel
instead of failing, both seeds would have compared EQUAL and **seal 3 would have PASSED**. A
broken instrument turning a seal green is strictly worse than one turning it red. So this
route never hands out a placeholder: `verb_iri` is `null` when unrecorded, and the recorded
non-answer `"UNKNOWN"` is normalised to `null` rather than forwarded, because two artifacts
that both say "UNKNOWN" would compare EQUAL on a value that means "no idea".

Run: uv run --frozen pytest tests/routing/test_an_artifact_can_be_read_back.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_VERB = "mesh:planCostCurve"
_SUBJ = "http://invincible-agent/idp#Portfolio"


class _User:
    authz_id = "alice"
    email = "alice@example.com"


def _row(**over):
    base = {
        "id": "artifact-1", "status": "complete", "summary": "Portfolio · plan Cost Curve",
        "question_text": "what does spend look like per period", "valid_as_of": 1788908472202,
        "duration_ms": 15873, "derived_from": None,
        "resolved_intent": json.dumps({
            "subject_uri": _SUBJ, "verb_iri": _VERB, "subject_instance_id": "",
        }),
        "routing_inline": None,
    }
    base.update(over)
    return base


@pytest.fixture()
def read(monkeypatch):
    """Call the REAL route with only the Neo4j session faked — the transport, not the logic."""
    import iagent.gateway as gw

    seen: dict = {}

    def _make(row):
        class _Res:
            def single(self_inner):
                return row

        class _Sess:
            def run(self_inner, cypher, **params):
                seen.update(cypher=cypher, params=params)
                return _Res()

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        class _Drv:
            def session(self_inner):
                return _Sess()

        return _Drv()

    async def _go(row, user=None):
        monkeypatch.setattr(gw, "neo4j_driver", _make(row))
        return await gw.get_artifact("artifact-1", user or _User()), seen

    return _go


@pytest.mark.asyncio
async def test_the_recorded_verb_comes_back(read):
    """The field the caller came for. Everything else on this route is context for it."""
    out, _ = await read(_row())
    assert out.verb_iri == _VERB and out.subject_uri == _SUBJ
    assert out.id == "artifact-1" and out.duration_ms == 15873


@pytest.mark.asyncio
async def test_UNKNOWN_is_normalised_to_null_not_forwarded(read):
    """`UNKNOWN` is what the router writes when it could not place a subject — a RECORDED
    non-answer. Forwarding it would let two artifacts compare EQUAL on a value that means
    "no idea", which is exactly how seal 3 would have passed on a broken instrument."""
    out, _ = await read(_row(resolved_intent=json.dumps(
        {"subject_uri": "UNKNOWN", "verb_iri": "UNKNOWN"})))
    assert out.subject_uri is None and out.verb_iri is None


@pytest.mark.asyncio
async def test_an_artifact_with_no_recorded_route_is_null_not_a_placeholder(read):
    """Artifacts written before subject capture. `null` says "not recorded"; any string
    says "recorded, and this is it"."""
    out, _ = await read(_row(resolved_intent=None))
    assert out.verb_iri is None and out.subject_uri is None
    assert out.id == "artifact-1", "the rest of the artifact is still readable"


@pytest.mark.asyncio
async def test_unparseable_intent_does_not_take_the_whole_read_down(read):
    out, _ = await read(_row(resolved_intent="{not json"))
    assert out.verb_iri is None and out.status == "complete"


# ── scoping ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_read_is_SCOPED_to_the_caller(read):
    """By the same `PRODUCED_FOR` edge `_pre_resolved_from_ask` uses. Asserted on the query
    actually sent, because a route that filtered in Python would pass every test above while
    reading the whole store."""
    _, seen = await read(_row())
    assert "PRODUCED_FOR" in seen["cypher"], seen["cypher"]
    assert seen["params"]["user_id"] == "alice"
    assert seen["params"]["artifact_id"] == "artifact-1"


@pytest.mark.asyncio
async def test_someone_elses_artifact_is_404_not_403(read):
    """404, deliberately. Telling a caller an id EXISTS but is not theirs is an existence
    oracle over other people's questions, and the question text is the sensitive part — the
    same finding `/resolve_instance` carries, applied before it becomes one here."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await read(None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_an_identityless_caller_is_DENIED_not_read_broadly(read):
    """Honest-absent identity denies. An empty user id in the query would match no Actor and
    return 404 — which is safe by accident rather than by decision, and the accident goes
    away the first time someone 'simplifies' the match."""
    from fastapi import HTTPException

    class _Anon:
        authz_id = ""
        email = ""

    with pytest.raises(HTTPException) as exc:
        await read(_row(), _Anon())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_a_dead_graph_is_503_not_404(read):
    """"We could not look" is not "there is no such thing" — the same pair the direct path
    keeps apart as FALL_BACK versus ABSTAIN. A 404 here would tell seal 3's arm that a real
    artifact does not exist, and it would record a difference that never happened."""
    import iagent.gateway as gw
    from fastapi import HTTPException

    class _Boom:
        def session(self):
            raise RuntimeError("connection refused")

    import pytest as _pytest
    _mp = _pytest.MonkeyPatch()
    _mp.setattr(gw, "neo4j_driver", _Boom())
    try:
        with pytest.raises(HTTPException) as exc:
            await gw.get_artifact("artifact-1", _User())
        assert exc.value.status_code == 503
    finally:
        _mp.undo()


def test_the_route_is_DECLARED_in_the_gating_manifest():
    """A new surface declares its gating posture or it ships unnoticed — the manifest's whole
    purpose. This one is `gated`: JWT plus an ownership edge in the query itself."""
    import yaml
    m = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "docs" / "architecture"
         / "endpoint_gating_manifest.yaml").read_text(encoding="utf-8")
    )
    routes = m["services"]["gateway"]["routes"]
    row = next((r for r in routes if r.get("path") == "/artifacts/{artifact_id}"), None)
    assert row is not None, "the artifact read route is undeclared"
    assert row["class"] == "gated" and row["identity"] == "keycloak-jwt"
