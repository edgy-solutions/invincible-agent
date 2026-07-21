"""Honest-degradation guard for subject resolution (recall-override).

Pure — no FastAPI / BAML / weaviate / neo4j — so it unit-tests without the
engine-o import chain (same split as registry_views). ``main.py``'s /resolve
handler imports ``recall_override_guard`` and applies it on the two paths where
the LLM's class pick stands ALONE (no mesh:resolveInstance preemption).

WHY. /resolve is vector-recall + LLM-precision, with resolveInstance preemption
as the safety net (a matched instance forces the subject class, overriding the
LLM). When the phone-book does NOT confirm and the LLM overrode a STRONG
vector-recall winner — picked a materially-lower-recall candidate — the answer
is on the WEAK path, and a confident score there is a SILENT-degradation
surface. The motivating case: a question of the form "what snowflake TABLES are
used in the <named> superset DASHBOARD" resolved subject=idp#Table @0.78 over
idp#Dashboard @recall-1.00 with no phone-book match — the target-type word
("tables") beat the subject entity, confidently wrong, reading like a normal
classification. This guard discounts the confidence and flags provenance so it
reads as weak (and can trip the supervisor's ADR-0008 fallback). It does NOT
change the pick — honesty about the path, not a second-guess.
"""
from __future__ import annotations

# pick lost to the recall winner by >= this gap ...
_RECALL_OVERRIDE_MARGIN = 0.35
# ... and that winner was itself a STRONG recall match ...
_RECALL_OVERRIDE_STRONG = 0.80
# ... then cap the reported confidence at this.
_RECALL_OVERRIDE_CEIL = 0.50


def recall_override_guard(
    resolved_uri: str,
    confidence: float,
    candidates: list[dict],
    reasoning: str | None,
    provenance: dict | None,
) -> tuple[float, str | None, dict]:
    """Return (confidence, reasoning, provenance) discounted + flagged when the
    LLM pick stood alone and overrode a strong-recall winner; otherwise a no-op
    (values unchanged, ``recall_override=False``).

    Fires only when ALL hold: the pick is NOT the top-recall candidate, the top
    candidate's recall is >= _RECALL_OVERRIDE_STRONG, and the pick trails it by
    >= _RECALL_OVERRIDE_MARGIN. Conservative on purpose — the LLM legitimately
    overriding noisy recall by a small margin must not trip it.
    """
    prov = dict(provenance or {})
    prov["recall_override"] = False
    scored = [(str(c.get("uri")), float(c.get("score") or 0.0)) for c in (candidates or [])]
    if not scored:
        return confidence, reasoning, prov
    top_uri, top_score = max(scored, key=lambda x: x[1])
    pick_score = next((s for u, s in scored if u == str(resolved_uri)), 0.0)
    if (top_uri != str(resolved_uri)
            and top_score >= _RECALL_OVERRIDE_STRONG
            and (top_score - pick_score) >= _RECALL_OVERRIDE_MARGIN):
        capped = min(confidence, _RECALL_OVERRIDE_CEIL)
        prov.update({
            "recall_override": True,
            "recall_top_uri": top_uri,
            "recall_top_score": round(top_score, 3),
            "recall_pick_score": round(pick_score, 3),
            "confidence_before_discount": round(confidence, 3),
        })
        note = (
            f" [WEAK PATH — no phone-book confirmation: the classifier overrode "
            f"vector recall, picking {str(resolved_uri).split('#')[-1]} "
            f"(recall {pick_score:.2f}) over {top_uri.split('#')[-1]} "
            f"(recall {top_score:.2f}); confidence discounted "
            f"{confidence:.2f}->{capped:.2f}.]"
        )
        return capped, (reasoning or "") + note, prov
    return confidence, reasoning, prov
