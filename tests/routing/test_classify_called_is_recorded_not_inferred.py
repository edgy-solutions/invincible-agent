"""`classify_called` MUST BE RECORDED BY THE ROUTER, NOT INFERRED AT THE MATERIALIZATION.

MEASURED 2026-09-08 on `artifact-1-1788837904248` — an honest refusal, the capability-path
question asked as PROGRAM_FINANCE_ANALYST. The routing record read:

    "action": {
        "iri": "UNKNOWN",
        "label": "General search",
        "confidence": 0.92,        <- a number only /classify_predicate produces
        "candidate_count": 6,
        "classify_called": false   <- ...beside a claim that it never ran
    }

Both cannot be true. The materialization derived the flag:

    "classify_called": status == _ROUTING_MATCHED
                       or telemetry.get("verb_iri") not in (None, "UNKNOWN")

and that expression cannot separate the two ways a route ends `no_match` with `UNKNOWN`:

    the classifier RAN and declined       <- 6 candidates, 0.92 confidence, a real judgement
    the classifier was NEVER ASKED        <- ADR-0019 Contract B short-circuit

The comment sitting directly above that derivation said the first case should be TRUE. The
derivation reported it FALSE. A note describing the intended behaviour, three lines from code
that contradicts it, is not a guard — this repo has now filed that exact shape three times.

WHY IT MATTERS BEYOND TIDINESS. To someone reading a refusal, "no verb fits this subject" and
"we never checked" are different answers, and only one of them suggests the question was
reasonable and the domain was wrong. That is the difference this field exists to carry, and
it was inverted in the only case where anyone would look.

Run: uv run --frozen pytest tests/routing/test_classify_called_is_recorded_not_inferred.py -v
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SUP = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")


def _telemetry_dicts() -> list[ast.Dict]:
    """Every dict literal the router RETURNS as telemetry.

    Identified by carrying `verb_confidence` and `subject_uri` — and by NOT being wrapped in
    `MetadataValue`, which is what separates the four telemetry dicts from the ONE
    materialization dict that re-publishes the same key names. The first version of this
    helper matched all five and then complained that the materialization was "computed",
    which it is supposed to be. Same shape as the rest of this file: a selector that catches
    the neighbour and reports it as the claim.
    """
    out = []
    for n in ast.walk(ast.parse(_SUP)):
        if not isinstance(n, ast.Dict):
            continue
        keys = {k.value for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if "verb_confidence" not in keys or "subject_uri" not in keys:
            continue
        if "MetadataValue" in ast.unparse(n):
            continue  # the materialization, not a telemetry return
        out.append(n)
    return out


def _pairs(d: ast.Dict) -> dict[str, str]:
    return {
        k.value: ast.unparse(v)
        for k, v in zip(d.keys, d.values)
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }


# ── every telemetry site records it ─────────────────────────────────────────

def test_there_are_several_telemetry_sites_to_check():
    """Non-vacuity. One site would satisfy everything below and prove nothing — and the
    reason this defect survived is that the router has FOUR ways to finish."""
    assert len(_telemetry_dicts()) >= 4, f"found {len(_telemetry_dicts())}"


def test_every_routing_telemetry_records_whether_the_classifier_RAN():
    """PER SITE, NOT AS A COUNT. A floor stayed green in this repo while a key was deleted
    from one branch — the aggregate-floor defect, inside the test written to prevent it."""
    missing = [
        sorted(_pairs(d))[:4] for d in _telemetry_dicts()
        if "classify_called" not in _pairs(d)
    ]
    assert not missing, (
        f"{len(missing)} routing telemetry dict(s) omit classify_called; an absent key reads "
        f"as False, which is right for a short-circuit and WRONG for a classifier that ran"
    )


def test_it_is_a_LITERAL_at_every_site_not_an_expression():
    """The whole fix. A derived value is what was wrong; each site knows the answer because
    each site IS the answer, so each must state it outright."""
    bad = {
        _pairs(d)["classify_called"] for d in _telemetry_dicts()
        if _pairs(d).get("classify_called") not in ("True", "False")
    }
    assert not bad, f"classify_called is computed rather than stated at: {bad}"


def test_exactly_one_site_says_True():
    """There is one path through this router that calls /classify_predicate. If a second
    site starts claiming it ran, either a real second call appeared — or someone copied a
    telemetry dict and did not read what they copied."""
    trues = [d for d in _telemetry_dicts() if _pairs(d).get("classify_called") == "True"]
    assert len(trues) == 1, f"{len(trues)} sites claim the classifier ran"


def test_the_site_that_says_True_is_the_one_holding_a_classifier_RESULT():
    """THE ASSERTION THAT PINS IT TO REALITY rather than to a count. The post-classify
    telemetry is the only dict whose verb_confidence is a variable — every short-circuit
    hard-codes 1.0 or 0.0 because no classifier produced a number for it."""
    d = next(d for d in _telemetry_dicts() if _pairs(d).get("classify_called") == "True")
    conf = _pairs(d)["verb_confidence"]
    assert not re.fullmatch(r"[0-9.]+", conf), (
        f"the site claiming the classifier ran reports a hard-coded confidence ({conf}) — "
        f"a literal means no classifier produced it"
    )


def test_the_short_circuits_all_say_False():
    """The other side of the same claim, and the case the old derivation got right by
    accident while getting the interesting one wrong."""
    falses = [d for d in _telemetry_dicts() if _pairs(d).get("classify_called") == "False"]
    assert len(falses) >= 3, f"only {len(falses)} short-circuit sites record False"
    for d in falses:
        conf = _pairs(d)["verb_confidence"]
        assert re.fullmatch(r"[0-9.]+", conf), (
            f"a site claiming no classifier ran reports a computed confidence ({conf}) — "
            f"one of the two is wrong, which is the defect this file exists for"
        )


# ── and the materialization reads it rather than re-deriving ────────────────

def test_the_materialization_reads_the_recorded_value():
    i = _SUP.index('"classify_called": MetadataValue.bool(')
    window = _SUP[i:i + 200]
    assert 'telemetry.get("classify_called")' in window, (
        "the materialization is not reading the recorded flag"
    )


def test_the_old_DERIVATION_is_gone():
    """The exact expression that shipped the inversion. Paired with the positive control
    above, because an absence assertion alone would pass if the whole field vanished."""
    assert "_ROUTING_MATCHED\n            or telemetry.get(\"verb_iri\")" not in _SUP, (
        "classify_called is being derived from status and verb_iri again — that expression "
        "reports False for a classifier that ran and returned UNKNOWN"
    )
