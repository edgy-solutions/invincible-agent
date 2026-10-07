"""LANES: per-lane state, printed every run — commit age, position, and UNREAD packets.

Ruled 2026-09-18 after the architect's own diagnosis: *"I told 32, 74 and the eo lane 'nothing
blocked on your side' this week while each had an unread packet sitting in their inbox."* The
inbox made DELIVERY checkable and left READING invisible, so a lane that ends a session on "idle
until X rolls" never learns X rolled.

    ia-32: 2 unread (5d, 3d), last commit 3d

would have been on the board on Thursday morning. **Printed as STATE, every run, never as news**
— the same discipline as the undeclared edge types, and for the same reason: a gap that only
appears as a delta goes quiet the moment it stops changing, which is exactly when it is worst.

IT DOES NOT CHANGE THE EXIT CODE. A lane being behind is a fact about people and scheduling, not
a failure of the fleet, and a census that failed on it would be turned off. The architect is the
scheduler; this gives them the list.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                       encoding="utf-8", errors="replace", timeout=60)
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def _age(epoch: str) -> str:
    try:
        days = (time.time() - float(epoch)) / 86400.0
    except (TypeError, ValueError):
        return "?"
    if days < 1:
        return f"{int(days * 24)}h"
    return f"{int(days)}d"


def _commit_epoch(repo: Path, path: str) -> float | None:
    """Seconds-since-epoch for `path`'s last commit in `repo`, or None if it has never been
    committed there. This is `unanswered_over`'s `age_of` -- an untracked file has no commit log
    at all, so `_git` returns "" and this returns None rather than guessing a time, which is what
    keeps an uncommitted packet from being measured as "fresh" (see that function's docstring)."""
    out = _git(repo, "log", "-1", "--format=%ct", "--", path)
    try:
        return float(out) if out else None
    except ValueError:
        return None


def _worktrees(repo: Path) -> list:
    """[(path, branch)] from `git worktree list --porcelain`; `branch` is the local branch name
    (e.g. `lane/74-sdk-revisions`) or None for a detached/bare entry. THE THIRD STATE block needs
    this twice: to know which directories to check for uncommitted packets, and to know which
    `origin/lane/*` branches have NO worktree at all -- the state that can never be enumerated
    from here, per docs/measurements/2026-09-28-...-the-third-state-is-not-where-the-dispatch-put-it.md."""
    raw = _git(repo, "worktree", "list", "--porcelain")
    out: list = []
    path, branch = None, None
    for line in raw.splitlines() + [""]:
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.startswith("branch "):
            ref = line[len("branch "):].strip()
            branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
        elif not line:
            if path:
                out.append((path, branch))
            path, branch = None, None
    return out


def report_lanes(repo: Path) -> None:
    """Print the LANES block. Never raises and never changes the caller's exit code."""
    try:
        sys.path.insert(0, str(repo / "src"))
        from iagent_pure.lane_packets import (
            external_packets,
            scan,
            unaddressed,
            unanswered_over,
            unread_by_lane,
            unread_by_seat,
        )
    except Exception as exc:  # noqa: BLE001 — a census must not die on its own reporting
        print(f"\nLANES: unavailable ({type(exc).__name__}) — NOT a claim that lanes are current.")
        return

    packets = scan(repo / "sessions")
    unread = unread_by_lane(packets)
    branches = [b for b in _git(repo, "branch", "-r", "--format=%(refname:short)").splitlines()
                if b.startswith("origin/lane/")]

    print(f"\nLANES: {len(branches)} lane branch(es), {len(packets)} packet(s) in the inbox.")
    if not branches:
        print("        no lane branches found — this block is reporting nothing, which is not "
              "the same as nothing being wrong.")

    standing = 0
    known_lanes = {b.rsplit("/", 1)[-1].lower() for b in branches}
    for b in sorted(branches):
        lane = b.rsplit("/", 1)[-1].lower()
        last = _git(repo, "log", "-1", "--format=%ct", b)
        lr = _git(repo, "rev-list", "--left-right", "--count", f"origin/master...{b}") or "? ?"
        behind, ahead = (lr.split() + ["?", "?"])[:2]
        mine = unread.get(lane, [])
        ages = ", ".join(_age(_git(repo, "log", "-1", "--format=%ct", "--", p.path)) for p in mine)
        note = f"{len(mine)} unread ({ages})" if mine else "inbox clear"
        print(f"        ia-{lane:<4} last commit {_age(last):>4}  behind {behind:>3} ahead "
              f"{ahead:>3}  {note}")
        # A STANDING GAP HAS A NAME: an unread packet older than a day is a lane that has not
        # picked up work someone is waiting on, and the architect is the only one who can open
        # or poke a session.
        for p in mine:
            if not _age(_git(repo, "log", "-1", "--format=%ct", "--", p.path)).endswith("h"):
                standing += 1

    # NO BRANCH: the general case of the `doc-tools`/`iagent-mesh-sdk` defect. Any lane-kind
    # addressee this repo's `_TO` grammar accepts but whose name matches no `origin/lane/*` branch
    # here is counted in `unread` above and printed by NOTHING in the per-branch loop -- the same
    # gap the seat form closed for seats, one layer up, for an unknown prefix rather than a known
    # one. This is not limited to the two names that were measured; it fires for ANY future lane
    # token with no branch in this tree.
    for lane, mine in sorted(unread.items()):
        if lane in known_lanes:
            continue
        ages = ", ".join(_age(_git(repo, "log", "-1", "--format=%ct", "--", p.path)) for p in mine)
        print(f"        NO BRANCH  {lane:<12} {len(mine)} unread ({ages}) — addressed to a lane "
              f"this repo does not have")
        for p in mine:
            if not _age(_git(repo, "log", "-1", "--format=%ct", "--", p.path)).endswith("h"):
                standing += 1

    # SEATS: the lane-less ones, ruled 2026-09-26. Enumerated from the PACKETS, because a seat owns
    # no worktree and so has no `origin/lane/*` branch to be enumerated from. Without this block the
    # seat form would have been strictly worse than leaving those packets unaddressed: an addressed
    # packet is excluded from the UNADDRESSED list above AND absent from every lane row, so it would
    # have printed nowhere at all — a gap the census had been built specifically to end, reopened by
    # the fix for a different gap one door over.
    for seat, mine in sorted(unread_by_seat(packets).items()):
        ages = ", ".join(_age(_git(repo, "log", "-1", "--format=%ct", "--", p.path)) for p in mine)
        print(f"        seat/{seat:<12} no branch, no commit age  {len(mine)} unread ({ages})")
        for p in mine:
            if not _age(_git(repo, "log", "-1", "--format=%ct", "--", p.path)).endswith("h"):
                standing += 1

    # EXTERNAL: recipients in ANOTHER repo -- `doc-tools/lane/7f`, `openddil`'s agent. This is NOT
    # a delivery report. An external inbox lives in a tree this repo cannot read, so there is no
    # "unread" to claim and no branch to be missing one; all this can honestly say is what WE SENT
    # and how old it is. A long age here means "we are still waiting to hear back", not "it sat
    # unread" -- that distinction is the whole reason this is its own block and not folded into
    # the lane rows above.
    externals = external_packets(packets)
    if externals:
        print(f"\n        EXTERNAL: {len(externals)} recipient(s) in other repos -- what we sent, "
              f"not what they read.")
        for addressee, mine in sorted(externals.items()):
            ages = ", ".join(_age(_git(repo, "log", "-1", "--format=%ct", "--", p.path)) for p in mine)
            print(f"        {addressee:<28} {len(mine)} packet(s) ({ages})")

    for p in unaddressed(packets):
        print(f"        UNADDRESSED  {Path(p.path).name}")
    if unaddressed(packets):
        print("        A packet naming no recipient cannot be read by one. Add `to: ia-<lane>/lane/"
              "<lane>`, or `to: <repo>/seat/<name>` for a lane-less seat; reported rather than "
              "dropped, because an inbox that silently discards what it cannot attribute is the "
              "same silence one layer down.")

    if standing:
        print(f"        {standing} packet(s) unread for more than a day. Reading is an ACT: the "
              f"recipient commits `read-by: ia-<lane>/lane/<lane> <date>` — or `read-by: "
              f"<repo>/seat/<name> <date>` — to the packet. Delivery is the inbox, reading is the "
              f"stamp, and both are on the rail.")

    # UNANSWERED >48h: a stamp is one way a packet gets closed; a REPLY is another, and until now
    # nothing watched for either taking too long. Grouped by (kind, addressee) so a lane and a
    # seat sharing a bare name never share a row -- see `unanswered_over`.
    unanswered, undecided = unanswered_over(
        packets, now=time.time(),
        age_of=lambda path: _commit_epoch(repo, path),
    )
    if unanswered:
        print(f"\n        UNANSWERED >48h: {sum(len(v) for v in unanswered.values())} packet(s), "
              f"{len(unanswered)} addressee(s). Answered = a `read-by` stamp OR a later reply; "
              f"neither has happened yet.")
        for (kind, addressee), mine in sorted(unanswered.items())[:15]:
            ages = ", ".join(_age(_git(repo, "log", "-1", "--format=%ct", "--", p.path)) for p in mine)
            print(f"        {kind}/{addressee:<24} {len(mine)} unanswered ({ages})")
        if len(unanswered) > 15:
            print(f"        ... and {len(unanswered) - 15} more addressee(s)")
    if undecided:
        print(f"\n        UNDECIDED: {len(undecided)} packet(s) whose `from:` line does not parse "
              f"-- cannot be tested for a reply, so not counted as answered OR unanswered.")
        for p, reason in undecided[:15]:
            print(f"        {Path(p.path).name}: {reason}")
        if len(undecided) > 15:
            print(f"        ... and {len(undecided) - 15} more")

    # THE THIRD STATE: a packet that was never COMMITTED -- not an unparseable `to:` line, an
    # untracked sessions/*.md sitting in some worktree. A census run from one tree reads another
    # worktree's uncommitted packets as a clean zero; see docs/measurements/2026-09-28-the-inbox-
    # census-and-the-third-state-is-not-where-the-dispatch-put-it.md §1 and §3. Never printed as a
    # zero: a branch with no local worktree gets its own UNENUMERABLE line instead of silence.
    worktrees = _worktrees(repo)
    seen: dict = {}
    first = True
    for wt_path, _branch in worktrees:
        try:
            files = [f for f in _git(Path(wt_path), "ls-files", "--others", "--exclude-standard",
                                      "sessions/").splitlines() if f]
        except (OSError, subprocess.SubprocessError):
            continue
        if files:
            lead = "\n        " if first else "        "
            print(f"{lead}NOT COMMITTED  {wt_path}  {len(files)} packet(s)")
            first = False
            for f in files:
                seen.setdefault(f, set()).add(wt_path)
    if seen:
        only_one = sum(1 for wts in seen.values() if len(wts) == 1)
        print(f"        {len(seen)} distinct uncommitted packet(s), {only_one} present in only "
              f"one worktree.")

    worktree_branches = {b for _, b in worktrees if b}
    for b in sorted(branches):
        suffix = b.rsplit("/", 1)[-1]
        if f"lane/{suffix}" not in worktree_branches:
            print(f"        UNENUMERABLE  ia-{suffix}  no local worktree — its uncommitted "
                  f"packets cannot be seen from here")

    print("        This is STATE, printed every run, and does NOT change the exit code.")


if __name__ == "__main__":
    # Normally called only from version_census.py's main(), which hardcodes its own repo root.
    # This guard exists so the block can be exercised directly against any repo -- e.g. a census
    # of invincible-agent's own sessions/ run from this worktree -- without going through that
    # caller. Defaulting to this file's own repo keeps `uv run python scripts/_lane_census.py`
    # with no argument working exactly as it always has.
    report_lanes(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1])
