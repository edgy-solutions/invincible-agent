"""THE PROJECTOR MUST NOT READ A PROPERTY NOTHING WRITES.

FOUND 2026-09-08 in the projector's own log, while measuring something else. Every poll —
twice a second, for months — Neo4j answered with:

    warn: property key does not exist. The property `duration_ms` does not exist.
    warn: property key does not exist. The property `code_hash`   does not exist.
    warn: property key does not exist. The property `kind`        does not exist.
    warn: property key does not exist. The property `valid_until` does not exist.

**Neo4j REMOVES a property assigned null.** So a field the writer sets from a bundle value
that is always `None` does not merely arrive empty — it does not exist, and reading it warns.
The four were not one defect but three:

    duration_ms   the field's own docstring said "compute this from `valid_as_of`, never
                  from the wire", and nothing ever computed it. Documented intent, no
                  producer. Now computed in the writer.
    kind          not a bundle field at all. The projector defaulted it to "answer" with a
                  comment citing Decision 2, so the COLUMN was always right — only the read
                  was a ghost. Now written, so the read is true and a second kind has a
                  source.
    valid_until   bundle field, never set by anything.
    code_hash     read off the producer node from a `produced_by` key the gateway does not
                  include.

The last two are dropped from the read. A column nothing writes is a promise nothing keeps,
and the read comes back when the write does.

WHY THIS IS WORTH A SEAL AND NOT JUST A FIX. It is the same producer/consumer defect this
repo has now closed four times in one week — `subtask_graph_trace` selected on a status its
producer never emitted, `resolved_intent` reading keys the supervisor did not write,
`too_many`'s count reaching the card only inside prose. Every instance passed both sides'
own tests. And the cost here is not the empty column: it is that a reader emitting four
warnings twice a second is a reader whose next REAL warning nobody reads.

Run: uv run --frozen pytest tests/routing/test_the_projector_reads_what_the_writer_writes.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_WRITER = (_REPO / "src" / "iagent" / "answer_artifact_writer.py").read_text(encoding="utf-8")
_PROJ = (_REPO / "src" / "iagent" / "projector" / "apply_loop.py").read_text(encoding="utf-8")


def _merge_pattern_props(var: str, label: str) -> set[str]:
    """Properties written INSIDE a `MERGE (v:Label {k: $v, ...})` pattern.

    THE FIRST VERSION OF THIS FILE MISSED THESE and reported `id`, `actor_id` and
    `actor_type` as ghosts — all three are real, all three are written in the merge key
    rather than a `SET`. A seal whose extractor sees only one of the two ways Cypher assigns
    a property invents defects, which is the same instrument failure as measuring a
    population through one sample. Caught because the "ghosts" it named were obviously
    load-bearing, which is luck, not method.
    """
    out: set[str] = set()
    for m in re.finditer(rf"MERGE\s*\(\s*{var}\s*:\s*{label}\s*\{{([^}}]*)\}}", _WRITER):
        out |= set(re.findall(r"([a-z_]+)\s*:", m.group(1)))
    return out


def _written_artifact_props() -> set[str]:
    """Properties the writer puts on the AnswerArtifact node, by either mechanism."""
    return (set(re.findall(r"\ba\.([a-z_]+)\s*=\s*\$", _WRITER))
            | _merge_pattern_props("a", "AnswerArtifact"))


def _read_artifact_props() -> set[str]:
    """Properties the projector's `a { ... }` projection asks Neo4j for."""
    i = _PROJ.index("MATCH (a:AnswerArtifact)")
    block = _PROJ[i:_PROJ.index("] AS producers", i)]
    return set(re.findall(r"^\s*\.([a-z_]+),?\s*$", block, re.MULTILINE))


def _written_producer_props() -> set[str]:
    return (set(re.findall(r"\bp\.([a-z_]+)\s*=", _WRITER))
            | _merge_pattern_props("p", "Actor"))


def _read_producer_props() -> set[str]:
    i = _PROJ.index("| p {")
    block = _PROJ[i:_PROJ.index("}] AS producers", i)]
    return set(re.findall(r"\.([a-z_]+)", block))


# ── the join ────────────────────────────────────────────────────────────────

