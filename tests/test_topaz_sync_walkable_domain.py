"""Walkable vocabulary edge (de-hardcode phase 1) — PURE core, no network.

catalog_domain_view.rego hardcodes the persona list because rego cannot
LIST objects of a type: answering "does U hold ANY (persona, D) cell"
required CONSTRUCTING candidate cell IDs, which required enumerating
personas. Phase 1 reifies cell→domain membership as a real relation
(domain:<D> #cell @cell:<P>:<D>; manifest: domain.can_view =
cell->can_assume) so phase 2 can swap the enumeration for a single walk.

These tests pin the pure transforms: the edge is DERIVED for every
granted cell (and only granted cells — prune=revoke depends on desired
state dropping the edge when the last grant goes), it sits in the
sync's managed prune scope, and derive_entitled_domains produces the
exact allow-set the readback verifies.

Run:  PYTHONPATH=policy/sync pytest tests/test_topaz_sync_walkable_domain.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SYNC = Path(__file__).resolve().parent.parent / "policy" / "sync"
if str(_SYNC) not in sys.path:
    sys.path.insert(0, str(_SYNC))

from topaz_sync import (  # noqa: E402
    DirRelation,
    PolicyBundle,
    derive_desired,
    derive_entitled_domains,
)


def _bundle(**over) -> PolicyBundle:
    base = dict(
        personas=["DATA_ENGINEER", "ARCHITECT"],
        domains=["SUSTAINMENT", "MAINTENANCE"],
        groups={
            "data-engineers": {"grants": [
                {"persona": "DATA_ENGINEER", "domain": "SUSTAINMENT"},
            ]},
            "architects": {"grants": [
                {"persona": "ARCHITECT", "domain": "SUSTAINMENT"},
                {"persona": "ARCHITECT", "domain": "MAINTENANCE"},
            ]},
        },
        users=[
            {"id": "E12345", "groups": ["data-engineers"]},
            {"id": "E67890", "groups": ["data-engineers", "architects"]},
        ],
    )
    base.update(over)
    return PolicyBundle(**base)


def _domain_cell_edges(state) -> set[tuple[str, str]]:
    return {
        (r.object_id, r.subject_id)
        for r in state.relations
        if r.object_type == "domain" and r.relation == "cell"
    }


def test_every_granted_cell_gets_a_domain_edge():
    state = derive_desired(_bundle())
    assert _domain_cell_edges(state) == {
        ("SUSTAINMENT", "DATA_ENGINEER:SUSTAINMENT"),
        ("SUSTAINMENT", "ARCHITECT:SUSTAINMENT"),
        ("MAINTENANCE", "ARCHITECT:MAINTENANCE"),
    }


def test_edge_shape_is_the_manifest_contract():
    """The relation must match the manifest's `domain: relations: cell:
    cell` declaration exactly — subject is the CELL object, not a user
    or group. A shape drift here would seed relations the can_view walk
    never traverses (silently dead edge)."""
    state = derive_desired(_bundle())
    edge = next(
        r for r in state.relations
        if r.object_type == "domain" and r.relation == "cell"
        and r.object_id == "MAINTENANCE"
    )
    assert edge == DirRelation(
        object_type="domain",
        object_id="MAINTENANCE",
        relation="cell",
        subject_type="cell",
        subject_id="ARCHITECT:MAINTENANCE",
        subject_relation="",
    )


def test_ungranted_cell_has_no_edge_and_revocation_drops_it():
    """prove-the-negative twice over: a (persona, domain) combination no
    group grants must produce NO edge (an edge without a grant would be
    a phantom domain-view path), and removing the LAST grant for a cell
    drops the edge from desired state — which is what makes the diff
    prune it (prune=revoke on the walkable path)."""
    # DATA_ENGINEER:MAINTENANCE is never granted → no edge.
    state = derive_desired(_bundle())
    assert ("MAINTENANCE", "DATA_ENGINEER:MAINTENANCE") not in _domain_cell_edges(state)

    # Revoke architects' MAINTENANCE grant → its edge leaves desired.
    revoked = _bundle(groups={
        "data-engineers": {"grants": [
            {"persona": "DATA_ENGINEER", "domain": "SUSTAINMENT"},
        ]},
        "architects": {"grants": [
            {"persona": "ARCHITECT", "domain": "SUSTAINMENT"},
        ]},
    })
    assert _domain_cell_edges(derive_desired(revoked)) == {
        ("SUSTAINMENT", "DATA_ENGINEER:SUSTAINMENT"),
        ("SUSTAINMENT", "ARCHITECT:SUSTAINMENT"),
    }


def test_multi_group_grant_survives_single_revocation():
    """Set semantics: two groups granting the SAME cell yield one edge,
    and it must persist while EITHER grant remains."""
    both = _bundle(groups={
        "data-engineers": {"grants": [
            {"persona": "DATA_ENGINEER", "domain": "SUSTAINMENT"},
        ]},
        "architects": {"grants": [
            {"persona": "DATA_ENGINEER", "domain": "SUSTAINMENT"},  # same cell
        ]},
    })
    assert _domain_cell_edges(derive_desired(both)) == {
        ("SUSTAINMENT", "DATA_ENGINEER:SUSTAINMENT"),
    }


def test_prune_scope_covers_the_new_edge():
    """The (domain, cell) pair must be in the sync's managed relations
    or revocation never propagates: the diff would only ever ADD edges,
    and a revoked cell would keep granting domain-view through the
    walk. Pinned here so a refactor can't silently drop it."""
    from topaz_sync import MANAGED_RELATIONS

    assert ("domain", "cell") in MANAGED_RELATIONS


def test_derive_entitled_domains_is_the_readback_allow_set():
    pairs = derive_entitled_domains(_bundle())
    assert pairs == {
        ("E12345", "SUSTAINMENT"),
        ("E67890", "SUSTAINMENT"),
        ("E67890", "MAINTENANCE"),
    }


def test_derive_entitled_domains_empty_bundle():
    empty = PolicyBundle(personas=[], domains=[], groups={}, users=[])
    assert derive_entitled_domains(empty) == set()
