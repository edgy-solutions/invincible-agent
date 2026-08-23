"""THE NARRATION CONTRACT — every number in the prose must come from the rows.

Views cannot lie because they are drawn from rows. This holds the prose to the
same standard: the LLM sees ONLY result rows and writes at most two sentences,
and any sentence containing a number that is not supported by those rows is
STRIPPED and replaced by a template caption.

WHY A PURE FUNCTION. The adversarial case — a narration with an invented number,
demonstrably stripped — must be testable without an LLM in the loop, or the arm
that matters most only runs when a model happens to hallucinate. The BFF wiring
is a separate, thin concern.

── THE MATCHING RULE, AND IT IS DIRECTIONAL ────────────────────────────────────

    A narration token matches a row value if the token, interpreted AT ITS OWN
    PRECISION, equals that row value ROUNDED TO THE SAME PRECISION.

One rule, and the direction falls out of it:

  * `$1.2M` in prose MATCHES a row value of 1,247,332. Display rounds truth, and
    a narration is allowed to be a projection of the data.
  * `1247332` in prose does NOT match a row that only carries 1,200,000. At full
    precision 1,200,000 is 1,200,000, so the extra digits are unsupported.

**Narration formats may be projections of row values, never the reverse.**
Precision appearing from nowhere is an invented number wearing a formatting
excuse, and it is exactly what a reader trusts most — a figure to two decimals
reads as measured.

── WHAT COUNTS AS A NUMBER, INCLUDING A DELIBERATE STRICTNESS ─────────────────

Every numeric token in the final-channel text is a CLAIM requiring support,
including year-like tokens. A narration naming a year the rows do not contain is
making a temporal claim the data does not support — "spend rises through 2027"
when the rows stop at FY26 is precisely the confident extrapolation this check
exists to catch.

This is deliberately strict and may fire on harmless phrasing. That is a
MEASURED cost: the eval records which arm each failure died on, so if year
tokens prove to be noise the evidence will say so. Loosening it now on the
theory that it might be annoying would be tuning a guard against an unmeasured
inconvenience.

Percent tokens match on their NUMERIC PART only: `12%` matches a row value of
12. Ratio conversion is NOT performed — silently treating 0.12 as equivalent to
12% is the kind of helpful equivalence that blesses a wrong number, and the two
are different claims about different quantities.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

#: Magnitude suffixes a narration may use as a projection of a raw row value.
_MAGNITUDES = {"k": 1_000, "m": 1_000_000, "bn": 1_000_000_000, "b": 1_000_000_000}

#: A numeric token: optional currency, digits with optional separators and
#: decimals, optional magnitude suffix, optional percent.
_TOKEN = re.compile(
    r"(?<![\w.])"
    r"(?P<sign>-)?"
    r"[$£€]?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<mag>bn|[kmb])?"
    r"(?P<pct>%)?"
    r"(?![\w])",
    re.IGNORECASE,
)


def _decimals(literal: str) -> int:
    """Decimal places the author actually wrote — this IS the claimed precision."""
    return len(literal.split(".", 1)[1]) if "." in literal else 0


def parse_tokens(text: str) -> list[tuple[str, float, int]]:
    """Extract ``(literal, value, precision_decimals)`` for every numeric claim.

    `precision_decimals` is expressed at the token's own scale AFTER the
    magnitude suffix is applied, so `$1.2M` claims one decimal of a million —
    i.e. a resolution of 100,000 — while `1200000` claims units.
    """
    out: list[tuple[str, float, int]] = []
    for m in _TOKEN.finditer(text):
        raw = m.group("num")
        value = float(raw.replace(",", ""))
        dec = _decimals(raw)
        mag = (m.group("mag") or "").lower()
        if mag:
            value *= _MAGNITUDES[mag]
            # `1.2M` resolves to 0.1 * 1e6 = 100_000; a NEGATIVE decimal count
            # expresses "coarser than units", which is what a magnitude token is.
            dec -= len(str(_MAGNITUDES[mag])) - 1
        if m.group("sign"):
            value = -value
        out.append((m.group(0), value, dec))
    return out


def _row_values(rows: Any) -> list[float]:
    """Every number ANYWHERE in the rows, including inside strings.

    Strings are mined too because a period label like "FY26-Q3" carries real
    numbers a narration may legitimately cite, and excluding them would make the
    checker reject true statements.
    """
    found: list[float] = []

    def walk(node: Any) -> None:
        if isinstance(node, bool):
            return  # bool is an int subclass; True is not the number 1 here
        if isinstance(node, (int, float)):
            found.append(float(node))
        elif isinstance(node, str):
            for _lit, val, _dec in parse_tokens(node):
                found.append(val)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, Iterable):
            for v in node:
                walk(v)

    walk(rows)
    return found


def _supported(value: float, dec: int, row_values: Iterable[float]) -> bool:
    """Is `value` a faithful projection of some row value at this precision?

    Rounding both sides to the TOKEN's precision is what makes the rule
    directional: a coarse token tolerates a precise row, and a precise token
    tolerates only a row that is precise in the same way.
    """
    for rv in row_values:
        if round(rv, dec) == round(value, dec):
            return True
    return False


def check_narration(text: str, rows: Any) -> tuple[str, list[dict]]:
    """Return ``(clean_text, violations)``.

    Sentences containing an unsupported number are REMOVED. The caller renders a
    template caption when everything is stripped — a caption is a good day
    compared to a confident invented figure.

    Stripping is per SENTENCE rather than per token because a sentence with one
    invented number is not partially true; removing the token alone would leave
    a grammatical claim whose subject has quietly changed.
    """
    values = _row_values(rows)
    kept: list[str] = []
    violations: list[dict] = []

    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if not sentence:
            continue
        bad = [
            {"literal": lit, "value": val, "sentence": sentence}
            for lit, val, dec in parse_tokens(sentence)
            if not _supported(val, dec, values)
        ]
        if bad:
            violations.extend(bad)
        else:
            kept.append(sentence)

    return " ".join(kept).strip(), violations
