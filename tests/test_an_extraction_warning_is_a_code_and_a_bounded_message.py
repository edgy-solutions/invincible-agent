"""An extraction warning that reaches a person is a code and a bounded message.

Ruling (architect, 2026-11-19): raw prompts, raw model replies and raw exception text stay in
telemetry and in the artifact; they never reach a review card or a triage task. The hop was
`doc_review_reasons` -> `extraction_warnings`, copied verbatim.

Run:  uv run --frozen python -m pytest tests/test_an_extraction_warning_is_a_code_and_a_bounded_message.py -q
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from iagent.extraction_warning import (  # noqa: E402
    CODE_RE, FALLBACK_CODE, WITHHELD, bound_warnings, bounded_detail,
)
from iagent.review_payload import build_start_review_payload  # noqa: E402

_SENSOR = _ROOT / "src" / "iagent" / "defs" / "extraction_review_sensor.py"
_spec = importlib.util.spec_from_file_location("ers_bounded", _SENSOR)
ers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ers)  # type: ignore[union-attr]

CANARY = "SECRETWORD-77"
RAW = ("header extraction failed: Error: model reply was not JSON. PROMPT: You are an extraction "
       "assistant. Extract the header fields from ...\nRAW REPLY: {\"doc_id\": \"SECRETWORD-77\" ...")
# The canary inside the first 160 characters once the newline is gone (a truncating bounder leaks).
RAW_EARLY = "Error: SECRETWORD-77 PROMPT: " + "y" * 50 + "\n" + "z" * 200
PRODUCER = "2/5 table crops failed — parts likely INCOMPLETE"
HEADER_BOUNDED = {"code": "header_extraction_failed",
                  "message": "Header extraction failed; the detail is withheld."}

_DICTS = [
    {"reason_code": "model_output_invalid", "reason": "the reply was not valid JSON", "raw": RAW},
    {"code": "BAD CODE", "message": "x" * 161, "telemetry_ref": "run-1"},
    {"code": "ok_code", "message": "fine", "telemetry_ref": "run\n1"},
]
CORPUS = [None, "", "  ", "a\rb", "x" * 160, "x" * 161, 42, ["list"], {}, RAW,
          "Vision crop failed: " + RAW, RAW_EARLY, PRODUCER, *_DICTS]


def _review_json(reasons):
    return {"doc_id": "D-1", "doc_type": "PDN", "needs_review": True,
            "doc_review_reasons": reasons,
            "review_items": [{"field_path": "parts[0].affected_mpn", "value": "MPN-A"}]}


def _leaks(obj) -> bool:
    s = json.dumps(obj)
    return CANARY in s or "PROMPT:" in s


def test_e1_the_hop_carries_a_code_and_a_bounded_message():
    payload = build_start_review_payload(_review_json([RAW, PRODUCER]))
    assert payload["extraction_warnings"] == [
        HEADER_BOUNDED, {"code": FALLBACK_CODE, "message": PRODUCER}]
    assert not _leaks(payload)


def test_e2_dict_forms():
    out = bound_warnings(_DICTS)
    assert out[0] == {"code": "model_output_invalid", "message": "the reply was not valid JSON"}
    assert out[1] == {"code": FALLBACK_CODE, "message": WITHHELD, "telemetry_ref": "run-1"}
    assert "telemetry_ref" not in out[2]


def test_e3_every_output_is_drawable_by_cortex():
    out = bound_warnings(CORPUS)
    assert out
    for e in out:
        assert set(e) <= {"code", "message", "telemetry_ref"}, e
        assert CODE_RE.match(e["code"]), e
        m = e["message"]
        assert isinstance(m, str) and "\n" not in m and "\r" not in m, e
        assert 0 < len(m) <= 160 and m == m.strip(), e
        assert not _leaks(e), e
    msgs = [e["message"] for e in bound_warnings(["x" * 160, "x" * 161])]
    assert msgs == ["x" * 160, WITHHELD]          # the boundary: kept verbatim / withheld, never cut
    assert bound_warnings(["a\rb"])[0]["message"] == WITHHELD
    assert not _leaks(bound_warnings([RAW_EARLY]))


def test_e4_idempotent():
    once = bound_warnings(CORPUS)
    assert bound_warnings(once) == once


def _is_bound_call(node) -> bool:
    return (isinstance(node, ast.Call)
            and ((isinstance(node.func, ast.Name) and node.func.id == "bound_warnings")
                 or (isinstance(node.func, ast.Attribute) and node.func.attr == "bound_warnings")))


def _unbounded_sites(src: str):
    """Line of every dict-literal key "extraction_warnings" whose value is not bound_warnings(...)."""
    bad = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "extraction_warnings" \
                        and not _is_bound_call(v):
                    bad.append(k.lineno)
    return bad


def _gateway_values():
    tree = ast.parse((_ROOT / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8"))
    return [v for n in ast.walk(tree) if isinstance(n, ast.Dict)
            for k, v in zip(n.keys, n.values)
            if isinstance(k, ast.Constant) and k.value == "extraction_warnings"]


def test_e5_gateway_ingress_is_bounded_ast_arm():
    """AST arm: no existing harness drives the start route with a Restate double."""
    sites = [v for v in _gateway_values()
             if _is_bound_call(v) and ast.unparse(v) == "bound_warnings(req.extraction_warnings)"]
    assert len(sites) == 1, "the start body must bound req.extraction_warnings"


def test_e6_gateway_egress_is_bounded_ast_arm():
    """AST arm: no existing harness drives the batch route."""
    sites = [v for v in _gateway_values()
             if _is_bound_call(v) and "b.get('extraction_warnings')" in ast.unparse(v)]
    assert len(sites) == 1, "the batch read must bound the stored warnings"


def test_e7_triage_carries_no_raw_text():
    out = ers.build_triage_payload(source_key="k", notice_id="N", reason_code="RULES_NOT_FOUND",
                                   detail="RULES_NOT_FOUND: " + RAW, warnings=[RAW])
    assert not _leaks(out)
    assert out["payload"]["warnings"] == [HEADER_BOUNDED]
    d = out["payload"]["detail"]
    assert "\n" not in d and len(d) <= 160 and d.startswith("RULES_NOT_FOUND")
    ctl = "NO_PARTS_EXTRACTED: the extraction produced no parts"
    out = ers.build_triage_payload(source_key="k", notice_id="N", reason_code="NO_PARTS_EXTRACTED",
                                   detail=ctl)
    assert out["payload"]["detail"] == ctl
    assert bounded_detail(ctl, code="X") == ctl


# E8. Census by FORM. Exemptions: path -> reason. Empty unless a site is not person-facing.
_EXEMPT: dict[str, str] = {}


def test_e8_every_extraction_warnings_literal_is_bounded():
    assert _unbounded_sites('{"extraction_warnings": list(x)}'), "positive control: detector is dead"
    assert not _unbounded_sites('{"extraction_warnings": bound_warnings(x)}')
    found = {}
    for p in sorted((_ROOT / "src" / "iagent").rglob("*.py")):
        if ".venv" in p.parts:
            continue
        bad = _unbounded_sites(p.read_text(encoding="utf-8"))
        if bad:
            found[p.relative_to(_ROOT).as_posix()] = bad
    unexpected = {k: v for k, v in found.items() if k not in _EXEMPT}
    assert not unexpected, f"unbounded extraction_warnings reaching a person: {unexpected}"
    stale = [k for k in _EXEMPT if k not in found]
    assert not stale, f"stale exemptions: {stale}"
