"""`resolved_intent` must hold RESOLUTION, and the hop that fills it must reach a consumer.

THE DEFECT. The AnswerArtifact's `resolved_intent` was populated once, at bundle creation, from
`/route_intent`'s ExtractIntent output — `mode` and `entity_refs`, captured BEFORE any resolution
happens — and never updated. A field named for resolution holding extraction, on every artifact
the system has ever written.

AND THE DATA COULD NOT HAVE REACHED IT EVEN IF SOMEONE HAD TRIED. `_log_subtask_route_assets`
fires at dynamic_supervisor.py:1883; slots are accepted at :2045. The routing materialization —
the gateway's only window onto the decision — carries subject, verb, candidates and
fallback_reason, and no slots at all, because at the moment it is emitted the slots do not exist.
The capture point preceded the data by 150 lines. That is why this is "the hop that was never
there" rather than "the hop that was wired wrong".

WHAT IS ASSERTED HERE is the JOIN, not the existence of two halves. Every provenance defect this
repo has filed has the same shape: a producer writes, a consumer reads a different key, and both
sides pass their own tests. So the keys the supervisor emits and the keys the gateway reads are
compared against each other, and a rename on either side goes red.

Run: uv run --frozen pytest tests/routing/test_resolved_intent_is_resolution.py -v
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SUP = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")
_GW = (_REPO / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")

_ASSET = "subtask_slots_decision"


def _emitted_keys() -> set:
    """The metadata keys the supervisor puts on the slots materialization."""
    i = _SUP.index(f'asset_key=["{_ASSET}"]')
    window = _SUP[i:i + 2500]
    return set(re.findall(r'"([a-z_]+)":\s*MetadataValue\.', window))


def _consumed_keys() -> set:
    """The metadata keys the gateway reads out of it."""
    i = _GW.index(f'path == ["{_ASSET}"]')
    window = _GW[i:i + 4000]
    return set(re.findall(r'_slots_md\.get\("([a-z_]+)"', window)) \
        | set(re.findall(r'_j\("([a-z_]+)"', window))


# ── the two halves exist ────────────────────────────────────────────────────

def test_the_supervisor_emits_the_slots_decision():
    assert f'asset_key=["{_ASSET}"]' in _SUP


def test_the_gateway_consumes_it():
    """A producer with no consumer is the orphan-field shape this repo has removed twice."""
    assert f'path == ["{_ASSET}"]' in _GW


# ── the join, which is the part that actually breaks ────────────────────────

def test_every_emitted_key_is_read_by_the_gateway():
    """A key the producer writes and nobody reads is a write with no consumer — and it
    passes both sides' own tests, which is exactly how it survives."""
    unread = sorted(_emitted_keys() - _consumed_keys())
    assert not unread, f"supervisor emits keys the gateway never reads: {unread}"


def test_every_key_the_gateway_reads_is_actually_emitted():
    """The other direction, and the more dangerous one: a key the consumer reads and nobody
    writes yields a silent default, so the field persists looking populated and empty."""
    unwritten = sorted(_consumed_keys() - _emitted_keys())
    assert not unwritten, f"gateway reads keys the supervisor never emits: {unwritten}"


def test_the_join_is_not_vacuous():
    """Both sets empty would satisfy the two assertions above and prove nothing — the
    aggregate-floor defect, which passed while harvesting zero from three engines."""
    assert len(_emitted_keys()) >= 4, f"only {len(_emitted_keys())} keys emitted"


# ── the content is resolution, not extraction ───────────────────────────────

def test_the_payload_carries_the_resolution_facts():
    """Named individually rather than by count: the whole defect was a field that looked
    populated while holding the wrong KIND of thing, so a count would not have caught it."""
    keys = _emitted_keys()
    for needed in ("accepted_slots", "slot_resolution", "disposition", "verb_iri"):
        assert needed in keys, f"{needed} missing from the slots decision"


def test_REFUSED_slots_are_carried_too():
    """A dropped slot is a question the system did not answer as asked. An artifact
    recording only acceptances is the silent-narrowing shape at the provenance layer: it
    reads as complete because the omission left no trace in it."""
    assert "refused_slots" in _emitted_keys()


# ── ordering: the emission must be able to see the data ─────────────────────

def test_the_emission_happens_AFTER_slots_are_accepted():
    """THE ORIGINAL DEFECT, pinned so it cannot return. The routing materialization fires
    before /fill_slots runs, which is why it carries no slots. An emission placed there
    would capture the same nothing while looking correct."""
    accept = _SUP.index("accepted = accept_slots(")
    emit = _SUP.index(f'asset_key=["{_ASSET}"]')
    route_assets = _SUP.index("        _log_subtask_route_assets(")
    assert accept < emit, "the slots materialization must come after accept_slots()"
    assert route_assets < accept, (
        "routing assets are expected to precede slot acceptance — if this moved, the "
        "premise of this test changed and the comment above needs rewriting"
    )


def test_the_capture_is_non_fatal():
    """Provenance that fails must not take an answer down. A run that succeeded and
    recorded less beats one that did not run."""
    i = _SUP.index(f'asset_key=["{_ASSET}"]')
    window = _SUP[max(0, i - 400):i + 1900]
    assert "except Exception" in window, "the slots materialization must be non-fatal"


def test_the_gateway_does_not_invent_an_SSE_event_for_it():
    """This is provenance for the artifact, not a step for the HUD. A UI event with no
    reader is the orphan shape in the other direction."""
    i = _GW.index(f'path == ["{_ASSET}"]')
    window = _GW[i:i + 1800]
    assert "_sse(" not in window, "the slots decision must not emit an SSE event"


def test_resolved_intent_still_reaches_the_writer():
    """The field is only worth filling if it persists. Asserted on the AST so a rename of
    the bundle field goes red here rather than silently dropping the capture."""
    tree = ast.parse(_GW)
    found = any(
        isinstance(n, ast.keyword) and n.arg == "resolved_intent"
        for n in ast.walk(tree)
    )
    assert found, "resolved_intent is no longer passed to AnswerArtifactBundle"
