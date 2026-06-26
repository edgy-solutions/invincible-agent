"""Deterministic idp:* class → DataHub entity_type mapping for Engine A.

Extracted to a dep-free module so pure-unit tests can pin the
mapping without dragging Engine A's heavy import chain (BAML
client, restate-sdk, smolagents, etc.). ``main.py`` imports from
here.

Why the split: the mapping table and the recommendation helper
are the contract that
``tests/routing/test_engine_a_entity_type_hint.py``
pins as the real Phase 3 closure (parameterized per class, not
"the LLM happened to guess right when we tested" — which was the
prior closure's [[verification-must-fail]] anti-pattern). The
contract is pure (URI in → string out); putting it next to
BAML/smolagents/restate in ``main.py`` would make unit tests
collect-error on transitive imports. Same shape as Engine F's
``capabilities.py`` / ``chart_normalizer.py`` extraction.

When the inverse forward table in
``datahub_wrapper/main.py:_DATAHUB_TO_IDP`` changes, this table
must move in lockstep. The test asserts that lockstep.
"""

from __future__ import annotations

from typing import Dict, Optional


# Inverse of ``agent_fleet/datahub_wrapper/main.py:_DATAHUB_TO_IDP``.
#
# When DataHub's entity_type taxonomy or the idp ontology gains a
# new entry, BOTH this table and the forward one must be updated
# together. The shape itself is canonical and stable: each idp:*
# class maps to exactly one DataHub entity_type. CHART folds into
# DASHBOARD (since CHART → idp#Dashboard in the forward direction);
# the inverse picks the primary entity_type per class.
#
# Why this is the right pattern: the resolved class IS known at
# routing time (engine_o's phone book resolves named instances
# with high confidence; the supervisor's subtask_routing_decision
# materialization carries it). Translating to DataHub's entity_type
# string is a deterministic table lookup, not a judgment call.
# Engine A's smolagent historically had to INFER the entity_type
# from the resolved_uri string ("idp#Dashboard means I should pass
# DASHBOARD") and got it wrong about half the time, producing
# honest-but-frustrating empty Sources cards. This module
# eliminates that variance — the recommendation is deterministic;
# the smolagent's only LLM judgment in the entity_type space is
# the broaden-on-miss escape hatch (legitimate, since the routing
# class could be wrong for edge cases).
IDP_CLASS_TO_DATAHUB_ENTITY_TYPE: Dict[str, str] = {
    "http://invincible-agent/idp#Table":     "DATASET",
    "http://invincible-agent/idp#Dashboard": "DASHBOARD",
    "http://invincible-agent/idp#Pipeline":  "DATA_FLOW",
    "http://invincible-agent/idp#Job":       "DATA_JOB",
    # ``idp#Column`` deliberately omitted — columns live inside a
    # dataset's schemaMetadata.fields and don't have their own
    # entity_type top-level. The smolagent's first search for a
    # column-shaped identifier still wants entity_type="DATASET"
    # so the dataset's schema comes back with the column embedded.
}


def recommended_entity_type(resolved_uri: str) -> Optional[str]:
    """Map an idp:* class URI to the DataHub entity_type string
    that the smolagent should pass as the ``entity_type`` argument
    to ``search_datahub``.

    Returns ``None`` when the class isn't in the table (router
    resolved to UNKNOWN, a mesh:* class that doesn't correspond
    to a DataHub entity, or a new idp:* class added without the
    table being updated). The ``None`` case is non-fatal — the
    smolagent gets no recommendation and falls back to its prior
    guess-then-broaden behavior, which is the legacy behavior.
    Returning a non-None fabricated guess for an unknown class
    would propagate a wrong-confident recommendation, which is
    worse than the variance it would replace.
    """
    if not resolved_uri:
        return None
    return IDP_CLASS_TO_DATAHUB_ENTITY_TYPE.get(resolved_uri)
