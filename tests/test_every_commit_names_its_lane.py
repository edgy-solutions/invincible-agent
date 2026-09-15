"""Every new commit carries `Lane: <worktree>/<branch>`, because git cannot say who wrote it.

WHY, measured on this repo: **every commit in the last forty, across every lane, is authored
`Chris Nogradi <cnogradi@gmail.com>`.** One human identity, many agents. So `git log --author`
disambiguates nothing and `git blame` names the person who owns the machine.

The gap surfaced when a dispatch went to the wrong lane. `_accumulated_slots`' docstring records
*"MEASURED 2026-09-12 by invincible-agent-81"* — correctly; that lane took the reading and said
twice the fix was someone else's. A reader looking for an OWNER found the measurer, because the
citation was the only name present. **A citation is not a signature** (R-058), and the citation
is precise, dated and verifiable, which makes it *more* convincing rather than less.

`8c7422c` names its measurer in the body and its author nowhere. Three of the last sixty commit
messages name their authoring lane. The only reliable test was *which files has this lane ever
touched* — a reconstruction that works solely while that lane is alive to be asked.

**THE TRAILER NAMES THE DURABLE KEY, NOT THE ADDRESS.** `ia-01/lane/01`, the way the roster does:
a session id (`invincible-agent-65`) dies with the session, and the worktree/branch pair outlives
it and is what a later reader can actually check out.

**MEASURER AND REVIEWER STAY DISTINCT FROM AUTHOR.** This asserts only authorship. A correction to
a misattribution must not create a second one in the other direction — being named in a thread is
not review, and taking a reading is not writing the line.

Run: uv run --frozen pytest tests/test_every_commit_names_its_lane.py -v
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]

#: Commits at or before this are exempt, WITH THE REASON: the convention was ratified
#: 2026-09-14 and no commit before it could have carried a trailer nobody had asked for.
#: Retro-fitting would mean rewriting published history, which R-030 forbids for the same
#: reason a pushed tag is never rewritten. So the rule binds forward only.
#:
#: This is a DATE rather than a sha because lanes carry unmerged work whose shas are not
#: reachable from here — a sha cutoff would exempt nothing on a branch that has not merged.
#: The commit that RATIFIED the trailer. A commit is bound iff this is in its ancestry.
#:
#: THIS WAS A WALL-CLOCK CUTOFF AND THE BOUNDARY WAS THE DEFECT, found by the `lane/eo` lane
#: when the seal reddened four of their commits. A date assumes the rule is visible to everyone
#: the moment it lands on master. IN A WORKTREE FLEET IT IS VISIBLE WHEN A LANE MERGES IT, and
#: lanes run behind BY DESIGN. Their four were written 20:02-21:37 — after the 19:53 cutoff and
#: before the rule existed in their tree, because that lane was 25 commits behind. The seal saw
#: them only once they merged master, which is the moment it became possible to comply and far
#: too late to have complied.
#:
#: AND THE SEAL DEMANDED A FIX IT ALSO FORBIDS: all four are pushed, and retro-fitting means
#: rewriting published history, which the rule below refuses on R-030 grounds. A check whose
#: only remedy is prohibited is not a check, it is a trap.
#:
#: `--is-ancestor` is the property the date was approximating. Measured before adopting: 16
#: commits bound by date, 12 with the rule in ancestry, difference exactly the four named. It
#: still binds the rule's OWN commit, since b466612 is an ancestor of itself — the property the
#: "one second before" cutoff was built to get. And an unmerged lane is exempt only until it
#: merges the rule; every commit it writes after that is bound. The gap is bounded and
#: self-closing, and no lane reaches master without that merge.
_RULE_COMMIT = "b466612"

_TRAILER = re.compile(r"^Lane:\s*(\S+?)/(\S+)\s*$", re.M)


def _git(*args: str) -> str:
    # ENCODING IS EXPLICIT. `text=True` decodes with the LOCALE codec — cp1252 on Windows — and
    # commit bodies in this repo carry em-dashes and other non-cp1252 characters. The decode
    # fails inside a subprocess reader thread and `stdout` comes back as None, which surfaces as
    # `AttributeError: NoneType has no attribute split` far from its cause. It only appeared once
    # this stopped windowing by date and began reading every commit — the wider population found
    # the first body the narrow one never reached.
    return subprocess.run(
        ["git", *args], cwd=str(_REPO), capture_output=True,
        encoding="utf-8", errors="replace", timeout=120,
    ).stdout or ""


def _bound_commits() -> list[tuple[str, str, str]]:
    """(sha, subject, body) for non-merge commits that HAVE THE RULE IN THEIR ANCESTRY.

    A lane cannot comply with a rule that is not yet in its tree, and lanes run behind by
    design, so membership is `_RULE_COMMIT is an ancestor of this commit` rather than a date.

    ONE `rev-list` RATHER THAN A `merge-base` PER COMMIT. The per-commit loop was correct and
    took 134 SECONDS on this history — a cost paid by every suite run, which is how a seal gets
    deselected and then deleted. `--ancestry-path A..HEAD` is the set of commits on a path from
    A, which is the same set; verified against the slow form before switching (13 and 13).

    `_RULE_COMMIT` IS ADDED BACK EXPLICITLY. `A..HEAD` excludes A, but A IS its own ancestor, so
    the rule binds the commit that created it. That was the whole point of the superseded
    "one second before" cutoff, and dropping it here would quietly exempt the rule from itself.

    MERGES ARE EXEMPT, deliberately: a merge commit is made by whoever integrates, and its
    authorship question is answered by the branch it brings in.
    """
    bound = set(_git("rev-list", "--ancestry-path", "--no-merges",
                     f"{_RULE_COMMIT}..HEAD").split())
    rule_sha = _git("rev-parse", _RULE_COMMIT).strip()
    if rule_sha:
        bound.add(rule_sha)

    fmt = "%H" + chr(31) + "%s" + chr(31) + "%b" + chr(30)
    out = _git("log", "--no-merges", f"--format={fmt}", "HEAD")
    rows = []
    for rec in out.split(chr(30)):
        rec = rec.strip(chr(10))
        if not rec:
            continue
        parts = rec.split(chr(31))
        if len(parts) >= 3 and parts[0] in bound:
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def test_GIT_AUTHOR_CANNOT_DISAMBIGUATE_LANES():
    """THE PREMISE, asserted rather than assumed.

    If lanes ever DID commit under distinct identities, this whole convention would be
    redundant ceremony and should be deleted rather than maintained. The seal states the
    condition that makes it necessary, so the day it stops being true somebody finds out here.
    """
    authors = {ln for ln in _git("log", "--format=%an <%ae>", "-60").splitlines() if ln.strip()}
    assert len(authors) == 1, (
        f"lanes now commit under {len(authors)} distinct git identities: {sorted(authors)}. "
        f"If that is durable, `--author` disambiguates lanes and R-058's trailer may be "
        f"redundant — re-read the ruling rather than deleting the trailer on this evidence."
    )


def test_THE_TRAILER_FORM_IS_PARSEABLE():
    """A floor. A regex matching nothing would make every assertion below vacuous — which is
    exactly how a convention check reads green while enforcing nothing."""
    assert _TRAILER.search("Lane: ia-01/lane/01")
    assert _TRAILER.search("body text\n\nLane: ia-eo/lane/eo\n")
    assert not _TRAILER.search("Lane: ia-01"), "a trailer with no branch half must not parse"
    assert not _TRAILER.search("Lane:"), "an empty trailer must not parse"


#: COMMITS EXEMPT BY NAME, EACH WITH ITS REASON. Ruled 2026-09-14: published history is not
#: rewritten to satisfy a lint (R-030, and this file's own docstring), and an exclusion WITH A
#: REASON fails loudly where a rewrite fails silently.
#:
#: Four of `lane/91`'s non-compliant commits are exempt BY ANCESTRY — `11b4070` is not among
#: their forebears, so they were written under the spelling that preceded the pair rule and no
#: list is needed for them. The two below DO descend from it, and they are the honest case: the
#: rule was already in this lane's tree, carried in by a master merge, and the lane kept using
#: the superseded spelling for two more commits.
#:
#: **THE LESSON IS THE REASON, NOT THE EXEMPTION.** A merge can bring a NEW SEAL, and running
#: only the directories you edited will not find it. Both commits ran `tests/finance/` and
#: `tests/cost/` green and never ran this file.
_EXEMPT: dict[str, str] = {
    "57e3aa3bd6570b725d91088609333dd05d903f94":
        "ratified spelling superseded by 11b4070 after this was written; the architect ratified "
        "`Lane: lane/91 (invincible-agent-81)` an hour before the pair rule landed",
    "6186339d9aa940df82f055a2e9a835d6f4d6f48b":
        "ratified spelling superseded by 11b4070 after this was written; same lane, same hour",
}


@pytest.mark.parametrize(
    "sha,subject,body",
    _bound_commits() or [("", "", "")],
    ids=lambda v: v[:12] if isinstance(v, str) else str(v),
)
def test_A_COMMIT_MADE_AFTER_THE_RULING_NAMES_ITS_LANE(sha: str, subject: str, body: str):
    """THE SEAL. Binds forward only; published history is not rewritten to satisfy it."""
    if not sha:
        pytest.skip("no commits after the cutoff yet — the rule binds forward")

    if sha in _EXEMPT:
        # SELF-RETIRING. If an exempt commit ever DOES carry a valid trailer the entry is stale,
        # and a stale exemption is a standing permission nobody reviews — so this reds and says
        # to delete it, rather than quietly covering a commit that no longer needs covering.
        assert not _TRAILER.search(body or ""), (
            f"{sha[:12]} is on the exemption list but now carries a valid trailer. Delete its "
            f"entry from `_EXEMPT`: an exemption that outlives its reason is a hole with a "
            f"comment on it."
        )
        pytest.skip(f"exempt: {_EXEMPT[sha]}")

    assert _TRAILER.search(body or ""), (
        f"{sha[:12]} ({subject[:60]!r}) carries no `Lane:` trailer.\n"
        f"Add `Lane: <worktree>/<branch>` — e.g. `Lane: ia-01/lane/01` — as a trailer. Git's "
        f"author field is one human identity for every lane, so without it this commit has no "
        f"recoverable owner once the session that made it has ended."
    )


def test_THE_TRAILER_MATCHES_THE_WORKTREE_IT_WAS_MADE_IN():
    """THE JOIN. A trailer naming a lane other than the one that made the commit is WORSE than
    no trailer: it is a confident wrong answer, and it sends the next dispatch further astray
    than silence would.

    Checked against `git worktree list`, which is the registry of the durable keys.
    """
    pairs = set()
    for ln in _git("worktree", "list").splitlines():
        m = re.search(r"^(\S+)\s+\S+\s+\[(\S+)\]", ln)
        if m:
            pairs.add((Path(m.group(1)).name, m.group(2)))
    if not pairs:
        pytest.skip("no worktree registry readable here")
    # THE PAIR, NOT THE HALVES. The first version checked only that the worktree existed, so
    # `ia-74/lane/01` - two real names that are not each other's - would have passed. A trailer
    # can be wrong by MISPAIRING as easily as by inventing, and the mispaired one is worse: it
    # resolves to a lane that exists and belongs to somebody else.
    #
    # AND THE DERIVATION IS THE THING TO FIX, NOT THE ROW. `invincible-agent-28` works in
    # `ia-74/lane/74`. A trailer built from the SESSION ADDRESS would read `ia-28/lane/28` - a
    # lane that does not exist. The session address and the worktree are independent and neither
    # predicts the other; the session address also churns, which is why the roster is not keyed
    # on it either. Read the trailer from the worktree, never from what a session calls itself.
    for sha, subject, body in _bound_commits():
        m = _TRAILER.search(body or "")
        if not m:
            continue                      # the assertion above owns that case
        claimed = (m.group(1), m.group(2))
        assert claimed in pairs, (
            f"{sha[:12]} claims `Lane: {claimed[0]}/{claimed[1]}`, which is not a registered "
            f"worktree/branch PAIR. Registered: {sorted(pairs)}. Read the trailer from the "
            f"worktree that made the commit (`git rev-parse --show-toplevel`, "
            f"`git branch --show-current`) - NEVER derive it from a session address."
        )
