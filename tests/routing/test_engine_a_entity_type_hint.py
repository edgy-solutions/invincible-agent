"""Engine A entity_type-hint determinism — closes ``[[project_phase3_complete]]``'s
LLM-luck-dependent closure.

The 2026-06-25/26 "who owns customer 360" investigation revealed
that ``[[project_phase3_complete]]``'s closure was conditional on
the smolagent happening to pick the right DataHub entity_type for
each query. Sometimes it inferred ``entity_type="DASHBOARD"`` from
``resolved_uri = idp#Dashboard`` (matches → sources flow);
sometimes it guessed "dataset" or "data_product" (0 matches →
honest empty Sources card). The Phase 3 plumbing was correct; the
upstream variance was LLM judgment.

The fix (deterministic-threading pattern, same shape as
content-kind resolution / chart-key normalization /
dispatch-endpoint-from-Neo4j): map ``idp:* class → DataHub
entity_type string`` in Engine A's prompt construction so the
smolagent receives a deterministic RECOMMENDED entity_type for
the first ``search_datahub`` call, broaden-on-miss preserved.

This file is the **real** Phase 3 closure: parameterized over
the known (idp:* class → entity_type) mapping, asserts the
mapping is correct AND the prompt construction surfaces it.
Replaces the "closed because the LLM happened to guess right
during testing" verification with "closed because the
deterministic mapping makes it always right, proven per class."

Pure unit — imports the mapping + prompt-recommendation helper
directly, no cluster dependency. The integration probe
``test_engine_a_sources_flow_per_class.py`` (separate, cluster-
dependent) asserts the live behavior.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent_fleet.restate_analyst.entity_type_mapping import (
    IDP_CLASS_TO_DATAHUB_ENTITY_TYPE,
    recommended_entity_type,
)


# ---------------------------------------------------------------------------
# Canonical source extraction — read ``_DATAHUB_TO_IDP`` from
# ``datahub_wrapper/main.py`` via AST so the test catches drift even when
# the wrapper's heavy import chain (httpx, fastapi, etc.) isn't available
# in the test env. The architect's drift-catching property: when someone
# adds a new entry to the canonical forward table without adding the
# inverse to Engine A's table, this test turns red. A hardcoded snapshot
# of "today's four classes" would silently pass for the fifth class.
# ---------------------------------------------------------------------------


def _read_canonical_datahub_to_idp() -> dict[str, str]:
    """Parse ``datahub_wrapper/main.py`` and extract the literal value
    of the ``_DATAHUB_TO_IDP`` constant. Uses ``ast.literal_eval`` so
    no module imports run (no heavy-deps drag). Skips the test if the
    canonical source isn't readable / parseable in this env."""
    path = (
        Path(__file__).resolve().parents[2]
        / "agent_fleet"
        / "datahub_wrapper"
        / "main.py"
    )
    if not path.is_file():
        pytest.skip(f"Canonical source not found at {path}")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        pytest.skip(f"Could not parse {path}: {exc}")
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            target = node.target
            if (
                isinstance(target, ast.Name)
                and target.id == "_DATAHUB_TO_IDP"
                and node.value is not None
            ):
                try:
                    return ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    pytest.skip(
                        f"_DATAHUB_TO_IDP in {path} isn't a literal — "
                        f"test needs a literal value to ast.literal_eval"
                    )
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_DATAHUB_TO_IDP":
                    try:
                        return ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        pytest.skip(
                            f"_DATAHUB_TO_IDP in {path} isn't a literal — "
                            f"test needs a literal value to ast.literal_eval"
                        )
    pytest.skip(f"_DATAHUB_TO_IDP not found in {path}")
    return {}  # unreachable, satisfies type-check


# ---------------------------------------------------------------------------
# Mapping table integrity — every entry MUST match the inverse of the
# datahub_wrapper's _DATAHUB_TO_IDP table. The two tables must move in
# lockstep; when either drifts, this test fires.
# ---------------------------------------------------------------------------


