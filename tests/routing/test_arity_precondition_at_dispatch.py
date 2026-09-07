"""A FLAGGED SINGLE-ASSET VERB MAY NOT DISPATCH WITHOUT ITS INSTANCE.

THE RULING (2026-09-04). The arity gate excluded a single-asset verb from a set-shaped
question, and that cost H06 its answer: "what is the capability path" grounds to `Capability`
cleanly and then reports NO VERB CLASSIFIED, because `planCapabilityPath` is arity=single, the
question names no instance, and the only verb that fits is removed FOR THE REASON IT WOULD HAVE
ASKED ABOUT. So the gate now FLAGS `needs_instance` and keeps the verb.

AND THE FLAG ALONE WOULD RESURRECT THE DEFECT THE GATE WAS BUILT FOR. That is the half this
file exists for. `arity_for` DERIVES "single" for planning's measures from one condition — a
slot both required and a referent — which is exactly what `decide_disposition` asks about, so
those verbs are safe to keep by construction. **But `arity` is a DECLARED string on a mesh
registration for every other engine**, and it promises nothing about slots. `describeAsset` is
that case, and it is the original defect: `show me data about customers` resolved to the class
Dataset, routed to a single-asset profiler, and honestly returned `assets: []`. With no
spoken-mandatory declaration, `decide_disposition` walks nothing, returns ROUTE, and that zero
comes straight back.

So the guarantee moved rather than weakened: it is now a DISPATCH PRECONDITION at the
disposition point. Asked-and-answered binds the instance and it never fires; nothing-to-ask
abstains instead of dispatching.

WHY THE CONDITION IS "NOTHING ASKABLE" AND NOT "NO INSTANCE BOUND". A BIND answer arrives here
as an accepted param, and the disposition then returns ROUTE — abstaining on that would refuse
a question the user had just answered. `needs_instance` is only ever set when the query was
set-shaped to begin with, so the shape is already implied and the open question is solely
whether an ask was ever possible.

Run: uv run --frozen pytest tests/routing/test_arity_precondition_at_dispatch.py -v
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SUP = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")


def _precondition_window() -> str:
    i = _SUP.index("arity_precondition")
    return _SUP[max(0, i - 1800):i + 900]


# ── the flag has to reach the disposition at all ────────────────────────────

def test_the_flag_is_carried_onto_the_dispatch_predicate():
    """The gate marks the compat-walk entry; the dispatch reads `predicate`. Without this
    carry the precondition can never fire — a guard reading a key nobody writes, which is
    the silent-default shape this repo has removed repeatedly."""
    assert 'predicate["needs_instance"] = True' in _SUP


def _carries_needs_instance(node) -> bool:
    """Does this block assign `<something>["needs_instance"] = True`?"""
    import ast as _ast
    for n in _ast.walk(node):
        if not isinstance(n, _ast.Assign):
            continue
        for t in n.targets:
            if (isinstance(t, _ast.Subscript)
                    and isinstance(t.slice, _ast.Constant)
                    and t.slice.value == "needs_instance"):
                return True
    return False


def test_the_carry_sits_where_neo4j_is_already_authoritative():
    """Placed inside the compat-walk `truth` block deliberately: that seam already treats the
    record as the source of dispatch coordinates, so the flag travels with them rather than
    being a second, separately-maintained hop.

    ASSERTED ON THE AST. This read `_SUP[i - 900:i]` where `i` was the index of
    `predicate["needs_instance"] = True` -- and on 2026-09-07 the pre-resolved path added
    `_pre_predicate["needs_instance"] = True`, of which the old needle is a SUBSTRING. So
    `index` began matching the new line, the 900-character window slid onto its comment, and
    the test failed while both carries were correct. Fifth magic-span rot in this repo, and
    the first caused by a substring rather than by length.

    BOTH carries are checked now, because there are two seams and each is one edit from
    silently losing the flag -- and a verb whose flag is lost dispatches against a set query
    instead of asking.
    """
    import ast as _ast
    tree = _ast.parse(_SUP)
    blocks = [
        n for n in _ast.walk(tree)
        if isinstance(n, _ast.If) and _carries_needs_instance(n)
    ]
    tests = {_ast.unparse(b.test) for b in blocks}
    assert any("truth" in t for t in tests), (
        f"the needs_instance carry is not inside a compat-walk `truth` block: {tests}"
    )
    assert any("_pre_truth" in t for t in tests), (
        "the PRE-RESOLVED path does not carry needs_instance — a single-asset verb would "
        "dispatch against a set query on that path while the full path correctly asks"
    )


# ── the precondition itself ─────────────────────────────────────────────────

def test_the_precondition_exists_and_abstains():
    w = _precondition_window()
    assert "disposition.action == ROUTE" in w
    assert 'get("needs_instance")' in w
    assert "action=ABSTAIN" in w


def test_it_fires_only_when_nothing_was_askable():
    """The narrow condition. Abstaining whenever no instance is bound would refuse a BIND
    the user just answered, because a filled slot returns ROUTE."""
    w = _precondition_window()
    assert "_askable" in w
    assert "_MUST_BE_SPOKEN_KINDS" in w
    assert "not _askable" in w


def test_it_does_not_fire_on_an_ask_or_an_abstain():
    """Only a ROUTE is converted. An ASK is the outcome this whole change exists to reach,
    and re-deciding an ABSTAIN would double-report it."""
    w = _precondition_window()
    m = re.search(r"if \(\s*disposition\.action == (\w+)", w)
    assert m and m.group(1) == "ROUTE"


def test_the_abstention_carries_a_distinguishable_reason():
    """A bare abstain is indistinguishable from every other abstain in the artifact. This
    one has a specific cause a reader can act on: the verb needed an instance and the
    system had no way to ask."""
    assert 'reason="needs_instance_no_ask"' in _SUP


def test_the_refusal_is_not_silent():
    """The defect being prevented is an answer that looks fine. A refusal nobody can find
    in the logs moves the problem rather than closing it."""
    assert "arity_precondition" in _SUP
    w = _precondition_window()
    assert "context.log.info" in w


# ── the constants it depends on are actually imported ───────────────────────

def test_ROUTE_and_ABSTAIN_are_imported():
    """A NameError here would be caught by any run — but this file is the reason the import
    exists, so it goes red here rather than in an unrelated dispatch test."""
    tree = ast.parse(_SUP)
    imported: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (n.module or "").endswith("slot_disposition"):
            imported |= {a.name for a in n.names}
    assert {"ROUTE", "ABSTAIN"} <= imported, f"imported: {sorted(imported)}"


# ── the gate must no longer exclude ─────────────────────────────────────────

def test_the_gate_no_longer_removes_a_candidate():
    """The H06 regression, pinned at the source. If the gate goes back to dropping, the
    pool empties on a set-shaped question and the classifier gets nothing to pick."""
    i = _SUP.index("def _filter_verbs_by_arity")
    body = _SUP[i:i + 3600]
    assert 'marked["needs_instance"] = True' in body
    assert "dropped.append(v)" not in body, (
        "the gate is excluding again — that is the defect H06 surfaced"
    )
