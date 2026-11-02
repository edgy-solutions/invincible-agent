"""Every new commit carries `Lane: <lane id>/<branch>`, because git cannot say who wrote it.

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
a session id (`invincible-agent-65`) dies with the session, and the lane id/branch pair outlives
it and is what a later reader can actually check out.

**A LANE ID, NEVER A WORKTREE PATH** (ruled 2026-10-26). The first half used to be "the worktree
that made it", checked against `git worktree list` — so a throwaway worktree's correct commit read
as an invented lane the day the worktree was removed. The id is now a row of `.githooks/lanes`,
which is versioned with the history it judges and is append-only; a throwaway worktree commits as
the lane it works for (`.githooks/pre-push --expected` prints the trailer).

**MEASURER AND REVIEWER STAY DISTINCT FROM AUTHOR.** This asserts only authorship. A correction to
a misattribution must not create a second one in the other direction — being named in a thread is
not review, and taking a reading is not writing the line.

Run: uv run --frozen pytest tests/test_every_commit_names_its_lane.py -v
"""
from __future__ import annotations

import re
import subprocess
from fnmatch import fnmatchcase
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

#: Commits that DESCEND from the rule and still carry no trailer, each with its reason.
#:
#: NOT A CONVENIENCE. A commit in here could have complied and did not, and the entry exists
#: only because published history is not rewritten (R-030) — the same reason the trailer wall
#: could not be fixed by amending. An exemption that outlives its reason is a hole with a
#: comment on it, so each entry says what happened rather than that it was allowed.
#:
#: THE ENTRIES RETIRE THEMSELVES: `test_AN_EXEMPTION_RETIRES_ITSELF` reds if an exempt commit
#: ever carries a valid trailer, so a stale row is a failure rather than a silent allowance.
#: (Mechanism from `lane/91`; adopted here before that branch merged.)
_EXEMPT: dict[str, str] = {
    # ── FOLDED IN FROM lane/91 BY THE 2026-09-18 MERGE ───────────────────────────────────
    # ⛔ THESE LIVED IN A SECOND `_EXEMPT` DEFINITION 140 LINES BELOW, and git merged both
    # without a conflict because they never touched. **Python then took the last one**, so
    # master's seven exemptions above were silently discarded and the lint reddened on commits
    # it was ruled not to bind. A TEXTUAL MERGE WITH NO CONFLICT IS NOT A SEMANTIC MERGE — the
    # markers showed me the one collision git could see, and the language resolved the one it
    # could not by last-wins, in silence.
    #
    # The reason these two exist: the rule WAS in this lane's ancestry, carried in by a master
    # merge, and the lane kept using the spelling the architect had ratified an hour before
    # 11b4070 landed the pair rule. THE LESSON IS THE REASON, NOT THE EXEMPTION — a merge can
    # bring a NEW SEAL, and running only the directories you edited will not find it.
    "57e3aa3bd6570b725d91088609333dd05d903f94":
        "ratified spelling superseded by 11b4070 after this was written; the architect ratified "
        "`Lane: lane/91 (invincible-agent-81)` an hour before the pair rule landed",
    "6186339d9aa940df82f055a2e9a835d6f4d6f48b":
        "ratified spelling superseded by 11b4070 after this was written; same lane, same hour",
    "b15adbc": (
        "engine-lg's compile fix, pushed direct to master. A genuine omission rather than a" + 
        " boundary case: the rule WAS in its ancestry. It is the R-063 shape in reverse — the" + 
        " lane merged master, which brought this seal, and pushed without running what the" + 
        " merge carried in. Recorded, not rewritten."
    ),
    # ── SECOND BATCH, 2026-09-15, and the pattern is the point rather than the rows ──────
    #
    # Three more pushed without the trailer, from two lanes, all with the rule in ancestry.
    # Caught by R-063.2 on the very next merge — the derived seal seeing new commits join its
    # population — which is the law working and NOT evidence the rule is landing.
    #
    # A GROWING EXEMPTION LIST IS A SIGNAL ABOUT THE RULE, NOT ABOUT THE COMMITS. Four
    # entries now, none of them boundary cases. The remedy is not more entries: it is that a
    # lane learns the trailer exists at the moment it merges master, which is exactly when
    # nobody re-reads the suite list. If a fifth batch appears, the rule needs a mechanism
    # that fires BEFORE a push rather than a seal that reports after one.
    "4ee0764": (
        "engine-lg's saver-ordering seal. Pushed direct to master; the rule was in ancestry."
    ),
    "054fb4c": (
        "engine-lg's durable checkpointing. Same push, same lane, same omission."
    ),
    "cada33b": (
        "the m3.3 cutover WIP. Marked NOT MERGEABLE in its own subject, so it is work in "
        "progress that reached master's ancestry — recorded rather than rewritten, and the "
        "entry retires itself if it is ever amended before merge."
    ),
    # ── THIRD BATCH, and the last one that can be a boundary case ───────────────────────
    #
    # Both predate the hook LANDING ON MASTER — it existed only on `lane/01` until `cf8e0b9`,
    # so `core.hooksPath .githooks` pointed at a directory these lanes did not have. That is a
    # genuine cannot-comply, unlike the first two batches: the mechanism was not reachable.
    #
    # THE LIST SHOULD STOP GROWING NOW. Every worktree can install the hook from master, and a
    # fourth batch would mean the install is not happening rather than that the rule is
    # unreachable — a different problem with a different fix.
    "e93fa0c": (
        "the m3.3 audit fix, pushed before the hook was on master and therefore installable"
    ),
    "cef690e": (
        "the runbook interval sites, same push window, same unreachable mechanism"
    ),
    "c9d66e6": (
        "the m3.3 cutover head on lane/ca-m33-cutover, same lane and same omission as its "
        "WIP parent above."
    ),
    # ── FOURTH BATCH (2026-10-26), and it is not the install failing the way the third
    # batch's note predicted: how it got past the hook is NOT MEASURED, and the entry says so
    # rather than supplying a cause. (#85's squash, 24e64a5e, was proposed for this batch and
    # measured NOT red: GitHub's squash body keeps the branch commit's `Lane:` line, and this
    # seal reads the body, not the trailer block. The retirement guard below refused it.)
    "ed6b530b": (
        "ca's ResolveInstanceRequest import, committed in the shared tree on "
        "lane/ca-resolve-instance-adoption and brought in by #83's merge 6dafe3b1. The shared "
        "tree has core.hooksPath=.githooks; whether the push bypassed it or came from elsewhere "
        "was not measured."
    ),
}


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


