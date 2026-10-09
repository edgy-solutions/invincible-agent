"""The lane-less seat form `<repo>/seat/<name>`, ruled 2026-09-26.

WHY IT EXISTS. Some seats own no worktree — the architecture seat routes and never commits shared
docs — so `ia-NN/lane/NN` has nothing to name them with, and a packet for one parsed as UNADDRESSED.
That is the `cortex-60` defect one door over: a real recipient the rule could not spell, quietable
only by misnaming the recipient.

WHAT THIS SEAL IS ACTUALLY DEFENDING, which is not the happy path. Making an address parseable
moves a packet OUT of the UNADDRESSED list, and the census's lane rows are enumerated from
`origin/lane/*` — which cannot enumerate a seat. So the obvious half of the fix, on its own, is
strictly WORSE than the defect it repairs: the packet would be attributed, excluded from the
unaddressed report, absent from every lane row, and printed NOWHERE. A gap that exists and nothing
prints is the class this whole module was built to end, and the fix for one instance of it is
exactly how the next one gets introduced. Three of the arms below are about that, not about parsing.

The other half is symmetry: `_TO` and `_READ_BY` must accept the SAME addresses. An address form
the stamp cannot spell makes its packets permanently unread — the seat commits the line the report
asks for, the regex declines it, and the census prints a standing gap against a seat that did the
work, with no way for the seat to tell. So both patterns are driven from ONE address list here
rather than being trusted to have been edited together.

Run: uv run --frozen pytest tests/test_a_seat_with_no_lane_is_still_an_address.py -v
"""

from __future__ import annotations

import ast
import io
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))
if str(_REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO / "scripts"))

from iagent_pure import lane_packets  # noqa: E402
from iagent_pure.lane_packets import (  # noqa: E402
    parse_packet,
    scan,
    unaddressed,
    unread_by_lane,
    unread_by_seat,
)

#: THE ONE ADDRESS LIST. Both patterns are fired against it, so a form added to the address and
#: forgotten in the stamp cannot pass. (text, expected name, expected kind).
ADDRESS_FORMS = [
    ("invincible-agent/seat/architecture", "architecture", "seat"),
    ("cortex-ui/seat/frontend", "frontend", "seat"),
    ("invincible-agent/seat/release-manager", "release-manager", "seat"),
    ("ia-74/lane/74", "74", "lane"),
    ("ia-eo/lane/eo", "eo", "lane"),
    ("cortex-60", "cortex-60", "lane"),
    ("32", "32", "lane"),
]

#: QUALIFIED addresses carrying a trailing clause. Lifted verbatim from packets sitting in this
#: inbox — both addressed to lane/74 in the conventional form, both invisible to the census for a
#: week because `$` refused the note after the address.
TRAILING_FORMS = [
    ("ia-74/lane/74 — from ia-32/lane/32, 2026-09-21. Lane 32 closes", "74"),
    ("`ia-74` / `lane/74` (the consolidated worker)", "74"),
    ("invincible-agent/seat/architecture — routes, never commits shared docs", "architecture"),
    ("ia-eo/lane/eo, and to Lane 1 for the roster", "eo"),
]

#: Addresses that must NOT parse. Without these the patterns above prove only that something
#: matched, never that the match was the address — an alternation this permissive is one `.*` away
#: from accepting the whole line.
#:
#: THE LAST FOUR ARE THE ONES THAT MATTER, and they are why a trailing clause is allowed only after
#: a QUALIFIED address. `to: the architect` appears on four real packets. If a bare token could
#: carry a trailer, it would parse as lane `the` — six honest UNADDRESSED reports silently becoming
#: six deliveries to a lane that does not exist, which is worse than the gap being fixed.
NON_ADDRESSES = [
    "/seat/architecture",          # no repo
    "invincible-agent/seat/",      # no seat name — matched `body` two lines down before `[ \t]`
    "invincible-agent/seat",       # no separator, no name
    "invincible-agent / / architecture",
    "the architect",
    "the architect seat (lane-less by R-019 — the inbox seal has no word for this)",
    "the — architect",             # a bare token FOLLOWED BY a trailer opener
    "whoever takes the shared master tree",
]


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def _seat_repo(tmp_path: Path, *bodies: str) -> Path:
    """A repo-shaped directory with a sessions/ inbox and nothing else. `report_lanes` shells out to
    git, which fails here and is handled — that is deliberate: it isolates the PACKET half of the
    report from the branch half."""
    (tmp_path / "sessions").mkdir(exist_ok=True)
    for i, body in enumerate(bodies):
        (tmp_path / "sessions" / f"2026-09-26-p{i}.md").write_text(body, encoding="utf-8")
    return tmp_path


