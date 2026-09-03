"""Every engine that registers verbs on boot must be in the re-register list.

WHY THIS EXISTS, measured 2026-08-22. The prime ran clean (`Ingest: 16 ok, 0 failed, 0
unfinished`), `ontologySeed` completed, `reregister` completed, and Engine P's twelve verbs
were STILL unregistered -- because `primeSubstrate.reregisterEngines.deployments` lists six
engines and Engine P was not one of them.

Nothing failed. Every hook reported success, the substrate was correct, the classes Contract D
had been refusing for were present and correctly domain-tagged, and the engine holding the
verbs was simply never restarted. The evidence was the POD NAME being unchanged across the
whole chain -- the only visible difference between "re-registered and refused again" and
"never asked".

THE SHAPE. `reregisterEngines.deployments` is a hand-maintained list that must agree with a
fact living somewhere else entirely: which agents call `register_engine_to_mesh` in their
lifespan. Two descriptions of one fact, with nothing comparing them -- the same species as
the ingest-timeout/queue pair and the intent-catalog/BAML id pair, and it fails the same way:
silently, and only in a cluster.

WHY IT MATTERS BEYOND ENGINE P. An engine missing from this list does not merely fail to
register once. It stays stale through EVERY future prime: the graph gets rebuilt, every other
engine re-registers against it, and this one keeps whatever registration it happened to make
at its last restart -- or none. The gap is permanent and invisible until someone counts rows.
"""
from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_VALUES = _ROOT / "helm" / "invincible-agent" / "values.yaml"
_FLEET = _ROOT / "agent_fleet"
_ENGINES_TPL = _ROOT / "helm" / "invincible-agent" / "templates" / "engines.yaml"

# Agent directory -> the `component` name engines.yaml deploys it under. Derived from the
# template's own $engines list, so a renamed component cannot desync this mapping silently.
_COMPONENT_LINE = re.compile(
    r'\(dict\s+"key"\s+"(?P<key>\w+)"\s+"component"\s+"(?P<component>[\w-]+)"'
)

# values.yaml key -> agent_fleet directory. The one mapping that cannot be derived: the chart
# knows nothing about source layout. Kept small and asserted against reality below.
_KEY_TO_AGENT_DIR = {
    "engineO": "ontology_service",
    "engineA": "restate_analyst",
    "engineB": "langgraph_support",
    "engineC": "swarms_scraper",
    "engineD": "datahub_wrapper",
    "engineE": "neo4j_expert",
    "engineF": "presentation_agent",
    "engineW": "weaviate_expert",
    "enginePlanning": "planning_agent",
    "engineFinance": "finance_agent",
    "engineCost": "cost_agent",
    "dataAnalyst": "data_analyst",
}

# Engine keys that deploy from this chart but are NOT agent_fleet engines, or that
# deliberately do not self-register. Every key in engines.yaml must be in the map above or
# in here — `test_every_engine_key_is_accounted_for` enforces the partition, which is what
# stops the map from silently stopping at whichever engine was newest when someone last
# looked.
_NOT_A_REGISTERING_AGENT = {
    "centralGateway": "not an agent_fleet engine; a gateway with no verbs of its own",
    "engineB": (
        "LangGraph support. Registers NOTHING and is invisible to the mesh by omission "
        "rather than by design — see ADR-0046, which documents it. Waived here so the "
        "partition holds; the waiver is a description of the defect, not an endorsement."
    ),
    "engineC": "swarms scraper; no mesh verbs",
    "engineF": (
        "presentation agent. Its capabilities reach the graph from its OWN startup off "
        "PRESENTATION_CAPABILITIES, not through register_engine_to_mesh."
    ),
}


def _components() -> dict[str, str]:
    """values-key -> component name, read from engines.yaml."""
    text = _ENGINES_TPL.read_text(encoding="utf-8")
    return {m.group("key"): m.group("component") for m in _COMPONENT_LINE.finditer(text)}


