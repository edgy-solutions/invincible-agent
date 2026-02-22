"""Standalone smoke-test for _evaluate_condition (no psycopg2 dependency)."""

import sys
from typing import Any


def _evaluate_condition(
    condition_expression: str | None,
    result: dict[str, Any],
) -> bool:
    """Copy of the function from dynamic_factory.py for isolated testing."""
    if not condition_expression:
        return True
    try:
        safe_ns: dict[str, Any] = {k: v for k, v in result.items()}
        return bool(eval(condition_expression, {"__builtins__": {}}, safe_ns))
    except Exception:
        return True


r1 = {"status": "approved", "score": 85}
r2 = {"status": "rejected", "score": 40}

tests = [
    (None,                   r1, True,  "None condition = default"),
    ("",                     r1, True,  "empty condition = default"),
    ("status == 'approved'", r1, True,  "matching string eq"),
    ("status == 'approved'", r2, False, "non-matching string eq"),
    ("score > 70",           r1, True,  "numeric gt match"),
    ("score > 70",           r2, False, "numeric gt no match"),
    ("status == 'rejected'", r2, True,  "rejected branch match"),
    ("INVALID!!!",           r1, True,  "bad expr = fallback True"),
]

all_pass = True
for expr, result, expected, desc in tests:
    actual = _evaluate_condition(expr, result)
    ok = actual == expected
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {desc}: expected={expected}, got={actual}")
    if not ok:
        all_pass = False

print()
if all_pass:
    print("ALL 8 TESTS PASSED")
else:
    print("SOME TESTS FAILED")
    sys.exit(1)
