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


# -- LOCATED STRUCTURALLY, NOT BY CHARACTER SPAN ------------------------------
#
# These helpers read `_SUP[i:i + 2500]` and `_GW[i:i + 4000]` until 2026-09-07, when adding
# `subject_uri` to the slots decision -- a change that ADDED a key and removed nothing --
# pushed `slot_resolution` past the 2500-character boundary and turned four tests red. Every
# key was still emitted. The window had simply stopped covering them.
#
# FOURTH INSTANCE of a magic span rotting in this repo, and the second where the rot was
# caused by comment prose written to explain a previous one. Widening the number resets the
# timer and nothing else, so the span is gone: the materialization is found by its asset key
# and the gateway branch by its test expression, and both grow with the code.


def _sup_tree():
    return ast.parse(_SUP)


def _is_slots_materialization(node) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if getattr(f, "id", getattr(f, "attr", "")) != "AssetMaterialization":
        return False
    for kw in node.keywords:
        if kw.arg == "asset_key" and isinstance(kw.value, (ast.List, ast.Tuple)):
            if _ASSET in [e.value for e in kw.value.elts if isinstance(e, ast.Constant)]:
                return True
    return False


def _materialization():
    found = [n for n in ast.walk(_sup_tree()) if _is_slots_materialization(n)]
    assert len(found) == 1, f"expected one {_ASSET} materialization, found {len(found)}"
    return found[0]


def _metadata_dict():
    for kw in _materialization().keywords:
        if kw.arg == "metadata" and isinstance(kw.value, ast.Dict):
            return kw.value
    raise AssertionError(f"the {_ASSET} materialization carries no metadata dict")


def _value_src(key: str) -> str:
    """The unparsed VALUE expression for one metadata key."""
    d = _metadata_dict()
    for k, v in zip(d.keys, d.values):
        if isinstance(k, ast.Constant) and k.value == key:
            return ast.unparse(v)
    raise AssertionError(f"{key} is not emitted at all")


def _emitted_keys() -> set:
    """The metadata keys the supervisor puts on the slots materialization."""
    return {
        k.value for k in _metadata_dict().keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }


def _gateway_branch_src() -> str:
    """The BODY of the `path == [_ASSET]` branch.

    The body ONLY -- an `elif` chain nests every later branch inside this node's `orelse`, so
    unparsing the whole `If` would drag them in and quietly widen every assertion made
    against it.
    """
    for n in ast.walk(ast.parse(_GW)):
        if isinstance(n, ast.If) and _ASSET in ast.unparse(n.test):
            return chr(10).join(ast.unparse(stmt) for stmt in n.body)
    raise AssertionError(f"no gateway branch tests for {_ASSET}")


def _consumed_keys() -> set:
    """The metadata keys the gateway reads out of it."""
    src = _gateway_branch_src()
    # SINGLE QUOTES, because `ast.unparse` normalises string literals to them. Matching any
    # character instead of a quote harvested "ey" out of `_j(key, fallback)` -- a phantom key
    # that no producer could ever emit, which read exactly like a real producer/consumer gap.
    return (set(re.findall(r"_slots_md\.get\('([a-z_]+)'", src))
            | set(re.findall(r"_j\('([a-z_]+)'", src)))


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
    guarded = [
        t for t in ast.walk(_sup_tree())
        if isinstance(t, ast.Try)
        and any(_is_slots_materialization(c) for stmt in t.body for c in ast.walk(stmt))
    ]
    assert guarded, (
        "the slots materialization is not inside a try -- a provenance failure would take "
        "the answer down with it"
    )
    assert all(t.handlers for t in guarded), "the try has no handler"


def test_the_gateway_does_not_invent_an_SSE_event_for_it():
    """This is provenance for the artifact, not a step for the HUD. A UI event with no
    reader is the orphan shape in the other direction."""
    assert "_sse(" not in _gateway_branch_src(), (
        "the slots decision must not emit an SSE event"
    )


def test_resolved_intent_still_reaches_the_writer():
    """The field is only worth filling if it persists. Asserted on the AST so a rename of
    the bundle field goes red here rather than silently dropping the capture."""
    tree = ast.parse(_GW)
    found = any(
        isinstance(n, ast.keyword) and n.arg == "resolved_intent"
        for n in ast.walk(tree)
    )
    assert found, "resolved_intent is no longer passed to AnswerArtifactBundle"


