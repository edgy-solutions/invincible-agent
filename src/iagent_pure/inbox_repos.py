"""Cross-repo inbox census: the pure logic (no git, no clock).

`lane_packets` parses ONE repo's `sessions/*.md` and assumes the packet lives in
`invincible-agent`. A packet addressed to another repo, and the reply that comes back from it,
live in different repos, so no single-repo scan can ever see that a packet was answered.
This module joins the whole cross-repo population on CANONICAL addresses (`<repo>/lane/<b>`,
`seat/<name>`, or an outside party) instead of the per-repo bare names.

AGE IS BY FILENAME DATE, NOT COMMIT TIME. A packet placed in another repo is by rule never
committed by its sender, so commit-time age (`lane_packets.unanswered_over`) excludes exactly the
cross-repo population this tool exists to see. The `YYYY-MM-DD` filename prefix is the sender's
own claim of when it was sent. A filename with no date is UNDECIDED, never fresh and never old.

Addressing ruling (2026-10-07): a packet is addressed `to: <repo>/<branch>`; a seat is
`<repo>/seat/<name>`; a worktree name or session name addresses nothing. A bare or title-form
address names no repo; it is resolved to the packet's HOME repo and marked ASSUMED -- the tool
never guesses another repo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from iagent_pure import lane_packets

INTERNAL = "invincible-agent"


def canonical(name, kind, form, home_repo):
    """(address | None, assumed)."""
    if name is None:
        return None, False
    if kind == "seat":
        return f"seat/{name}", False
    if kind == "external":
        return name, False
    if form in ("repo", "worktree"):
        return f"{INTERNAL}/lane/{name}", False
    return f"{home_repo}/lane/{name}", True


@dataclass
class Rec:
    name: str                      # filename: the packet's identity
    home_repo: str
    addressee: str | None = None
    kind: str = "lane"
    form: str = "none"
    sender: str | None = None
    sender_kind: str = "lane"
    sender_form: str = "none"
    is_read: bool = False
    locations: list = field(default_factory=list)   # (repo, file_path, tracked)
    divergent: bool = False
    views: list = field(default_factory=list)       # (path, to_addr, from_addr) per copy

    @property
    def tracked(self) -> bool:
        return any(t for _, _, t in self.locations)

    def to_addr(self):
        return canonical(self.addressee, self.kind, self.form, self.home_repo)

    def from_addr(self):
        return canonical(self.sender, self.sender_kind, self.sender_form, self.home_repo)


def parse_rec(path: Path, home_repo: str) -> Rec:
    """Parse one file with the single-repo grammar; also recover the sender's address FORM."""
    p = lane_packets.parse_packet(path)
    head = "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[:40])
    fm = lane_packets._FROM.search(head)
    return Rec(name=path.name, home_repo=home_repo, addressee=p.addressee, kind=p.kind,
               form=p.form, sender=p.sender, sender_kind=p.sender_kind,
               sender_form=lane_packets._form(fm) if fm else "none", is_read=p.is_read)


def pick_copy(copies) -> int:
    """Index of the canonical copy among `copies` = [(is_main, tracked, mtime, Rec, path)]:
    a copy in a repo MAIN worktree, else a tracked copy, else the newest mtime. Provenance, not
    mtime: a stale checkout is often the newest file on disk and lacks later read-by stamps."""
    for pred in (lambda c: c[0], lambda c: c[1]):
        for i, c in enumerate(copies):
            if pred(c):
                return i
    return max(range(len(copies)), key=lambda i: copies[i][2])


def merge_copies(copies) -> Rec:
    """One Rec for one filename. Text-derived fields come from the canonical copy; a read-by
    stamp is ADDITIVE (read if ANY copy is read). `views` records every copy canonical
    (to, from), all resolved against the canonical copy home repo so a bare address does not
    disagree with itself merely by being found in another repo."""
    rec = copies[pick_copy(copies)][3]
    out = Rec(**{**rec.__dict__, "locations": [], "views": []})
    out.is_read = any(c[3].is_read for c in copies)
    for c in copies:
        v = Rec(**{**c[3].__dict__, "home_repo": rec.home_repo})
        out.views.append((c[4], v.to_addr()[0], v.from_addr()[0]))
    return out


