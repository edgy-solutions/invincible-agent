"""The trailer rule fires BEFORE a push, not only after one.

WHY THIS EXISTS, and it is the exemption list rather than any single commit. Within one day the
post-hoc seal accumulated FOUR exemptions from three lanes, none of them a boundary case:

    b15adbc  engine-lg's compile fix          pushed direct to master, no trailer
    4ee0764  engine-lg's ordering seal        same lane, same push
    054fb4c  engine-lg's durable checkpointing same
    cada33b / c9d66e6  the m3.3 cutover       a different lane, same omission

Each was caught AFTER the push, and by then R-030 forbids rewriting published history — so the
only available remedy is an exemption entry. **A check that can only report is a check whose
remedy is always "record it and move on."**

> **The exemption list was a signal about the RULE, not about the commits.** They were not
> unusual; the rule was not reaching anyone in time. A lane learns the trailer exists at the
> moment it merges master, which is exactly when nobody re-reads the suite list (R-063).

**THE VALUE IS PRODUCED BY THE ACT, NEVER TYPED.** The hook derives `Lane: <worktree>/<branch>`
from `git rev-parse --show-toplevel` and `--show-current` in the worktree the push runs from, so
the trailer cannot name a lane that is not this one. That is R-058.1's whole content: a session
address predicts neither half, and a hand-typed pair is how `ia-28/lane/28` came to be written for
a lane that works in `ia-74`. Same construction as the roll script deriving its image tag rather
than accepting one.

**PRESENCE, NOT THE PAIR.** A commit cherry-picked from another lane legitimately carries THAT
lane's trailer — it is the author, and rewriting it would be a false attribution of exactly the
kind R-058.2 names. So the hook asks "does this name a lane", and the post-hoc seal asks the
question that needs the registry: "is that a REGISTERED pair". Two arms, two questions.

Run: uv run --frozen pytest tests/test_the_lane_trailer_hook_refuses_before_a_push.py -v
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_HOOK = _REPO / ".githooks" / "pre-push"
_SEAL = _REPO / "tests" / "test_every_commit_names_its_lane.py"


def _hook() -> str:
    return _HOOK.read_text(encoding="utf-8")


def test_THE_HOOK_EXISTS_AND_IS_A_SHELL_PROGRAM():
    assert _HOOK.is_file(), "the pre-push hook is gone; the rule reports only after the fact"
    assert _hook().startswith("#!"), "the hook has no interpreter line and will not run"


def test_IT_PARSES():
    """A hook with a syntax error does not refuse anything — git reports the failure and, on
    some configurations, carries on. A guard that cannot run is worse than none because the
    exemption list stops growing and everyone reads that as the rule landing."""
    # A RELATIVE PATH FROM `cwd`, because `bash` here is Git Bash and neither Windows form
    # addresses the file: backslashes are stripped, and `C:/...` is not a path it can resolve
    # (it wants `/c/...`). BOTH failures report "No such file or directory" — a MISSING-FILE
    # error for a file that is present, which reads as the hook having been deleted rather than
    # as the check being unable to address it. Same class as a probe sending a field name the
    # contract does not have and reading the default as behaviour.
    r = subprocess.run(
        ["bash", "-n", ".githooks/pre-push"],
        cwd=str(_REPO), capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, f"the hook does not parse: {r.stderr}"


def test_THE_LANE_IS_DERIVED_FROM_THE_WORKTREE_not_typed():
    """THE PROPERTY THAT MAKES IT SAFER THAN A CONVENTION. If the expected value were a literal
    in the hook, every worktree would need a different copy and the copies would drift into
    exactly the mispairing R-058.1 records."""
    src = _hook()
    assert "--show-toplevel" in src, "the worktree half is not derived"
    assert "rev-parse --abbrev-ref HEAD" in src or "--show-current" in src, (
        "the branch half is not derived"
    )
    assert not re.search(r'EXPECTED="Lane: ia-\d', src), (
        "the expected lane is hard-coded, so this copy of the hook is wrong in every worktree "
        "but one"
    )


def test_IT_BINDS_BY_ANCESTRY_like_the_seal():
    """Both arms must agree on WHO is bound, or a commit refused by one and exempt by the other
    is a contradiction a person has to adjudicate. `--ancestry-path` from the rule commit is the
    seal's own membership test."""
    src = _hook()
    assert "--ancestry-path" in src
    assert "merge-base --is-ancestor" in src
    seal_rule = re.search(r'_RULE_COMMIT\s*=\s*"([0-9a-f]+)"', _SEAL.read_text(encoding="utf-8"))
    hook_rule = re.search(r'RULE_COMMIT="([0-9a-f]+)"', src)
    assert seal_rule and hook_rule, "one of the two arms no longer names a rule commit"
    assert seal_rule.group(1) == hook_rule.group(1), (
        f"the hook binds from {hook_rule.group(1)} and the seal from {seal_rule.group(1)} — "
        f"two arms of one rule disagreeing about who it applies to"
    )


def test_MERGES_ARE_SKIPPED_in_both_arms():
    """A merge commit's authorship question is answered by the branch it brings in. Refusing one
    would make every lane's first merge of master unpushable."""
    assert "--no-merges" in _hook()


def test_IT_STANDS_ASIDE_WHEN_IT_CANNOT_KNOW():
    """A shallow clone may not contain the rule commit. Refusing there blocks EVERY push, and a
    guard that fails closed on its own missing input is a guard that gets uninstalled — after
    which the rule has neither arm."""
    src = _hook()
    i = src.index("rev-parse --verify --quiet")
    window = src[i:i + 400]
    assert "exit 0" in window, (
        "an unresolvable rule commit does not stand aside; it will block every push in a "
        "shallow clone"
    )


