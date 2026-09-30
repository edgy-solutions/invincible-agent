"""A canvas, read as a disclosure: which lots and which page sections an export carries.

`package_export` used to take a recipient and produce ONE fixed document: every section,
every lot the recipient is entitled to. The dispatch (lane/74, 2026-09-30) is that it takes a
CANVAS instead: the answers a person assembled (ADR-0028: a selected set of SPO-tagged
answers), plus the recipient. The package then carries exactly what those answers are about.

WHAT A CANVAS NARROWS, AND WHAT IT DOES NOT.
  * LOTS: the disclosure. A lot-bound answer contributes its subject lot, and a program-wide
    answer contributes every lot the recipient is entitled to. Everything embedded is
    disclosed (export.py), so this is the entitlement decision, and it is checked against the
    recipient's scope before anything is built.
  * SECTIONS: the presentation. A section is on the page when some answer on the canvas asks
    the question that section answers.
  * NOT THE ROWS WITHIN A LOT. The verification manifest reprices each disclosed lot from all
    of its inputs, so a lot's rows ride whole whichever sections show. A canvas holding only
    a labor answer for lot 3 still embeds lot 3's material rows. That is ADR-0047's unit of
    disclosure (the lot, per recipient), not a leak this module could close by trimming.

REFUSED, NEVER DROPPED. An answer this engine cannot export, or a lot outside the recipient's
scope, refuses the whole export by name. Dropping it would ship a document that differs from
the canvas the person assembled, with nothing on the document to say so.

The refusal ORDER is deliberate: the canvas's shape first, then entitlement, then
exportability. An out-of-scope lot answers `Unentitled` even when it is also not a lot in the
model, because "we do not disclose that to this recipient" must not reveal whether the lot
exists.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

try:  # flat in the image (/app), packaged in the repo; see section 5 of the engine runbook
    from entities import NotInModel, Unentitled
except ImportError:
    from agent_fleet.cost_agent.entities import NotInModel, Unentitled

MESH = "http://invincible-agent/mesh#"

#: The page's sections, in page order. The page template marks each one, and the builder
#: removes the ones a package does not carry. The algorithm panel is NOT a section: it is the
#: evidence the verification rests on, and it ships with every package.
SECTIONS: tuple[str, ...] = ("labor", "program", "composition", "sepm", "material", "scenario")

#: Each exportable verb: the measure it names, what its subject spans, and the sections that
#: answer the same question on the page.
#:
#:   spans "lot":     the answer is about one lot, named by its subject.
#:   spans "program": the answer is about every lot (a trend across lots).
#:   spans "none":    the answer is about no lot (an assumption set), so it adds none.
#:
#: Sealed against the engine's own catalogue: every answering verb has a row here, and no
#: row names a verb the engine does not serve. `packageExport` has no row: an export is not
#: an answer a canvas can export.
EXPORTABLE: dict[str, dict[str, Any]] = {
    "costLaborComposition":      {"fn": "cost_labor_composition", "spans": "lot",
                                  "sections": ("labor", "sepm")},
    "costUnitPriceTrend":        {"fn": "cost_unit_price_trend", "spans": "program",
                                  "sections": ("program",)},
    "costPriceComposition":      {"fn": "cost_price_composition", "spans": "lot",
                                  "sections": ("composition",)},
    "costLotBreakdown":          {"fn": "cost_lot_breakdown", "spans": "lot",
                                  "sections": ("composition",)},
    "costCategoryBreakdown":     {"fn": "cost_category_breakdown", "spans": "lot",
                                  "sections": ("material",)},
    "costRateComparison":        {"fn": "cost_rate_comparison", "spans": "lot",
                                  "sections": ("material",)},
    "costSupplierConcentration": {"fn": "cost_supplier_concentration", "spans": "lot",
                                  "sections": ("material",)},
    "costRateAssumptions":       {"fn": "cost_rate_assumptions", "spans": "none",
                                  "sections": ("scenario",)},
}


def _verb_local(verb_iri: Any) -> Optional[str]:
    """`mesh:costX` or the full mesh IRI, to `costX`. Anything else is not a mesh verb."""
    if not isinstance(verb_iri, str):
        return None
    v = verb_iri.strip()
    if v.startswith("mesh:"):
        return v[len("mesh:"):] or None
    if v.startswith(MESH):
        return v[len(MESH):] or None
    return None


def _lot_number(subject: Any) -> Optional[int]:
    """This engine's lot instance id is the bare lot number (`instances._lots`)."""
    if isinstance(subject, bool):
        return None
    if isinstance(subject, int):
        return subject
    if isinstance(subject, str) and subject.strip().isdigit():
        return int(subject.strip())
    return None


