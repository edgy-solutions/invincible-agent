"""ADR-0051 seal 1, offline half — every `output_uri` resolves to a class a TTL declares.

THIS SEAL EXISTS BECAUSE IT CAUGHT THE THING IT WAS WRITTEN FOR, IN THIS ENGINE, ON ITS SECOND
DAY. `engine-safety` registered two verbs in `eecb7c4` naming `safety:OrphanedHazardSet` and
`safety:DeferralRiskCard` as their outputs, and no TTL declared either.

That is `mesh:proposeDisposition`'s failure repeated exactly. It named its output class from the
day it woke; the class existed only because `scripts/seed_sandbox_predicates.py` MERGEd it into
being as a side effect; sandbox therefore had the node and every fresh cluster did not; and the
registrar — which MATCHes, correctly, because it must never invent ontology — refused the edge
with a Contract D 422 that was telling the exact truth. **Nine of Engine A's ten verbs registered
and that one could not, permanently.** A restart cannot conjure a class no source declares.

THE POPULATION IS DERIVED FROM `VERBS`, NEVER HAND-LISTED. A hand-kept list of output classes
would pass on the day a verb is added without one, which is the only day it matters. This repo has
paid for remembered lists more times than it has paid for anything else.

WHAT THIS HALF CANNOT SEE, stated so the full seal is not assumed from it: it reads the TTL in the
working tree, so it proves the DECLARATION exists, not that a cluster PRIMED it. Seal 1's other
half runs against a fresh prime and is increment 5's. A green here plus a green there is the
complete claim; a green here alone is "we wrote it down".
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_fleet.safety_agent import main as safety_main

_REPO = Path(__file__).resolve().parents[2]
_SAFETY_NS = "http://internal/sustainment/safety#"

#: Every TTL this engine's classes may legitimately be declared in. Derived from the prime
#: manifest's own rows rather than typed, so a vocabulary added to the manifest is covered
#: without anyone remembering this file exists.
_PRIME_MANIFEST = _REPO / "setup" / "prime_databases.py"


def _declared_safety_classes() -> set[str]:
    """Every `safety:` class declared by a TTL the PRIME MANIFEST actually ships.

    Reading the manifest rather than globbing `setup/ontologies/` is the load-bearing part: a TTL
    sitting in the directory and absent from the manifest is exactly as undeclared, at a fresh
    cluster, as a TTL that does not exist. Globbing would call that green.
    """
    manifest = _PRIME_MANIFEST.read_text(encoding="utf-8")
    shipped = set(re.findall(r'"path":\s*"(ontologies/[^"]+\.ttl)"', manifest))
    assert shipped, "no ontology paths parsed from the prime manifest — instrument failure"

    declared: set[str] = set()
    for rel in shipped:
        ttl = _REPO / "setup" / rel
        if not ttl.exists():
            continue
        text = ttl.read_text(encoding="utf-8")
        declared |= {f"{_SAFETY_NS}{m}" for m in re.findall(r"^safety:(\w+)\s+a\s+owl:Class", text, re.M)}
    return declared


def test_every_output_uri_is_declared_by_a_shipped_ttl():
    """SEAL 1, offline half. The population is VERBS; the authority is the prime manifest."""
    declared = _declared_safety_classes()
    missing = [
        (v["fn"], v["output_uri"])
        for v in safety_main.VERBS
        if v["output_uri"].startswith(_SAFETY_NS) and v["output_uri"] not in declared
    ]
    assert not missing, (
        "verb(s) name an output_uri that no TTL in the prime manifest declares — on a fresh "
        "cluster the registrar MATCHes and refuses the edge with a Contract D 422, permanently: "
        f"{missing}"
    )


def test_every_input_uri_in_the_safety_namespace_is_declared_too():
    """The same rule on the subject side.

    An undeclared INPUT class fails differently and just as permanently: the verb registers
    against a class nothing can ground to, so it is unroutable rather than unregisterable.
    Asserted separately because the two failures need different fixes and a combined assertion
    would name the wrong one.
    """
    declared = _declared_safety_classes()
    missing = [
        (v["fn"], v["input_uri"])
        for v in safety_main.VERBS
        if v["input_uri"].startswith(_SAFETY_NS) and v["input_uri"] not in declared
    ]
    assert not missing, f"verb(s) declare an undeclared safety input class: {missing}"


def test_the_declaration_reader_can_say_no():
    """THE CONTROL. A reader that has only ever been handed declared classes has not been shown
    able to spot an undeclared one — and a regex that silently matches nothing looks identical to
    one that matches everything it was asked about."""
    declared = _declared_safety_classes()
    assert declared, "zero safety classes parsed — instrument failure, not an empty vocabulary"
    fabricated = f"{_SAFETY_NS}DefinitelyNotADeclaredClass"
    assert fabricated not in declared, (
        "the reader reports a fabricated class as declared — it is not discriminating"
    )


def test_the_manifest_is_what_is_consulted_not_the_directory():
    """A TTL on disk but absent from the prime manifest must NOT count as declared.

    This is the difference between "we wrote the file" and "a fresh cluster has the class", and
    it is the distinction the proposeDisposition failure turned on. Asserted by construction:
    the reader parses `prime_databases.py`, so a file added to `setup/ontologies/` without a
    manifest row contributes nothing here.
    """
    manifest = _PRIME_MANIFEST.read_text(encoding="utf-8")
    assert "safety_extension.ttl" in manifest, (
        "safety_extension.ttl is not in the prime manifest — its classes do not exist on a "
        "fresh cluster no matter what the working tree contains"
    )
    assert "safety_risk_matrix.ttl" in manifest, "the ratified matrix is not in the prime manifest"
