"""FORMAT FINGERPRINT — the vendor-format half of the trust key. ONE implementation, two consumers.

WHY IT LIVES HERE (ADR-0034 phase 1.3). This value is computed in TWO places that must agree
exactly:

  * the extraction→review sensor, which stamps it on every decision record, and
  * ``ReviewStarter``, which derives it from the fetched artifact to choose a workflow.

If those two ever disagree, the corpus documents a decision the router did not make — and worse, the
disagreement is SILENT AND SAFE: fingerprints stop matching the table, every promoted format falls to
the supervised floor, and nothing is wrong except that a governed decision has no effect. That is the
passthrough class one layer down, so the two computations are not two functions. They are this one.

``agent_fleet/utils/`` is the only tree BOTH runtimes carry — engine-a flattens it to ``/app/utils/``
and the Dagster user-code image has ``/app/agent_fleet/utils/``.

ARTIFACT-PURE BY CONSTRUCTION. It reads ONLY ``review.json`` content (plus the git-asserted alias
table). That is what makes the server-side derive possible: the starter fetches the artifact by
pointer and computes the same value the producer's extraction implies, with no caller-asserted input.

── CANONICAL-FORM RESOLUTION AT THE COMPARISON BOUNDARY (added 2026-08-06) ─────────────────────────
This function IS the comparison boundary, so canonicalisation happens here rather than in a cleanup
pass over artifacts — a pass would never outrun extraction accrual. Same shape as the settled
compact→full-IRI class-fix: storage-form variation splits one logical entity across records, and the
durable defence is resolving to a canonical form where the comparison is made.

Normalisation is deliberately NON-SEMANTIC (case, whitespace) plus an EXPLICIT witnessed alias table
(``policy/vendor_aliases.yaml``). Case/whitespace insensitivity cannot merge two genuinely different
vendors; stemming or edit-distance could, silently, and a wrong merge grants one vendor's
accumulated trust to another's artifacts.

── `doc_type` NO LONGER SILENTLY DEFAULTS ────────────────────────────────────────────────────────
It used to fall back to ``PCN`` when absent — 9 of 16 live artifacts — which made "identified as a
PCN" and "we did not know" the SAME KEY. That is the default-collision shape: a guard on that
segment could not tell the two apart, so none could be written. Absent now yields ``unknown``, which
makes the missing case DISTINGUISHABLE and therefore guardable — and the sentinel-fingerprint rule
covers that segment too.

This CHANGES the fingerprint of every artifact lacking a doc_type. That is why the normalisation
item is sequenced BEFORE the first real promotion: doing it now orphans nothing, because nothing is
promoted and no artifact yet carries a producer stamp.
"""
from __future__ import annotations

import os
import re
from typing import Optional

__all__ = ["format_fingerprint", "canonical_vendor", "load_vendor_aliases",
           "parse_vendor_aliases", "VendorAliasesInvalid", "UNKNOWN_SEGMENT"]

# The value each segment takes when the artifact did not identify it. Deliberately the SAME token on
# both segments, and deliberately implausible as a real vendor or doc type, so an unidentified
# artifact stands out in the corpus instead of blending in — the property the sentinel rule keys on.
UNKNOWN_SEGMENT = "unknown"

_VENDOR_ALIASES_FILE = os.getenv("VENDOR_ALIASES_FILE", "policy/vendor_aliases.yaml")
_WS = re.compile(r"\s+")


class VendorAliasesInvalid(RuntimeError):
    """The alias overlay is malformed. Nothing is applied; canonicalisation falls back to the
    literal normalised form, which is the safe direction — an unmapped vendor is simply a key
    nobody promoted."""


def _normalise(value: str) -> str:
    """Case + whitespace only. NON-SEMANTIC by design: this cannot merge two different vendors."""
    return _WS.sub(" ", (value or "").strip().lower()).strip()