# ── the address, and the stamp, from one list ───────────────────────────────────────────────────

@pytest.mark.parametrize("text,name,kind", ADDRESS_FORMS, ids=[f[0] for f in ADDRESS_FORMS])
def test_every_address_form_parses_as_an_address(tmp_path, text, name, kind):
    got = parse_packet(_write(tmp_path, "a.md", f"# A packet\n\nto: {text}\n\nbody\n"))
    assert (got.addressee, got.kind, got.source) == (name, kind, "to"), (
        f"`to: {text}` parsed as {got.addressee!r}/{got.kind!r} via {got.source!r}"
    )


@pytest.mark.parametrize("text,name,kind", ADDRESS_FORMS, ids=[f[0] for f in ADDRESS_FORMS])
def test_every_address_form_can_also_be_STAMPED(tmp_path, text, name, kind):
    """The symmetry arm. An address `_TO` accepts and `_READ_BY` refuses makes its packets
    permanently unread, and the recipient cannot tell — worse than being unaddressable, because
    the failure is invisible from the side doing the work."""
    body = f"# A packet\n\nto: {text}\n\nbody\n\nread-by: {text} 2026-09-26\n"
    got = parse_packet(_write(tmp_path, "b.md", body))
    assert name in got.read_by, f"`read-by: {text}` recorded {got.read_by!r}, not {name!r}"
    assert got.is_read, f"{text} stamped its own packet and it still reports unread"


@pytest.mark.parametrize("text,name", TRAILING_FORMS, ids=[f[1] + ":" + f[0][:24] for f in TRAILING_FORMS])
def test_a_qualified_address_may_carry_a_note_after_it(tmp_path, text, name):
    """`$` was refusing correctly-named recipients over punctuation. Two packets addressed to
    lane/74 sat unread for a week because of it, one of them lane 32's closing handoff."""
    got = parse_packet(_write(tmp_path, "t.md", f"# A packet\n\nto: {text}\n\nbody\n"))
    assert got.addressee == name, f"`to: {text}` parsed as {got.addressee!r}"


def test_a_space_alone_does_not_open_a_trailing_clause(tmp_path):
    """The accepted set is a claim, so the REFUSED neighbour is fired too. Only `— ( , :` open a
    clause; widening to any whitespace is what would let prose addresses back in."""
    got = parse_packet(_write(tmp_path, "u.md", "# P\n\nto: ia-74/lane/74 from ia-32\n\nbody\n"))
    assert got.addressee is None, f"a bare space opened a clause: {got.addressee!r}"


def test_the_two_lane_74_packets_in_the_REAL_inbox_are_now_delivered():
    """Derived from the population, not from a fixture. These two files are the measured instance
    of the defect: conventionally addressed, never delivered. A fixture-only seal would control the
    logic and say nothing about whether the logic still points at anything real."""
    by_name = {Path(p.path).name: p for p in scan(_REPO / "sessions")}
    wanted = [n for n in by_name if "handoff-lane-32-closing-the-ledger" in n
              or "handoff-eo-mode-reads-hybrid" in n]
    assert len(wanted) == 2, f"expected both packets in the inbox, found {wanted}"
    for n in wanted:
        assert by_name[n].addressee == "74", (
            f"{n} is addressed to lane/74 on its `to:` line and parsed as "
            f"{by_name[n].addressee!r} — it is in my inbox and the census cannot see it"
        )


@pytest.mark.parametrize("text", NON_ADDRESSES)
def test_a_malformed_seat_address_is_not_an_address(tmp_path, text):
    got = parse_packet(_write(tmp_path, "c.md", f"# Note with no title form\n\nto: {text}\n\nbody\n"))
    assert got.addressee is None, f"`to: {text}` parsed as {got.addressee!r}/{got.kind!r}"


def test_a_stamp_from_a_different_seat_is_not_a_read(tmp_path):
    body = ("# A packet\n\nto: invincible-agent/seat/architecture\n\nbody\n\n"
            "read-by: invincible-agent/seat/frontend 2026-09-26\n")
    got = parse_packet(_write(tmp_path, "d.md", body))
    assert got.read_by == ["frontend"]
    assert not got.is_read, "a stamp from another seat must not mark the packet read"


# ── the group(1) trap: the change had to not break the existing tree ────────────────────────────

