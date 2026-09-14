"""`mesh:explain` — the pure core. Takes a row and bytes, returns a card or refuses.

NO I/O, NO CLOCK, NO NETWORK, and that is what makes the interesting parts testable without a
cluster: every decision this verb makes is a function of the row, the bytes, and the caller's
subject. The reads live behind `reads.py`'s Protocols and the transport lives in `main.py`.

**THE CARD IS THE PAGE, NOT A SUMMARY WRITTEN OVER IT.** A generated summary is a second artifact
that drifts from the page silently and carries none of the review the page had. So the body goes
through unmodified and the card's other fields are metadata ABOUT the page rather than a retelling
of it.

**THE SHA IS ASSERTED BEFORE ANYTHING RENDERS, AND A MISMATCH IS A REFUSAL.** The graph holds a
pointer; the pointer is only safe if the claim and the bytes are checked against each other at
answer time. Rendering text that is not what was indexed is the confidently-wrong answer this
corpus exists to avoid, and a reader cannot detect it by looking — the page will be plausible,
well-formed, and about the right topic.
"""
from __future__ import annotations

import hashlib
import re

from .reads import PageRow

ARCHETYPE = "KNOWLEDGE_DOCUMENT"

#: A seal is a test path. Derived from the body AT RENDER TIME and never stored — which is the
#: literal-property refusal (ADR-0037's 2026-09-12 amendment) followed through rather than
#: contradicted. That refusal was about STORING a seal name as a field: a stored literal has no
#: gate and keeps reading as true after the test is renamed. Deriving it from the very bytes being
#: shown cannot go stale, because the derivation and the render are the same act.
_SEAL = re.compile(r"\b(tests/[A-Za-z0-9_/.\-]+\.py)")


class BodyShaMismatch(Exception):
    """The bytes read back are not the bytes the graph indexed.

    A REFUSAL, NOT A WARNING. The alternative — render it and note the discrepancy — asks a reader
    to evaluate a claim about provenance in the middle of reading a how-to, which nobody does.
    """

    def __init__(self, page_iri: str, expected: str, actual: str, locator: str):
        super().__init__(
            f"body sha mismatch for {page_iri}: the graph indexed {expected[:12]}… and "
            f"{locator} now holds {actual[:12]}…. Refusing to render text that is not what was "
            f"indexed. Re-run scripts/generate_docs_corpus.py and re-prime; if they still "
            f"disagree the object was written by something other than the prime.")
        self.page_iri = page_iri
        self.expected = expected
        self.actual = actual
        self.locator = locator


def cited_seals(body: str) -> tuple[str, ...]:
    """Test paths the page names, in first-appearance order, de-duplicated.

    ORDER IS THE PAGE'S, NOT SORTED. A runbook names its seals in the order the work happens, and
    alphabetising them would reorder a sequence the author chose — the same reason a step ladder
    is not a ranking.
    """
    seen: dict[str, None] = {}
    for m in _SEAL.finditer(body):
        seen.setdefault(m.group(1), None)
    return tuple(seen)


def explain(row: PageRow, body_bytes: bytes) -> dict:
    """Render one page as a card, or refuse.

    `body_bytes` is what the store returned for `row.source`. It is hashed here rather than by the
    caller so that no path exists in which a card is built without the check having run.
    """
    actual = hashlib.sha256(body_bytes).hexdigest()
    if actual != row.body_sha:
        raise BodyShaMismatch(row.iri, row.body_sha, actual, row.source)

    body = body_bytes.decode("utf-8")
    return {
        "archetype": ARCHETYPE,
        "page_iri": row.iri,
        "title": row.title,
        "doc_kind": row.doc_kind,
        "audience_hint": row.audience_hint,
        "explains": list(row.explains),
        "cited_seals": list(cited_seals(body)),
        "source": row.source,
        "body_sha": row.body_sha,
        "body": body,
    }


def abstain(subject_iri: str) -> dict:
    """No page explains this subject yet — a RESULT, and the corpus's normal state.

    It names the subject rather than apologising generically, because the reader's next question
    is *"which one?"* and an answer that cannot be acted on is a different failure from one that
    can. The index is honest by construction: nobody writes a page for a task nobody has done, so
    an uncovered subject is expected and must not read as a malfunction.
    """
    return {
        "archetype": ARCHETYPE,
        "page_iri": None,
        "subject": subject_iri,
        "abstained": True,
        "reason": "no_page_explains_this_subject",
        "body": (f"No page in the corpus explains {subject_iri} yet. That is a gap in the "
                 f"documentation, not a failure of the question."),
    }
