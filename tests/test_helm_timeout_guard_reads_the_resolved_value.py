"""THE GUARD MUST CHECK WHAT HELM ACTUALLY RECEIVES, NOT THE LITERAL IN THE SCRIPT.

MEASURED 2026-09-06: `helm upgrade --timeout 10m` marked release 100 **failed** while the prime
hook ran on healthily underneath. Third instance across two lanes.

`tests/test_prime_timeout_bounds_agree.py` was GREEN throughout and could not have caught any of
them. It reads the LITERAL DEFAULT out of the script — `HELM_TIMEOUT="${HELM_TIMEOUT:-75m}"` —
and asserts it exceeds `primeSubstrate.ingestTimeout`. That assertion is true and useless,
because two things change the effective value and the seal sees neither:

    1. an env override          HELM_TIMEOUT=10m bash scripts/upgrade-sandbox.sh
    2. a caller-supplied flag   "$@" lands AFTER --timeout, so a later --timeout WINS

The script's own comment has said *"anything passed in `"$@"` comes after and therefore wins"*
the entire time. **A comment that must be read to be obeyed is not a guard** — the same finding
as the tuple-arity note that sat stale for three weeks.

The two-ways-it-differs finding is the engine-cost lane's, from reading the script rather than
trusting that a green seal meant a guarded value.

═══════════════════════════════════════════════════════════════════════════════════════
WHAT THIS FILE MEASURES, AND WHAT IT DOES NOT — read this before trusting it green.

**It asserts on the script's SOURCE.** These are structural checks, and they are weaker than
running the thing.

**The behaviour was verified by hand, once, on 2026-09-06**, by executing the real script with
a fake `helm` first on PATH. All six paths behaved:

    default (no args)              rc=0   helm invoked
    --timeout 10m                  rc=2   REFUSED, helm not invoked
    --timeout=10m                  rc=2   REFUSED, helm not invoked
    --timeout 90m                  rc=0   helm invoked
    HELM_TIMEOUT=10m (env)         rc=2   REFUSED, helm not invoked
    ALLOW_SHORT_HELM_TIMEOUT=1     rc=0   "under protest", helm invoked

**That verification is NOT automated here, and the reason is recorded rather than hidden:** the
`bash` this environment hands a Python subprocess reports an empty `$BASH_VERSION` and cannot
`set -o pipefail`, so the script dies on line 23 before reaching the guard. A subprocess seal
would have been red for a reason unrelated to what it tests, and a permanently-skipped test is
a green that means nothing.

**So this is a real gap.** A regression that keeps the guard's shape while breaking its logic —
an off-by-one in the arg scan, a comparison inverted — passes everything below. On a machine
with a working bash, the executable version of this seal is worth writing and is the better
test.
═══════════════════════════════════════════════════════════════════════════════════════

Run: uv run --frozen pytest tests/test_helm_timeout_guard_reads_the_resolved_value.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SRC = (_REPO / "scripts" / "upgrade-sandbox.sh").read_text(encoding="utf-8")


def _guard() -> str:
    """The guard block: from the default assignment to the refusal's close."""
    i = _SRC.index('HELM_TIMEOUT="${HELM_TIMEOUT:-75m}"')
    j = _SRC.index("exec helm upgrade")
    return _SRC[i:j]


# ── it reads the RESOLVED value, both ways it can differ ────────────────────

def test_it_scans_the_caller_arguments():
    """The blind spot that caused the incident: `"$@"` lands after the script's own
    `--timeout`, so a caller's flag is the one helm honours."""
    g = _guard()
    assert 'for _arg in "$@"' in g, "the guard does not look at caller arguments at all"


def test_it_handles_BOTH_flag_forms():
    """`--timeout 10m` and `--timeout=10m` are the same instruction in different clothes. A
    guard handling one is right in a test and wrong in a shell."""
    g = _guard()
    assert "--timeout=*)" in g, "the = form is unhandled"
    assert '"${_prev}" = "--timeout"' in g, "the space-separated form is unhandled"


def test_the_LAST_occurrence_wins():
    """helm honours the last `--timeout`. A guard reading the first would certify a number
    helm will not use — worse than no guard, because it says the run is safe."""
    g = _guard()
    i = g.index('for _arg in "$@"')
    # BOUNDED BY `done`, NOT BY A CHARACTER COUNT. The first version used `i + 420` and a
    # `break` added to the last line of the loop landed OUTSIDE the window — the mutation
    # passed. Third instance of a magic span rotting in one day, and this one was written
    # after naming the pattern twice.
    body = g[i:g.index("done", i) + 4]
    assert "_effective_timeout=" in body
    assert "break" not in body, "the scan stops early and would read the FIRST --timeout"


def test_the_env_override_is_the_starting_point():
    g = _guard()
    assert '_effective_timeout="${HELM_TIMEOUT}"' in g


# ── it refuses, rather than warning ─────────────────────────────────────────

def test_it_EXITS_rather_than_printing_and_continuing():
    """The killed-client trap directly above this guard warns and cannot prevent, and that
    is precisely how the 10m incident happened — to the author of the warning. A warning in
    a long log is not a control."""
    g = _guard()
    assert "exit 2" in g, "the guard warns but does not stop"


def test_an_unparseable_value_is_refused():
    """The case where nobody can say what the budget is. A failed parse yielding 0 would
    compare as tiny or enormous depending on the operator, and neither was chosen."""
    g = _guard()
    assert '[ -z "${_mins}" ]' in g


def test_the_threshold_matches_the_prime_bound_it_protects():
    """75 minutes, because primeSubstrate.ingestTimeout is 60m and must be the binding
    constraint — the inner bound is the one that can say WHY it failed."""
    g = _guard()
    assert re.search(r'"\$\{_mins\}"\s+-lt\s+75', g), "the threshold moved without a reason"


# ── the escape hatch is deliberate, named, and loud ─────────────────────────

def test_the_hatch_exists_and_must_be_named():
    """Refusing outright would break a genuinely short upgrade that skips the prime. The
    hatch requires saying its name — an accident cannot take it."""
    g = _guard()
    assert "ALLOW_SHORT_HELM_TIMEOUT" in g
    assert 'ALLOW_SHORT_HELM_TIMEOUT:-}" = "1"' in g


def test_taking_the_hatch_still_prints():
    g = _guard()
    assert "under protest" in g


def test_the_refusal_names_the_value_it_read():
    """A refusal that does not say WHICH number it read sends the reader to the default —
    the one thing that was not the problem."""
    g = _guard()
    assert "${_effective_timeout}" in g


# ── the guard's premise still holds ─────────────────────────────────────────

def test_the_exec_line_still_puts_caller_args_last():
    """The whole reason the scan is needed. If `"$@"` ever moves BEFORE `--timeout`, the
    script's own value wins and this guard is solving a problem that no longer exists —
    which is worth failing on, because the comment and the guard would then both be lying."""
    i = _SRC.index("exec helm upgrade")
    line = _SRC[i:_SRC.index("\n", i)]
    assert line.index('--timeout "${HELM_TIMEOUT}"') < line.index('"$@"'), (
        "caller args no longer come last — re-read the guard's premise before deleting it"
    )


def test_the_guard_runs_BEFORE_helm_is_invoked():
    """Non-vacuity for every assertion above: a guard placed after the exec is unreachable."""
    assert _SRC.index("ALLOW_SHORT_HELM_TIMEOUT") < _SRC.index("exec helm upgrade")
