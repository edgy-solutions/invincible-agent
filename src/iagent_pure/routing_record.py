"""THE ROUTING RECORD — one builder, two execution shapes.

A question can be answered by a Dagster run or, when the ask already settled subject, verb
and slots, by the direct path in the gateway. Those are two ROUTES to the same answer, and
the rule that keeps them from drifting is: they may take different routes to the same
components, they may not have their own copies of them.

Everything else on the spine was already shared — the eligibility verifier, the artifact
writer, the engine endpoint, the projector. THIS was not. Each side built its own label→value
mapping and a test asserted the two agreed, which is a copy with a seal on it. That seal
found three fields missing from the direct path on the day it was written (`output_uri`,
`sub_query`, and `route_status` on the graph trace — the key `_primary_routing_mat` selects
by), which is exactly the failure the arrangement guarantees eventually: a field added to one
emitter and not the other is invisible to every test that exercises one route at a time.

So there is one builder now, and the seal that diffed them is replaced by a seal that both
call it.

PURE, AND THEREFORE HERE. It returns plain Python values — no Dagster `MetadataValue`, no
materialization envelope. Each side wraps the same content in its own transport:

    supervisor      MetadataValue by type -> AssetMaterialization -> Dagster GraphQL
    direct path     direct_dispatch.materialization() -> the same entry shape

Those two transports converge again at the gateway's `_metadata_dict`, which flattens
`text` / `jsonString` / `floatValue` / `intValue` / `boolValue` back to one label→value dict.
That convergence is what makes wrapping a detail and the CONTENT the thing worth sharing.

EMPTY STRING, NEVER None, FOR AN ABSENT TEXT FIELD. The two sides used to disagree here in a
way no label comparison could see: the run emitted `subject_instance_id: ""` and the direct
path omitted the label entirely, because its envelope drops None. Both project to falsy, so
nothing broke — but "the label is present and empty" and "the label was never emitted" are
different states, and a consumer that learns to distinguish them would find the fast path
lying. One builder, one convention, no exception to carve into a test.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

__all__ = ["routing_record", "graph_trace_record", "ROUTING_LABELS", "GRAPH_TRACE_LABELS"]


def _provider_from_endpoint(predicate: Dict[str, Any]) -> str:
    """A display name derived from the endpoint host, when no provider is registered."""
    endpoint = str(predicate.get("endpoint") or "")
    if "//" not in endpoint:
        return ""
    host = endpoint.split("//", 1)[1].split("/", 1)[0].split(":", 1)[0]
    return host.split(".", 1)[0]


def routing_record(
    *,
    status: str,
    subject_uri: str,
    subject_confidence: float,
    subject_instance_id: str,
    subject_instance_label: str,
    verb_iri: str,
    verb_confidence: float,
    classify_called: bool,
    candidate_count: int,
    subject_candidates: Optional[List[Any]],
    fallback_reason: str,
    eligibility_excluded: Optional[List[Any]],
    acting_persona: str,
    acting_domains: Optional[List[str]],
    sub_query: str,
    predicate: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The `subtask_routing_decision` content, whichever route produced it.

    `predicate` is None only when there was nothing to dispatch to — an unrouted turn. Its
    four fields are then absent rather than blank, which is the run's existing behaviour and
    the honest one: no handler is not the same as a handler with no name.
    """
    record: Dict[str, Any] = {
        "route_status": status,
        "subject_uri": subject_uri or "UNKNOWN",
        "subject_confidence": float(subject_confidence or 0.0),
        "subject_instance_id": subject_instance_id or "",
        "subject_instance_label": subject_instance_label or "",
        "verb_iri": verb_iri or "UNKNOWN",
        "verb_confidence": float(verb_confidence or 0.0),
        # READ, NOT RE-DERIVED. Only the router knows whether it called the classifier.
        # Deriving it here once reported FALSE for a classifier that ran and returned
        # UNKNOWN — the layer that knows is the layer that records.
        "classify_called": bool(classify_called),
        "candidate_count": int(candidate_count or 0),
        "subject_candidates": json.dumps(subject_candidates or []),
        "fallback_reason": str(fallback_reason or ""),
        # WHAT EACH GATE REMOVED OR FLAGGED. Carried beside `subject_candidates` (what
        # survived) because the difference between them is the difference between "nothing
        # fit" and "something fit and was excluded", and only the second is a cue to
        # rephrase.
        "eligibility_excluded": json.dumps(eligibility_excluded or []),
        "acting_persona": str(acting_persona or ""),
        "acting_domains": ",".join(acting_domains or []),
        "sub_query": sub_query or "",
    }
    if predicate:
        # WHO ANSWERED, with the endpoint host as a last resort. `handler_provider`
        # arrives empty for engines that register no provider and the HUD then renders
        # "Unknown engine" beside a perfectly good endpoint — a lookup whose miss
        # becomes text. Deriving the host is not a fix for the registration gap; it is
        # a better empty than the word "Unknown". IT LIVES HERE so both routes read the
        # same name for the same engine; on one side only, it would be a divergence
        # that shows up as the fast path and the slow path disagreeing about WHO
        # answered the identical question.
        record["handler_provider"] = (
            str(predicate.get("provider") or "") or _provider_from_endpoint(predicate)
        )
        record["handler_endpoint"] = str(predicate.get("endpoint") or "")
        record["owner_persona"] = str(predicate.get("owner_persona") or "")
        record["output_uri"] = str(predicate.get("output_uri") or "")
    return record


def graph_trace_record(
    *,
    status: str,
    subject_uri: str,
    picked_verb_iri: str,
    compatible_verbs: Optional[List[Any]],
) -> Dict[str, Any]:
    """The `subtask_graph_trace` content.

    `route_status` is NOT a duplicate of the routing record's. It is the key
    `_primary_graph_trace_mat` selects by, and without it the gateway can only take the
    FIRST emitted trace — a third rule over a choice that already has two, and the reason a
    trace once claimed one subject while a different engine answered.
    """
    return {
        "route_status": status,
        "subject_uri": subject_uri,
        "picked_verb_iri": picked_verb_iri or "",
        "compatible_verbs": json.dumps(compatible_verbs or []),
    }


#: The labels each record carries, derived from the builders themselves at import so a seal
#: never transcribes them. `predicate=None` is deliberate for ROUTING_LABELS: it names the
#: fields present on EVERY routing record, and the four handler fields are conditional.
ROUTING_LABELS = frozenset(
    routing_record(
        status="", subject_uri="", subject_confidence=0.0, subject_instance_id="",
        subject_instance_label="", verb_iri="", verb_confidence=0.0, classify_called=False,
        candidate_count=0, subject_candidates=None, fallback_reason="",
        eligibility_excluded=None, acting_persona="", acting_domains=None, sub_query="",
    )
)
GRAPH_TRACE_LABELS = frozenset(
    graph_trace_record(
        status="", subject_uri="", picked_verb_iri="", compatible_verbs=None,
    )
)
