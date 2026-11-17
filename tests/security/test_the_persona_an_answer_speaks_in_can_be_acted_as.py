"""The persona an engine answers in must be one a caller can act as.

MEASURED at the 2026-11-16 rehearsal: every sustainment answer read VOICE SUSTAINMENT_ENGINEER,
while "Acting as" read SAFETY_ENGINEER for every caller. The persona engine-o registers its verbs
and providers with was not in `policy/personas.yaml`, so no cell could carry it, and the picker
could only offer the hazard plane's cell. A viewer could not tell which of the two governed.

The rule sealed here: every `owner_persona` on a registration of engine-o that ANSWERS (any
verb but the `mesh:resolveInstance` lookup) is (1) in the persona vocabulary, which the sync
requires before a group may grant it, and (2) granted by at least one group's cell. The
personas are READ from the source, never typed here, so a new one reds this file until a cell
carries it.

The lookup provider is excluded on purpose. It registers as OPS_OPERATOR, which
`tests/docs/test_every_explained_verb_has_a_derived_invoker.py` records as deliberately absent
from the vocabulary. A lookup's persona is never an answer's voice.

Control: the same two checks pass for a persona that has always had a cell, so a reader
that found nothing cannot pass vacuously.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[2]
_ENGINE_O = _REPO / "agent_fleet" / "ontology_service" / "main.py"
_POLICY = _REPO / "policy"


#: How far above an `owner_persona=` its registration's `verb=` sits (measured: 8 to 12 lines).
_WINDOW = 15


def _owner_personas() -> set[str]:
    lines = _ENGINE_O.read_text(encoding="utf-8").splitlines()
    out = set()
    for i, line in enumerate(lines):
        m = re.search(r'owner_persona\s*=\s*"([A-Z_]+)"', line)
        if m and not any('"mesh:resolveInstance"' in x for x in lines[max(0, i - _WINDOW):i]):
            out.add(m.group(1))
    return out


def _vocabulary() -> set[str]:
    return set(yaml.safe_load((_POLICY / "personas.yaml").read_text(encoding="utf-8"))["personas"])


def _granted_personas() -> set[str]:
    groups = yaml.safe_load((_POLICY / "groups.yaml").read_text(encoding="utf-8"))["groups"]
    return {c["persona"] for g in groups.values() for c in ((g or {}).get("grants") or [])}


def test_the_reader_finds_engine_o_s_personas():
    assert _owner_personas(), (
        "no owner_persona literal read from engine-o's source: the pattern stopped matching, "
        "and every assertion below would pass on an empty set")


def test_every_persona_engine_o_answers_in_is_declared_and_granted():
    personas = _owner_personas()
    undeclared = sorted(personas - _vocabulary())
    assert not undeclared, (
        f"engine-o answers as {undeclared}, which policy/personas.yaml does not declare; the "
        f"sync refuses any group grant naming it, so nobody can act as the answer's voice")
    ungranted = sorted(personas - _granted_personas())
    assert not ungranted, (
        f"engine-o answers as {ungranted}, which no group in policy/groups.yaml grants; the "
        f"picker can never offer it, and 'Acting as' disagrees with the answer's voice")


def test_control_a_persona_that_has_always_had_a_cell_passes_the_same_checks():
    control = "SAFETY_ENGINEER"
    assert control in _vocabulary() and control in _granted_personas()
