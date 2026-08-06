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
and the Dagster user-code image has ``/app/agent_fleet/utils/``. Third relocation for that reason,
after ``service_identity.py`` and ``trust_table.py``; the rule is the same each time: two escapers of
one meaning are two chances to disagree.

ARTIFACT-PURE BY CONSTRUCTION. It reads ONLY ``review.json`` content. That is what makes the derive
possible at all: the starter can fetch the artifact by pointer and compute the same value the
producer's own extraction implies, with no caller-asserted input. (The old signature took a ``key``
argument and never used it — the purity was already there, undeclared.)
"""
from __future__ import annotations

__all__ = ["format_fingerprint"]


def format_fingerprint(review: dict) -> str:
    """``<mfr>/<doc_type>/<layout-era>`` — a first-cut vendor-format key.

    DELIBERATELY COARSE AND DECLARED AS SUCH. ADR-0034 open question 3 says the fingerprint needs
    real corpus data to sharpen: too coarse silently grants trust ACROSS a format boundary, too fine
    and nothing ever accumulates enough evidence to promote. It is recorded on every record from day
    one precisely so the corpus can tell us which way it is wrong — a fingerprint invented later
    cannot be applied to immutable records already written.

    Tolerant of a missing/odd ``review`` because BOTH callers may hand it degraded input: the sensor
    reads a possibly-partial extraction, and the starter reads whatever the bucket returned. It
    yields ``unknown/...`` rather than raising — a fingerprint that cannot match a promoted format is
    the safe direction, and the caller decides what to do about the degradation.
    """
    mfr = ""
    for it in (review or {}).get("review_items") or []:
        if isinstance(it, dict) and it.get("field_path") == "header.mfr":
            mfr = str(it.get("value") or "").strip().lower()
            break
    doc_type = str((review or {}).get("doc_type") or "PCN").lower()
    return f"{mfr or 'unknown'}/{doc_type}/v1"
