"""THE ELIGIBILITY GATES READ PROPERTIES NOTHING WROTE.

WHY THIS EXISTS. `_filter_verbs_by_arity` and `_filter_verbs_by_argument_fit` are the
structural half of verb eligibility — they drop a single-asset verb from a set-shaped
query, and a verb whose `required_args` the query cannot supply, BEFORE the classifier
ever sees them. Both read their declaration off `/find_compatible_verbs`.

The read half was complete and had been for months: the compat walk's Cypher RETURNs
`r.arity` and `r.required_args`, `CompatibleVerb` declares both fields, and its
constructor passes both. **The write half existed nowhere.** `_build_rel_props_for_saga`
— the one function whose output lands on the Neo4j relationship — named neither, and
`arity` was not even a field on `RegistrationManifest`, so an engine could not declare
it if it wanted to. Every verb read back null; both gates are written to treat null as
"never exclude"; the arity gate was structurally INERT on every cluster since it shipped.

MEASURED on the sandbox cluster 2026-08-31, through the consumer's own view rather than
the graph: 0 of 10 verbs on `idp#Portfolio` carried either property. Neo4j had been
saying so on every single compat walk —

    Received notification from DBMS server: ... the missing property name is: arity

— which is the rare case of a silent gap that was not actually silent.

WHY THE EXISTING TESTS DID NOT CATCH IT, and this is the part worth keeping.
`tests/test_arity_gate.py` and `tests/test_argument_fit_gate.py` are green, thorough,
and build every verb dict BY HAND (`_v(iri, arity="single")`). They prove the FILTER
does what it says when handed a declaration. They cannot fail when no declaration can
ever arrive, because they are the thing that supplies it. The claim was "a single-asset
verb is excluded from a set query"; the assertion was on the neighbouring claim that a
pure function excludes what it is passed. See
docs/plans/a-registration-property-must-be-enumerated-seven-times.md.

So this file asserts on the CARRY, and closes the loop by feeding the registrar's real
property bag straight into the real gate. The key names are the join, and a rename on
either side breaks these rather than going quiet.

Run: uv run --frozen --with pytest --with pydantic pytest tests/test_eligibility_declarations_reach_the_edge.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "agent_fleet" / "mesh_registrar" / "main.py"

# Unique module name, never bare "main" — 155 files in this repo are named main.py
# and `import main` returns whichever was cached FIRST.
_MOD_NAME = "mesh_registrar_main__eligibility_carry_test"


def _mod():
    cached = sys.modules.get(_MOD_NAME)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(_MOD_NAME, _SRC)
    m = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(_MOD_NAME, None)
        pytest.fail(f"mesh_registrar must be importable for this suite: {exc!r}")
    return m


_IDP = "http://invincible-agent/idp#"


def _bag(**over):
    """The property bag that actually lands on the Neo4j relationship."""
    m = _mod()
    fields = dict(
        name="engine_d_describe_asset",
        verb_iri="mesh:describeAsset",
        input_uri=f"{_IDP}Dataset",
        output_uri=f"{_IDP}AssetProfile",
        endpoint_url="http://iagent-engine-d:8086/describe",
        owner_persona="DATA_STEWARD",
    )
    fields.update(over)
    return m._build_rel_props_for_saga(
        manifest=m.RegistrationManifest(**fields),
        provider="engine_d",
        tool_urn="urn:li:mlModel:(urn:li:dataPlatform:mesh,engine_d_describe_asset,PROD)",
    )


# ── the carry itself ────────────────────────────────────────────────────────

def test_a_declared_arity_reaches_the_property_bag():
    """The regression. Before the fix this key was absent for every verb."""
    assert _bag(arity="single")["arity"] == "single"


def test_declared_required_args_reach_the_property_bag():
    assert _bag(required_args=["tag"])["required_args"] == ["tag"]


def test_an_UNDECLARED_arity_writes_no_property_at_all():
    """Absent, not "" — an empty string is a value, and `null = never exclude` is the
    gate's contract. Follows the `timeout_s` idiom in the same bag."""
    assert "arity" not in _bag()


def test_undeclared_required_args_are_an_empty_list_not_a_missing_key():
    """Unlike arity: a list of primitives is a legal Neo4j property, and the gate reads
    empty as unconstrained. Writing it keeps the edge self-describing."""
    assert _bag()["required_args"] == []


def test_required_args_are_strings_not_a_json_string():
    """The `slots` neighbour in this bag IS a JSON string, because it is a list of MAPS
    and Neo4j refuses those. `required_args` is a list of primitives and must stay one —
    stringifying it would make `list()` on the read side yield one entry per CHARACTER,
    the defect that produced "422 unknown fiscal period(s): F, Y, 2, 6, -, Q, 4"."""
    got = _bag(required_args=["tag", "owner"])["required_args"]
    assert got == ["tag", "owner"] and all(isinstance(a, str) for a in got)


# ── the loop: the registrar's bag, fed to the supervisor's real gate ────────
#
# The compat walk RETURNs these under the SAME names the bag writes
# (`r.arity AS arity`, `r.required_args AS required_args`), so the bag is a faithful
# stand-in for the dict the gate receives. That identity is the thing under test.

def _gates():
    src = _REPO / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from iagent.defs.dynamic_supervisor import (  # noqa: PLC0415
        _filter_verbs_by_argument_fit,
        _filter_verbs_by_arity,
    )
    return _filter_verbs_by_arity, _filter_verbs_by_argument_fit


def test_a_single_asset_verb_is_ACTUALLY_FLAGGED_on_a_set_query():
    """THE CLAIM ITSELF, end to end, using the registrar's own output as the input.

    The disposal changed 2026-09-04: a registered single-asset verb is MARKED
    `needs_instance` and kept, so the disposition can ask rather than the pool going empty.
    What still may not happen is a silent dispatch — that guarantee moved to the dispatch
    precondition at the disposition point, and this asserts the flag it reads."""
    by_arity, _ = _gates()
    kept, flagged = by_arity([_bag(arity="single")], query_is_set=True)
    assert len(kept) == 1 and len(flagged) == 1
    assert kept[0].get("needs_instance") is True, (
        "the router reads the KEPT list; a flag only in the report is invisible to it"
    )


def test_a_verb_registered_without_arity_survives_a_set_query():
    """The conservative direction: an incomplete backfill must never over-restrict."""
    by_arity, _ = _gates()
    kept, dropped = by_arity([_bag()], query_is_set=True)
    assert len(kept) == 1 and dropped == []


def test_a_verb_whose_required_args_are_unavailable_is_ACTUALLY_dropped():
    _, by_args = _gates()
    kept, dropped = by_args([_bag(required_args=["tag"])], available_args={"owner"})
    assert kept == [] and len(dropped) == 1


def test_the_argument_fit_gate_stays_inert_without_a_typed_arg_signal():
    """`available_args is None` means "no signal", not "nothing available". The
    supervisor passes None today; this gate must not activate on that."""
    _, by_args = _gates()
    kept, dropped = by_args([_bag(required_args=["tag"])], available_args=None)
    assert len(kept) == 1 and dropped == []
