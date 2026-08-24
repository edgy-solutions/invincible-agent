"""THE COVERAGE COUNTER MUST MEASURE THE VECTOR, NOT THE DICT AROUND IT.

Weaviate returns ``{"default": []}`` for a row that was written WITHOUT a
vector. That dict is truthy. A counter written as ``if obj.vector:`` therefore
reports FULL COVERAGE on a collection where every single vector is empty.

This is not hypothetical and it is not a style point. It shipped: the guard
added to make "Predicate rows without vectors" visible — after that exact
state hid for months behind an unread log line — reported 65/65 vectorized on
a collection whose real coverage was 14/65. The instrument built to expose the
defect concealed it, and a guard's green is trusted more than silence, so the
wrong instrument was worse than the missing one.

THE CLASS, now three instances deep in this repo:
    * the DA size gate matched its own explanatory comment
    * the cloud-client check matched the text forbidding cloud clients
    * this counter matched the container instead of the contents

All three assert on something ADJACENT to the claim. The rule they share:
ASSERT ON THE THING THE CLAIM IS ABOUT, and prove the assertion RED before
trusting its green.

Run: uv run --frozen --with pytest pytest tests/test_vector_coverage_counts_content.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "agent_fleet" / "mesh_registrar" / "main.py"


def _rule():
    """Load ONLY the rule, without importing the registrar's whole module.

    main.py pulls in weaviate, fastapi and the mesh client at import time; this
    test must run in CI with none of them present, or it becomes a test that is
    always skipped, which is a test that is not a test.
    """
    src = _SRC.read_text(encoding="utf-8")
    start = src.index("def row_is_vectorized(")
    end = src.index("\ndef ", start + 1)
    ns: dict = {}
    exec(compile(src[start:end], str(_SRC), "exec"), ns)  # noqa: S102
    return ns["row_is_vectorized"]


UNVECTORIZED = [
    pytest.param({"default": []}, id="weaviate's-empty-vector-shape"),
    pytest.param({}, id="no-vector-key-at-all"),
    pytest.param(None, id="attribute-absent"),
    pytest.param({"default": [], "other": []}, id="several-named-empty-vectors"),
]

VECTORIZED = [
    pytest.param({"default": [0.1, 0.2]}, id="a-real-vector"),
    pytest.param({"default": [0.0]}, id="a-single-ZERO-component-is-still-a-vector"),
    pytest.param({"default": [], "named": [0.3]}, id="one-empty-one-real"),
]


@pytest.mark.parametrize("field", UNVECTORIZED)
def test_a_row_with_no_actual_numbers_is_NOT_vectorized(field):
    """The arm that was red. `{"default": []}` is the shape that shipped a lie."""
    assert _rule()(field) is False


@pytest.mark.parametrize("field", VECTORIZED)
def test_a_row_carrying_numbers_IS_vectorized(field):
    """The other direction, so the rule cannot be satisfied by always saying no.

    A counter hardcoded to False would pass every arm above and report zero
    coverage forever — alarming, permanently un-actionable, and eventually
    ignored. Both directions or neither.
    """
    assert _rule()(field) is True


def test_zero_is_data_not_absence():
    """`[0.0]` is a legitimate vector component. A rule that filtered falsy
    NUMBERS rather than empty SEQUENCES would drop real rows and under-report
    coverage — the same confusion as the original bug, one level down."""
    assert _rule()({"default": [0.0, 0.0, 0.0]}) is True