# Every git identity the one human commits under, keyed to that human. A web-UI merge on
# GitHub commits as the account's noreply address, not the local config: PR #6's merge
# (d1976ef4) is the commit that showed it. Same person, another surface -- so it does not
# disambiguate lanes and the premise below still holds.
_ONE_HUMAN = {
    "Chris Nogradi <cnogradi@gmail.com>": "cnogradi",
    "cnogradi <81271909+cnogradi@users.noreply.github.com>": "cnogradi",
}


def test_GIT_AUTHOR_CANNOT_DISAMBIGUATE_LANES():
    """THE PREMISE, asserted rather than assumed.

    If lanes ever DID commit under distinct identities, this whole convention would be
    redundant ceremony and should be deleted rather than maintained. The seal states the
    condition that makes it necessary, so the day it stops being true somebody finds out here.
    """
    authors = {ln for ln in _git("log", "--format=%an <%ae>", "-60").splitlines() if ln.strip()}
    unknown = sorted(authors - set(_ONE_HUMAN))
    assert not unknown, (
        f"commits under an identity not known to be the one human: {unknown}. Either it is the "
        f"same person through another surface (add it to _ONE_HUMAN with the commit that showed "
        f"it), or lanes now commit under distinct identities -- and if that is durable, `--author` "
        f"disambiguates lanes and R-058's trailer may be redundant: re-read the ruling rather "
        f"than deleting the trailer on this evidence."
    )
    humans = {_ONE_HUMAN[a] for a in authors}
    assert len(humans) == 1, f"{len(humans)} humans commit here: {sorted(humans)}"


