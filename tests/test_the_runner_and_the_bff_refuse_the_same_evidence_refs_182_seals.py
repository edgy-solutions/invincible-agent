"""Review seals for #182 (lane saf, NOT committed to Lane 1's branch).

  C1  the checks are DERIVED from the SDK model (its validators and error classes over a corpus),
      never typed: every class the SDK refuses is a 422 whose `check` is a named one, not `invalid`.
  C2  the gateway is never LOOSER than the SDK; where it is stricter the cases are listed.
  P1  census of every route/body type that carries a box, from the served OpenAPI + the source;
      each carrier is given a PIXEL box and must refuse it.
  P2  the Restate runner's own normalizer (the other end of the same edit) refuses pixels.
"""
from __future__ import annotations

import itertools
import math
import pathlib
import re

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from agent_fleet.restate_analyst import steward_correction as sc
from iagent_mesh.provenance import EvidenceRef as Sdk
from src.iagent import gateway

ROOT = pathlib.Path(__file__).resolve().parents[1]
PX = [223, 917, 661, 953]

_PAGES = [1, 2, 0, -1, "1", 1.0, 1.5, True, None, "x", [], {}]
_BBOXES = [None, [0.1, 0.1, 0.2, 0.2], [0, 0, 1, 1], PX, [-0.1, 0.1, 0.2, 0.2], [0.1, 0.1, 1.0000001, 0.2],
           [0.5, 0.1, 0.5, 0.9], [0.9, 0.1, 0.1, 0.9], [0.1, 0.5, 0.9, 0.5], [0.1, 0.1, 0.2],
           [0.1, 0.1, 0.2, 0.2, 0.3], [], ["0.1", 0.1, 0.2, 0.2], [True, 0.1, 0.5, 0.9], [False, 0.1, 0.5, 0.9],
           [float("nan"), 0, 1, 1], [0, 0, float("inf"), 1], "0.1,0.1,0.2,0.2", {"x0": 0.1}, [[0.1], [0.1], [0.2], [0.2]]]
# every coordinate POSITION out of range, either side (a bound dropped on one position is a pixel hole)
_BBOXES += [[5 if i == j and sign > 0 else (-5 if i == j else (0.1, 0.1, 0.2, 0.2)[j]) for j in range(4)]
            for i in range(4) for sign in (1, -1)]
_NOTES = ["__omit__", None, "", "  ", "x", 5, ["a"]]
_EXTRAS = [{}, {"units": "px"}, {"page_dims": {"width": 1, "height": 1}}, {"bboxes": []}]


def _corpus():
    for p, b, n, x in itertools.product(_PAGES, _BBOXES, _NOTES, _EXTRAS):
        d = {"page": p, "bbox": b, **x}
        if n != "__omit__":
            d["note"] = n
        yield d


def _sdk_errors(d):
    try:
        Sdk.model_validate(d)
        return None
    except ValidationError as e:
        return e


def _gw(d):
    try:
        gateway._wire_evidence_ref(d)
        return None
    except HTTPException as e:
        assert e.status_code == 422, e.status_code
        return e.detail
    except ValueError as e:      # the dependency-layer form (pydantic wraps it into a 422 on the route)
        return {"error": "value_error", "check": None, "msg": str(e)}


def _family(err: ValidationError) -> set[str]:
    out = set()
    for e in err.errors():
        loc = e["loc"][0] if e["loc"] else ""
        if e["type"] == "extra_forbidden":
            out.add("extra_key")
        elif loc == "page":
            out.add("page")
        elif loc == "note":
            out.add("note_blank")
        elif loc == "bbox":
            out.add("bbox")
    return out


def test_c0_the_sdk_checks_are_derived_not_typed():
    """The classes of refusal the SDK has, read from its model: extra=forbid, a validator per field."""
    dec = Sdk.__pydantic_decorators__.field_validators
    assert Sdk.model_config.get("extra") == "forbid"
    assert {f for v in dec.values() for f in v.info.fields} == {"page", "note", "bbox"}
    classes = set()
    for d in _corpus():
        e = _sdk_errors(d)
        if e:
            classes |= _family(e)
    assert classes == {"extra_key", "page", "note_blank", "bbox"}, classes


