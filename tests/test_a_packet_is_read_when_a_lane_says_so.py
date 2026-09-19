"""Delivery is the inbox; reading is a stamp. Both on the rail, both derivable.

RULED 2026-09-18, from the architect's own diagnosis: *"I told 32, 74 and the eo lane 'nothing
blocked on your side' this week while each had an unread packet sitting in their inbox — because
I rule to Lane 1, Lane 1 writes the packet, and nobody, INCLUDING ME, checks whether it was
read."*

**The inbox fixed DELIVERY and left READING invisible.** A lane that ends a session on "idle until
X rolls" never learns X rolled; a session that is idle does not know it has work. Cost: two days
on the brief and the safety walk. It is the census's own defect class — a gap that exists and
nothing prints — so the remedy is the one every other one took this week: derive, partition,
print as STATE every run.

The first run of the derivation reported what the week had hidden:

    ia-32: 2 unread (1d, 3d)   ia-91: 3 unread   ia-74: 1   ia-eo: 1   ia-5f: 1

Run: uv run --frozen pytest tests/test_a_packet_is_read_when_a_lane_says_so.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from iagent_pure.lane_packets import (  # noqa: E402
    parse_packet,
    scan,
    unaddressed,
    unread_by_lane,
)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_the_inbox_is_not_empty():
    """THE FLOOR. A derivation reading zero packets would report every lane clear forever —
    which is precisely the silence this exists to end, wearing a green."""
    packets = scan(_REPO / "sessions")
    assert len(packets) >= 5, f"only {len(packets)} packets found in sessions/"
    assert any(p.addressee for p in packets), "no packet could be attributed to any lane"


def test_an_explicit_to_line_wins(tmp_path):
    p = _write(tmp_path, "x.md", "# Packet for lane 99\n\nto: ia-32/lane/32\n\nbody\n")
    assert parse_packet(p).addressee == "32", "an explicit `to:` must beat the title"
    assert parse_packet(p).source == "to"


def test_THE_TITLE_FORMS_ALREADY_IN_THE_TREE_ARE_READ(tmp_path):
    """R-041's floor applied BEFORE the first run: a derivation that ignored the ten packets
    already written would have started at zero and reported every lane clear."""
    for title, expect in (
        ("# Packet for lane 91 — cost's enumerate provider", "91"),
        ("# Dispatch to the eo lane — the suffix rule scores a bare digit", "eo"),
        ("# Dispatch to lane 74 — the safety TTL", "74"),
    ):
        p = _write(tmp_path, f"{expect}.md", title + "\n\nbody\n")
        got = parse_packet(p)
        assert got.addressee == expect, f"{title!r} -> {got.addressee!r}, expected {expect!r}"
        assert got.source == "title"


def test_READING_IS_THE_STAMP_not_the_delivery(tmp_path):
    """The whole point. A packet sitting in the inbox is DELIVERED; it is READ when the lane it
    is addressed to commits a stamp. 'They were told' stops being a claim anyone can make."""
    unstamped = _write(tmp_path, "a.md", "# Packet for lane 32\n\nbody\n")
    assert not parse_packet(unstamped).is_read

    stamped = _write(tmp_path, "b.md", "# Packet for lane 32\n\nread-by: ia-32/lane/32 2026-09-19\n")
    assert parse_packet(stamped).is_read


def test_A_STAMP_BY_ANOTHER_LANE_IS_NOT_A_READ(tmp_path):
    """Otherwise any lane could clear another's inbox, and the line would measure attention paid
    by whoever happened to open the file."""
    p = _write(tmp_path, "c.md", "# Packet for lane 32\n\nread-by: ia-91/lane/91 2026-09-19\n")
    got = parse_packet(p)
    assert got.read_by == ["91"]
    assert not got.is_read, "a stamp from a different lane must not mark the packet read"


def test_AN_UNADDRESSED_PACKET_IS_NAMED_not_dropped(tmp_path):
    """An inbox that silently discards what it cannot attribute is the same silence one layer
    down. It also cannot be READ — so it is its own state, needing its own repair."""
    p = _write(tmp_path, "d.md", "# Some note with no addressee\n\nbody\n")
    got = parse_packet(p)
    assert got.addressee is None and got.source == "none"
    assert not got.is_read
    assert unaddressed([got]) == [got]
    assert unread_by_lane([got]) == {}, "an unaddressed packet must not be charged to a lane"


def test_THE_REPO_INBOX_IS_FULLY_ADDRESSED():
    """Every packet in the tree names a lane.

    The census's own author having unattributed packets is the first thing a reader would use to
    dismiss the line — so this is asserted against the REAL inbox rather than a fixture.
    """
    stray = [Path(p.path).name for p in unaddressed(scan(_REPO / "sessions"))]
    assert not stray, (
        f"packets naming no lane: {stray}. Add `to: ia-<lane>/lane/<lane>` — an unaddressed "
        f"packet can never be read, so it is invisible to the very line that exists to surface it"
    )