def test_THE_ALLOWED_IDENTITIES_ARE_ONE_HUMAN():
    """The allow-list is the seal's excuse, so it is checked too: every entry names the SAME
    human. An entry for a second person would make the premise above pass while false."""
    assert len(set(_ONE_HUMAN.values())) == 1, _ONE_HUMAN


def test_THE_TRAILER_FORM_IS_PARSEABLE():
    """A floor. A regex matching nothing would make every assertion below vacuous — which is
    exactly how a convention check reads green while enforcing nothing."""
    assert _TRAILER.search("Lane: ia-01/lane/01")
    assert _TRAILER.search("body text\n\nLane: ia-eo/lane/eo\n")
    assert not _TRAILER.search("Lane: ia-01"), "a trailer with no branch half must not parse"
    assert not _TRAILER.search("Lane:"), "an empty trailer must not parse"


@pytest.mark.parametrize(
    "sha,subject,body",
    _bound_commits() or [("", "", "")],
    ids=lambda v: v[:12] if isinstance(v, str) else str(v),
)
def test_A_COMMIT_MADE_AFTER_THE_RULING_NAMES_ITS_LANE(sha: str, subject: str, body: str):
    """THE SEAL. Binds forward only; published history is not rewritten to satisfy it."""
    if not sha:
        pytest.skip("no bound commits yet — the rule binds forward")

    # ── MERGED 2026-09-18, AND EITHER SIDE ALONE DROPS A REAL IMPROVEMENT ──────────────────
    # master made the lookup PREFIX-based; `lane/91` added the SELF-RETIRING assertion. They
    # are two different fixes to one branch, not two versions of one fix.
    #
    # ⚠ THE PREFIX HALF IS LOAD-BEARING, NOT STYLE: every key in `_EXEMPT` is a SHORT sha, so
    # `sha in _EXEMPT` matches nothing and all seven exemptions silently stop exempting —
    # the lint then reds on commits it was ruled not to bind. Measured before merging.
    _hit = next((k for k in _EXEMPT if sha.startswith(k)), None)
    if _hit:
        # SELF-RETIRING. If an exempt commit ever DOES carry a valid trailer the entry is stale,
        # and a stale exemption is a standing permission nobody reviews — so this reds and says
        # to delete it, rather than quietly covering a commit that no longer needs covering.
        # Checked at merge time: all seven still carry no trailer, so this fires on none of them
        # today and is a guard against the list rotting rather than a claim about it now.
        assert not _TRAILER.search(body or ""), (
            f"{sha[:12]} is on the exemption list but now carries a valid trailer. Delete its "
            f"entry from `_EXEMPT`: an exemption that outlives its reason is a hole with a "
            f"comment on it."
        )
        pytest.skip(f"exempt: {_EXEMPT[_hit]}")

    assert _TRAILER.search(body or ""), (
        f"{sha[:12]} ({subject[:60]!r}) carries no `Lane:` trailer.\n"
        f"Add `Lane: <lane id>/<branch>` — e.g. `Lane: ia-01/lane/01` — as a trailer. Git's "
        f"author field is one human identity for every lane, so without it this commit has no "
        f"recoverable owner once the session that made it has ended."
    )


_LANES = _REPO / ".githooks" / "lanes"


def _registry(text: str) -> dict[str, list[str]]:
    """lane id -> branch globs, from the text of `.githooks/lanes`. `#` starts a comment, and a
    row with no glob is not a row — the same reading as the hook's `awk`, so the two arms cannot
    disagree about what is registered."""
    rows: dict[str, list[str]] = {}
    for ln in text.splitlines():
        fields = ln.split("#", 1)[0].split()
        if len(fields) > 1:
            rows.setdefault(fields[0], []).extend(fields[1:])
    return rows


def _verdict(lane_id: str, branch: str, lanes: dict[str, list[str]]) -> str | None:
    """None when `lane_id/branch` is a REGISTERED PAIR, else the reason it is not. There is no
    third answer: an id with no row and a branch outside its row are both refusals."""
    globs = lanes.get(lane_id)
    if globs is None:
        return f"lane id {lane_id!r} has no row in .githooks/lanes"
    if not any(fnmatchcase(branch, g) for g in globs):
        return f"branch {branch!r} is not one of {lane_id}'s ({' '.join(globs)})"
    return None