def _registers_on_boot(agent_dir: pathlib.Path) -> bool:
    """Does this agent call register_engine_to_mesh at startup?

    Matches the CALL, not the import: Engine O imports registration helpers as the registry
    CONSUMER and must not appear in the re-register list, which is exactly the distinction an
    import-based check would get wrong.
    """
    for path in agent_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*register_engine_to_mesh\s*\(", text, re.MULTILINE):
            return True
    return False


# Engine O is EXCLUDED BY DESIGN and that exclusion is CORRECT — verified against the live
# graph, not inferred from the comment claiming it. Engine O self-registers
# `mesh:resolveInstance` in its own lifespan with the note "runs every boot, survives
# re-prime", and the graph holds exactly 1 resolveInstance row (measured 2026-08-22). So its
# registration lands without the re-register hook and adding it here would change the restart
# behaviour of the ontology service to fix nothing.
#
# Recorded rather than silently allowed, because the FIRST measurement said 0 rows and looked
# like a real gap — that query named a Weaviate field (`verb`) that does not exist, errored,
# and counted zero. The correct field is `verb_iri`. A waiver resting on a number is only as
# good as the query behind it.
WAIVED_BY_DESIGN = {
    "engine-o": "registry consumer; self-registers resolveInstance every boot (1 row, verified)",
}


def _declared_reregister_list() -> list[str]:
    values = yaml.safe_load(_VALUES.read_text(encoding="utf-8"))
    return list(values["primeSubstrate"]["reregisterEngines"]["deployments"])


def test_the_inputs_are_readable():
    """Positive control. Either side reading empty makes the comparison vacuous."""
    assert len(_components()) >= 8, "engines.yaml component list did not parse"
    assert len(_declared_reregister_list()) >= 4, "reregisterEngines.deployments did not parse"
    assert (_FLEET / "planning_agent").is_dir(), "agent_fleet layout moved"


def test_the_agent_dir_mapping_is_real():
    """Every mapped directory exists — a typo here would silently exempt an engine."""
    missing = sorted(d for d in _KEY_TO_AGENT_DIR.values() if not (_FLEET / d).is_dir())
    assert not missing, f"_KEY_TO_AGENT_DIR names directories that do not exist: {missing}"


def test_at_least_one_engine_is_detected_as_registering():
    """Negative control for the detector. If the regex stopped matching, the seal below would
    pass by finding nothing to require — the guard-gone-quiet shape."""
    detected = [k for k, d in _KEY_TO_AGENT_DIR.items() if _registers_on_boot(_FLEET / d)]
    assert len(detected) >= 4, (
        f"only {detected} detected as registering on boot — the call-site pattern moved, "
        f"and this seal would otherwise pass over nothing."
    )


def test_every_registering_engine_is_in_the_reregister_list():
    """THE SEAL.

    An engine that registers verbs on boot but is absent here never re-registers after a
    prime rebuilds the class graph. Its verbs stay missing, every hook reports success, and
    the only symptom is a row count nobody is watching.
    """
    components = _components()
    declared = set(_declared_reregister_list())

    missing = []
    for key, agent_dir in sorted(_KEY_TO_AGENT_DIR.items()):
        if not _registers_on_boot(_FLEET / agent_dir):
            continue
        component = components.get(key)
        if component in WAIVED_BY_DESIGN:
            continue
        if component and component not in declared:
            missing.append(f"{component} (agent_fleet/{agent_dir}, values key {key})")

    assert not missing, (
        "these engines register verbs on boot but are NOT in "
        "primeSubstrate.reregisterEngines.deployments:\n  "
        + "\n  ".join(missing)
        + "\n\nThey will not re-register after a prime rebuilds the class graph. Every hook "
        "will still report success."
    )


def test_the_reregister_list_names_only_real_components():
    """The other direction: a stale entry restarts nothing and hides that it restarts nothing."""
    known = set(_components().values())
    unknown = sorted(c for c in _declared_reregister_list() if c not in known)
    assert not unknown, (
        f"reregisterEngines.deployments names components engines.yaml does not deploy: "
        f"{unknown}. A stale entry patches a deployment that does not exist."
    )


# ---------------------------------------------------------------------------------------
# THE REVERSE AXIS, added 2026-09-03 after engine-cost shipped UNREGISTERED for a commit.
#
# THE SEAL ABOVE ENUMERATES CALLERS: it finds every agent that calls register_engine_to_mesh
# and asserts each is in the re-register list. That direction cannot see an engine that
# calls it ZERO times — such an engine simply is not in the population, so the seal passes
# while the engine is invisible to the mesh. engine-cost sat in the re-register list, served
# /health, and registered nothing; the seal was green throughout.
#
# WORSE, AND FOUND WHILE FIXING IT: `_KEY_TO_AGENT_DIR` was hand-kept and stopped at Engine
# P. `engineFinance` was never in it, so THE SEAL HAD NEVER CHECKED ENGINE F EITHER — added
# 2026-08-29, unexamined by this file for five days. A seal whose population is a hand-kept
# dict tests whatever someone remembered to add.
#
# So both directions are now closed, and the population is DERIVED from engines.yaml rather
# than remembered.
# ---------------------------------------------------------------------------------------


def test_every_engine_key_is_accounted_for():
    """Every key in engines.yaml maps to an agent dir OR is explicitly not-an-agent.

    THIS IS THE TEST THAT WOULD HAVE CAUGHT THE STALE MAP. A key in neither set is a key the
    rest of this file silently skips.
    """
    keys = set(_components())
    mapped = set(_KEY_TO_AGENT_DIR)
    waived = set(_NOT_A_REGISTERING_AGENT)
    unaccounted = keys - mapped - waived
    assert not unaccounted, (
        f"engines.yaml declares {sorted(unaccounted)}, which are in neither "
        "_KEY_TO_AGENT_DIR nor _NOT_A_REGISTERING_AGENT. Until one of those names it, every "
        "check in this file skips it — which is how engineFinance went five days unexamined."
    )


def test_every_mapped_engine_actually_registers():
    """The reverse of the seal above: a MAPPED engine that registers nothing is a defect.

    An engine deployed, transport-authed and health-green while registering zero verbs is
    ADR-0046's Engine B shape. If a new engine legitimately does not register, it belongs in
    _NOT_A_REGISTERING_AGENT with a stated reason — declared, not defaulted.
    """
    silent = []
    for key, agent_dir in sorted(_KEY_TO_AGENT_DIR.items()):
        if key in _NOT_A_REGISTERING_AGENT:
            # Mapped AND waived: the dir mapping stays so other checks can find the source,
            # while the must-register rule is lifted with a written reason. Being in both
            # sets is legitimate; being in NEITHER is what the partition test catches.
            continue
        path = _ROOT / "agent_fleet" / agent_dir
        if not _registers_on_boot(path):
            silent.append(f"{key} ({agent_dir})")
    assert not silent, (
        "mapped engines that call register_engine_to_mesh ZERO times: "
        f"{silent}. Each is deployed and invisible to the mesh. Either register, or move the "
        "key to _NOT_A_REGISTERING_AGENT with the reason written down."
    )
