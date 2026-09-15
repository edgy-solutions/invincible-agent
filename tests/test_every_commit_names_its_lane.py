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
_BINDS_AFTER = "2026-09-14T23:00:00"

#: `Lane: <worktree>/<branch>` — e.g. `Lane: ia-01/lane/01`. The branch half may contain `/`.
_TRAILER = re.compile(r"^Lane:\s*(\S+?)/(\S+)\s*$", re.M)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(_REPO), capture_output=True, text=True, timeout=120,
    ).stdout


def _bound_commits() -> list[tuple[str, str, str]]:
    """(sha, subject, body) for non-merge commits after the cutoff, reachable from HEAD.

    MERGES ARE EXEMPT and that is deliberate: a merge commit is made by whoever integrates, and
    its authorship question is answered by the branch it brings in, not by the merge itself.
    """
    out = _git(
        "log", f"--since={_BINDS_AFTER}", "--no-merges",
        "--format=%H%x1f%s%x1f%b%x1e", "HEAD",
    )
    rows = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        parts = rec.split("\x1f")
        if len(parts) >= 3:
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


@pytest.mark.parametrize(
    "sha,subject,body",
    _bound_commits() or [("", "", "")],
    ids=lambda v: v[:12] if isinstance(v, str) else str(v),
)
def test_A_COMMIT_MADE_AFTER_THE_RULING_NAMES_ITS_LANE(sha: str, subject: str, body: str):
    """THE SEAL. Binds forward only; published history is not rewritten to satisfy it."""
    if not sha:
        pytest.skip("no commits after the cutoff yet — the rule binds forward")
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
    known_worktrees = {w for w, _ in pairs}
    for sha, subject, body in _bound_commits():
        m = _TRAILER.search(body or "")
        if not m:
            continue                      # the assertion above owns that case
        wt = m.group(1)
        assert wt in known_worktrees, (
            f"{sha[:12]} claims `Lane: {wt}/{m.group(2)}` but {wt!r} is not a registered "
            f"worktree ({sorted(known_worktrees)}). A trailer naming a lane that does not "
            f"exist points the next dispatch at nobody."
        )