def test_every_real_packet_in_the_tree_still_parses():
    """THE REGRESSION ARM, and the reason it is not a formality: the first named group in the new
    alternation is `seat`, so the pre-existing `m.group(1)` became None for every LANE address and
    raised on `.lower()`. Every packet in the inbox is a lane packet, so the whole inbox was broken
    by the edit that made seats work, and no arm about seats would have noticed."""
    packets = scan(_REPO / "sessions")
    assert len(packets) >= 3, f"only {len(packets)} packets — this arm is not reading a population"
    assert any(p.addressee and p.kind == "lane" for p in packets), (
        "no LANE-addressed packet in the inbox, so this arm cannot see the trap it exists for"
    )


# ── the part that is actually dangerous: attributed and printed nowhere ─────────────────────────

def test_a_seat_packet_is_not_charged_to_a_lane(tmp_path):
    got = parse_packet(_write(tmp_path, "e.md", "# P\n\nto: invincible-agent/seat/architecture\n"))
    assert unread_by_lane([got]) == {}, "a seat's packet must not appear in the lane enumeration"
    assert list(unread_by_seat([got])) == ["architecture"]
    assert unaddressed([got]) == [], "it IS addressed — which is why the census must print it"


def test_the_census_prints_a_seat_that_has_work_standing(tmp_path):
    """The defect this seal exists for. The packet is addressed (so the UNADDRESSED block skips it)
    and has no branch (so no lane row mentions it). If the report does not name it, the seat form
    has moved a visible gap into an invisible one."""
    from _lane_census import report_lanes

    repo = _seat_repo(tmp_path, "# P\n\nto: invincible-agent/seat/architecture\n\nbody\n")
    buf = io.StringIO()
    with redirect_stdout(buf):
        report_lanes(repo)
    out = buf.getvalue()

    assert "unavailable" not in out, f"the report declined to run, so it asserts nothing:\n{out}"
    assert "architecture" in out, f"a seat with an unread packet is printed nowhere:\n{out}"
    assert "1 unread" in out, f"the seat is named but its work is not counted:\n{out}"


def test_the_census_does_NOT_invent_a_seat_row(tmp_path):
    """The negative control for the arm above, differing in exactly what the report decides on: the
    same code path, the same repo shape, one lane-addressed packet instead of a seat-addressed one.
    Without it, a row printed unconditionally would pass the arm above."""
    from _lane_census import report_lanes

    repo = _seat_repo(tmp_path, "# P\n\nto: ia-74/lane/74\n\nbody\n")
    buf = io.StringIO()
    with redirect_stdout(buf):
        report_lanes(repo)
    out = buf.getvalue()

    assert "unavailable" not in out
    assert "\n        seat/" not in out, f"a seat row printed with no seat packet in the inbox:\n{out}"