def parse_vendor_aliases(raw: dict) -> dict:
    """PURE: parsed YAML -> {alias: canonical}. Raises on a malformed overlay.

    Refuses, rather than skips, because a partially-applied alias table would canonicalise some
    artifacts and not others — producing exactly the split it exists to prevent, intermittently.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise VendorAliasesInvalid("vendor aliases must be a mapping")
    aliases = raw.get("aliases")
    if aliases is None:
        aliases = {}
    if not isinstance(aliases, dict):
        raise VendorAliasesInvalid("`aliases` must be a mapping of alias -> canonical")

    out: dict[str, str] = {}
    for alias, canonical in aliases.items():
        # A non-string value is how a stray note lands in here and becomes a bogus alias — which
        # happened while authoring this file's first draft. Refuse it loudly.
        if not isinstance(canonical, str) or not canonical.strip():
            raise VendorAliasesInvalid(
                f"alias {alias!r} maps to {canonical!r} — every entry must be a non-empty string "
                f"(a note or comment placed under `aliases` becomes a bogus alias)")
        a, c = _normalise(str(alias)), _normalise(canonical)
        if not a:
            raise VendorAliasesInvalid("an empty alias cannot be mapped")
        if a == c:
            raise VendorAliasesInvalid(f"alias {alias!r} maps to itself — a no-op entry")
        out[a] = c

    # NO CHAINS: an alias may not itself be a canonical target, or resolution would depend on order.
    canonicals = set(out.values())
    chained = sorted(set(out) & canonicals)
    if chained:
        raise VendorAliasesInvalid(
            f"alias(es) {chained} are also canonical targets — chains make canonicalisation "
            f"order-dependent; map every spelling DIRECTLY to its final form")
    return out


def load_vendor_aliases(path: Optional[str] = None) -> dict:
    """Read + validate. A MISSING file is not an error (a deployment may declare no aliases); a
    MALFORMED one raises, because silently ignoring it would split vendors intermittently."""
    import yaml

    p = path or _VENDOR_ALIASES_FILE
    try:
        with open(p, "r", encoding="utf-8") as fh:
            content = fh.read()
    except FileNotFoundError:
        return {}
    return parse_vendor_aliases(yaml.safe_load(content))


def canonical_vendor(raw_mfr: Optional[str], *, aliases: Optional[dict] = None) -> str:
    """The manufacturer segment, canonicalised. Empty/absent -> ``unknown`` (the sentinel).

    A miss returns the normalised literal — a key nobody has promoted yet, which is the safe
    direction and the reason an incomplete alias table cannot cause a wrong merge.
    """
    norm = _normalise(raw_mfr or "")
    if not norm:
        return UNKNOWN_SEGMENT
    if aliases is None:
        try:
            aliases = load_vendor_aliases()
        except Exception:  # noqa: BLE001 — a bad table falls back to literals, never to a guess
            aliases = {}
    return aliases.get(norm, norm)


def format_fingerprint(review: dict, *, aliases: Optional[dict] = None) -> str:
    """``<manufacturer>/<doc_type>/<layout-era>`` — the vendor-format key.

    DELIBERATELY COARSE AND DECLARED AS SUCH. ADR-0034 open question 3 says the fingerprint needs
    real corpus data to sharpen: too coarse silently grants trust ACROSS a format boundary, too fine
    and nothing ever accumulates enough evidence to promote.

    Tolerant of missing/odd input because BOTH callers may hand it degraded content — the sensor a
    partial extraction, the starter whatever the bucket returned. It yields ``unknown`` segments
    rather than raising: an unidentified key cannot match a promoted format (and is barred from
    promotion outright), which is the safe direction, and the caller decides what to do about it.
    """
    mfr = ""
    for it in (review or {}).get("review_items") or []:
        if isinstance(it, dict) and it.get("field_path") == "header.mfr":
            mfr = str(it.get("value") or "")
            break
    vendor = canonical_vendor(mfr, aliases=aliases)

    # DOC TYPE — trusted only when the ARTIFACT ATTESTS it was extracted.
    #
    # Two ways this segment can be uninformative, and both must collapse to the sentinel:
    #   1. `doc_type` absent from review.json entirely (older artifacts);
    #   2. `doc_type` PRESENT but DEFAULTED — doc-tools emits `header_d.get("doc_type") or "PCN"`,
    #      so an unextracted notice carries a perfectly plausible `PCN`.
    # (2) is invisible from the value alone, which is exactly why this segment was unguardable. The
    # producer now emits `doc_type_source` ("extraction" | "defaulted") — a provenance-bearing
    # field, the same shape as `review_state_source` — and the classification field keeps its usable
    # value for the disposition proposer, which needs it.
    #
    # ABSENT ATTESTATION IS TREATED AS UNKNOWN, not as extracted: every artifact written before the
    # producer emitted it is exactly the population whose doc_type cannot be trusted, so the
    # conservative reading is the correct one for the back-corpus too.
    raw = review or {}
    attested = str(raw.get("doc_type_source") or "").strip().lower() == "extraction"
    doc_type = _normalise(str(raw.get("doc_type") or "")) if attested else ""
    return f"{vendor}/{doc_type or UNKNOWN_SEGMENT}/v1"
