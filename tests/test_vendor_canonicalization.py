"""Canonical-form resolution for the trust key's manufacturer segment.

WHY IT MATTERS NOW. `format_fingerprint()` was a recording device; as of ADR-0034 phase 1.3 it
ROUTES. `header.mfr` became trust-key material, and storage-form variation in trust-key material
splits one logical vendor across several keys — measured live: `onsemi` x6 and `ONSEM` x1, one
vendor, two keys. A promotion for one silently excludes the other, and evidence never accumulates
for the split-off variant.

THE SHAPE FOLLOWS THE compact→full-IRI PRECEDENT: canonicalise AT THE COMPARISON BOUNDARY (this
function), not via a cleanup pass over artifacts — a pass never outruns extraction accrual.

THE TWO PROPERTIES THE RULING NAMED, both sealed below:
  * a MISS FAILS SAFE — an unmapped vendor becomes its own literal, a key nobody promoted;
  * NO FUZZY MERGE — only case/whitespace normalisation plus witnessed aliases, because a wrong
    merge grants one vendor's accumulated trust to another's artifacts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.utils.format_fingerprint import (  # noqa: E402
    UNKNOWN_SEGMENT, VendorAliasesInvalid, canonical_vendor, format_fingerprint,
    load_vendor_aliases, parse_vendor_aliases,
)

_ALIASES = {"onsem": "onsemi"}


def _review(mfr, doc_type="PCN"):
    """An artifact that ATTESTS its doc_type was extracted — the shape a current producer emits.

    The attestation is explicit in every fixture on purpose: an unattested doc_type is treated as
    unknown, so a fixture that omits it is asserting something different from what it looks like.
    """
    return {"doc_type": doc_type,
            "doc_type_source": "extraction",
            "review_items": [{"field_path": "header.mfr", "value": mfr}]}


# ===========================================================================
# THE SPLIT THIS EXISTS TO CLOSE — measured in the live corpus
# ===========================================================================
def test_the_witnessed_split_CONVERGES():
    """`onsemi` x6 and `ONSEM` x1 must become ONE key. This is the whole item."""
    a = format_fingerprint(_review("onsemi"), aliases=_ALIASES)
    b = format_fingerprint(_review("ONSEM"), aliases=_ALIASES)
    assert a == b == "onsemi/pcn/v1", (
        f"one vendor still yields two trust keys: {a!r} vs {b!r}")


@pytest.mark.parametrize("spelling", ["onsemi", "ONSEMI", "  onsemi  ", "OnSemi", "onsem", "ONSEM"])
def test_every_witnessed_spelling_lands_on_one_key(spelling):
    assert format_fingerprint(_review(spelling), aliases=_ALIASES) == "onsemi/pcn/v1"


# ===========================================================================
# A MISS FAILS SAFE — the property that makes an incomplete table harmless
# ===========================================================================
def test_an_unmapped_vendor_becomes_its_own_literal():
    """No mapping entry means no merge — just a key nobody has promoted yet. That is what lets the
    alias table be INCOMPLETE without being dangerous, which in turn is what lets it contain only
    witnessed entries instead of guesses."""
    assert format_fingerprint(_review("Diodes Incorporated"), aliases=_ALIASES) == \
        "diodes incorporated/pcn/v1"
    assert format_fingerprint(_review("Analog Devices, Inc."), aliases=_ALIASES) == \
        "analog devices, inc./pcn/v1"


def test_a_broken_alias_table_falls_back_to_literals_never_to_a_guess(monkeypatch):
    """A malformed overlay must not silently merge anything. Canonicalisation degrades to the
    normalised literal — the same safe direction as an absent entry."""
    import agent_fleet.utils.format_fingerprint as mod

    monkeypatch.setattr(mod, "load_vendor_aliases",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("bad table")))
    assert canonical_vendor("ONSEM") == "onsem"   # literal, NOT merged to onsemi


# ===========================================================================
# NO FUZZY MERGE — the failure that would be worse than the split
# ===========================================================================
def test_similar_but_distinct_vendors_do_NOT_merge():
    """A wrong merge grants one vendor's accumulated trust to another's artifacts — strictly worse
    than the split it would be fixing. Only exact (post-normalisation) matches resolve."""
    aliases = {"onsem": "onsemi"}
    assert canonical_vendor("onsemi holdings", aliases=aliases) == "onsemi holdings"
    assert canonical_vendor("onsemiconductor", aliases=aliases) == "onsemiconductor"
    assert canonical_vendor("ons", aliases=aliases) == "ons"


def test_normalisation_is_case_and_whitespace_ONLY():
    """These two cannot merge distinct vendors. Anything semantic (suffix stripping, stemming,
    edit distance) can, and would do it silently — so it is not done."""
    assert canonical_vendor("  Diodes   Incorporated ", aliases={}) == "diodes incorporated"
    # `Inc.` is NOT stripped: deciding that "X, Inc." and "X" are the same company is a judgement,
    # and this function does not make judgements.
    assert canonical_vendor("Analog Devices, Inc.", aliases={}) != "analog devices"


# ===========================================================================
# `doc_type` no longer silently defaults — which is what made it guardable
# ===========================================================================
def test_a_DEFAULTED_doc_type_is_not_trusted_even_though_it_reads_PCN():
    """THE COLLISION THAT MADE THIS SEGMENT UNGUARDABLE, closed at the source.

    doc-tools emits `header_d.get("doc_type") or "PCN"`, so an unextracted notice carries a
    perfectly plausible `PCN` — indistinguishable from a real one BY VALUE. The producer now also
    emits `doc_type_source`, and only `extraction` is trusted here.

    Note what this is NOT: doc-tools was not changed to emit a sentinel in `doc_type` itself,
    because that field DRIVES the disposition proposer and a sentinel would make every unextracted
    notice unclassifiable. The classification field keeps its usable value; a provenance field says
    where the value came from.
    """
    defaulted = {"doc_type": "PCN", "doc_type_source": "defaulted",
                 "review_items": [{"field_path": "header.mfr", "value": "Qorvo"}]}
    extracted = {"doc_type": "PCN", "doc_type_source": "extraction",
                 "review_items": [{"field_path": "header.mfr", "value": "Qorvo"}]}
    assert format_fingerprint(defaulted, aliases={}) == f"qorvo/{UNKNOWN_SEGMENT}/v1"
    assert format_fingerprint(extracted, aliases={}) == "qorvo/pcn/v1"
    assert format_fingerprint(defaulted, aliases={}) != format_fingerprint(extracted, aliases={}), (
        "a defaulted doc_type still keys the same as an extracted one — the collision is back")


def test_an_UNATTESTED_doc_type_is_treated_as_unknown():
    """The back-corpus: every artifact written before the producer emitted `doc_type_source`. Its
    doc_type is exactly the population that cannot be trusted, so absence of the attestation reads
    as unknown rather than as extracted."""
    legacy = {"doc_type": "PCN",
              "review_items": [{"field_path": "header.mfr", "value": "Qorvo"}]}
    assert format_fingerprint(legacy, aliases={}) == f"qorvo/{UNKNOWN_SEGMENT}/v1"


def test_absent_doc_type_yields_unknown_not_pcn():
    """It used to default to `pcn`, making "identified as a PCN" and "we did not know" the SAME
    key — 9 of 16 live artifacts. That collision is exactly why the sentinel guard could not cover
    the segment. Now the missing case is distinguishable, and therefore guardable."""
    fp = format_fingerprint({"review_items": [{"field_path": "header.mfr", "value": "Qorvo"}]},
                            aliases={})
    assert fp == f"qorvo/{UNKNOWN_SEGMENT}/v1"
    assert not fp.endswith("/pcn/v1")


def test_absent_manufacturer_yields_unknown():
    """Both segments go unknown here: no manufacturer, and a doc_type that is present but
    UNATTESTED — which is not trusted, because doc-tools defaults an unextracted one to "PCN"."""
    assert format_fingerprint({"doc_type": "PCN"}, aliases={}) == \
        f"{UNKNOWN_SEGMENT}/{UNKNOWN_SEGMENT}/v1"
    assert format_fingerprint({"doc_type": "PCN", "doc_type_source": "extraction"},
                              aliases={}) == f"{UNKNOWN_SEGMENT}/pcn/v1"


# ===========================================================================
# The overlay's own rules — refuse, never partially apply
# ===========================================================================
def test_a_note_placed_under_aliases_is_REFUSED():
    """How a stray comment becomes a bogus alias. Caught while authoring the real file's first
    draft — the note sat inside `aliases` and would have parsed as an entry."""
    with pytest.raises(VendorAliasesInvalid) as ei:
        parse_vendor_aliases({"aliases": {"onsem": "onsemi", "note": ["not", "a", "string"]}})
    assert "non-empty string" in str(ei.value)


def test_chains_are_REFUSED():
    """An alias that is also a canonical target makes resolution order-dependent."""
    with pytest.raises(VendorAliasesInvalid) as ei:
        parse_vendor_aliases({"aliases": {"a": "b", "b": "c"}})
    assert "chains" in str(ei.value).lower() or "canonical targets" in str(ei.value)


def test_a_self_mapping_is_REFUSED():
    with pytest.raises(VendorAliasesInvalid):
        parse_vendor_aliases({"aliases": {"onsemi": "onsemi"}})


def test_a_missing_file_is_not_an_error_but_a_malformed_one_is(tmp_path):
    """A deployment may declare no aliases; that is a valid posture. A malformed overlay must NOT
    be silently ignored — it would canonicalise some artifacts and not others, producing the very
    split intermittently."""
    assert load_vendor_aliases(str(tmp_path / "nope.yaml")) == {}
    bad = tmp_path / "bad.yaml"
    bad.write_text("aliases: [not, a, mapping]\n", encoding="utf-8")
    with pytest.raises(VendorAliasesInvalid):
        load_vendor_aliases(str(bad))


# ===========================================================================
# The COMMITTED overlay must be valid and must contain the witnessed split
# ===========================================================================
def test_the_committed_overlay_loads_and_closes_the_witnessed_split():
    aliases = load_vendor_aliases(str(_ROOT / "policy" / "vendor_aliases.yaml"))
    assert aliases.get("onsem") == "onsemi", (
        "the committed overlay no longer closes the one split actually observed in the corpus")
    assert format_fingerprint(_review("ONSEM"), aliases=aliases) == \
        format_fingerprint(_review("onsemi"), aliases=aliases)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