def test_the_census_reads_the_seat_enumeration_and_not_only_the_lane_one():
    """Named-call arm. The two arms above are behavioural and would both survive a report that
    happened to name the seat for another reason; this one pins WHICH derivation it came from."""
    src = (_REPO / "scripts" / "_lane_census.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "unread_by_seat" in called, "the census never calls the seat enumeration"
    assert "unread_by_lane" in called, "the lane enumeration was dropped, not joined"


# ── the ambiguity the bare name leaves open ─────────────────────────────────────────────────────

def test_the_lane_and_seat_namespaces_are_disjoint():
    """`read_by` holds BARE names across both kinds, so a lane `x` and a seat `x` would read each
    other's packets. That is defended here rather than by qualifying the name, because this fires
    when the colliding name is ADDED — the moment the ambiguity becomes real — instead of demanding
    a shape change for a collision that does not exist yet.

    Derived on both sides: lanes from the branch list, seats from the inbox. If either population
    comes back empty the arm says so, since two empty sets are trivially disjoint."""
    r = subprocess.run(["git", "branch", "-a", "--format=%(refname:short)"],
                       cwd=str(_REPO), capture_output=True, encoding="utf-8", errors="replace")
    lanes = {b.rsplit("/", 1)[-1].lower() for b in (r.stdout or "").splitlines() if "lane/" in b}
    seats = {p.addressee for p in scan(_REPO / "sessions") if p.kind == "seat" and p.addressee}

    assert lanes, "no lane branches found — this arm is comparing against an empty population"
    overlap = lanes & seats
    assert not overlap, (
        f"{sorted(overlap)} names both a lane and a seat. `read_by` holds bare names, so each "
        f"would count as having read the other's packets. Rename one, or qualify the stamp."
    )


# ── the documentation is a claim about the population of valid forms ────────────────────────────

def test_the_reports_hints_spell_forms_the_parser_actually_ACCEPTS():
    """The census tells the reader what to write. A hint naming a form the parser refuses would send
    a seat off to commit a stamp that never counts, so the forms are lifted OUT of the printed text
    and fired through the real regexes — derived, not retyped."""
    src = (_REPO / "scripts" / "_lane_census.py").read_text(encoding="utf-8")
    assert "seat/<name>" in src, "the report still documents only the lane form"

    for pattern, label in ((lane_packets._TO, "to"), (lane_packets._READ_BY, "read-by")):
        line = f"{label}: invincible-agent/seat/architecture"
        m = pattern.search(line)
        assert m and lane_packets._addressed(m) == ("architecture", "seat"), (
            f"the report tells people to write `{line}` and the parser does not accept it"
        )


def test_the_disjointness_arm_reads_the_LANE_NAMES_THE_INBOX_NAMES_not_only_branch_refs():
    """The arm above derives lanes from `git branch -a` IN THIS REPO. That is the wrong layer, and
    it was measured wrong rather than argued wrong: on 2026-09-26 a packet was addressed
    `invincible-agent/seat/ca` while `2026-09-18-dispatch-ca-cut-v0-9-3.md` already addressed
    `ia-ca/lane/ca`. The name `ca` was live in BOTH registries and the arm reported disjoint.

    The reason is a term in the wrong layer. `read_by` collides across PARSED ADDRESSES, but the
    population was taken from REFS, and the two differ exactly where it matters: ca's branch lives
    in the SDK repo, so this tree has no `lane/ca` (only `lane/ca-m33-cutover`, whose last segment
    is not `ca`). Four names the inbox treats as lanes -- `7f`, `ca`, `cortex-60`, `cortex-ui` --
    have no branch here at all, and they are the names MOST likely to be re-addressed as seats,
    because whoever writes the packet cannot see the branch that would have said "lane".

    So the population is the UNION: refs, plus every addressee the parser already calls a lane.
    Refs are kept because a lane with an empty inbox still exists and could still be collided with.
    """
    r = subprocess.run(["git", "branch", "-a", "--format=%(refname:short)"],
                       cwd=str(_REPO), capture_output=True, encoding="utf-8", errors="replace")
    from_refs = {b.rsplit("/", 1)[-1].lower() for b in (r.stdout or "").splitlines() if "lane/" in b}

    packets = scan(_REPO / "sessions")
    from_inbox = {p.addressee for p in packets if p.kind == "lane" and p.addressee}
    lanes = from_refs | from_inbox
    seats = {p.addressee for p in packets if p.kind == "seat" and p.addressee}

    assert from_refs, "no lane branches found -- this arm is comparing against an empty population"
    assert from_inbox, "no lane-addressed packets found -- the inbox half of the population is empty"

    overlap = lanes & seats
    assert not overlap, (
        f"{sorted(overlap)} names both a lane and a seat. `read_by` holds bare names, so each "
        f"would count as having read the other's packets, and the census prints the name in two "
        f"registries with neither row holding the whole inbox. Address it the way the inbox "
        f"already addresses it, or rename one."
    )


def test_the_inbox_half_of_the_population_is_what_CATCHES_a_branchless_lane():
    """A control for the arm above, differing in exactly what the guard decides on: the POPULATION
    SOURCE, not the comparison. It reconstructs the old ref-only derivation and asserts it is blind
    to a seat colliding with a lane that has no branch in this tree -- so the widening is load
    bearing and not a decoration. If this arm ever goes green because the ref set grew to cover the
    inbox set, say so by deleting it; do not widen it further.
    """
    r = subprocess.run(["git", "branch", "-a", "--format=%(refname:short)"],
                       cwd=str(_REPO), capture_output=True, encoding="utf-8", errors="replace")
    from_refs = {b.rsplit("/", 1)[-1].lower() for b in (r.stdout or "").splitlines() if "lane/" in b}
    from_inbox = {p.addressee for p in scan(_REPO / "sessions") if p.kind == "lane" and p.addressee}

    branchless = from_inbox - from_refs
    assert branchless, (
        "every lane the inbox names now has a branch in this tree, so the ref-only derivation is "
        "no longer blind and this control has nothing left to establish -- delete it"
    )
    # The collision the ref-only arm cannot see is a seat named for any of these.
    assert not (branchless & from_refs)
