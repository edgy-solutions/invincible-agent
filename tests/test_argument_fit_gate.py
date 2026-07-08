"""Structural argument-fit gate — the 4th eligibility term (domain ∩ arity ∩
argument-fit ∩ permission). Sibling of the arity gate; same pure-structural,
conservative discipline.

A verb that POSITIVELY declares `required_args` (argument keys it cannot run
without — e.g. filterByTag needs "tag") is ineligible for a query that cannot
supply them: it was never a candidate, so the classifier can't pick a verb it
can't satisfy. Drop iff required_args is NON-empty and NOT ⊆ available_args.

CONSERVATIVE, exactly like arity's null-handling:
  - empty/absent required_args → ALWAYS kept (unconstrained);
  - available_args is None ("no typed-arg signal for this query") → NEVER exclude
    (INERT). This is the guarantee that wiring the term in — while no verb
    declares required_args and no typed-arg resolver exists yet — perturbs
    NOTHING. The value→arg-key resolver (needs the arg's vocab, e.g. DataHub
    tags) travels with the concrete verb; it is NOT a naive entity_refs match
    baked here.

Run:  PYTHONPATH=src pytest tests/test_argument_fit_gate.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent.defs.dynamic_supervisor import _filter_verbs_by_argument_fit  # noqa: E402


def _v(iri, required_args=None):
    return {"verb_iri": iri, "required_args": required_args}


# ---------------------------------------------------------------------------
# THE RED FIXTURE — a tag-requiring verb must NOT survive a query that supplies
# no tag; an unconstrained verb survives. (filterByTag needs "tag".)
# ---------------------------------------------------------------------------
def test_required_arg_absent_is_dropped_present_is_kept():
    verbs = [_v("mesh:filterByTag", ["tag"]), _v("mesh:enumerateCatalog", [])]
    kept, dropped = _filter_verbs_by_argument_fit(verbs, available_args=set())
    assert {v["verb_iri"] for v in kept} == {"mesh:enumerateCatalog"}
    assert [v["verb_iri"] for v in dropped] == ["mesh:filterByTag"]

    # Same verb, query now supplies the tag arg-key → kept.
    kept2, dropped2 = _filter_verbs_by_argument_fit(verbs, available_args={"tag"})
    assert {v["verb_iri"] for v in kept2} == {"mesh:filterByTag", "mesh:enumerateCatalog"}
    assert dropped2 == []


def test_empty_or_absent_required_never_excluded():
    verbs = [_v("a", []), _v("b", None), _v("c")]  # none declare required_args
    kept, dropped = _filter_verbs_by_argument_fit(verbs, available_args=set())
    assert {v["verb_iri"] for v in kept} == {"a", "b", "c"}
    assert dropped == []


def test_required_subset_satisfied_is_kept():
    verbs = [_v("multi", ["tag", "region"])]
    # available has both → kept
    kept, _ = _filter_verbs_by_argument_fit(verbs, available_args={"tag", "region", "extra"})
    assert [v["verb_iri"] for v in kept] == ["multi"]
    # available missing one → dropped (NOT ⊆)
    _, dropped = _filter_verbs_by_argument_fit(verbs, available_args={"tag"})
    assert [v["verb_iri"] for v in dropped] == ["multi"]


# ---------------------------------------------------------------------------
# THE INERTNESS GUARANTEE — available_args=None (no typed-arg signal, today's
# production reality) NEVER excludes anything, even a verb that declares
# required_args. This is what makes wiring the term in pre-flip safe.
# ---------------------------------------------------------------------------
def test_none_available_args_is_inert_even_with_required():
    verbs = [_v("mesh:filterByTag", ["tag"]), _v("mesh:enumerateCatalog", [])]
    kept, dropped = _filter_verbs_by_argument_fit(verbs, available_args=None)
    assert kept == verbs and dropped == []


def test_empty_input_safe():
    assert _filter_verbs_by_argument_fit([], set()) == ([], [])
    assert _filter_verbs_by_argument_fit([], None) == ([], [])
