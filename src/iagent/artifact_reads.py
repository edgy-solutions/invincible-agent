"""The gateway's implementation of the SDK's `MeshArtifacts` Protocol (iagent-mesh 0.9.9).

GET /artifacts/{id} is its first caller. Entitlement is an obligation on THIS implementation
(the Protocol carries no mechanism): a read the initiator is not entitled to comes back
`outcome="empty"`, byte-for-byte what an absent id comes back as -- the existence side channel
the Protocol exists to close.

ENTITLED = the OWNER (the artifact is PRODUCED_FOR the initiator), OR the SEEDING DELEGATE.
ADR-0041 §8.1: a delegate reads what its workflows produced. ADR-0047 §5.1 as amended
(RULED 2026-10-08): a `svc:` delegate is a recipient only as the seeding delegate. The
confused-deputy reason does not apply, because the read is scoped to what that delegate's own
workflows produced (`seeded_by`), not to what the service can reach for any caller.

This module does not import gateway: the delegate map arrives as a callable.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from iagent_mesh import Initiator
from iagent_mesh.interfaces import MeshResult

# DEPARTURE: the Protocol says `kind` is a registered ContentKindRegistration.kind; AnswerArtifact
# is an OUTPUT, not an ingested kind, and no row registers it -- routed to
# iagent-mesh-sdk/lane/ca 2026-10-08.
ANSWER_ARTIFACT_KIND = "answer-artifact"

_RETURN = """
RETURN a.id                    AS id,
       a.status                AS status,
       a.summary               AS summary,
       a.question_text         AS question_text,
       a.valid_as_of           AS valid_as_of,
       a.duration_ms           AS duration_ms,
       a.resolved_intent       AS resolved_intent,
       a.routing_inline        AS routing_inline,
       parent.id               AS derived_from,
       owner IS NOT NULL       AS is_owner,
       a.origin_owner_domain   AS origin_owner_domain,
       a.origin_program        AS origin_program,
       a.seeded_by             AS seeded_by
"""

ARTIFACT_BY_ID_CYPHER = """
MATCH (a:AnswerArtifact {id: $artifact_id})
OPTIONAL MATCH (a)-[:PRODUCED_FOR]->(owner:Actor {actor_id: $user_id})
OPTIONAL MATCH (a)-[:DERIVED_FROM]->(parent:AnswerArtifact)
""" + _RETURN

# Every AnswerArtifact the subject owns or seeded. The seeding arm is added in Python only when
# the subject is a declared delegate, so a person whose id equals some `seeded_by` matches nothing.
ARTIFACTS_VISIBLE_CYPHER = """
MATCH (a:AnswerArtifact)
OPTIONAL MATCH (a)-[:PRODUCED_FOR]->(owner:Actor {actor_id: $user_id})
OPTIONAL MATCH (a)-[:DERIVED_FROM]->(parent:AnswerArtifact)
WITH a, owner, parent
WHERE owner IS NOT NULL OR ($is_delegate AND a.seeded_by = $authz_id)
""" + _RETURN


def _as_dict(rec: Any) -> dict:
    return rec.data() if hasattr(rec, "data") else dict(rec)


def is_entitled(rec: Any, *, authz_id: str, delegates: dict) -> bool:
    """Owner, or the seeding delegate. A planted `seeded_by` equal to a person's id admits
    nobody: the caller must itself be a key of the delegate map."""
    if rec.get("is_owner"):
        return True
    seeded_by = rec.get("seeded_by")
    return bool(seeded_by) and seeded_by == authz_id and authz_id in delegates


class GatewayArtifacts:
    """`MeshArtifacts` over the gateway's neo4j driver."""

    def __init__(self, driver: Any, delegate_principals: Callable[[], dict]):
        self._driver = driver
        self._delegates = delegate_principals

    @staticmethod
    def _require_kind(kind: str) -> None:
        if kind != ANSWER_ARTIFACT_KIND:
            raise ValueError(
                f"unsupported artifact kind {kind!r}; only {ANSWER_ARTIFACT_KIND!r} is held here"
            )

    def read_row(self, artifact_id: str, user_id: str) -> Optional[Any]:
        """The raw record, UNGATED -- for the route's origin-entitlement fallback only. Not part
        of the Protocol; never return its result to a caller without a gate."""
        with self._driver.session() as session:
            return session.run(
                ARTIFACT_BY_ID_CYPHER, artifact_id=artifact_id, user_id=user_id
            ).single()

    def get(self, initiator: Initiator, *, kind: str, id: str,
            authz_id: Optional[str] = None) -> MeshResult:
        """`authz_id` is an extension beyond the Protocol: PRODUCED_FOR is keyed on the JWT
        `sub` (`initiator.subject`) while the delegate map is keyed on authz_id, and the two
        differ. Omitted, the subject stands for both."""
        self._require_kind(kind)
        rec = self.read_row(id, initiator.subject)
        if rec is None or not is_entitled(
            rec, authz_id=authz_id or initiator.subject, delegates=self._delegates()
        ):
            return MeshResult(outcome="empty")
        return MeshResult(outcome="answered", rows=(_as_dict(rec),))

    def list_by_kind(self, initiator: Initiator, *, kind: str,
                     authz_id: Optional[str] = None) -> MeshResult:
        self._require_kind(kind)
        who = authz_id or initiator.subject
        with self._driver.session() as session:
            recs = list(session.run(
                ARTIFACTS_VISIBLE_CYPHER, user_id=initiator.subject, authz_id=who,
                is_delegate=who in self._delegates(),
            ))
        if not recs:
            return MeshResult(outcome="empty")
        return MeshResult(outcome="answered", rows=tuple(_as_dict(r) for r in recs))
