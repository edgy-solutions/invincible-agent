"""What `engine-docs` needs from the mesh, stated as a contract before the client exists.

WRITTEN AS THE FIRST CONSUMER, ON PURPOSE. `MeshGraph` is not defined yet — verified 2026-09-13:
no occurrence anywhere in this repo, and absent from `iagent-mesh` at the pinned v0.8.1. Being the
client's first consumer means these operations are an INPUT to its design rather than a guess at
it, so they are written down here where the eo lane can read them, instead of being discovered
when the two halves meet.

**THIS FILE HOLDS NO IMPLEMENTATION AND IMPORTS NO DRIVER**, which is the property the engine is
being built to demonstrate: `engine-docs` is meant to be the first engine born without one. A
temporary Neo4j read placed here "just until MeshGraph lands" would make it the first engine born
WITH a driver and a plan to remove it, and that plan is the thing that never happens.

ONE NAMED OPERATION, AND THE SECOND WAS REMOVED RATHER THAN IMPLEMENTED. This file first declared
`page_by_iri` as well — "the addressed path", for something that already holds a page's identity.
Then the engine was built and **never reached for it**. Implementing it would have been
implementing against this docstring, which is exactly what the first-consumer rule exists to
prevent: the operations are supposed to come from calls, and an operation with zero callers is a
name with no working consumer.

**RULED 2026-09-16: declared-but-uncalled comes out.** It is the same shape as a write path nobody
writes through, and the conformance suite should refuse an operation with no callers the way it
refuses an empty operation list. If a caller appears, it goes back in — sourced from that caller.

**A SUBJECT WITH NO PAGE IS AN ANSWER**, not an error. `page_for_subject` returns an empty list,
and the verb abstains with the subject named. An engine that raised here would turn "nothing
explains this yet" — the honest and common state of a young corpus — into a failure, and the
corpus's whole discipline is that a gap must be visible rather than fatal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PageRow:
    """One `mesh:DocPage`, as the graph holds it. THE BODY IS NOT HERE AND THAT IS THE DESIGN.

    The graph is the index and the docs are the leaves: the row carries a LOCATOR and the SHA of
    the bytes it was indexed from. Whoever renders reads the body from `source` and asserts
    `body_sha` before showing it to anyone.
    """

    iri: str
    title: str
    doc_kind: str
    audience_hint: str
    source: str
    body_sha: str
    explains: tuple[str, ...] = field(default=())


@runtime_checkable
class DocPageReader(Protocol):
    """The mesh operations `engine-docs` calls. Implemented by `MeshGraph`, not by this engine."""

    def page_for_subject(self, subject_iri: str) -> list[PageRow]:
        """Pages whose `mesh:explains` includes `subject_iri`, ORDERED. Empty is an answer.

        THE ORDER IS PART OF THE CONTRACT, because two pages explaining one subject is legal and
        will happen, and a consumer that takes the first row of an unordered list is choosing
        silently. Declared precedence:

          1. AUDIENCE MATCH to the caller's persona.  **DECLARED AND NOT IMPLEMENTABLE TODAY** —
             see below. It is first because a how-to written for an architect is the wrong answer
             for a data engineer even when both pages are correct.
          2. MOST RECENTLY INGESTED BODY.  The corpus is prime-wiped and re-landed, so this is a
             property of the ingest rather than of an author's timestamp.
          3. STILL TIED?  The reader returns them all and **the engine renders every one**. A tie
             broken silently is the `banana 4` failure applied to documents: a plausible winner
             chosen on no evidence, indistinguishable from a confident answer.

        **KEY 1 IS BLOCKED AND THE CAUSE IS MEASURED, NOT ASSUMED.** Ordering by audience needs the
        caller's persona, and no persona crosses the engine boundary: the only originator identity
        an engine receives is `X-Originator-Email` and `X-Originator-Sub` (derived — those are the
        only two spellings anywhere in `agent_fleet/` or `src/`). The persona exists upstream on
        the caller record and does not travel.

        SO THERE IS NO `audience` PARAMETER, AND ITS ABSENCE IS THE SAME RULING AS `page_by_iri`'s
        removal. Adding one that every caller passes `None` to would be a parameter with no
        working consumer — declared-but-unsupplied instead of declared-but-uncalled, the same
        defect wearing the other hat.

        **RULED 2026-09-16, AND IT HAS AN OWNER: the gateway threads the caller's persona on the
        dispatch**, the way it already passes a `run_id` — a fact the gateway holds, the engine
        needs, and the wire never carried. Lane 1's change, filed by name, and this parameter
        appears the moment it lands.

        ONE CORRECTION TO THE PRECEDENT, checked rather than repeated: `run_id` travels as a
        **body field** on the dispatch (`src/iagent/gateway.py:2302`), not as a header. The only
        `X-` originator spellings in the tree are still `Email` and `Sub`. That makes the change
        smaller than a new header would be, and it is the difference between citing a pattern and
        citing a mechanism.

        UNTIL IT LANDS the precedence is key 2 then key 3 — most recently ingested body, then the
        whole list. Key 1 stays declared here so the eo lane implements TOWARD it rather than
        around it: an ordering built without a slot for audience is one that has to be rewritten
        rather than extended.
        """


@runtime_checkable
class BodyStore(Protocol):
    """Reading the page's bytes back from the locator the row carries.

    **RAISED RATHER THAN ASSUMED: THE ONE-CLIENT TABLE HAS NO ENTRY FOR OBJECT BYTES.** `MeshData`
    covers DataHub datasets read by URN; `MeshGraph`, `MeshOntology`, `MeshVectors` and `MeshTrace`
    cover the other four stores. A page body is none of those — it is an object in a bucket, and
    `engine-docs` is the first engine that needs one. So either object reads are a sixth named
    operation on the one client, or they sit outside the ADR's boundary and an engine may hold an
    S3 client for them.

    That question is asked in the ADR rather than answered here, and the seam is drawn so the
    answer costs one adapter either way: nothing below this Protocol knows what a bucket is.
    """

    def read(self, locator: str) -> bytes:
        """The page's bytes, exactly as indexed. No decoding, no normalising — the sha is over
        these bytes, and a helpful transformation here breaks the assertion downstream."""