def _registry_commit() -> str:
    """The commit that ADDED `.githooks/lanes` — the registry's own rule commit.

    DERIVED, NOT PINNED, so the commit that creates the file is bound by it; the same reason
    `_RULE_COMMIT` is added back in `_bound_commits`. Pinning it would need a second commit to
    write the sha of the first, and everything between the two would be unbound.
    """
    shas = _git("log", "--diff-filter=A", "--format=%H", "HEAD", "--", ".githooks/lanes").split()
    return shas[-1] if shas else ""


def test_THE_REGISTRY_EXISTS_AND_ITS_IDS_ROUND_TRIP():
    """A missing registry would make the join below skip as "shallow clone" — so its absence is
    asserted here, where it reds instead. And an id containing `/` can never match: `_TRAILER`
    splits the trailer at its FIRST slash, so `a/b` would be read as id `a`."""
    assert _LANES.is_file(), ".githooks/lanes is gone; no trailer can name a registered lane"
    lanes = _registry(_LANES.read_text(encoding="utf-8"))
    assert "ia-01" in lanes, f"Lane 1 has no row, so the registry is not the one ruled: {lanes}"
    for lane_id in lanes:
        assert "/" not in lane_id, f"lane id {lane_id!r} contains '/' and cannot round-trip"


@pytest.mark.parametrize("lane_id,branch,refusal", [
    ("ia-01", "lane/01", None),
    ("ia-01", "lane/01-register-422", None),
    ("ia-saf", "lane/saf-seal-frs-knowledge-document", None),
    ("ia-fin", "fin/canvas-seed-answer-names-its-template", None),
    # THE REJECTED RULE ACCEPTED THIS ONE: `wkc` was a live worktree when its commit was made,
    # so `git worktree list` registered it — until the worktree was removed and the same commit
    # turned red. A case only the new rule refuses is the case that shows which rule is running.
    ("wkc", "lane/01-register-422", "has no row"),
    ("ia-74", "lane/01-x", "is not one of"),            # two real names, not each other's
    ("ia-28", "lane/28", "has no row"),                 # derived from a session name (R-058.1)
    ("invincible-agent", "master", "has no row"),       # the shared tree is no lane
    ("ia-01", "lane/011", "is not one of"),             # `lane/01-*`, not `lane/01*`
])
def test_THE_PAIR_CHECK_DECIDES_EACH_CASE(lane_id: str, branch: str, refusal: str | None):
    """Against the LIVE registry, so a row edited into accepting a refused case reds here."""
    got = _verdict(lane_id, branch, _registry(_LANES.read_text(encoding="utf-8")))
    if refusal is None:
        assert got is None, f"`Lane: {lane_id}/{branch}` should be registered: {got}"
    else:
        assert got and refusal in got, f"`Lane: {lane_id}/{branch}` should be refused ({refusal}): {got}"