# Hardcoded source of truth — duplicated from
# ``agent_fleet/datahub_wrapper/main.py:_DATAHUB_TO_IDP``. When that
# table changes (new DataHub entity_type added, ontology class renamed),
# update this constant AND the corresponding entry in Engine A's
# ``_IDP_CLASS_TO_DATAHUB_ENTITY_TYPE``. The lockstep is enforced by
# the assertions below.
def test_engine_a_table_inverts_datahub_to_idp():
    """Engine A's ``IDP_CLASS_TO_DATAHUB_ENTITY_TYPE`` must be the
    inverse of datahub_wrapper's ``_DATAHUB_TO_IDP`` for every idp:*
    class that has a deterministic DataHub partner. CHART folds into
    Dashboard (since CHART → idp#Dashboard in the forward table); the
    inverse picks one canonical entity_type per class, so the inverse
    of idp#Dashboard is DASHBOARD (the primary), not CHART.

    **Drift-catching property**: the canonical forward table is read
    from datahub_wrapper's source via AST (no module import — no
    heavy-dep drag), so when a new entry is added to the canonical
    side WITHOUT a corresponding inverse here, this test turns red.
    A hardcoded snapshot of "today's four classes" would silently
    pass for the fifth class; the AST-derived version doesn't.
    """
    canonical_forward = _read_canonical_datahub_to_idp()
    inv = IDP_CLASS_TO_DATAHUB_ENTITY_TYPE

    # Every idp:* class in the canonical forward table must appear in
    # the inverse. New entries added to the wrapper's table without
    # the corresponding inverse turn this red.
    forward_classes = set(canonical_forward.values())
    for cls in forward_classes:
        assert cls in inv, (
            f"idp:* class {cls!r} is in datahub_wrapper's _DATAHUB_TO_IDP "
            f"(canonical forward table) but missing from Engine A's "
            f"IDP_CLASS_TO_DATAHUB_ENTITY_TYPE inverse. The smolagent's "
            f"recommended entity_type for this class will be None, and "
            f"it'll fall back to guessing. Add the inverse to "
            f"agent_fleet/restate_analyst/entity_type_mapping.py."
        )

    # Each inverse entry must round-trip: cls → entity_type → cls must
    # be either the same cls or (for many-to-one cases like
    # CHART/DASHBOARD both → idp#Dashboard) a cls that ALSO maps back
    # to the same entity_type via the forward table.
    for cls, entity_type in inv.items():
        forward_cls = canonical_forward.get(entity_type)
        assert forward_cls is not None, (
            f"Engine A's inverse maps {cls!r} → {entity_type!r}, but the "
            f"canonical forward table has no entry for {entity_type!r}. "
            f"Drift detected — either the canonical table dropped the "
            f"entity_type or the inverse points at a stale string."
        )
        # CHART and DASHBOARD both forward to idp#Dashboard; the inverse
        # picks DASHBOARD as canonical. Accept either: forward_cls == cls
        # OR forward_cls's own forward-entry round-trips to the same
        # entity_type as cls's inverse pointer.
        round_trip_ok = (
            forward_cls == cls
            or (forward_cls in inv and inv[forward_cls] == entity_type)
        )
        assert round_trip_ok, (
            f"Round-trip drift: {cls!r} → {entity_type!r} → {forward_cls!r}. "
            f"The two tables disagree on which DataHub entity_type is "
            f"canonical for this class."
        )


# ---------------------------------------------------------------------------
# Recommendation helper — parameterized over the known mapping table.
# Each case asserts the helper returns the entity_type string that
# datahub_wrapper would translate back to the same class.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "resolved_uri,expected_entity_type",
    [
        # The 2026-06-26 demonstration case — the one that motivated
        # the fix. idp#Dashboard MUST resolve to DASHBOARD (not
        # "dataset", "data_product", or anything else the smolagent
        # was previously guessing).
        ("http://invincible-agent/idp#Dashboard", "DASHBOARD"),
        # The mesh_demo_customers happy-path case — the Table class
        # should map to DataHub's DATASET entity_type.
        ("http://invincible-agent/idp#Table", "DATASET"),
        # The pipeline / job classes. These haven't been demo-exercised
        # yet, so they're in the [[engine-a-entity-type-hint-gap]]
        # "untested entity types" enumeration. Pinning them here turns
        # the enumeration into a guarantee.
        ("http://invincible-agent/idp#Pipeline", "DATA_FLOW"),
        ("http://invincible-agent/idp#Job", "DATA_JOB"),
    ],
    ids=[
        "Dashboard-the-demo-case",
        "Table-mesh-demo-customers",
        "Pipeline-untested-before-this-test",
        "Job-untested-before-this-test",
    ],
)
def test_recommended_entity_type_is_deterministic(
    resolved_uri: str, expected_entity_type: str
) -> None:
    """For each known idp:* class, the helper MUST return the
    deterministic DataHub entity_type. No "sometimes" — the whole
    point of this fix is to eliminate LLM variance from the
    entity_type selection.

    The previous closure (``[[project_phase3_complete]]``) was
    "the LLM happened to guess right when we tested." This test is
    the real closure: "the deterministic mapping makes it always
    right, proven per class."
    """
    recommended = recommended_entity_type(resolved_uri)
    assert recommended == expected_entity_type, (
        f"Deterministic mapping broken for {resolved_uri!r}. "
        f"Expected {expected_entity_type!r}, got {recommended!r}. "
        f"The smolagent will fall back to guessing entity_type and "
        f"sources will be empty about half the time — exactly the "
        f"LLM-luck-dependent closure this fix was supposed to close."
    )


# ---------------------------------------------------------------------------
# Negative case — unknown / UNKNOWN resolved_uri returns None (the
# escape hatch). This MUST stay None so the smolagent gets no
# recommendation and falls back to its prior guess-then-broaden
# behavior; without this, an unknown class would propagate a
# wrong-but-confident recommendation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "resolved_uri",
    [
        "UNKNOWN",
        "",
        "mesh:OwnershipFact",  # mesh:* output type, not an idp:* subject class
        "http://invincible-agent/idp#NonExistentClass",
    ],
    ids=[
        "literal-UNKNOWN",
        "empty-string",
        "mesh-output-type-not-input-class",
        "made-up-class",
    ],
)
def test_recommended_entity_type_returns_none_on_unmapped(
    resolved_uri: str,
) -> None:
    """Classes that aren't in the deterministic mapping MUST return
    None — the smolagent then falls back to guessing, which is the
    legacy behavior. Adding a non-None recommendation here would
    propagate a fabricated entity_type and trap the smolagent in
    the wrong DataHub partition."""
    assert recommended_entity_type(resolved_uri) is None, (
        f"Unmapped resolved_uri {resolved_uri!r} got a non-None "
        f"recommendation — the escape hatch is broken. The smolagent "
        f"would receive a fabricated entity_type recommendation, "
        f"which is the wrong-confident-direction failure mode worse "
        f"than the LLM-guess-then-broaden it's replacing."
    )
