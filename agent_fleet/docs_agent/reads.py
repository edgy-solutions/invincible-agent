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

TWO NAMED OPERATIONS, AND THE SECOND IS NOT A CONVENIENCE. `page_for_subject` is the answering
path: a question names a subject, and the corpus is asked which page explains it. `page_by_iri` is
the addressed path: something already holds a page's identity and wants the row. They are
different questions and a caller that had only the first would filter the second out of it in
application code — which is a query language reassembled one comprehension at a time, and the
thing the one-client rule exists to prevent.

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
        """Pages whose `mesh:explains` includes `subject_iri`. Empty is an answer, not an error."""

    def page_by_iri(self, page_iri: str) -> PageRow | None:
        """One page by its declared identity, or None. Identity is the IRI, never the path."""


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
