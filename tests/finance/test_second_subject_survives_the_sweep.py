"""A verb askable of two subjects needs two registration NAMES, or the second deletes the first.

THE HAZARD THIS PINS, measured 2026-09-02 before the change that needed it:

Engine F's six verbs hang off four subjects — burn rate and performance indices off
`fin:PerformanceMeasurementBaseline`, funding status off `fin:FundingLine`, drivers off
`fin:ControlAccount`. Every question phrased about the PROGRAM grounded to `fin:Program`,
where `compatible_count=2`, so four of six verbs were never candidates and the classifier
correctly returned `no_match`. A program manager says "Meridian", not "Meridian's performance
measurement baseline".

The repair is to ALSO register those verbs against `fin:Program`. The trap is that doing it
naively deletes what it was meant to add:

    the registrar's compensate-on-rescope sweep removes Predicate rows matching
    (tool_urn, verb_iri) whose input_uri differs from the one being written

— which is precisely what makes a re-registration an upsert instead of a duplicate. The
registration NAME becomes the tool_urn, so two subjects under one name is not "two edges", it
is one edge written twice with the second winning.

MEASURED ON THE LIVE SUBSTRATE: 0 of 46 engine verb rows held two subjects under one
(tool_urn, verb_iri). The precedent for doing it right is Engine A's `findSchema`, which
carries BOTH `idp:Column` and `idp:Dataset` — under `engine_a_find_schema_column` and
`engine_a_find_schema`. Two names.

These assert the property, not the current values, so a fifth subject inherits the guard.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.finance_agent.main import (  # noqa: E402
    VERBS, _all_subjects, _dead_end_classes, _unroutable_classes,
)

FIN = "http://invincible-agent/fin#"


def _planned_registrations():
    """The exact (verb, subject, name) triples the lifespan will emit."""
    return (
        [(v["verb"], v["input_uri"], "engine_fin_finance") for v in VERBS]
        + [(v["verb"], s, "engine_fin_finance_by_subject")
           for v in VERBS for s in v.get("also_askable_of", ())]
    )


def test_no_two_registrations_share_a_name_AND_a_verb():
    """THE SEAL. A repeated (name, verb) is a delete wearing the shape of an add.

    This is the whole reason `also_askable_of` registers under a second name. If someone
    later "simplifies" the loop back to one name, every secondary subject silently replaces
    its primary and four verbs lose the subject they actually measure — with no error, and a
    green startup.
    """
    dupes = [k for k, c in Counter(
        (name, verb) for verb, _subj, name in _planned_registrations()
    ).items() if c > 1]
    assert not dupes, (
        f"{len(dupes)} (registration name, verb) pair(s) registered more than once: {dupes}. "
        "The registrar sweeps rows matching (tool_urn, verb_iri) with a different input_uri, "
        "so the second write DELETES the first. Give the extra subject its own name."
    )


def test_every_verb_is_askable_of_the_program():
    """The coverage property the change exists to create, asserted on the SET.

    Not 'four verbs gained a subject' — that is the change. This is the invariant: a question
    naming the program can reach every verb. A seventh verb added against a sub-entity fails
    here rather than in a cluster.
    """
    program = FIN + "Program"
    reachable = {verb for verb, subj, _n in _planned_registrations() if subj == program}
    missing = sorted({v["verb"] for v in VERBS} - reachable)
    assert not missing, (
        f"{len(missing)} verb(s) unreachable from a question naming the program: {missing}. "
        "Grounding picks ONE class and that pick decides the candidate set; a verb whose only "
        "subject is a sub-entity nobody names in a question can never be a candidate."
    )


def test_the_primary_subject_is_still_what_the_verb_MEASURES():
    """The secondary must not quietly become the model.

    `also_askable_of` is a routing accommodation, not a re-modelling. Burn rate is a property
    of the baseline; saying its subject IS the program would make the ontology describe the
    wrong thing, which is the cost the cheap fix was chosen to avoid paying.
    """
    for v in VERBS:
        if v.get("also_askable_of"):
            assert v["input_uri"] != FIN + "Program", (
                f"{v['verb']} lists Program as ALSO askable while its primary subject is "
                f"already Program — the accommodation has replaced the modelling"
            )


def test_boot_checks_read_every_subject_not_just_the_primary():
    """Both directions of the resolvability guard must see the secondary subjects.

    `_unroutable_classes()` asks 'can every verb's subject be found?'. Reading `input_uri`
    alone would make it blind to a secondary subject that resolves nowhere — the exact silent
    gap it exists to catch, reintroduced by the change that widened the set.
    """
    assert _all_subjects() >= {v["input_uri"] for v in VERBS}
    assert FIN + "Program" in _all_subjects()
    assert not _dead_end_classes(), _dead_end_classes()
    assert not _unroutable_classes(), _unroutable_classes()
