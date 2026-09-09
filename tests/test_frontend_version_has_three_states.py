"""`frontend_version` — null means the question does not apply, NOT that nobody answered.

**Ruled 2026-09-09:** *"null means 'no frontend applies to this service.' A service that has a
frontend and can't report it is a fault, not a null. Same rule as `favourable`."*

    None        NO FRONTEND APPLIES — an engine, the registrar, a job
    a version   a frontend that knows what it is
    a FAULT     a frontend that HAS a version and cannot report it

**The third must never be laundered into the first.** `null` is a statement that the question
does not apply; a frontend that cannot answer it is a defect wearing that statement's clothes,
and a reader who sees null stops asking.

WHAT MADE THIS URGENT. `frontend_version` was the literal string `"dev"` for the entire life of
the cortex-ui surface — it read an env var nothing in that repo sets — so every registration it
ever made recorded `"dev"`, and the drift detection this field exists for could never have
fired. **A value that is always the same is indistinguishable from a value nobody set.** The
registry then coerced absence to the word `"unknown"`, which is the same defect one layer down:
a plausible word where an absence belongs.

cortex-ui-60 declined to send a unilateral `null` while the field was typed `str`, on the
grounds that a 422 would break registration outright and the wire is not theirs to change.
That was right on both counts, and it is why this change is here rather than there.

Run: uv run --frozen pytest tests/test_frontend_version_has_three_states.py -v
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_REGISTRY = _REPO / "agent_fleet" / "presentation_agent" / "capability_registry.py"
_GATEWAY = _REPO / "src" / "iagent" / "gateway.py"


@pytest.fixture()
def registry(monkeypatch):
    sys.path.insert(0, str(_REPO / "agent_fleet" / "presentation_agent"))
    import capability_registry as cr
    monkeypatch.setattr(cr, "_REGISTRY", {}, raising=False)
    return cr


def _stored(cr, version):
    cr.register("cortex-ui-desktop", version, [{"subject_uri": "x", "archetype": "y"}])
    return cr._REGISTRY["cortex-ui-desktop"]["frontend_version"]


def test_ABSENT_stays_absent(registry):
    """The question does not apply. Any word here — `unknown`, `dev`, `n/a` — reads as a
    reported value and is indistinguishable from a frontend that reported that word."""
    assert _stored(registry, None) is None
    assert _stored(registry, "   ") is None


def test_a_REAL_version_survives_verbatim(registry):
    """The control. A store that returned None for everything would satisfy the test above."""
    assert _stored(registry, "0c6bcaad4f4e") == "0c6bcaad4f4e"


def test_a_FAULT_is_not_laundered_into_absence(registry):
    """THE MIDDLE STATE, AND THE WHOLE POINT. A frontend that HAS a version and cannot report
    it sends a sentinel. Normalising that to None would say "no frontend applies" about a
    frontend that is right there and broken — and a reader who sees null stops asking."""
    assert _stored(registry, "unstamped") == "unstamped"


def test_the_three_are_DISTINGUISHABLE(registry):
    """A collapse is a property about a SET, so it needs an assertion about the set. Each
    test above could pass against a store that returned its own input unchanged, or against
    one that returned None for everything, if each case happened to expect that."""
    seen = {_stored(registry, v) for v in (None, "0c6bcaad4f4e", "unstamped")}
    assert len(seen) == 3, f"the three states collapsed to {seen}"


def test_the_WIRE_accepts_absence():
    """The model must permit None, or a caller with no frontend gets a 422 and registration
    fails outright — which is exactly why cortex-ui-60 kept sending a sentinel rather than
    unilaterally sending null. Read by AST from the annotation, so a widened type that is
    never used still counts and a narrowed one goes red."""
    tree = ast.parse(_GATEWAY.read_text(encoding="utf-8"))
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
               and n.name == "RegisterFrontendCapabilitiesRequest")
    ann = next(n for n in cls.body
               if isinstance(n, ast.AnnAssign)
               and getattr(n.target, "id", "") == "frontend_version")
    text = ast.unparse(ann.annotation)
    assert "None" in text, f"the wire still requires a version: {text}"
    assert ann.value is not None, "nullable but with no default — an omitted field still 422s"


def test_None_does_not_reach_the_mesh_as_the_STRING_None():
    """The downstream helper is typed `version: str`. `str(None)` puts the word "None" into
    the graph, where a reader sees it as a version — the same class of defect as `"dev"`, and
    invisible for the same reason. Asserted on the call site's expression."""
    tree = ast.parse(_GATEWAY.read_text(encoding="utf-8"))
    kws = [
        ast.unparse(k.value)
        for n in ast.walk(tree) if isinstance(n, ast.Call)
        for k in n.keywords
        if k.arg == "version" and "frontend_version" in ast.unparse(k.value)
    ]
    assert kws, "no call site passes frontend_version as a version"
    for expr in kws:
        assert "or" in expr, (
            f"frontend_version reaches a str-typed parameter unguarded: {expr!r} — None "
            f"becomes the word 'None' in the graph"
        )


def test_the_registry_signature_admits_absence():
    """A stored None that the signature forbids is a type lie the next reader inherits."""
    tree = ast.parse(_REGISTRY.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "register")
    arg = next(a for a in fn.args.args if a.arg == "frontend_version")
    assert arg.annotation is not None and "None" in ast.unparse(arg.annotation)