def test_every_property_the_projector_reads_is_one_the_writer_writes():
    """THE ASSERTION THIS FILE EXISTS FOR. Not "both files mention duration_ms" — the read
    set must be a SUBSET of the written set, so adding a read without a write goes red.
    Verified against the real pre-fix state: deleting `a.kind = $kind` from the writer while
    the projector still reads `.kind` fails here.

    WHAT IT CANNOT SEE, stated because the gap is load-bearing. `valid_until` was one of the
    four ghosts and this assertion never covered it — the writer DOES `SET a.valid_until`,
    always to null, and Neo4j removes a property assigned null. A write that is structurally
    present and semantically absent looks identical to a real one from the source.

    So this check holds "read with no write"; `test_the_two_unsourced_reads_are_gone` holds
    the always-null pair by name. Neither subsumes the other, and a future ghost of the
    always-null kind will need naming rather than being caught here.
    """
    ghosts = sorted(_read_artifact_props() - _written_artifact_props())
    assert not ghosts, (
        f"the projector reads {ghosts}, which the writer never SETs — Neo4j removes a "
        f"property assigned null, so these do not exist and every poll logs a warning for "
        f"each of them"
    )


def test_the_producer_sub_read_is_a_subset_too():
    """`code_hash` lived here, one level down, and was missed for the same reason: the
    producer projection is a separate read that no assertion covered."""
    ghosts = sorted(_read_producer_props() - _written_producer_props())
    assert not ghosts, f"the producer projection reads unwritten propert(ies): {ghosts}"


def test_the_join_is_not_vacuous():
    """Both sets empty satisfies the subset checks and proves nothing — the aggregate-floor
    defect, which this repo has shipped inside a test written to prevent it."""
    assert len(_read_artifact_props()) >= 10, sorted(_read_artifact_props())
    assert len(_written_artifact_props()) >= 10, sorted(_written_artifact_props())
    assert len(_read_producer_props()) >= 3, sorted(_read_producer_props())


# ── the specific four, pinned by name so a regression says which ────────────

def test_duration_ms_is_now_actually_produced():
    """The field with documented intent and no producer. Computed in the WRITER because that
    is where `valid_as_of` and the write time both exist — and because the field's own
    docstring forbids taking it from the wire."""
    assert "duration_ms" in _written_artifact_props()
    i = _WRITER.index("duration_ms=(")
    window = _WRITER[i:i + 260]
    assert "now_ms - bundle.valid_as_of" in window, (
        "duration_ms is no longer computed from valid_as_of — see the field's docstring"
    )


def test_duration_ms_is_not_taken_from_the_wire():
    """The docstring's actual instruction. An SSE-path duration and a persisted duration
    share a repo, a concept and a unit, which is what makes wiring one from the other the
    plausible mistake."""
    i = _WRITER.index("duration_ms=(")
    window = _WRITER[i:i + 260]
    assert "request" not in window and "payload" not in window


def test_kind_is_written_rather_than_only_defaulted():
    """The column was always right — the projector defaults it. The READ was the ghost."""
    assert "kind" in _written_artifact_props()
    assert 'kind: str = "answer"' in _WRITER


def test_the_projector_still_defaults_kind_anyway():
    """THE CONTROL, and it stays deliberately. Artifacts written before this commit have no
    `kind` on the node; the default is what keeps them projecting correctly. Removing it
    because the write now exists would break every historical row."""
    assert 'art.get("kind") or "answer"' in _PROJ


def test_the_two_unsourced_reads_are_gone():
    """`valid_until` and `code_hash` have no producer today. Dropped from the READ, kept as
    projection COLUMNS — the read returns when the write does."""
    assert "valid_until" not in _read_artifact_props()
    assert "code_hash" not in _read_producer_props()


def test_but_their_columns_survive():
    """The positive control for the assertion above. Dropping the columns as well would be a
    schema change wearing a warning fix's clothes, and would lose data the moment something
    starts writing them."""
    assert '"valid_until"' in _PROJ, "the valid_until column was removed, not just the read"
    assert "valid_until" in _WRITER, "the writer no longer accepts a valid_until at all"