def test_c1_every_sdk_refusal_is_a_422_naming_a_check_in_the_same_family():
    unnamed, wrong, passed = [], [], []
    for d in _corpus():
        e = _sdk_errors(d)
        if e is None:
            continue
        got = _gw(d)
        if got is None:
            passed.append(d)
            continue
        check = got.get("check")
        if check is None:
            unnamed.append((d, got))
            continue
        if check == "invalid":
            wrong.append((d, check))
    assert not passed, f"{len(passed)} refs the SDK refuses were ACCEPTED, e.g. {passed[:3]}"
    assert not unnamed, f"{len(unnamed)} refusals without a check, e.g. {unnamed[:3]}"
    assert not wrong, f"{len(wrong)} refusals named only `invalid`, e.g. {wrong[:4]}"


def test_c1b_a_single_fault_ref_is_named_in_the_family_of_the_one_field_the_sdk_refused():
    ok = {"extra_key": {"extra_key"}, "page": {"page"}, "note_blank": {"note_blank"},
          "bbox": {"bbox_not_fractions", "bbox_degenerate"}}
    base = {"page": 1, "bbox": [0.1, 0.1, 0.2, 0.2]}
    singles = ([dict(base, page=p) for p in _PAGES] + [dict(base, bbox=b) for b in _BBOXES]
               + [dict(base, note=n) for n in _NOTES if n != "__omit__"] + [dict(base, **x) for x in _EXTRAS])
    wrong, n = [], 0
    for d in singles:
        e = _sdk_errors(d)
        if e is None:
            continue
        n += 1
        check = (_gw(d) or {}).get("check") or ""
        if not any(check.split(":")[0] in ok[f] for f in _family(e)):
            wrong.append((d, check, sorted(_family(e))))
    assert n > 20 and not wrong, (n, wrong[:4])


def test_c2_the_gateway_is_never_looser_and_the_stricter_cases_are_listed():
    """Single-fault refs only, so each stricter case is attributed to the one field that makes it."""
    base = {"page": 1, "bbox": [0.1, 0.1, 0.2, 0.2]}
    singles = ([("page", dict(base, page=p)) for p in _PAGES] + [("bbox", dict(base, bbox=b)) for b in _BBOXES]
               + [("note", dict(base, note=n)) for n in _NOTES if n != "__omit__"])
    # looser anywhere in the full corpus is a defect
    assert [d for d in _corpus() if _sdk_errors(d) is not None and _gw(d) is None] == []
    stricter = {(f, repr(d[f])) for f, d in singles if _sdk_errors(d) is None and _gw(d) is not None}
    assert stricter == {("page", "True"), ("page", "'1'"), ("page", "1.0"), ("note", "None"),
                        ("bbox", "['0.1', 0.1, 0.2, 0.2]"), ("bbox", "[False, 0.1, 0.5, 0.9]")}, sorted(stricter)


def test_c3_a_valid_ref_is_not_refused():
    for d in ({"page": 1, "bbox": [0, 0, 1, 1]}, {"page": 2, "bbox": None}, {"page": 1},
              {"page": 1, "bbox": [0.1, 0.2, 0.3, 0.4], "note": "x"}):
        assert _sdk_errors(d) is None and _gw(d) is None, d


# -- P1: the census -------------------------------------------------------------------------------

def _openapi_request_carriers() -> set[tuple[str, str]]:
    spec = gateway.app.openapi()
    sch = spec["components"]["schemas"]
    found = set()

    def walk(o, route, seen=()):
        if isinstance(o, dict):
            if "$ref" in o:
                n = o["$ref"].split("/")[-1]
                if n not in seen:
                    walk(sch[n], route, seen + (n,))
                return
            for k, v in (o.get("properties") or {}).items():
                is4 = any(a.get("type") == "array" and a.get("minItems") == 4 and a.get("maxItems") == 4
                          for a in [v] + list(v.get("anyOf", [])))
                if "bbox" in k.lower() or "evidence_ref" in k.lower() or is4:
                    found.add((route, k))
            for k, v in o.items():
                walk(v, route, seen)
        elif isinstance(o, list):
            for i in o:
                walk(i, route, seen)

    for path, ops in spec["paths"].items():
        for m, op in ops.items():
            if isinstance(op, dict) and op.get("requestBody"):
                walk(op["requestBody"], f"{m.upper()} {path}")
    return found


