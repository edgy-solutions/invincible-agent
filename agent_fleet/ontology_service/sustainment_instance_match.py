"""Pure name-matching for the pcn (PCN/PDN) mesh:resolveInstance provider — dep-free, unit-testable.

The pcn analogue of ``datahub_wrapper/instance_match.py`` (BI/catalog). It resolves a user's
identifier ("the PDN for NSR01L30NXT5G", "PCN 23_0120") to a pcn instance in Jena's
``SUSTAINMENT_INSTANCES`` graph, whose IRIs are DETERMINISTIC and keyed by MPN / notice-id (written by
doc-tools ``SustainmentPlugin.to_graph_queries``). Design: docs/plans/pcn-pdn-bulk-resolve.md §6a.

Two paths, in order:
  1. EXACT (the happy case, trivial): the instance IRI is a pure function of the MPN / notice-id, so
     ``component_iri`` / ``notice_iri`` build the candidate IRI directly — no stripping, no fuzzing.
  2. DESCRIPTOR-STRIP + fuzzy score (the fallback): strip the prose a user wraps around the id, then
     score candidates from a graph query.

THE ADMISSION RULE (banked; do NOT copy the BI ``_DESCRIPTOR_TOKENS``). A descriptor is a word a user
APPENDS ("notice", "part"); an identifier-FRAGMENT is part of the genuine name and is never stripped.
The pcn trap: ``pcn`` / ``pdn`` / ``ptn`` LOOK like entity-type nouns but are almost always part of the
real identifier ("PCN 23_0120") — so they are NOT descriptors. MPNs (``LTC6226HDC#TRMPBF``,
``090-44310-31``) are identifiers verbatim — never normalized, hyphenated, or "corrected".
"""
from __future__ import annotations

import difflib

# pcn-domain descriptors: entity-type nouns a user appends to a notice/part, plus articles.
# EXCLUDES pcn / pdn / ptn (identifier fragments) and every MPN (identifiers). This set is
# SUSTAINMENT-specific; a different provider owns its own set with the same admission test.
_PCN_DESCRIPTOR_TOKENS = frozenset({
    "the", "a", "an", "for", "of",
    "notice", "notices", "part", "parts", "component", "components", "mpn", "mpns",
})

# Deterministic IRI bases — MUST match doc-tools SustainmentPlugin.to_graph_queries exactly, or an
# exact-match candidate lands on a node that does not exist.
_COMPONENT_BASE = "http://internal/components/"
_NOTICE_BASE = "http://internal/sustainment/doc/"


def component_iri(mpn: str) -> str:
    """The deterministic component IRI for an MPN (doc-tools: ``affected_mpn.replace(' ', '_')``).
    e.g. ``NSR01L30NXT5G`` -> ``http://internal/components/NSR01L30NXT5G``."""
    return _COMPONENT_BASE + (mpn or "").strip().replace(" ", "_")


def notice_iri(notice_id: str) -> str:
    """The deterministic notice IRI for a doc_id (doc-tools:
    ``doc_id.replace(' ', '_').replace('"', '')``). e.g. ``IPCN25300X`` ->
    ``http://internal/sustainment/doc/IPCN25300X``; ``PCN 23_0120`` -> ``.../doc/PCN_23_0120``."""
    return _NOTICE_BASE + (notice_id or "").strip().replace(" ", "_").replace('"', "")


def strip_descriptor_tokens(identifier: str) -> str:
    """"the discontinuation notice for NSR01L30NXT5G" -> "discontinuation NSR01L30NXT5G". Only ever
    used to build an ADDITIONAL fallback query; the original is tried first and candidates are scored
    against the ORIGINAL, so this never lowers precision. Crucially, ``pcn`` / ``pdn`` / ``ptn`` are
    NOT stripped (identifier fragments), and MPNs are never touched — only prose words are removed."""
    toks = [t for t in (identifier or "").strip().split() if t.lower() not in _PCN_DESCRIPTOR_TOKENS]
    return " ".join(toks)


def _contiguous_sublist(sub: list[str], full: list[str]) -> bool:
    """True when ``sub`` appears as a contiguous run of tokens inside ``full``."""
    n = len(sub)
    if not n or n > len(full):
        return False
    return any(full[i:i + n] == sub for i in range(len(full) - n + 1))


def name_score(identifier: str, candidate_name: str) -> float:
    """Provider relevance for a candidate MPN / notice-id against the lookup token.

    1.0  exact match (case-insensitive).
    0.9  one name is a suffix of the other, OR one's word-tokens are a contiguous multi-word run
         inside the other — EXCEPT when the shorter side is a lone descriptor word ("notice"), which
         must not win by being a substring of a descriptor phrase.
    else difflib ratio — fuzzy / typo tolerant.

    Honest scores only; the routing decision table treats anything below the resolve floor as absent
    (providers MUST abstain rather than return least-bad matches)."""
    a = (identifier or "").strip().lower()
    b = (candidate_name or "").strip().lower()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    shorter = a if len(a) <= len(b) else b
    # A lone descriptor word gets no strong boost — it would tie the real hit and force an abstain.
    if shorter not in _PCN_DESCRIPTOR_TOKENS:
        if a.endswith(b) or b.endswith(a):
            return 0.9
        at, bt = a.split(), b.split()
        if (len(bt) >= 2 and _contiguous_sublist(bt, at)) or (len(at) >= 2 and _contiguous_sublist(at, bt)):
            return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()
