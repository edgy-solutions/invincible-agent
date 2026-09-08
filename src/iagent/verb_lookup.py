"""THE ELIGIBILITY VERIFIER, callable from either side of the Dagster boundary.

`_find_compatible_verbs` lived in `dynamic_supervisor` and took a Dagster `context` — used
for nothing but a log line describing the error it already returns. That signature is the only
reason the BFF could not call it, and the BFF is about to need it: a pre-resolved re-ask
dispatches directly, without a run, and the verifier is the one thing that must NOT be skipped
on that path.

WHY IT MUST NOT BE SKIPPED. It is the invalidation. Entitlements are revoked, engines retired,
the TTL re-primed — a verb remembered from an earlier ask is a cache, and this is the only
thing that expires it. It is also a graph read rather than a model call, so it costs
milliseconds, and it is authoritative for dispatch coordinates regardless.

NOT PURE, DELIBERATELY, AND THEREFORE NOT IN `iagent_pure`. It makes an HTTP call. The two
rules it feeds — `filter_verbs_by_arity` and `predicate_from_compat_record` — are pure and
live in `iagent_pure.verb_eligibility`; the split is what keeps those testable without a
network and this one honest about needing one.

Returns ``(verbs, error_or_None)``:

    ([], None)        the subject is unknown or has no compatible verb — a real, empty answer
    ([...], None)     the compat-walk succeeded
    (None, "...")     the check could not be made. NOT the same as "nothing is compatible",
                      and callers must not collapse them: one means route to the generalist,
                      the other means the substrate did not answer.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import requests

__all__ = ["find_compatible_verbs"]

#: ADR-0018 addendum — how far up the subClassOf chain a verb's `input_uri` may sit and still
#: cover this subject. Shared by both callers so a re-ask and a run agree on eligibility;
#: diverging here would make the same question routable from one path and not the other.
DEFAULT_MAX_HOPS = 5

#: A graph read, not a model call. The old value was 10s inside a Dagster op where the whole
#: run already cost tens of seconds; on the direct path it sits inside a request a person is
#: waiting on, so a hung ontology service must fail fast rather than hold the turn open.
DEFAULT_TIMEOUT_S = 10.0


def find_compatible_verbs(
    subject_uri: str,
    entitled_domains: List[str],
    *,
    ontology_url: str,
    max_hops: int = DEFAULT_MAX_HOPS,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Ask Engine O which predicates can operate on this subject, per Neo4j.

    Empty list = no verb whose registered ``input_uri`` covers this subject's class chain.
    ``error`` is a non-fatal message; the caller decides what a failed check means, because
    the two callers genuinely differ — the supervisor falls through to unconstrained
    classification, the direct path falls back to the full run.
    """
    if not subject_uri or subject_uri == "UNKNOWN":
        return [], None
    try:
        resp = requests.post(
            f"{ontology_url}/find_compatible_verbs",
            json={
                "subject_uri": subject_uri,
                "max_hops": max_hops,
                "entitled_domains": list(entitled_domains or []),
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return list(resp.json().get("verbs") or []), None
    except Exception as exc:  # noqa: BLE001 -- the caller decides; this never raises
        return None, str(exc)
