"""Standing-guard invariants for Recipe v2.

These tests don't exercise the system — they enforce the architectural
rule that the recipe was built around: lexical pattern → ontology
class assignments are FORBIDDEN inside Engine O. If a future patch
tries to bring back the dotted-path bias (or any sibling shape →
kind mapping — DMC regex, tail-number regex, etc.) at the router
layer, these tests turn red before that patch can ship.

The rule (Recipe v2 §1):
  "Spotting a name may only decide 'consult the phone books with this
   token.' Nothing may EVER decide what kind the thing is from the
   token's shape."

Where shape→class IS allowed: inside a phone-book provider (Engine D
uses DataHub's authoritative entity type; a future docs provider can
look at DMC structure). Where it's forbidden: Engine O's resolver
code and ontology service. Test files are exempt — strings like
'idp:Table' appearing in test assertions are fine.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_ENGINE_O_ROOT = Path(__file__).resolve().parents[2] / "agent_fleet" / "ontology_service"


# Source files inside Engine O that are NOT exempt from the no-lexical-
# class-mapping rule. instance_resolution.py is allowed to reference
# class URIs because the decision table consumes them; what it must NOT
# do is derive them from string shape.
_ENGINE_O_RESOLVER_SOURCES = [
    _ENGINE_O_ROOT / "main.py",
    _ENGINE_O_ROOT / "registry_views.py",
    _ENGINE_O_ROOT / "instance_resolution.py",
]


# Patterns that would indicate a lexical→class mapping reappearing in
# the router. Each entry is (regex, why_it_is_forbidden). The regex
# must match patterns the recipe explicitly bans; not be so permissive
# it fires on legitimate code.
_FORBIDDEN_PATTERNS = [
    (
        re.compile(r"""\.count\(['"]\.['"]\)\s*[><=!]+\s*\d""", re.MULTILINE),
        "Counts dots in a token — the canonical dot-counting heuristic the recipe forbids.",
    ),
    (
        re.compile(r"""re\.(?:match|search|fullmatch)\([^,]*['"][^'"]*\\\.[^'"]*['"]""", re.MULTILINE),
        "Regex over dot-shaped strings inside Engine O — likely lexical-class mapping.",
    ),
    (
        re.compile(r"""if\s+['"]\.['"]\s+in\s+\w+:\s*\n\s*[^#].*idp:""", re.MULTILINE),
        "Branches on 'dot is in token' to assign an idp:* class — forbidden by recipe.",
    ),
]


def _read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "src_path", [p for p in _ENGINE_O_RESOLVER_SOURCES if p.exists()],
    ids=lambda p: p.name,
)
def test_no_lexical_class_mapping(src_path: Path) -> None:
    """Catch the dot-counting / shape-to-class disease reappearing."""
    src = _read_source(src_path)
    for pattern, reason in _FORBIDDEN_PATTERNS:
        match = pattern.search(src)
        assert match is None, (
            f"\n  {src_path.name}: forbidden lexical-class pattern detected\n"
            f"  Pattern: {pattern.pattern!r}\n"
            f"  Reason: {reason}\n"
            f"  Match:  {match.group(0)!r}\n"
            f"\n  Recipe v2 §1: 'spotting a name may only decide consult the "
            f"phone books with this token. Nothing may EVER decide what kind "
            f"the thing is from the token's shape.' If you need shape→class "
            f"logic, put it inside a phone-book provider, not Engine O."
        )


def test_engine_o_imports_decision_table_from_pure_module() -> None:
    """The decision table must remain in its dedicated pure-logic
    module — that's what keeps it testable without a cluster. Moving
    the function inline into main.py would silently kill the pure
    tests in test_instance_resolution_decision.py."""
    main_src = _read_source(_ENGINE_O_ROOT / "main.py")
    assert "from agent_fleet.ontology_service.instance_resolution import" in main_src, (
        "Engine O's main.py must import the decision table from "
        "instance_resolution.py (the pure module) — do NOT inline the "
        "decision logic."
    )


def test_engine_d_url_is_not_hardcoded_in_engine_o() -> None:
    """Provider URLs come from the predicate-graph registry, not from
    code constants in the router. If any backend's name or URL is
    hardcoded inside Engine O, the discovery design has failed and
    adding the second provider (Engine E) will need router changes —
    which is exactly the failure mode Recipe v2's generality gate is
    designed to catch."""
    forbidden = [
        "iagent-engine-d",        # k8s service name
        "datahub_wrapper",        # provider module name
        "DATAHUB_WRAPPER_SVC_URL",  # provider-specific env var
        "iagent-mesh-registrar",  # gateway URL doesn't belong in router either
    ]
    for src_path in _ENGINE_O_RESOLVER_SOURCES:
        if not src_path.exists():
            continue
        src = _read_source(src_path)
        for token in forbidden:
            assert token not in src, (
                f"\n  {src_path.name}: backend-specific name {token!r} "
                f"hardcoded in router code.\n"
                f"  Recipe v2 §1: 'No `if datahub` / `ENGINE_D_URL` / any "
                f"backend name inside Engine O. The router stays backend-"
                f"blind. Phone books are discovered from the registry, "
                f"like every other capability in this system.'"
            )
