"""TASK VERBS ARE PART OF A TASK'S MEANING — a wrong verb is REFUSED, not stored.

THE BUG THIS CLOSES (seen live 2026-07-31, screenshot). The triage task — "Notice
PCN-2683-CROPFAIL could not be prepared for review" — rendered with **Approve / Reject**,
because `extraction_refusal` was an unregistered kind and the registry's honest default is
`APPROVAL_TASK`.

Approve… the failure? The task's semantics are DISPOSITION OF A BROKEN INPUT, not a decision
on a proposal. And the cost is not awkward wording: whichever button is clicked records a
decision the data cannot represent. `acted_by: alice, decision: approved` on an extraction
failure is provenance nonsense — and ADR-0034's decision records would archive it IMMUTABLY,
as evidence, into the corpus that governs vendor promotion. Fix the verbs before the first
real click, or the trust work starts on a polluted corpus it cannot clean.

The sharper reading of the default, worth keeping: it was honest about LABELS ("TASK") and
dishonest about AFFORDANCES (`APPROVAL_TASK`). A label that says nothing is harmless; an
affordance that says nothing still offers buttons.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_task_verbs_by_kind.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _ht():
    try:
        from src.iagent import human_tasks  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"human_tasks not importable here: {type(e).__name__}: {e}")
    return human_tasks


# ── the vocabulary is per species ──────────────────────────────────────────

_OVERLAY = _ROOT / "policy" / "overlays" / "sample" / "task_kinds"


def _composed(monkeypatch):
    """Make the composed set KNOWABLE for a test that asks about a species.

    After the M3.3 cutover there is no code table behind an unresolvable overlay, so a test that
    asks what a DOMAIN species accepts must say where the domain rows are — otherwise it is
    asking a question the process is right to refuse. The seeded species need nothing; this is
    for the arms that name a domain kind.
    """
    ht = _ht()
    monkeypatch.setenv(ht._OVERLAY_DIRS_ENV, str(_OVERLAY))
    monkeypatch.setattr(ht, "_DECLARED_KINDS_CACHE", None, raising=False)
    monkeypatch.setattr(ht, "_SEED_ROWS_CACHE", None, raising=False)
    return ht


def test_a_triage_task_refuses_approve_and_reject():
    """THE REGRESSION. These are the two verbs the card actually offered, and both must be
    refused at the write — the UI is where the bug was seen, the API is where it is FIXED, so
    a future card (or a curl) cannot reintroduce it."""
    ht = _ht()
    for wrong in ("approved", "rejected"):
        with pytest.raises(ht.InvalidDecisionForKind) as exc:
            ht.validate_decision("extraction_refusal", wrong, "some comment")
        assert "cannot represent" in str(exc.value)


@pytest.mark.parametrize("verb", ["acknowledged", "redriven"])
def test_a_triage_task_accepts_its_own_verbs(verb):
    ht = _ht()
    ht.validate_decision("extraction_refusal", verb, "parts entered in the legacy system")


def test_ordinary_approvals_are_untouched(monkeypatch):
    """The ordinary vocabulary is correct for a task that IS a decision — no change here may make
    every other species stricter.

    THE CLAIM SURVIVED THE CUTOVER; ITS FIXTURE DID NOT. These verbs used to come from a code
    table and now come from declared rows, so the arm needs the composed set to be KNOWABLE
    before it can ask about `pcn_disposition` — a domain species whose row is in the overlay.
    Failing here without the overlay was the gate working, not the claim breaking.
    """
    ht = _composed(monkeypatch)
    for kind in ("workflow_ack", "access_request", "grouped_review", "pcn_disposition"):
        ht.validate_decision(kind, "approved")
        ht.validate_decision(kind, "rejected")
        with pytest.raises(ht.InvalidDecisionForKind):
            ht.validate_decision(kind, "acknowledged", "reason")


def test_an_unregistered_kind_NO_LONGER_gets_a_default(monkeypatch):
    """⛔ INVERTED AT THE M3.3 CUTOVER. This arm asserted the opposite and was right to.

    It read: "the default stays approve/reject — deliberately. The triage lesson is NOT 'default
    to nothing'; it is that a default must not assert semantics the task may not have."

    That reasoning held while a code table was the fallback for kinds no declaration covered.
    The tables are gone, so there is nothing left to default FROM — and the ruled answer for a
    species the seed does not carry, under a knowable set, is that it accepts nothing. **The
    claim was not wrong; its premise was deleted.** Kept inverted rather than removed, because
    an arm that vanishes takes its reasoning with it and the next person re-derives the default.
    """
    ht = _composed(monkeypatch)
    assert ht.verbs_for_kind("some_future_kind") == (), (
        "an undeclared species was handed verbs — the code-table default is back"
    )


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_acknowledge_without_a_reason_is_refused(blank):
    """"Parts entered in the legacy system" and "notice withdrawn by the vendor" are entirely
    different facts about the pipeline. A bare acknowledgement erases the difference — and the
    difference is exactly the evidence ADR-0034's corpus needs. The reason field is also v1 of
    key-it-in: it covers the honest cases before the manual-entry lane exists."""
    ht = _ht()
    with pytest.raises(ht.InvalidDecisionForKind) as exc:
        ht.validate_decision("extraction_refusal", "acknowledged", blank)
    assert "REQUIRES a reason" in str(exc.value)


def test_redrive_does_not_require_a_reason():
    """Re-drive states its own reason by being re-drive: the underlying issue is fixed, try
    again. Demanding prose there is friction without information."""
    _ht().validate_decision("extraction_refusal", "redriven", "")


# ── the projection must not LIE about what happened ────────────────────────
def test_status_is_not_coerced_into_rejected():
    """An acknowledged triage task was NOT rejected, and a projection row that says so is a
    lie the audit trail keeps forever. `pending` is the only status queue queries depend on,
    so widening the terminal vocabulary is safe — while coercing is not."""
    ht = _ht()
    src = (_ROOT / "src" / "iagent" / "human_tasks.py").read_text(encoding="utf-8")
    body = src[src.index("def mark_task_resolved"):]
    body = body[:body.index("with _pg_connect")]
    assert '"approved" if decision == "approved" else "rejected"' not in body, (
        "the old coercion is back: every non-approval becomes 'rejected', so an acknowledged "
        "extraction failure is recorded as a rejection"
    )
    # ⛔ THIS ASSERTED THE ALLOWLIST CONTAINED `acknowledged` AND `redriven`. That was the right
    # check against a PARTIAL widening — the fix of the day it was written, which named the
    # verbs that existed then. It is superseded rather than wrong: there is no allowlist now,
    # so those words do not appear, and the property is stronger without them.
    #
    # THE ALLOWLIST WAS THE DEFECT, NOT ITS CONTENTS. Measured 2026-09-15 against the composed
    # declaration: THIRTEEN verbs declared, three named. Every safety verb — `accepted`,
    # `concurred`, `returned_for_rework` and the rest — stored as REJECTED, and a risk
    # acceptance recorded as its opposite is the one act under ADR-0051 whose record IS the
    # evidence. Widening a list verb-by-verb only ever covers the species someone remembered.
    assert "status = decision" in body, (
        "the status is no longer taken from the decision, so some vocabulary is being imposed "
        "on it again"
    )
    assert "else \"rejected\"" not in body, (
        "a coercion to 'rejected' survives in any form; the declaration is the only source of "
        "what a species accepts and the projection must record what it was given"
    )
    # The one value that must NOT widen, because the queue reads it as OPEN.
    assert 'if decision == "pending":' in body


class _RecordingCursor:
    """Captures `execute` rather than running it. `rowcount` is 1 so the function returns a
    plausible row count and nothing downstream branches on zero."""

    def __init__(self, sink):
        self._sink = sink
        self.rowcount = 1

    def execute(self, sql, params=None):
        self._sink.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _RecordingConnection:
    def __init__(self, sink):
        self._sink = sink
        self.commits = 0

    def cursor(self):
        return _RecordingCursor(self._sink)

    def commit(self):
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _resolve_capturing(ht, decision: str):
    """Call `mark_task_resolved` with the database replaced, returning what it WOULD write.

    Returns `(executed, connection)` — the list of (sql, params) the function issued, and the
    connection double so a caller can assert it was actually used.
    """
    executed: list = []
    conn = _RecordingConnection(executed)
    original = ht._pg_connect
    ht._pg_connect = lambda: conn
    try:
        ht.mark_task_resolved("task-under-test", caller_id="tester", decision=decision)
    finally:
        ht._pg_connect = original
    return executed, conn


def test_every_declared_verb_survives_the_status_mapping():
    """THE PROPERTY, ASSERTED AS BEHAVIOUR: every declared verb is STORED as itself.

    Derived from the vocabulary rather than hand-listed, so adding a species' verb without
    teaching the status mapping fails HERE instead of silently recording it as 'rejected'.

    AND ITS OLD SOURCE IS WHY NOBODY SAW THE ORIGINAL DEFECT. It derived from `_VERBS_BY_KIND`,
    which carried one row and never held a safety verb — so the arm whose whole purpose was "a
    new verb must not be silently recorded as rejected" EXCLUDED EXACTLY THE SPECIES AT RISK. A
    fixture that cannot contain the failing case reports green forever. Re-sourced to the
    declared rows, it found the defect on its first run.

    ── WHY THIS ARM IS NO LONGER A GREP, AND THE MARKER IS GONE ────────────────────────────────

    It used to assert each verb NAME APPEARED IN THE FUNCTION BODY — a source-text proxy for a
    behavioural property. That held only while the implementation was an allowlist. `ad29f5c`
    replaced the coercion with a pass-through, `status = decision`, which is the correct answer
    and mentions no verb names at all, **so the arm began failing BECAUSE the defect was fixed.**

    > The seal punished the right answer, and its `strict=True` marker could not report that.
    > A strict xfail promises "you will hear about it the day this passes" — and this test never
    > started passing, it just failed for the opposite reason. **A strict xfail is only as good
    > as the test under it: it guarantees a signal only if the failure mode cannot CHANGE.**

    Three things were wrong at once and the marker made all three quiet: its reason quoted a
    coercion that no longer exists, `strict` could not fire, and nothing verified the property
    at all — a newly declared verb the mapping mishandled would have passed as "1 xfailed".

    ── THE DEPENDENCY THAT MADE A GREP TEMPTING ────────────────────────────────────────────────

    `mark_task_resolved` WRITES TO POSTGRES, which is why the original sliced the body at
    `with _pg_connect` and read only the pre-write logic. The grep was not laziness; it was the
    cheap way around a dependency (recorded by its author, `iagent-mesh-sdk-ca`). So this arm
    substitutes the connection and asserts the parameters the UPDATE WOULD carry.

    That substitution introduces its own failure mode — a patch that misses the real call site
    asserts nothing while passing — so `test_THE_DOUBLE_IS_ACTUALLY_REACHED` is a control on the
    instrument itself, not on the subject.
    """
    ht = _ht()
    import yaml  # noqa: PLC0415

    declared = set()
    for d in (_ROOT / "policy" / "task_kinds", _OVERLAY):
        for f in sorted(d.glob("*.yaml")):
            row = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            declared |= set(row.get("accepts") or ())
    # THE FLOOR. Without it the loop below iterates an empty set and passes while proving
    # nothing — the vacuum this property has already been lost to once.
    assert declared, "derived no verbs from the declarations — the source moved, not the property"

    for verb in sorted(declared - {"rejected"}):
        executed, _conn = _resolve_capturing(ht, verb)
        assert executed, (
            f"nothing was executed for {verb!r} — the connection double was not reached, so "
            f"this assertion is about nothing. Fix the patch target before trusting a green."
        )
        sql, params = executed[0]
        assert "UPDATE human_task_projection" in sql, (
            f"the first statement issued for {verb!r} is not the projection update: {sql[:120]}"
        )
        stored_status, stored_decision = params[0], params[1]
        assert stored_status == verb, (
            f"decision {verb!r} would be STORED as {stored_status!r}. A declared verb is being "
            f"coerced into some other vocabulary — and under ADR-0051 a risk ACCEPTANCE "
            f"recorded as its opposite is the one act whose record IS the evidence."
        )
        assert stored_decision == verb, (
            f"the decision column would hold {stored_decision!r} for decision {verb!r}"
        )


def test_THE_DOUBLE_IS_ACTUALLY_REACHED():
    """CONTROL ON THE INSTRUMENT. If `_pg_connect` is renamed or the write moves behind another
    helper, the patch above silently stops intercepting and every assertion in the arm becomes
    vacuous — it would capture nothing and, without this, report nothing.

    Asserts the double was entered AND committed, which is the pair that distinguishes "the
    function ran the write path" from "the function returned early".
    """
    ht = _ht()
    executed, conn = _resolve_capturing(ht, "approved")
    assert executed, "the connection double was never used — the patch target is wrong"
    assert conn.commits == 1, (
        f"the write path did not commit ({conn.commits} commits), so the captured parameters "
        f"are not what a real resolution would have stored"
    )


def test_PENDING_IS_REFUSED_AS_A_RESOLUTION():
    """The one value that must not widen, asserted as BEHAVIOUR rather than as a source match.

    `pending` is what every queue reads as OPEN, so storing it would return a resolved task to
    every queue that skips it. This is the sibling of the widening above: the vocabulary opens
    for terminal verbs and stays shut for the single non-terminal one.
    """
    ht = _ht()
    with pytest.raises(ValueError) as exc:
        _resolve_capturing(ht, "pending")
    assert "pending" in str(exc.value).lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
