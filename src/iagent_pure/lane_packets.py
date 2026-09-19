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
_TO = re.compile(r"^\s*to:\s*(?:ia-)?([A-Za-z0-9]+)(?:\s*/\s*lane/[A-Za-z0-9]+)?\s*$", re.M | re.I)

#: `read-by: ia-91/lane/91 2026-09-19` — the stamp. The date is recorded for the report and is
#: deliberately not parsed for correctness: a stamp with a wrong date is still a lane saying it
#: read the packet, and refusing it on format would make the honest act harder than skipping it.
_READ_BY = re.compile(
    r"^\s*read-by:\s*(?:ia-)?([A-Za-z0-9]+)(?:\s*/\s*lane/[A-Za-z0-9]+)?\s*(\S+)?", re.M | re.I
)

#: The conventions already in the tree, read from the H1.
_TITLE_FORMS = (
    re.compile(r"^#\s.*?\bfor\s+lane\s+([A-Za-z0-9]+)", re.I),
    re.compile(r"^#\s.*?\bto\s+the\s+([A-Za-z0-9]+)\s+lane\b", re.I),
    re.compile(r"^#\s.*?\bto\s+lane\s+([A-Za-z0-9]+)", re.I),
)


@dataclass
class Packet:
    path: str
    addressee: str | None          # lane id, e.g. "91", or None when unattributable
    read_by: list = field(default_factory=list)   # lane ids that stamped it
    source: str = "none"           # how the addressee was found: to | title | none

    @property
    def is_read(self) -> bool:
        """Read by the lane it is ADDRESSED to. A stamp from another lane is not a read.

        An unaddressed packet can never be read, which is why UNADDRESSED is reported as its own
        state rather than folded in with unread — they need different repairs.
        """
        return bool(self.addressee) and self.addressee in self.read_by


def parse_packet(path: Path) -> Packet:
    text = path.read_text(encoding="utf-8", errors="replace")
    head = "\n".join(text.splitlines()[:40])

    addressee, source = None, "none"
    m = _TO.search(head)
    if m:
        addressee, source = m.group(1).lower(), "to"
    else:
        for form in _TITLE_FORMS:
            t = form.search(head)
            if t:
                addressee, source = t.group(1).lower(), "title"
                break

    read_by = [r.group(1).lower() for r in _READ_BY.finditer(text)]
    return Packet(path=path.as_posix(), addressee=addressee, read_by=read_by, source=source)


def scan(sessions_dir: Path) -> list:
    """Every packet in the inbox, parsed. Sorted newest-first by filename, which carries the date."""
    if not sessions_dir.is_dir():
        return []
    return [parse_packet(p) for p in sorted(sessions_dir.glob("*.md"), reverse=True)]


def unread_by_lane(packets) -> dict:
    """lane -> [packets addressed to it and not stamped by it]."""
    out: dict = {}
    for p in packets:
        if p.addressee and not p.is_read:
            out.setdefault(p.addressee, []).append(p)
    return out


def unaddressed(packets) -> list:
    """Packets naming no lane. A NAMED state, not a silent drop — an inbox that discards what it
    cannot attribute is the same silence this module exists to end."""
    return [p for p in packets if not p.addressee]
