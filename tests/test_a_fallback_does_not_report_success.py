"""A FALLBACK MUST NOT LOG SUCCESS — the direct-emit path is an audit record, not a
registration.

MEASURED 2026-09-08 on engine-f, immediately after the fleet re-registered. Two
presentations were rejected by the gateway under Contract D for missing object classes, and
each rejection was followed — three lines later, same presentation — by:

    ⚠️  presentation ..._for_categorybreakdown FELL BACK to direct DataHub emit
        reason class: gateway-rejected-REFUSED ... The fallback writes an AUDIT RECORD ONLY:
        no rendersAs row reaches Weaviate, so this presentation stays undiscoverable ...
    ✅ Registered presentation urn:...categorybreakdown as (cost:CategoryBreakdown -> ...)

The second line is only ever reached on the fallback path: the gateway-accepted case returns
earlier with its own "registered VIA GATEWAY" message. So the ✅ was unconditionally false,
and it contradicted a warning the same function had just emitted.

WHY THE WORD MATTERS MORE THAN THE LEVEL. A person scanning for green ticks reads it as done.
Worse, this is the natural signal a readiness probe would be built on — and the readiness work
was next on the list. A probe keyed to this line would have reported ready for an engine whose
presentations reach nobody, which is the same latent shape as the seven engines that served
UNREGISTERED for four hours behind passing probes.

Same family as `classify_called` reporting `false` for a classifier that ran, and as the
projector reading four properties nothing wrote: a field or a message that states an outcome
it never checked.

Run: uv run --frozen pytest tests/test_a_fallback_does_not_report_success.py -v
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_MOD = _REPO / "agent_fleet" / "utils" / "mesh_registration.py"
_SRC = _MOD.read_text(encoding="utf-8")


def _fn(name: str) -> ast.FunctionDef:
    fn = next(
        (n for n in ast.walk(ast.parse(_SRC))
         if isinstance(n, ast.FunctionDef) and n.name == name),
        None,
    )
    assert fn is not None, f"{name} not found"
    return fn


def _log_calls(fn: ast.AST) -> list[tuple[str, str]]:
    """(level, first-format-arg) for every logger.<level>(...) in the function."""
    out = []
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if not (isinstance(f, ast.Attribute) and getattr(f.value, "id", "") == "logger"):
            continue
        if not n.args:
            continue
        first = n.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            out.append((f.attr, first.value))
        elif isinstance(first, ast.JoinedStr):
            out.append((f.attr, ast.unparse(first)))
    return out


_SUCCESS_MARKERS = ("✅", "Registered ", "registered VIA")


def test_the_direct_emit_branch_does_not_claim_registration():
    """THE DEFECT. The emit inside the fallback's `try` must not report success — it wrote an
    audit record, and the function has already said so."""
    fn = _fn("register_presentation_to_mesh")
    tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try)]
    assert tries, "the direct emit is no longer wrapped — this test is looking at the wrong shape"

    offenders = []
    for t in tries:
        for lvl, msg in _log_calls(ast.Module(body=t.body, type_ignores=[])):
            if any(m in msg for m in _SUCCESS_MARKERS):
                offenders.append(f"logger.{lvl}({msg[:70]!r})")
    assert not offenders, (
        f"the fallback emit reports success: {offenders} — it writes an audit record only, "
        f"and the warning above it says so"
    )


def test_it_still_says_what_DID_happen():
    """THE POSITIVE CONTROL. Deleting the line entirely would satisfy the assertion above and
    lose the record that a claim was written at all — which is the one thing the audit path
    exists to do."""
    fn = _fn("register_presentation_to_mesh")
    msgs = [m for _, m in _log_calls(fn)]
    assert any("audit record only" in m.lower() for m in msgs), (
        "nothing reports that an audit record was written"
    )
    assert any("NOT registered" in m for m in msgs), (
        "the fallback no longer states that this is not a registration"
    )


def test_the_reason_class_reaches_the_line_that_reports_the_outcome():
    """The three reason classes have OPPOSITE repairs and one symptom (rendersAs stays 0), so
    the line stating the outcome must name which one it was. The earlier warning names it —
    but that warning does not fire on the `no-registrar-url` path, which reaches the emit
    with no prior explanation at all."""
    fn = _fn("register_presentation_to_mesh")
    for lvl, msg in _log_calls(fn):
        if "audit record only" in msg.lower():
            return
    raise AssertionError("no outcome line found to check")


def test_the_GATEWAY_path_still_reports_success_and_is_the_only_one_that_does():
    """THE OTHER HALF, and the reason this is not just 'remove the tick'. A real registration
    happened when the gateway accepted, and that must still say so — otherwise the fix trades
    a false success for a false failure."""
    fn = _fn("register_presentation_to_mesh")
    successes = [
        (lvl, msg) for lvl, msg in _log_calls(fn)
        if any(m in msg for m in _SUCCESS_MARKERS)
    ]
    assert successes, "no success line survives — a real registration now reports nothing"
    for lvl, msg in successes:
        assert "GATEWAY" in msg or "gateway" in msg, (
            f"a success line that is not the gateway path: logger.{lvl}({msg[:70]!r})"
        )


def test_the_warning_about_the_fallback_still_names_all_three_reason_classes():
    """Non-vacuity for the module's own documentation of the repairs — they are what make the
    reason class worth carrying, and a fix that quietly dropped them would pass everything
    above."""
    for cls in ("gateway-rejected-STALE-IMAGE", "gateway-rejected-REFUSED",
                "gateway-unreachable"):
        assert cls in _SRC, f"the {cls} repair note is gone"
