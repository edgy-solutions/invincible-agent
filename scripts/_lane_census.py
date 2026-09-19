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


def report_lanes(repo: Path) -> None:
    """Print the LANES block. Never raises and never changes the caller's exit code."""
    try:
        sys.path.insert(0, str(repo / "src"))
        from iagent_pure.lane_packets import scan, unaddressed, unread_by_lane
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

    for p in unaddressed(packets):
        print(f"        UNADDRESSED  {Path(p.path).name}")
    if unaddressed(packets):
        print("        A packet naming no lane cannot be read by one. Add `to: ia-<lane>/lane/"
              "<lane>`; reported rather than dropped, because an inbox that silently discards "
              "what it cannot attribute is the same silence one layer down.")

    if standing:
        print(f"        {standing} packet(s) unread for more than a day. Reading is an ACT: the "
              f"lane commits `read-by: ia-<lane>/lane/<lane> <date>` to the packet. Delivery is "
              f"the inbox, reading is the stamp, and both are on the rail.")
    print("        This is STATE, printed every run, and does NOT change the exit code.")
