"""Content-addressed contract identity — the drift signal, pinned.

A version string is an ASSERTION about change; a content hash is a FACT about it. These tests
pin the properties that make the fact usable, and the one that makes it dangerous if lost:
CANONICALISATION. Two clients publishing the same contract with different key order MUST agree,
or "the same contract" registers as two nodes and the drift signal fires on a non-difference.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_contract_identity.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.presentation_agent.contract_identity import (  # noqa: E402
    CANONICAL_FORM_VERSION,
    contract_id,
    contracts_agree,
)

_CHART = {
    "archetype": "CHART_WIDGET",
    "component": "ChartWidget",
    "fields": {"chart_data": {"encoding": "json-string", "required": True}},
    "refusalReasons": ["no rows", "no numeric column"],
}


def test_the_same_contract_hashes_the_same():
    assert contract_id(_CHART) == contract_id(dict(_CHART))


def test_KEY_ORDER_DOES_NOT_CHANGE_THE_ID():
    """The load-bearing one. A TypeScript export and a Python dict will not agree on key
    order; if order mattered, one contract would register as two nodes and the drift signal
    would fire on a non-difference."""
    reordered = {
        "refusalReasons": _CHART["refusalReasons"],
        "fields": _CHART["fields"],
        "component": _CHART["component"],
        "archetype": _CHART["archetype"],
    }
    assert contract_id(reordered) == contract_id(_CHART)


def test_a_CHANGED_contract_is_a_DIFFERENT_id():
    changed = {**_CHART, "refusalReasons": ["no rows"]}
    assert contract_id(changed) != contract_id(_CHART)
    assert not contracts_agree(changed, _CHART)


def test_a_changed_FIELD_ENCODING_changes_the_id():
    """The encoding is the fact expected_fields could never carry. If it did not affect the
    id, the graph could serve a stale encoding under a current-looking reference."""
    changed = {**_CHART, "fields": {"chart_data": {"encoding": "array", "required": True}}}
    assert contract_id(changed) != contract_id(_CHART)


def test_the_canonical_form_version_is_part_of_the_id():
    """A canonicalisation change must be VISIBLE in the id, not silently re-address every
    contract in the graph."""
    assert contract_id(_CHART).startswith(CANONICAL_FORM_VERSION + ":")


def test_a_tuple_and_a_list_are_the_SAME_contract():
    """A contract declaring fields as a tuple in Python and an array in TypeScript is one
    contract. The point of canonicalisation is that two PUBLISHERS of one contract agree."""
    as_tuple = {**_CHART, "refusalReasons": ("no rows", "no numeric column")}
    assert contracts_agree(as_tuple, _CHART)


def test_nested_key_order_also_does_not_matter():
    nested = {**_CHART, "fields": {"chart_data": {"required": True, "encoding": "json-string"}}}
    assert contracts_agree(nested, _CHART)


def test_the_id_is_stable_across_processes():
    """Not PYTHONHASHSEED-dependent -- the whole mechanism exists to cross a process
    boundary, so an id that varied per interpreter would be worse than useless."""
    import subprocess, json as _json
    code = (
        "import json,sys;sys.path.insert(0,r'%s');"
        "from agent_fleet.presentation_agent.contract_identity import contract_id;"
        "print(contract_id(json.loads(sys.argv[1])))" % str(_ROOT)
    )
    out = subprocess.run([sys.executable, "-c", code, _json.dumps(_CHART)],
                         capture_output=True, text=True, timeout=120)
    assert out.stdout.strip() == contract_id(_CHART), out.stderr[-300:]
