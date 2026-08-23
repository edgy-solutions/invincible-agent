"""THE NUMBER-CHECK — and its equivalence classes, stated per DIRECTION.

Gate 2 names one adversarial test explicitly: a narration with an invented
number, demonstrably stripped. That arm is here, plus the equivalence classes
around it — because "every numeric token appears in the rows" is only as honest
as its definition of *appears*, and that definition is where number-checks
quietly rot.

THE RULE, one sentence, directional by construction:

    A narration token matches a row value if the token, interpreted AT ITS OWN
    PRECISION, equals that row value ROUNDED TO THE SAME PRECISION.

  * `$1.2M` MATCHES 1,247,332 — display rounds truth, and prose may project.
  * `1247332` does NOT match a row of only 1,200,000 — precision appearing from
    nowhere is an invented number wearing a formatting excuse, and a figure to
    two decimals is exactly what a reader trusts most.

Every class below is tested in BOTH directions, because a checker that only ever
sees the permissive direction blesses the other one by omission.

Run: uv run --frozen --with pytest pytest tests/planning/test_number_check.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "agent_fleet" / "planning_agent" / "number_check.py"


def _mod():
    spec = importlib.util.spec_from_file_location("number_check__test", _SRC)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


# ── THE ADVERSARIAL ARM — Gate 2's named requirement ───────────────────────

def test_an_INVENTED_number_strips_its_sentence():
    """GATE 2's NAMED TEST. The number does not appear in the rows at any
    precision, so the sentence carrying it does not survive."""
    m = _mod()
    rows = [{"period": "FY26-Q1", "amount": 1200000}]
    text = "Spend in FY26-Q1 is 1200000. The programme will overrun by 4400000."
    clean, violations = m.check_narration(text, rows)
    assert "4400000" not in clean, "an invented figure survived into the caption"
    assert "1200000" in clean, "a SUPPORTED sentence was stripped along with the bad one"
    assert any(v["value"] == 4400000 for v in violations)


def test_stripping_is_per_SENTENCE_not_per_token():
    """Removing the token alone would leave a grammatical claim whose subject
    has quietly changed — "the programme will overrun by " is not safer, it is
    a sentence missing its object."""
    m = _mod()
    clean, _ = m.check_narration("Total is 500. Growth is 999.", [{"v": 500}])
    assert clean == "Total is 500."


def test_everything_unsupported_leaves_an_EMPTY_string_for_the_caller():
    """The caller renders a template caption. A caption is a good day compared to
    a confident invented figure."""
    m = _mod()
    clean, violations = m.check_narration("It rose by 42 percent to 9999.", [{"v": 1}])
    assert clean == ""
    assert violations


# ── EQUIVALENCE CLASSES, PERMISSIVE DIRECTION (prose projects the rows) ────

@pytest.mark.parametrize("prose,rows,why", [
    ("Total is 1200000.",      [{"v": 1200000}], "plain integer"),
    ("Total is 1,200,000.",    [{"v": 1200000}], "thousands separators"),
    ("Total is $1.2M.",        [{"v": 1200000}], "currency + magnitude suffix"),
    ("Total is 1.2m.",         [{"v": 1200000}], "lowercase magnitude"),
    ("Load is 450k.",          [{"v": 450000}],  "k suffix"),
    ("Level is 3.5.",          [{"v": 3.5}],     "decimal"),
    ("Delta is -500.",         [{"v": -500}],    "negative"),
    ("Share is 12%.",          [{"v": 12}],      "percent matches its numeric part"),
    ("Spend is $1.2M.",        [{"v": 1247332}], "ROUNDING PROJECTION: display rounds truth"),
    ("Period is FY26-Q3.",     [{"period": "FY26-Q3"}], "numbers mined from row STRINGS"),
])
def test_a_faithful_projection_is_ACCEPTED(prose, rows, why):
    m = _mod()
    clean, violations = m.check_narration(prose, rows)
    assert not violations, f"{why}: rejected a faithful projection {violations}"
    assert clean == prose


# ── THE SAME CLASSES, RESTRICTIVE DIRECTION (prose invents precision) ──────

@pytest.mark.parametrize("prose,rows,why", [
    ("Total is 1247332.", [{"v": 1200000}],
     "PRECISION FROM NOWHERE — the row is coarse, the prose is exact"),
    ("Total is $1.5M.",   [{"v": 1247332}],
     "wrong rounding — 1.247M does not round to 1.5M"),
    ("Level is 3.7.",     [{"v": 3.5}],
     "a decimal that is simply different"),
    ("Delta is 500.",     [{"v": -500}],
     "sign dropped — magnitude alone is a different claim"),
    ("Share is 12%.",     [{"v": 0.12}],
     "RATIO IS NOT CONVERTED — treating 0.12 as 12% blesses a different quantity"),
    ("Spend reaches 2027.", [{"period": "FY26-Q3", "v": 5}],
     "a YEAR the rows do not contain is a temporal claim the data does not support"),
])
def test_precision_or_meaning_from_NOWHERE_is_REFUSED(prose, rows, why):
    m = _mod()
    _clean, violations = m.check_narration(prose, rows)
    assert violations, f"{why}: accepted an unsupported number"


# ── PARSING ────────────────────────────────────────────────────────────────

def test_magnitude_suffixes_lower_the_claimed_precision():
    """`$1.2M` claims one decimal OF A MILLION — a resolution of 100,000 — which
    is what lets it tolerate 1,247,332 while `1200000` does not."""
    m = _mod()
    (_lit, value, dec), = m.parse_tokens("$1.2M")
    assert value == 1_200_000
    assert dec == -5


def test_a_bare_integer_claims_UNIT_precision():
    m = _mod()
    (_lit, value, dec), = m.parse_tokens("1200000")
    assert (value, dec) == (1_200_000, 0)


def test_booleans_in_rows_are_not_mined_as_numbers():
    """`bool` is an int subclass; True is not the number 1, and treating it as
    one would silently support a narration citing '1'."""
    m = _mod()
    _clean, violations = m.check_narration("Count is 1.", [{"flag": True}])
    assert violations, "True was mined as the number 1"


def test_prose_with_no_numbers_passes_untouched():
    """The check must not become a general prose filter."""
    m = _mod()
    text = "Spend is concentrated in the later periods."
    clean, violations = m.check_narration(text, [{"v": 5}])
    assert clean == text and not violations
