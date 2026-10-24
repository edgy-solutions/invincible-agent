"""`mesh:plannedInspectionInterval` — the MAINTENANCE read "what is the inspection interval for <the
array module>".

WHY THIS EXISTS. The 320A planning data module records an interval (`mil:hasPlanningInterval`) and
cites the procedure modules it governs. The question "what is the inspection interval for the array
module" had no verb: it resolved nowhere and the generalist answered it. This is the verb.

WHAT IT READS, AND WHERE THE QUERY LIVES. The maintenance instance graph in Jena, the graph the
fault walk reads. The SPARQL is DECLARED DATA (policy/overlays/openddil-lab/verbs/
planned_inspection_interval.yaml, a `QueryVerb`); this module names no `mil:` IRI and no SPARQL. It
only shapes the declared select's rows into an answer. READ-ONLY.

THE SUBJECT IS A PARAMETER, RESOLVED FROM THE TEXT. No instance resolver covers `mil:` parts, so
the verb is registered on the class of the thing it returns (`mil:PlanningInterval`) and the subject
-- a part or a platform -- is found by the declared select from the question's own text. The
subject text is `params["subject"]` when a slot filled one, else the dispatch body's `user_query`.

ANSWERS, NEVER CONFLATED. Every refusal is the fleet's named envelope (`_refused`):
  * REFUSED, `not_entitled` / `no_subject` — the route's, before the graph is read / when there is
    no text to find a subject in.
  * REFUSED, `unknown_subject` — the question names nothing the manual lists. A different fact from:
  * REFUSED, `no_planned_inspection` — the manual lists the subject and no planning module that
    cites it records an interval. A refusal, never a default and never an interval of "none".
  * REFUSED, `ambiguous_subject` — the longest-named match carries more than one part number or
    ident. Never picked by the store's order.

THE CITATION IS COPIED, NEVER INVENTED. `evidence_ref` is the planning module's `rdfs:label`
verbatim; `refers_to` are the labels of the modules it cites. A plan with neither an interval label
nor a value is not an interval, and is treated as unrecorded.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

VERB = "mesh:plannedInspectionInterval"
DOMAIN = "MAINTENANCE"
INPUT_URI = "http://edgy-solutions.com/ontology/mil#PlanningInterval"
OUTPUT_URI = "http://invincible-agent/mesh#PlannedInspectionInterval"
#: The declared-query verb (the YAML's `verb:`) the route loads by name.
QUERY_VERB = "planned_inspection_interval"
#: The declared select's name, and the one parameter it binds.
SELECT = "interval_rows"
PARAM = "question"


def _refused(reason: str, message: str, **extra: Any) -> Dict[str, Any]:
    """The named refusal envelope every refusal here speaks: `refused` + `outcome` + `reason` is
    what presentation keys on; `status` stays for existing consumers."""
    return {
        "status": "refused",
        "refused": True,
        "outcome": "refused",
        "reason": reason,
        "verb": VERB,
        "message": message,
        **extra,
    }


def not_entitled() -> Dict[str, Any]:
    return _refused("not_entitled",
                    f"This read needs the {DOMAIN} domain, which the caller is not entitled to.")


def no_subject() -> Dict[str, Any]:
    return _refused("no_subject", "No text reached the verb to find a subject in.")


def subject_text(params: Optional[Mapping[str, Any]], user_query: str = "") -> str:
    """`params["subject"]` if a non-blank string, else the dispatch body's `user_query`."""
    slot = (params or {}).get("subject")
    if isinstance(slot, str) and slot.strip():
        return slot.strip()
    return (user_query or "").strip()


def _interval_of(label: Any, value: Any, unit: Any) -> Optional[str]:
    if isinstance(label, str) and label.strip():
        return label.strip()
    if value not in (None, ""):
        return f"{value} {unit}".strip() if unit not in (None, "") else str(value)
    return None


def answer_from_rows(rows: List[Mapping[str, Any]], question: str = "") -> Dict[str, Any]:
    """The answer the declared select's rows support. Pure: no I/O."""
    rows = [r for r in (rows or []) if r.get("name")]
    if not rows:
        return _refused("unknown_subject",
                        "The question names no part or platform the maintenance manual lists.")
    longest = max(len(str(r["name"])) for r in rows)
    mine = [r for r in rows if len(str(r["name"])) == longest]
    keys = sorted({str(r.get("subject_key")) for r in mine if r.get("subject_key")})
    if len(keys) > 1:
        return _refused("ambiguous_subject",
                        f"The question names more than one subject: {', '.join(keys)}.",
                        candidates=keys)
    name = str(mine[0]["name"])
    key = keys[0] if keys else name
    # Every row of THIS subject (a shorter name for the same key is the same subject).
    subject_rows = [r for r in rows if str(r.get("subject_key") or r["name"]) == key]
    plans: Dict[str, Dict[str, Any]] = {}
    for r in subject_rows:
        dmc = r.get("plan_dmc")
        if not dmc:
            continue
        p = plans.setdefault(str(dmc), {"label": None, "value": None, "unit": None, "cited": set()})
        for src, dst in (("interval_label", "label"), ("interval_value", "value"),
                         ("interval_unit", "unit")):
            if p[dst] is None and r.get(src) not in (None, ""):
                p[dst] = r[src]
        if r.get("cited_dmc"):
            p["cited"].add(str(r["cited_dmc"]))
    intervals = []
    for dmc in sorted(plans):
        p = plans[dmc]
        text = _interval_of(p["label"], p["value"], p["unit"])
        if text is None:
            continue
        intervals.append({"evidence_ref": dmc, "interval": text, "value": p["value"],
                          "unit": p["unit"], "refers_to": sorted(p["cited"])})
    if not intervals:
        return _refused(
            "no_planned_inspection",
            f"The manual lists {name} ({key}) but no planning data module that cites it records "
            "an inspection interval.", subject=name, subject_key=key)
    parts = [f"{i['interval']}, per planning data module {i['evidence_ref']}"
             + (f", which cites {', '.join(i['refers_to'])}" if i["refers_to"] else "")
             for i in intervals]
    summary = (f"The planned inspection interval for {name} ({key}) is "
               + ("; and ".join(parts) if len(parts) > 1 else parts[0]) + ".")
    out: Dict[str, Any] = {
        "status": "answered", "verb": VERB, "subject": name, "subject_key": key,
        "intervals": intervals, "summary": summary,
    }
    if len(intervals) == 1:
        one = intervals[0]
        out.update(interval=one["interval"], evidence_ref=one["evidence_ref"],
                   refers_to=one["refers_to"])
    out["structured_data"] = {k: v for k, v in out.items() if k != "summary"}
    return out