def test_p1_the_request_carriers_of_a_box_are_exactly_the_ones_this_review_probed():
    assert _openapi_request_carriers() == {
        ("POST /human_tasks/{task_id}/act", "evidence_ref"),
        ("POST /human_tasks/{task_id}/act", "bbox"),            # review_coverage.shared[].bbox
        ("POST /ingest/{ingest_id}/title_leaf", "evidence_ref"),
        ("POST /ingest/{ingest_id}/title_leaf", "bbox"),
    }


def test_p1_the_source_files_that_name_a_box_are_exactly_the_ones_this_review_read():
    hits = set()
    for base in ("src", "agent_fleet"):
        for p in (ROOT / base).rglob("*.py"):
            if "baml_client" in p.parts or "__pycache__" in p.parts or ".venv" in p.parts:
                continue
            if re.search(r"bbox", p.read_text(encoding="utf-8", errors="ignore"), re.I):
                hits.add(str(p.relative_to(ROOT)).replace("\\", "/"))
    assert hits == {"src/iagent/gateway.py", "src/iagent/ingest_api.py", "src/iagent/ingest_status.py",
                    "src/iagent/promotion.py", "agent_fleet/restate_analyst/steward_correction.py"}, hits


def test_p1_every_inbound_carrier_refuses_a_pixel_box():
    ref = {"page": 3, "bbox": PX}
    assert _gw(ref)["check"] == "bbox_not_fractions"                                    # act: row/header edits
    for model, body in (
        (gateway.TitleEvidenceRef, ref),                                                 # title_leaf
        (gateway.CoverageShared, {"rule": "r", "page": 1, "bbox": PX, "parts": [1], "confirmed": True}),
        (gateway._rcov.ItemCoverageShared, {"rule": "r", "page": 1, "bbox": PX, "parts": [1], "confirmed": True}),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(body)
    assert gateway._backstop_candidates([{"leaf": "pcn", "score": 0.9, "evidence_ref": ref}]) == []   # manifest


# -- P2: the other end of the same edit ----------------------------------------------------------

@pytest.mark.parametrize("bbox", [PX, [-5, 900, 1e9, 2], [0.1, 0.1, 5, 5], [0.5, 0.5, 0.5, 0.5], [0.9, 0.9, 0.1, 0.1]],
                         ids=["pixels", "neg_huge", "partly_pixel", "zero_area", "reversed"])
def test_p2_the_runner_refuses_what_the_bff_refuses(bbox):
    d = {"page": 3, "bbox": bbox}
    assert _gw(d) is not None, "the BFF door must refuse this (control)"
    with pytest.raises(sc.EditRefusal):
        sc.normalize_evidence_ref(d)


def test_p2_control_the_runner_takes_a_fraction_box_and_the_legacy_string():
    assert sc.normalize_evidence_ref({"page": 1, "bbox": [0.1, 0.1, 0.2, 0.2]})["bbox"] == [0.1, 0.1, 0.2, 0.2]
    assert sc.normalize_evidence_ref("page 2, row 1")["note"] == "page 2, row 1"


def test_p2_a_null_note_is_the_sdks_verdict_not_a_literal():
    """Architect 10-31: `note` is absent-or-string. The runner holds no null-note rule of its own; it
    follows the SDK model, so the verdict moves with the pin (v0.9.13 refuses it)."""
    d = {"page": 1, "bbox": [0.1, 0.1, 0.2, 0.2], "note": None}
    if _sdk_errors(d) is None:
        assert sc.normalize_evidence_ref(d)["page"] == 1
    else:
        with pytest.raises(sc.EditRefusal):
            sc.normalize_evidence_ref(d)