# ── refusals must be readable by a RENDERER, not only by a person ───────────

def test_refused_slots_are_structured_records_not_formatted_prose():
    """`[str(r) for r in refusals]` renders as "program_id='meridian' refused (undeclared)",
    and a surface wanting the slot NAME had to parse an English sentence to get it.

    That is presence-is-not-content in a field — the same defect this repo named when
    `too_many`'s count reached the card only inside `message` prose, so a caller wanting
    "14 projects" had to read a sentence. Found 2026-09-05 while ruling what the disclosure
    strip should render: cortex cannot show a refusal it cannot parse.

    `Refusal.__str__` is unchanged and stays right where it is — a LOG LINE is read by a
    person, a PAYLOAD is read by a renderer, and the same string cannot serve both.
    """
    window = _value_src("refused_slots")
    assert "[str(r) for r in" not in window, (
        "refused_slots is being stringified again — a renderer would have to parse prose"
    )
    # Unparsed form: `ast.unparse` renders dict keys with single quotes.
    for field in ("'name': r.name", "'reason': r.reason", "'spoken': r.spoken"):
        assert field in window, f"the refusal record lost {field}"


def test_the_log_line_keeps_its_prose_form():
    """The fix must not go the other way: a log line that dumps a dict is worse for the
    person reading it than the sentence it replaced."""
    from iagent_pure.slot_acceptance import Refusal

    assert str(Refusal("program_id", "undeclared", "meridian")) == (
        "program_id='meridian' refused (undeclared)"
    )


def test_the_disclosure_keys_the_strip_needs_are_all_carried():
    """Ruled 2026-09-05: the strip sources rows from `slot_resolution` (everything the
    resolver touched) and marks each by membership in `accepted_slots`, with `refused_slots`
    naming which were dropped and why. All three must reach the artifact or the ruling is
    unimplementable on the consumer side."""
    for key in ("slot_resolution", "accepted_slots", "refused_slots"):
        assert key in _emitted_keys(), f"{key} missing from the slots decision"
        assert key in _consumed_keys(), f"{key} is emitted but the gateway drops it"


# ── the SUBJECT, beside the verb it was chosen for ──────────────────────────
#
# MEASURED 2026-09-07, on the ask/pick pair a user actually walked:
#
#     artifact-1-...058552   verb_iri=mesh:planCapabilityPath  disposition=ask
#     artifact-2-...429144   verb_iri=mesh:planCapabilityPath  disposition=route
#                            accepted_slots={"capability_id": "C8"}  outcome=bound
#
# The pick re-derived the verb the ask had already established, at the cost of the whole
# pipeline -- /plan, /resolve, /classify_predicate -- which is why a follow-up costs what a
# first question costs. The artifact could not have been used to skip that work even in
# principle: it named the verb and never the subject the verb was found compatible WITH, and
# ADR-0019 Contract B forbids calling a verb without subject grounding. A verb alone is not a
# dispatchable route.

_SUBJECT_KEYS = ("subject_uri", "subject_instance_id", "subject_instance_label")


def test_the_subject_is_captured_beside_the_verb():
    missing = [k for k in _SUBJECT_KEYS if k not in _emitted_keys()]
    assert not missing, f"the slots decision names an action and not the thing acted on: {missing}"


def test_the_gateway_carries_the_subject_onto_the_artifact():
    missing = [k for k in _SUBJECT_KEYS if k not in _consumed_keys()]
    assert not missing, f"the subject is emitted but never reaches resolved_intent: {missing}"


def test_the_subject_is_read_from_the_ROUTING_TELEMETRY_not_a_placeholder():
    """NON-VACUITY ON THE VALUES, which the key-set assertions above cannot see. Three keys
    mapped to `""` satisfy every join check in this file while capturing nothing -- presence
    is not content -- and an empty subject would send a re-route back through /resolve while
    reporting that it had skipped it."""
    for key in _SUBJECT_KEYS:
        src = _value_src(key)
        assert "telemetry" in src, f"{key} is not read from the routing telemetry: {src}"
