"""A qualified identifier must reach the phone book in a form it can match (2026-08-20).

WHY THIS TESTS THE SEAM AND NOT THE FUNCTION. `test_segment_specificity_gate` passes
`publog.p_cage` straight into `decide()` ALONG WITH a candidate, and asserts the candidate is
accepted. That test was green while the live path returned `not_specific` with **n=0** — the
provider had been asked for the literal string `publog.p_cage`, matched nothing, and the gate
correctly rejected an empty set. The unit test supplied the very thing the real path failed to
obtain.

Fifth instance today of [[a-green-check-proves-only-its-scope]], and the sharpest: the guard's
scope was *the scoring function*, the defect was *what reaches it*, and no amount of
decide-level testing could see the difference. So this drives `_resolve_instance` — normalize,
fan out, score — with a fake provider recording exactly which terms it was asked for.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent_fleet.ontology_service.instance_resolution import (  # noqa: E402
    InstanceCandidate,
    decide,
    identifier_name_and_qualifiers,
)

URN = "urn:li:dataset:(urn:li:dataPlatform:s3,iagent-minio.publog-lake/publog/p_cage,PROD)"


class _Phonebook:
    """A provider that only matches the asset's OWN name — like the real one."""

    def __init__(self):
        self.asked: list[str] = []

    def lookup(self, term: str) -> list[InstanceCandidate]:
        self.asked.append(term)
        if term.strip().lower() == "p_cage":
            return [InstanceCandidate(instance_id=URN, class_uri="http://x#Table",
                                      label="p_cage", score=0.86, provider="fake")]
        return []


def _resolve(identifier: str, book: _Phonebook):
    """The seam, in miniature: normalize -> fan out -> score."""
    name, _q = identifier_name_and_qualifiers(identifier)
    terms = [identifier] + ([name] if name and name != identifier.strip().lower() else [])
    cands = [c for t in terms for c in book.lookup(t)]
    return decide(cands, identifier=identifier)


@pytest.mark.parametrize("identifier", [
    "publog.p_cage", "publog p_cage", "publog's p_cage", "PUBLOG.P_CAGE",
])
def test_a_qualified_identifier_is_asked_for_by_its_NAME(identifier):
    """THE DEFECT. Before the fix only the literal string was sent, the phone book had no
    row for it, and the gate then rejected an empty set."""
    book = _Phonebook()
    d = _resolve(identifier, book)
    assert "p_cage" in [a.strip().lower() for a in book.asked], (
        f"the provider was only asked for {book.asked} — a qualified identifier never reached "
        "it in a matchable form, so the gate scores nothing and reports a rejection"
    )
    assert d.subject_uri == "http://x#Table"
    assert d.provenance["instance_match"] == "fuzzy"


def test_a_bare_name_is_not_asked_twice():
    """Normalization must not double the fan-out when there is no qualifier to strip."""
    book = _Phonebook()
    _resolve("p_cage", book)
    assert book.asked == ["p_cage"], f"redundant lookups: {book.asked}"


def test_an_empty_provider_result_is_EMPTY_not_not_specific():
    """THE VOCABULARY BUG THAT HID THE STARVATION. `not_specific` means the phone book knew
    things and none of them were named by the token. A provider that returned nothing is a
    different fact, and wearing the rejection's name is what made n=0 look like a judgement."""
    book = _Phonebook()
    d = _resolve("zzz_no_such_asset", book)
    assert d.subject_uri is None
    assert d.provenance["instance_match"] == "empty", (
        "an empty provider result must not report as a specificity rejection — that "
        "conflation is what disguised the fan-out defect as correct behaviour"
    )


def test_a_content_word_still_loses_when_the_phone_book_DOES_answer():
    """The gate must keep biting: `cage` reaches a provider that answers for `p_cage` only,
    so nothing comes back — but if a candidate DID come back, the name must not match."""
    d = decide([InstanceCandidate(instance_id=URN, class_uri="http://x#Table",
                                  label="p_cage", score=0.99, provider="fake")],
               identifier="cage")
    assert d.subject_uri is None
    assert d.provenance["instance_match"] == "not_specific"