def test_IT_CHECKS_PRESENCE_AND_SAYS_WHY_IT_DOES_NOT_CHECK_THE_PAIR():
    """The division of labour is a decision, and a later reader finding only presence-checking
    would reasonably 'finish the job' — turning a legitimate cherry-pick from another lane into
    a refused push, and inviting exactly the false attribution R-058.2 is about."""
    src = _hook()
    assert "PRESENCE ONLY" in src
    assert "cherry-pick" in src


def test_THE_REFUSAL_NAMES_THE_COMMIT_AND_THE_REMEDY():
    """A refusal a person cannot act on gets worked around. It must print WHICH commit and the
    exact trailer for this worktree — and say that amending an unpushed commit is not a rewrite
    of published history, because that is the rule people will think they are breaking."""
    src = _hook()
    assert "PUSH REFUSED" in src
    assert "${EXPECTED}" in src
    assert "not pushed" in src and "rewrite" in src


@pytest.mark.parametrize("marker", ["R-058", "R-030", "R-063"])
def test_THE_REASONING_TRAVELS_WITH_THE_HOOK(marker: str):
    """A hook is the least-read file in a repository and the easiest to delete when it is
    inconvenient. The cost of not having it is recorded where the deletion would happen."""
    assert marker in _hook()


def test_PUBLISHED_COMMITS_ARE_NOT_THIS_PUSHS_TO_VOUCH_FOR():
    """`--not --remotes`, and its absence made the hook demand the rule it enforces be broken.

    MEASURED on a simulated `lane/5f` push — their remote tip, then a merge of `origin/master`
    into it, which is what every lane does when it takes master:

        without `--not --remotes`    99 commits checked, 99 already on origin/master
        with    `--not --remotes`     0

    `--ancestry-path` does NOT exclude them, which is the part that is easy to get wrong: once a
    lane has been merged to master, every LATER master commit is a DESCENDANT of that lane's
    last-pushed tip, so all of it falls inside `remote_sha..local_sha`.

    > **THE REFUSAL WAS WORSE THAN A FALSE POSITIVE.** Its text says *"these commits are not
    > pushed, so amending is not a rewrite of published history"* — false for all 99. A lane
    > following the instruction literally would have rewritten other lanes' published commits.
    > **The guard written to uphold R-030 was instructing its violation**, and the only ways past
    > it were `--no-verify` or doing exactly that.

    Reported by `invincible-agent-f3`, who hit it, measured both directions, and refused both
    escapes rather than taking either.

    A commit reachable from any remote-tracking ref has been published, and THIS push is not the
    act that publishes it. That is also why the hook needs no exemption table while the seal does:
    every exempt commit on master is published, so the hook never sees one.
    """
    src = _hook()
    assert "--not --remotes" in src, (
        "the hook checks commits that are already published, so a lane merging master is told to "
        "amend other lanes' history — the R-030 violation this rule exists to prevent"
    )
    i = src.index("git rev-list")
    line = src[i:src.index(chr(10), i)]
    assert "--not --remotes" in line, (
        "`--not --remotes` is present but not on the rev-list that selects the commits to "
        "check, so it constrains nothing: " + line.strip()
    )


def test_THE_REFUSALS_CLAIM_ABOUT_PUBLISHED_HISTORY_IS_TRUE_BY_CONSTRUCTION():
    """The message and the selection are two halves of one claim, and only the pair is checkable.

    The text promises the named commits are unpushed. That is a statement ABOUT THE SELECTION, so
    it is true only while the selection excludes published commits — which is what the clause
    above does. Asserted together because the message was correct prose beside a query that made
    it false, and neither half looks wrong alone.
    """
    src = _hook()
    assert "not pushed" in src and "rewrite" in src
    assert "--not --remotes" in src, (
        "the refusal still promises the commits are unpushed while the selection no longer "
        "guarantees it"
    )


def test_THE_HOOK_IS_LF_ONLY():
    """A CRLF hook DOES NOT RUN, and it fails in the way that looks like something else.

    Measured 2026-09-15: a Python rewrite converted 100 line endings, after which `bash -n`
    reported `syntax error near unexpected token 'newline'` at line 52 while `sh -n` still
    passed cleanly. Two shells disagreeing reads as a syntax bug in the script rather than as an
    encoding problem with the file — and the script had not changed.

    Git would reintroduce it on any checkout with `core.autocrlf` set, so `.gitattributes`
    pins it and this asserts the pin held. The failure mode is total and silent: git prints the
    hook's error and carries on, so the rule it enforces is simply off.
    """
    raw = _HOOK.read_bytes()
    crlf = raw.count(bytes([13, 10]))
    assert crlf == 0, (
        f"the hook has {crlf} CRLF line ending(s) and will not run. Convert it to LF; "
        f"`.gitattributes` pins `.githooks/* text eol=lf` so a checkout does not undo it."
    )


def test_GITATTRIBUTES_PINS_THE_HOOK_LINE_ENDINGS():
    """Without the pin, the seal above passes in this checkout and the hook is broken in the
    next one — a property of a working copy rather than of the repository."""
    ga = _REPO / ".gitattributes"
    assert ga.is_file(), ".gitattributes is gone; nothing keeps the hook LF across checkouts"
    assert ".githooks/* text eol=lf" in ga.read_text(encoding="utf-8")
