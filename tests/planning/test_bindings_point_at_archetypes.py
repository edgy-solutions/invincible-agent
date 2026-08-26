"""A rendersAs triple's OBJECT end must be an Archetype, and its SUBJECT end a Response.

WHY THIS EXISTS. `mesh:ContributionSequence` shipped bound to `object_uri: "mesh:IntervalSchedule"`
— the SUBJECT of the row directly above it, copied into the object slot. The triple then read
"a ContributionSequence renders as an IntervalSchedule": one payload rendering as another
payload, which is not a claim this model can mean.

IT PASSED EVERY GATE, and the comment that shipped with it explains why in its own words:
"both endpoints pre-exist and Contract D is satisfied." Both statements were true.

    CONTRACT D CHECKS EXISTENCE, NOT CLASSIFICATION.

`mesh:IntervalSchedule` is a declared `owl:Class`, so a triple pointing at it is well-formed
and meaningless at the same time. Every existing seal agreed the row was fine: the archetype
vocabulary check passed (the CONTRACT names INTERVAL_TIMELINE, which is registered), the
four-registry seal passed, and the component rendered — because the component is chosen from
the contract, not from the object_uri. The only thing that was wrong was the graph edge, which
nothing looked at.

THE FINDING CAME IN MISDIAGNOSED, and that is worth recording. It was handed over as
"IntervalSchedule hangs off Response rather than Archetype" — i.e. as a TTL defect. The TTL is
RIGHT: `mesh:IntervalSchedule subClassOf mesh:Response` is exactly correct for a payload type,
and `mesh:IntervalTimeline subClassOf mesh:Archetype` is exactly correct for a rendering kind.
What was wrong was a binding USING the payload class where an archetype belongs. Seeing a
Response class in an archetype position and concluding the class is misfiled is the natural
reading, and it would have "fixed" a correct ontology to accommodate a broken row.

So the check is on the USE, not on the declaration.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_TTL = Path(__file__).resolve().parents[2] / "setup" / "ontologies" / "mesh_system.ttl"
_BINDINGS = (
    Path(__file__).resolve().parents[3]
    / "cortex-ui" / "src" / "registry" / "assembleCapabilities.ts"
)

#: Rows whose subject_uri is itself an Archetype class. LEGACY SELF-BINDINGS: the response type
#: and the archetype were the same name before the payload/rendering split was drawn, and these
#: are two of the hand-authored rows the registry's own comments describe as not yet migrated.
#: Exempted rather than silently skipped — an exemption is a claim, and this one says "known
#: legacy shape", not "acceptable for new rows".
_LEGACY_SELF_BOUND = {"mesh:WorkflowObservation", "mesh:InstancesByProperty"}


def _parents() -> dict[str, str]:
    """class -> its rdfs:subClassOf parent, read from the TTL itself."""
    ttl = _TTL.read_text(encoding="utf-8")
    return {
        m.group(1): m.group(2)
        for m in re.finditer(
            r"^(mesh:\w+)\s+a\s+owl:Class\s*;\s*\n\s*rdfs:subClassOf\s+(mesh:\w+)", ttl, re.M
        )
    }


def _bindings() -> list[tuple[str, str]]:
    if not _BINDINGS.is_file():
        return []
    src = _BINDINGS.read_text(encoding="utf-8")
    return re.findall(
        r'subject_uri:\s*"([^"]+)",\s*\n\s*object_uri:\s*"([^"]+)"', src
    )


def test_the_inputs_are_readable():
    """Positive control. Without this a moved file or a changed formatting style would make
    every assertion below pass over an empty list — which is exactly how this defect survived:
    the checks that existed all agreed, because none of them was looking here."""
    parents = _parents()
    assert len(parents) >= 40, f"only {len(parents)} classes parsed — the TTL's shape moved"
    if not _BINDINGS.is_file():
        pytest.skip(f"cortex-ui not checked out beside this repo ({_BINDINGS})")
    assert len(_bindings()) >= 15, "binding table did not parse — the TS shape moved"


@pytest.mark.skipif(not _BINDINGS.is_file(), reason="cortex-ui not checked out beside this repo")
def test_every_binding_renders_a_response_AS_AN_ARCHETYPE():
    """The whole rule, in one assertion.

    An object end that is a Response makes the triple well-formed and meaningless — it says a
    payload renders as another payload. A subject end that is an Archetype inverts the edge.
    Both are invisible to Contract D, which only asks whether the classes exist.
    """
    parents = _parents()
    offences: list[str] = []
    for subject, obj in _bindings():
        sp, op = parents.get(subject), parents.get(obj)
        if op != "mesh:Archetype":
            offences.append(
                f"{subject} -> {obj}: OBJECT end is {op or 'undeclared'}, not mesh:Archetype"
            )
        if sp != "mesh:Response" and subject not in _LEGACY_SELF_BOUND:
            offences.append(
                f"{subject} -> {obj}: SUBJECT end is {sp or 'undeclared'}, not mesh:Response"
            )
    assert not offences, (
        "rendersAs triples pointing at the wrong kind of class:\n  "
        + "\n  ".join(offences)
        + "\n\nContract D passes these — it checks that both classes EXIST, not what they are."
    )


@pytest.mark.skipif(not _BINDINGS.is_file(), reason="cortex-ui not checked out beside this repo")
def test_the_legacy_exemptions_are_still_real():
    """An exemption that no longer applies is a hole nobody remembers opening.

    If a legacy self-binding is migrated or removed, this fails and the name comes out of the
    exemption set — rather than sitting there quietly permitting a shape that has since been
    fixed everywhere else.
    """
    subjects = {s for s, _ in _bindings()}
    stale = _LEGACY_SELF_BOUND - subjects
    assert not stale, (
        f"exempted rows that no longer exist: {sorted(stale)} — drop them from "
        "_LEGACY_SELF_BOUND so the exemption cannot outlive what it excused"
    )