def resolve(canvas: Any, *, recipient_scope: str, entitled_lots: Iterable[int]) -> dict[str, Any]:
    """Read a canvas into the lots and sections its export carries. Refuses by name.

    `canvas` is `{"answers": [{"id", "verb_iri", "subject_instance_id"}, ...]}`: the fields
    the bff's `ArtifactResponse` carries for each answer on a board. Extra keys are ignored.
    """
    entitled = tuple(entitled_lots)
    if not isinstance(canvas, dict) or not isinstance(canvas.get("answers"), list):
        raise NotInModel(
            "a canvas is {'answers': [...]}, each answer carrying its id, verb_iri and "
            "subject_instance_id")
    answers = canvas["answers"]
    if not answers:
        raise NotInModel("the canvas holds no answers, so there is nothing to export")

    parsed: list[tuple[str, Optional[str], Any]] = []
    seen: set[str] = set()
    for i, a in enumerate(answers):
        aid = a.get("id") if isinstance(a, dict) else None
        if not isinstance(aid, str) or not aid.strip():
            raise NotInModel(f"canvas answer #{i} carries no id")
        if aid in seen:
            raise NotInModel(f"canvas answer {aid!r} appears twice")
        seen.add(aid)
        parsed.append((aid, _verb_local(a.get("verb_iri")), a.get("subject_instance_id")))

    # ENTITLEMENT BEFORE EXPORTABILITY. A lot-bound answer's subject is a disclosure request,
    # whatever else is wrong with the canvas.
    unentitled = sorted({
        (aid, str(subj)) for aid, verb, subj in parsed
        if EXPORTABLE.get(verb or "", {}).get("spans") == "lot"
        and _lot_number(subj) is not None and _lot_number(subj) not in entitled
    })
    if unentitled:
        raise Unentitled(
            f"{recipient_scope!r} is not entitled to the lot(s) these answers are about: "
            + ", ".join(f"{aid} (lot {s})" for aid, s in unentitled))

    unexportable = [aid for aid, verb, _ in parsed if verb not in EXPORTABLE]
    if unexportable:
        raise NotInModel(
            "these canvas answers are not cost answers this engine can export: "
            f"{unexportable}. Exportable verbs: {sorted(EXPORTABLE)}")
    no_subject = [aid for aid, verb, subj in parsed
                  if EXPORTABLE[verb]["spans"] == "lot" and _lot_number(subj) is None]
    if no_subject:
        raise NotInModel(
            f"these canvas answers are about a lot and name none: {no_subject}")

    lots: set[int] = set()
    sections: set[str] = set()
    for _aid, verb, subj in parsed:
        row = EXPORTABLE[verb]
        sections.update(row["sections"])
        if row["spans"] == "lot":
            lots.add(_lot_number(subj))
        elif row["spans"] == "program":
            lots.update(entitled)
    if not lots:
        raise NotInModel(
            "no answer on the canvas is about a lot, so the package would verify nothing: "
            "add a lot-bound or program-wide cost answer")

    return {
        "lots": tuple(n for n in entitled if n in lots),
        "sections": tuple(s for s in SECTIONS if s in sections),
        "answers": [aid for aid, _, _ in parsed],
    }