def disagreeing(rec: Rec) -> bool:
    return len({(t, f) for _, t, f in rec.views}) > 1


_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def filename_date(name: str):
    m = _DATE.match(name)
    if not m:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc)
    except ValueError:
        return None


def age_hours(name: str, now: datetime):
    d = filename_date(name)
    return None if d is None else (now - d).total_seconds() / 3600.0


def is_over(name: str, now: datetime, hours: float = 48.0):
    """True/False, or None when the filename carries no date. Exactly `hours` is NOT over."""
    a = age_hours(name, now)
    return None if a is None else a > hours


def replied(p: Rec, recs) -> bool:
    """A LATER packet in `recs`, canonically from P's addressee to P's sender."""
    want_from, want_to = p.to_addr()[0], p.from_addr()[0]
    for q in recs:
        if q is p or not (q.name > p.name):
            continue
        if q.from_addr()[0] == want_from and q.to_addr()[0] == want_to:
            return True
    return False


@dataclass
class Result:
    unanswered: dict = field(default_factory=dict)   # address -> [Rec]
    undecided: list = field(default_factory=list)    # (Rec, reason)
    unaddressed: list = field(default_factory=list)
    assumed: list = field(default_factory=list)      # Rec with an assumed address (either end)


def analyze(recs, now: datetime, hours: float = 48.0) -> Result:
    res = Result()
    for p in recs:
        if (p.addressee and p.to_addr()[1]) or (p.sender and p.from_addr()[1]):
            res.assumed.append(p)
        if p.addressee is None:
            res.unaddressed.append(p)
            continue
        if p.is_read:
            continue
        if p.from_addr()[0] is None:
            res.undecided.append((p, "from: line did not parse"))
            continue
        pool = recs
        if replied(p, pool):
            continue
        over = is_over(p.name, now, hours)
        if over is None:
            res.undecided.append((p, "no date in filename"))
        elif over:
            res.unanswered.setdefault(p.to_addr()[0], []).append(p)
    return res


def render_result(res: Result, now: datetime, hours: float, missing_branches=frozenset()) -> list:
    n = sum(len(v) for v in res.unanswered.values())
    out = [f"UNANSWERED >{hours:g}h BY ADDRESSEE: {n} packet(s), {len(res.unanswered)} addressee(s)"]
    rows = sorted(res.unanswered.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for addr, ps in rows:
        ages = sorted((age_hours(p.name, now) / 24.0 for p in ps), reverse=True)
        flags = []
        a = sum(1 for p in ps if p.to_addr()[1])
        if a:
            flags.append(f"ASSUMED {a}")
        if addr in missing_branches:
            flags.append("NO SUCH BRANCH")
        pl = sum(1 for p in ps if not p.tracked)
        if pl:
            flags.append(f"placed {pl}")
        tail = f"  [flags: {', '.join(flags)}]" if flags else ""
        out.append(f"  {addr}  {len(ps)} unanswered ({', '.join(f'{x:.1f}d' for x in ages)}){tail}")
    out.append(f"UNDECIDED: {len(res.undecided)}")
    by: dict = {}
    for p, why in res.undecided:
        by.setdefault(why, []).append(p.name)
    for why in sorted(by):
        out.append(f"  {why}: {len(by[why])}")
        out.extend(f"    {x}" for x in sorted(by[why])[:5])
    out.append(f"UNADDRESSED: {len(res.unaddressed)}")
    out.append(f"ASSUMED ADDRESSES: {len(res.assumed)} bare/title addresses resolved to their home repo")
    out.append("NO SUCH BRANCH:" + ("" if missing_branches else " none"))
    for addr in sorted(missing_branches):
        out.append(f"  {addr}  {len(res.unanswered.get(addr, []))} unanswered packet(s)")
    return out
