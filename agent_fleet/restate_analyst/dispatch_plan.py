"""PCN/PDN dispatch — the per-item effect of a resolved disposition (PURE plan; the driver executes).

When the grouped review resolves, each ``ItemResolution`` fans out to ONE dispatch: the workflow model
consuming its own output (the ADR-0029 Case-2 thesis). Three writes, all in owned substrates:
  1. the durable ``ItemResolution`` itself (already produced by [[workflow_bulk_resolve]]);
  2. disposition STATE onto the item's graph node — ``pcn:dispositionState`` / ``pcn:dispositionRef`` /
     ``pcn:proposedByRuleset`` in the SUSTAINMENT_INSTANCES graph (DECIDED: runtime data, survives
     prime, same graph as the instances; makes "all parts in LTB" a one-hop read-union SPARQL);
  3. a per-item HumanTask keyed by (notice_fingerprint × mpn), type = the disposition, routed to the
     persona who handles it — the "another user's queue" moment.

Pure: ``plan_dispatch`` returns a ``DispatchPlan`` (the graph write + the task spec as DATA); the
Restate driver executes it (per-item VirtualObject-on-composite — the settled idempotency ruling — so
a redelivered dispatch is a no-op). ``archive`` acknowledges with no task (no human action needed).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

try:  # same lazy-import dance as the other restate_analyst cores
    from workflow_bulk_resolve import ItemResolution  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.workflow_bulk_resolve import ItemResolution

_PCN = "http://internal/sustainment/pcn#"
_INSTANCES_GRAPH = "http://internal/SUSTAINMENT_INSTANCES"  # DECIDED: runtime state lives with instances

# Which persona's queue a dispatch routes to. ``archive`` -> None (acknowledge, no task). Kept small
# and structural (the disposition already names the action); a candidate to move to data if it grows.
_DISPOSITION_QUEUE = {
    "dispatchLTB": "procurement",
    "dispatchQualification": "qualification",
    "dispatchAltSourcing": "sourcing",
    "archive": None,
}


@dataclass
class GraphStateWrite:
    """Disposition state onto the item's node, in SUSTAINMENT_INSTANCES. ``triples`` is
    ``{predicate_local: value}``; ``to_sparql`` renders the scoped INSERT the driver runs."""
    subject_iri: str
    triples: dict = field(default_factory=dict)

    def to_sparql(self) -> str:
        lines = "\n".join(
            f'    <{self.subject_iri}> <{_PCN}{p}> "{str(v)}" .' for p, v in self.triples.items()
        )
        return f"INSERT DATA {{\n  GRAPH <{_INSTANCES_GRAPH}> {{\n{lines}\n  }}\n}}"


@dataclass
class HumanTaskSpec:
    """A per-item dispatch task. ``task_key`` is the idempotency key (notice_fingerprint × mpn);
    ``audience`` is the persona queue. The driver mints the actual Restate HumanTask from this.

    RE-LINK path (rider): when ``subject_ref`` is None the subject was unresolved, so no graph-state
    write happened — but the task carries ``mpn`` + ``notice_fingerprint`` (the resolution-attempt
    provenance) so a later pass can re-resolve and stamp the state RETROACTIVELY when the subject
    becomes resolvable (phone-book growth / alias ratification). Without these, unresolved tasks are
    permanent orphans in the persona queues — the default-graph-residue pattern in task form."""
    task_key: str
    kind: str
    audience: str
    disposition: str
    subject_ref: Optional[str]
    mpn: str
    notice_fingerprint: str
    title: str
    summary: str
    needs_review: bool
    proposed_by_ruleset: Optional[str]
    subject_unresolved: bool = False   # explicit re-link marker (subject_ref is None)


@dataclass
class DispatchPlan:
    resolution: ItemResolution
    graph_write: Optional[GraphStateWrite]
    human_task: Optional[HumanTaskSpec]


def plan_dispatch(resolution: ItemResolution, *, notice_fingerprint: str, notice_id: str = "") -> DispatchPlan:
    """Plan the three-write effect for one resolved item. Idempotent on ``resolution.idempotency_key``.
    ``archive`` produces a graph state write but NO task (acknowledge). A disposition over an unresolved
    subject (``resolution.subject is None``) skips the graph write honestly — you can't stamp state on a
    node you couldn't resolve — but still records the ItemResolution + opens the task."""
    disp = resolution.disposition
    subject = resolution.subject

    graph_write: Optional[GraphStateWrite] = None
    if subject:
        triples = {
            "dispositionState": disp,
            "dispositionRef": resolution.idempotency_key,   # links back to the ItemResolution
        }
        if resolution.proposed_by_ruleset:
            triples["proposedByRuleset"] = resolution.proposed_by_ruleset
        graph_write = GraphStateWrite(subject_iri=subject, triples=triples)

    queue = _DISPOSITION_QUEUE.get(disp)
    human_task: Optional[HumanTaskSpec] = None
    if queue:  # archive (None) opens no task
        human_task = HumanTaskSpec(
            task_key=resolution.idempotency_key,
            kind="pcn_disposition",
            audience=queue,
            disposition=disp,
            subject_ref=subject,
            mpn=resolution.mpn,
            notice_fingerprint=notice_fingerprint,
            title=f"{disp}: {resolution.mpn}",
            summary=(
                f"Part {resolution.mpn} from notice {notice_id or notice_fingerprint} was dispositioned "
                f"'{disp}'"
                + (" [MPN extraction UNVERIFIED]" if resolution.needs_review else "")
                + ("" if subject else " [subject UNRESOLVED — state pending re-link]")
            ),
            needs_review=resolution.needs_review,
            proposed_by_ruleset=resolution.proposed_by_ruleset,
            subject_unresolved=subject is None,
        )

    return DispatchPlan(resolution=resolution, graph_write=graph_write, human_task=human_task)
