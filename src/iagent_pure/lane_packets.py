"""Which lane a packet is for, and whether that lane has said it read it.

WHY THIS EXISTS, in the architect's own diagnosis: *"I told 32, 74 and the eo lane 'nothing
blocked on your side' this week while each had an unread packet sitting in their inbox — because
I rule to Lane 1, Lane 1 writes the packet, and nobody, including me, checks whether it was
READ."*

**The inbox fixed DELIVERY. It made "delivered" checkable and left "read" invisible** — so a lane
that ends its session on "idle until X rolls" never learns X rolled, and a session that is idle
does not know it has work. The cost was two days on the brief and the safety walk.

That is the census's own defect class: **a gap that exists and nothing prints.** So the remedy is
the shape every other one took this week — derive the population, partition it, print it as STATE
every run rather than as news.

    ia-32: 2 unread (5d, 3d), last commit 3d

would have been on the board on Thursday morning.

── READING IS AN ACT, NOT AN ASSUMPTION ────────────────────────────────────────────────────────

A packet is READ when the addressed lane commits a one-line stamp to it:

    read-by: ia-32/lane/32 2026-09-19

Delivery is the inbox; reading is the stamp; **both are on the rail**. "They were told" stops
being a claim anyone can make — including the architect, who named themselves in the diagnosis.

── ADDRESSING, DERIVED AND PARTITIONED ─────────────────────────────────────────────────────────

An explicit `to:` line wins. Failing that the H1 is read, because a convention already existed
before this module did — *"Packet for lane 91"*, *"Dispatch to the eo lane"* — and a derivation
that ignored the packets already written would start with an empty population.

**A packet matching neither is reported UNADDRESSED, never dropped.** An inbox that silently
discards what it cannot attribute is the same silence one layer down.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: `to: ia-91/lane/91` — the explicit form, and the one a new packet should carry.
#:
#: A LANE TOKEN MAY CARRY A HYPHEN. `cortex-60` is a real session address and the first
#: character class here could not express it, so a packet addressed to that session could not
#: be addressed at all — the inbox seal reported it UNADDRESSED and the only way to quiet that
#: was to misname the recipient. A rule that cannot spell a real address is a rule that
#: manufactures its own violations.
#:
#: `to: invincible-agent/seat/architecture` — THE LANE-LESS SEAT, ruled 2026-09-26. Some seats own
#: no worktree: the architecture seat routes and never commits shared docs, so `ia-NN/lane/NN` has
#: nothing to name it with. Until this form existed those packets parsed as UNADDRESSED, which is
#: the `cortex-60` defect one door over — a real recipient the rule could not spell.
#:
#: THE ADDRESS IS THE SEAT, NOT THE REPO, by the same logic as the lane form: `ia-74/lane/74`
#: captures `74` and treats `ia-74` as where the work happens, so `<repo>/seat/<name>` captures
#: `<name>` and treats `<repo>` as where the inbox lives. Capturing the repo would file every seat's
#: packets under one address and make an inbox nobody could read.
#:
#: ── THREE THINGS THIS PATTERN GOT WRONG, all found by measuring the inbox rather than by reading
#: the regex ─────────────────────────────────────────────────────────────────────────────────────
#:
#: 1. `\s` CROSSES NEWLINES. `re.M` rebinds `^` and `$`; it does not stop `\s*` eating a line break,
#:    so `to: <repo>/seat/` with an empty name reached two lines down and addressed the packet to
#:    the word `body`. Every horizontal run here is `[ \t]` for that reason.
#:
#: 2. `$` REFUSED REAL ADDRESSES WITH A NOTE AFTER THEM. Two packets in this inbox are addressed to
#:    `lane/74` in the conventional form and were invisible to the census for a week, because the
#:    line carries a trailing clause — `to: ia-74/lane/74 — from ia-32/lane/32, 2026-09-21` and
#:    ``to: `ia-74` / `lane/74` (the consolidated worker)``. One of them is lane 32's closing
#:    handoff. The rule was refusing correctly-named recipients over punctuation, which is the
#:    `cortex-60` defect again, and the backtick form shows the same thing: people write the address
#:    the way the docs render it.
#:
#: 3. THE TRAILING CLAUSE IS ALLOWED ONLY AFTER A QUALIFIED ADDRESS — one carrying `/lane/` or
#:    `/seat/`. A BARE token must still own the whole line. This is not fussiness: four packets here
#:    say `to: the architect`, and a trailer permitted after a bare token would parse that as lane
#:    `the` — turning six honest UNADDRESSED reports into six confident deliveries to a lane that
#:    does not exist. A widened set with a stale description, where the new members are the junk.
_QUALIFIED = (
    r"`?[A-Za-z0-9][A-Za-z0-9-]*`?[ \t]*/[ \t]*`?seat/(?P<seat>[A-Za-z0-9][A-Za-z0-9-]*)`?"
    r"|`?(?:ia-)?(?P<lane>[A-Za-z0-9][A-Za-z0-9-]*)`?[ \t]*/[ \t]*`?lane/[A-Za-z0-9-]+`?"
)
#: Only `— note`, `(note)`, `,` and `:` open a trailing clause. A bare space does not, so
#: `to: ia-74/lane/74 from ia-32` is still refused — stated here because the accepted set is a
#: claim, and the seal fires each of these rather than restating them.
_TRAILER = r"[ \t]*(?:[-—–(,:].*)?"
_BARE = r"(?:ia-)?(?P<bare>[A-Za-z0-9][A-Za-z0-9-]*)"

_TO = re.compile(
    rf"^[ \t]*to:[ \t]*(?:(?:{_QUALIFIED}){_TRAILER}|{_BARE}[ \t]*)$",
    re.M | re.I,
)

#: `read-by: ia-91/lane/91 2026-09-19` — the stamp. The date is recorded for the report and is
#: deliberately not parsed for correctness: a stamp with a wrong date is still a lane saying it
#: read the packet, and refusing it on format would make the honest act harder than skipping it.
#:
#: IT MUST SPELL EVERY FORM `_TO` SPELLS. Adding the seat form to the ADDRESS and not to the STAMP
#: would make a seat's packet PERMANENTLY UNREAD: the seat commits the one line the report asks
#: for, this regex does not match it, and the census goes on printing a standing gap against a seat
#: that did the work. That is the `cortex-60` defect with its sign flipped — not a recipient the
#: rule cannot name, but an ACT the rule cannot record — and it is worse than the original, because
#: the seat has no way to tell that its stamp did not count. So the two patterns carry the SAME
#: alternation, and a seal drives both from one address list rather than trusting them to match.
_READ_BY = re.compile(
    rf"^[ \t]*read-by:[ \t]*(?:{_QUALIFIED}|{_BARE})[ \t]*(?P<date>\S+)?",
    re.M | re.I,
)


def _addressed(m) -> tuple[str, str]:
    """The (name, kind) a matched address names. ONE reader for both patterns, so the address form
    and the stamp form cannot drift apart by being parsed in two places.

    `m.group(1)` was what both sites used before the seat form existed, and it is now a TRAP: the
    first named group in the alternation is `seat`, so a plain lane address makes `group(1)` None
    and every existing packet in the tree raises on `.lower()`. The named groups are the fix, and
    this helper is why there is only one place to get it wrong.
    """
    seat = m.group("seat")
    if seat:
        return seat.lower(), "seat"
    # QUALIFIED lane (`ia-74/lane/74`) or BARE token (`cortex-60`). They are separate groups
    # because only the qualified form may carry a trailing clause — see `_TO`.
    return (m.group("lane") or m.group("bare")).lower(), "lane"

#: The conventions already in the tree, read from the H1.
_TITLE_FORMS = (
    re.compile(r"^#\s.*?\bfor\s+lane\s+([A-Za-z0-9]+)", re.I),
    re.compile(r"^#\s.*?\bto\s+the\s+([A-Za-z0-9]+)\s+lane\b", re.I),
    re.compile(r"^#\s.*?\bto\s+lane\s+([A-Za-z0-9]+)", re.I),
)


@dataclass
class Packet:
    path: str
    addressee: str | None          # lane id ("91") or seat name ("architecture"); None = unattributable
    read_by: list = field(default_factory=list)   # names that stamped it, of either kind
    source: str = "none"           # how the addressee was found: to | title | none
    #: WHICH REGISTRY the addressee is in — a lane (has a worktree and a branch) or a lane-less
    #: seat. This is a SECOND AXIS and not another value of `source`: `source` answers how the
    #: address was FOUND (explicit line, H1, nowhere) and `kind` answers what it NAMES. Folding
    #: them into one field is the mistake `route_status` and the disposition vocabulary were kept
    #: apart to avoid, and the cost is paid by the reader: the census enumerates lanes from
    #: `origin/lane/*`, which cannot enumerate a seat, so it needs to ask this directly.
    kind: str = "lane"

    @property
    def is_read(self) -> bool:
        """Read by the lane or seat it is ADDRESSED to. A stamp from another one is not a read.

        An unaddressed packet can never be read, which is why UNADDRESSED is reported as its own
        state rather than folded in with unread — they need different repairs.

        IDENTITY IS THE BARE NAME, ACROSS BOTH KINDS. A lane called `x` and a seat called `x` would
        therefore read each other's packets. That is not defended here by qualifying the name —
        `read_by` is a list of bare names and a seal pins that shape — but by a seal asserting the
        two namespaces are DISJOINT, which fires when someone adds the colliding name, i.e. at the
        moment the ambiguity becomes real rather than at the moment it becomes possible.
        """
        return bool(self.addressee) and self.addressee in self.read_by


def parse_packet(path: Path) -> Packet:
    text = path.read_text(encoding="utf-8", errors="replace")
    head = "\n".join(text.splitlines()[:40])

    addressee, source, kind = None, "none", "lane"
    m = _TO.search(head)
    if m:
        addressee, kind = _addressed(m)
        source = "to"
    else:
        # THE TITLE FORMS NAME LANES ONLY, and deliberately stay that way: they exist to read
        # packets written before the inbox did, and no such packet addresses a seat.
        for form in _TITLE_FORMS:
            t = form.search(head)
            if t:
                addressee, source = t.group(1).lower(), "title"
                break

    read_by = [_addressed(r)[0] for r in _READ_BY.finditer(text)]
    return Packet(path=path.as_posix(), addressee=addressee, read_by=read_by, source=source, kind=kind)


def scan(sessions_dir: Path) -> list:
    """Every packet in the inbox, parsed. Sorted newest-first by filename, which carries the date."""
    if not sessions_dir.is_dir():
        return []
    return [parse_packet(p) for p in sorted(sessions_dir.glob("*.md"), reverse=True)]


def unread_by_lane(packets) -> dict:
    """lane -> [packets addressed to it and not stamped by it].

    LANES ONLY, since the seat form arrived. Its caller looks each key up against a branch derived
    from `origin/lane/*`, so a seat's packets landing in this dict would be counted and then
    printed by nobody — see `unread_by_seat`.
    """
    out: dict = {}
    for p in packets:
        if p.addressee and p.kind == "lane" and not p.is_read:
            out.setdefault(p.addressee, []).append(p)
    return out


def unread_by_seat(packets) -> dict:
    """seat -> [packets addressed to it and not stamped by it].

    WHY THIS IS A SEPARATE ENUMERATION AND NOT A FILTER ON THE SAME ONE. A lane's population comes
    from the branch list: the census can print `inbox clear` for a lane with no packets at all,
    because the lane exists whether or not anything is addressed to it. **A lane-less seat has no
    branch, so its only evidence of existing is a packet addressed to it** — the population has to
    be derived FROM THE PACKETS, and an unread count is all that can be reported.

    The consequence is worth stating where the code is, because it is the one blind spot this form
    keeps: a seat with an EMPTY inbox is indistinguishable from a seat that does not exist. That is
    the acceptable half of the trade (nothing is waiting on it either way), whereas the alternative
    — routing seat packets through `unread_by_lane` — loses the case that matters, a seat with work
    standing and no row anywhere to print it.
    """
    out: dict = {}
    for p in packets:
        if p.addressee and p.kind == "seat" and not p.is_read:
            out.setdefault(p.addressee, []).append(p)
    return out


def unaddressed(packets) -> list:
    """Packets naming neither a lane nor a seat. A NAMED state, not a silent drop — an inbox that
    discards what it cannot attribute is the same silence this module exists to end."""
    return [p for p in packets if not p.addressee]