def test_A_TRAILER_MADE_UNDER_THE_REGISTRY_NAMES_A_REGISTERED_LANE():
    """THE JOIN. A trailer naming a lane other than the one that made the commit is WORSE than
    no trailer: it is a confident wrong answer, and it sends the next dispatch further astray
    than silence would.

    ⛔ WHAT THIS REPLACED, AND WHY (ruled 2026-10-26). The pair used to be checked against
    `git worktree list` and the branch against refs git knew. BOTH ARE PRESENT-TENSE REGISTRIES
    and a trailer is a past-tense claim: a throwaway worktree's correct commit went red the day
    the worktree was removed, and a merged branch's commits would go red the day the branch was
    deleted. That is the stale-claim shape running backwards — correct history failing. The
    first version had already met it once (`invincible-agent/lane/ca-m33-cutover`, red the moment
    the shared tree was parked back on master) and patched the halves instead of the registry.

    NOW: the id is a row of `.githooks/lanes` and the branch must match that row's globs. The
    registry is versioned with the history it judges and is append-only, so a row a commit cited
    is still there when the commit is read. THE PAIR, NOT THE HALVES: `ia-74/lane/01` is two real
    names that are not each other's, and a mispaired trailer resolves to somebody else.

    BOUND BY ANCESTRY FROM THE COMMIT THAT ADDED THE REGISTRY. Commits before it were made when
    the hook told every throwaway worktree to write its own basename, so they could not comply;
    they are held to the trailer's FORM only, by the arm above. Retro-fitting them would mean
    rewriting published history (R-030).
    """
    reg = _registry_commit()
    if not reg:
        pytest.skip("the commit that added .githooks/lanes is not in this clone (shallow?)")
    lanes = _registry(_LANES.read_text(encoding="utf-8"))
    bound = set(_git("rev-list", "--ancestry-path", "--no-merges", f"{reg}..HEAD").split())
    bound.add(reg)
    bad = []
    for sha, subject, body in _bound_commits():
        if sha not in bound:
            continue
        for lane_id, branch in _TRAILER.findall(body or ""):
            why = _verdict(lane_id, branch, lanes)
            if why:
                bad.append(f"{sha[:12]} {subject[:50]!r}: `Lane: {lane_id}/{branch}` — {why}")
    assert not bad, (
        "trailers naming no registered lane id/branch pair:\n  " + "\n  ".join(bad) + "\n"
        "A trailer names a LANE ID from .githooks/lanes, never a worktree path: a throwaway "
        "worktree commits as the lane it works for. `.githooks/pre-push --expected` prints it."
    )


def test_THE_REGISTRY_IS_APPEND_ONLY():
    """The join reads every bound commit against TODAY's registry, which is only sound if no row
    a commit cited has gone. So every (id, glob) any committed version held must still be here.
    Close a lane with a comment on its row; removing the row would turn its history red — the
    exact failure `git worktree list` produced."""
    now = _registry(_LANES.read_text(encoding="utf-8"))
    lost = []
    for sha in _git("log", "--format=%H", "HEAD", "--", ".githooks/lanes").split():
        for lane_id, globs in _registry(_git("show", f"{sha}:.githooks/lanes")).items():
            lost += [f"{lane_id} {g} (in {sha[:12]})" for g in globs if g not in now.get(lane_id, [])]
    assert not lost, "rows removed from .githooks/lanes that history cites:\n  " + "\n  ".join(lost)


def test_EVERY_EXEMPTION_NAMES_A_REASON():
    """An exemption with an empty reason is a silenced failure wearing a decision's clothes."""
    for sha, why in _EXEMPT.items():
        assert why and why.strip(), f"{sha} is exempt with no reason"


def test_AN_EXEMPTION_RETIRES_ITSELF():
    """THE MECHANISM THAT KEEPS THE LIST FROM ROTTING, from `lane/91`.

    If an exempt commit ever carries a valid trailer, the exemption is stale and the seal says
    so rather than quietly allowing what no longer needs allowing. An exemption that outlives
    its reason is a hole with a comment on it.
    """
    for sha, body in ((s_, b_) for s_, _sub, b_ in _bound_commits()):
        key = next((k for k in _EXEMPT if sha.startswith(k)), None)
        if key and _TRAILER.search(body or ""):
            raise AssertionError(
                f"{key} is in _EXEMPT but now carries a valid Lane: trailer. Delete the entry — "
                f"it is allowing something that no longer needs allowing."
            )


# ── THE PER-FILE DUPLICATE-BINDING SEAL MOVED, 2026-09-18 ────────────────────────────────────
# `test_THIS_FILE_DEFINES_ITS_TABLES_EXACTLY_ONCE` lived here after two `_EXEMPT` tables shipped
# in one merge. It could only ever see THIS module — and the very next instance of the class was
# one file over, in `tests/finance/test_the_wire_carries_what_the_engine_declares.py`, where a
# doubly-bound `_CORTEX` disabled a cross-repo scan that then skipped with a false reason and
# reported green.
#
# A SEAL SCOPED TO THE FILE THAT TAUGHT IT CANNOT FIND THE NEXT ONE. Retired into
# `tests/test_no_module_level_name_is_bound_twice.py`, which walks every module-level binding in
# the tree and distinguishes a TRANSFORM (the rebinding reads the old value) from a COLLISION
# (it does not). One assertion, one exclusion list.
