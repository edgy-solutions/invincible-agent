"""EXTERNAL addresses, the 48h unanswered report, and the third state in the lane census.

Measured defects (architect seat): `doc-tools/lane/7f` filed under a lane named `doc-tools` and
printed nowhere; `to: OpenDDIL's agent` UNADDRESSED; nothing watching unanswered packets; and the
census blind to a packet that was never COMMITTED (docs/measurements/2026-09-28-the-inbox-census-
and-the-third-state-is-not-where-the-dispatch-put-it.md).

Run: uv run pytest tests/test_an_address_in_another_repo_is_external_and_unanswered_is_reported.py
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
for sub in ("src", "scripts"):
    if str(_REPO / sub) not in sys.path:
        sys.path.insert(0, str(_REPO / sub))

from iagent_pure import lane_packets  # noqa: E402
from iagent_pure.lane_packets import (  # noqa: E402
    external_packets,
    parse_packet,
    scan,
    unaddressed,
    unread_by_seat,
    unanswered_over,
)

#: ONE list drives `_TO` and `_READ_BY`. (text, name, kind)
FORMS = [
    ("doc-tools/lane/7f", "doc-tools/lane/7f", "external"),
    ("iagent-mesh-sdk/lane/ca", "iagent-mesh-sdk/lane/ca", "external"),
    ("doc-tools/seat/architect", "architect", "seat"),
    ("cortex-ui/seat/frontend", "frontend", "seat"),
    ("OpenDDIL's agent", "openddil", "external"),
    ("`OpenDDIL`'s agent (the walk owner)", "openddil", "external"),
    ("invincible-agent/seat/architect", "architect", "seat"),
    ("ia-74/lane/74", "74", "lane"),
    ("invincible-agent/lane/01", "01", "lane"),  # this repo, no worktree prefix: the branch suffix is the name
]

H = 3600.0
NOW = 1_000_000_000.0


def _w(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


@pytest.mark.parametrize("text,name,kind", FORMS, ids=[f[0] for f in FORMS])
def test_every_form_parses_by_TO_and_by_READ_BY(tmp_path, text, name, kind):
    got = parse_packet(_w(tmp_path, "a.md", f"# P\n\nto: {text}\n\nread-by: {text} 2026-10-07\n"))
    assert (got.addressee, got.kind, got.source) == (name, kind, "to")
    assert got.read_by == [name], f"`read-by: {text}` did not record {name!r}"
    assert got.is_read


def test_the_architect_is_still_UNADDRESSED_control(tmp_path):
    got = parse_packet(_w(tmp_path, "a.md", "# P\n\nto: the architect\n\nbody\n"))
    assert got.addressee is None and unaddressed([got]) == [got]


def test_a_bare_token_is_a_lane_never_external(tmp_path):
    got = parse_packet(_w(tmp_path, "a.md", "# P\n\nto: openddil\n"))
    assert (got.addressee, got.kind) == ("openddil", "lane")


def test_a_foreign_repo_SEAT_is_a_seat_not_external(tmp_path):
    """lane/74's ruling: THE ADDRESS IS THE SEAT, NOT THE REPO. Seat form is never external."""
    _w(tmp_path, "2026-10-06-a.md", "# P\n\nto: doc-tools/seat/architect\n\nbody\n")
    packets = scan(tmp_path)
    assert [p.path for p in unread_by_seat(packets)["architect"]] == [packets[0].path]
    assert external_packets(packets) == {}


def test_external_packets_enumerates_by_addressee(tmp_path):
    a = parse_packet(_w(tmp_path, "a.md", "# P\n\nto: doc-tools/lane/7f\n"))
    b = parse_packet(_w(tmp_path, "b.md", "# P\n\nto: ia-74/lane/74\n"))
    assert list(external_packets([a, b])) == ["doc-tools/lane/7f"]


# ── unanswered > 48h ────────────────────────────────────────────────────────────────────────────

def _pk(tmp_path, name, frm, to, extra=""):
    return parse_packet(_w(tmp_path, name, f"# P\n\nfrom: {frm}\nto: {to}\n{extra}\nbody\n"))


def _run(packets, age_h):
    return unanswered_over(packets, now=NOW, age_of=lambda path: NOW - age_h * H)


def test_unanswered_at_49h_is_reported(tmp_path):
    p = _pk(tmp_path, "2026-10-01-a.md", "ia-74/lane/74", "ia-32/lane/32")
    got, undecided = _run([p], 49)
    assert list(got) == [("lane", "32")] and undecided == []


def test_not_reported_at_47h(tmp_path):
    p = _pk(tmp_path, "2026-10-01-a.md", "ia-74/lane/74", "ia-32/lane/32")
    assert _run([p], 47) == ({}, [])


def test_answered_by_stamp(tmp_path):
    p = _pk(tmp_path, "2026-10-01-a.md", "ia-74/lane/74", "ia-32/lane/32",
            "read-by: ia-32/lane/32 2026-10-02\n")
    assert _run([p], 100) == ({}, [])


def test_answered_by_a_later_reply(tmp_path):
    p = _pk(tmp_path, "2026-10-01-a.md", "ia-74/lane/74", "ia-32/lane/32")
    r = _pk(tmp_path, "2026-10-02-b.md", "ia-32/lane/32", "ia-74/lane/74")
    got, _ = _run([p, r], 100)
    assert ("lane", "32") not in got, "a later mirrored packet must answer the first"
    # the reply itself is unanswered (nobody replied to it) -- it is addressed to 74
    assert ("lane", "74") in got


def test_an_EARLIER_mirrored_packet_is_not_a_reply(tmp_path):
    r = _pk(tmp_path, "2026-09-30-b.md", "ia-32/lane/32", "ia-74/lane/74")
    p = _pk(tmp_path, "2026-10-01-a.md", "ia-74/lane/74", "ia-32/lane/32")
    got, _ = _run([p, r], 100)
    assert ("lane", "32") in got


def test_unparseable_from_is_UNDECIDED_not_unanswered(tmp_path):
    p = _pk(tmp_path, "2026-10-01-a.md", "invincible-agent/master (Lane 1)", "ia-32/lane/32")
    got, undecided = _run([p], 100)
    assert got == {} and len(undecided) == 1 and "from:" in undecided[0][1]


def test_uncommitted_is_the_third_state_not_fresh(tmp_path):
    p = _pk(tmp_path, "2026-10-01-a.md", "ia-74/lane/74", "ia-32/lane/32")
    got, undecided = unanswered_over([p], now=NOW, age_of=lambda path: None)
    assert got == {} and undecided == []


# ── the census: NO BRANCH, NOT COMMITTED, UNENUMERABLE ──────────────────────────────────────────

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=str(cwd),
                       capture_output=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    return r.stdout


def _census(repo: Path) -> str:
    from _lane_census import report_lanes
    buf = io.StringIO()
    with redirect_stdout(buf):
        report_lanes(repo)
    return buf.getvalue()


@pytest.fixture
def gitrepo(tmp_path):
    """A real repo: `origin` (bare) holding master + `lane/zz`; a clone `main` with a worktree
    `wt` on lane/ww. `lane/zz` has NO local worktree."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "master")
    (seed / "sessions").mkdir()
    (seed / "sessions" / "2026-10-01-seed.md").write_text(
        "# P\n\nfrom: ia-74/lane/74\nto: ia-nolane/lane/nolane\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "branch", "lane/zz")
    _git(seed, "branch", "lane/ww")
    _git(tmp_path, "clone", "--bare", str(seed), str(origin))
    main = tmp_path / "main"
    _git(tmp_path, "clone", str(origin), str(main))
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", str(wt), "-b", "lane/ww", "origin/lane/ww")
    return main, wt


@needs_git
def test_NO_BRANCH_row_for_a_lane_the_repo_does_not_have(gitrepo):
    main, _ = gitrepo
    out = _census(main)
    assert "NO BRANCH  nolane" in out, out


@needs_git
def test_UNENUMERABLE_for_a_branch_with_no_worktree(gitrepo):
    main, _ = gitrepo
    out = _census(main)
    assert "UNENUMERABLE  lane/zz" in out, out
    assert "UNENUMERABLE  lane/ww" not in out, "lane/ww HAS a worktree"
    # The branch is the name. A guessed `ia-<suffix>` worktree name collided with a real
    # worktree holding a different branch (ia-74 / lane/74-engine-w-mesh, 2026-10-08).
    assert "UNENUMERABLE  ia-" not in out, out


@needs_git
def test_NOT_COMMITTED_counts_untracked_only_and_dedupes(gitrepo):
    main, wt = gitrepo
    (wt / "sessions").mkdir(exist_ok=True)
    (wt / "sessions" / "2026-10-07-new.md").write_text("# P\n\nto: ia-74/lane/74\n", encoding="utf-8")
    out = _census(main)
    assert "NOT COMMITTED" in out and "1 packet(s)" in out, out
    assert "1 distinct uncommitted packet(s), 1 present in only one worktree" in out, out
    # the tracked seed packet must not be counted
    assert "2 packet(s)" not in out.split("NOT COMMITTED", 1)[1].splitlines()[0]


@needs_git
def test_a_clean_tree_prints_no_NOT_COMMITTED(gitrepo):
    main, _ = gitrepo
    assert "NOT COMMITTED" not in _census(main)


@needs_git
def test_the_census_scans_a_tree_with_ITS_OWN_scanner_never_the_subjects(gitrepo):
    """The instrument and the subject must not share a surface. The scanned tree carries a decoy
    `iagent_pure.lane_packets` with none of the census's names -- as master did on 2026-10-07,
    when `report_lanes(master)` printed `LANES: unavailable (ImportError)`. A subprocess, because
    in-process the real module is already in sys.modules and would hide the shadowing."""
    main, _ = gitrepo
    decoy = main / "src" / "iagent_pure"
    decoy.mkdir(parents=True)
    (decoy / "__init__.py").write_text("", encoding="utf-8")
    (decoy / "lane_packets.py").write_text("DECOY = True\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(_REPO / "scripts" / "_lane_census.py"), str(main)],
                       capture_output=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0, r.stderr
    assert "LANES: unavailable" not in r.stdout, r.stdout[-400:]
    assert "LANES:" in r.stdout, r.stdout[-400:]


# ── the ruled address form `<repo>/<branch>` (2026-10-07) ───────────────────────────────────────

#: (text, name, kind, form). ONE list drives `_TO`, `_READ_BY` and `_FROM`.
RULED = [
    ("invincible-agent/lane/gov", "gov", "lane", "repo"),
    ("ia-74/lane/74-acceptance-and-docs-subject", "74-acceptance-and-docs-subject", "lane",
     "worktree"),
    ("cortex-ui/lane/cortex-60", "cortex-ui/lane/cortex-60", "external", "repo"),
    ("ia-cortex-60/lane/cortex-60", "cortex-60", "lane", "worktree"),
]


@pytest.mark.parametrize("text,name,kind,form", RULED, ids=[r[0] for r in RULED])
def test_the_ruled_form_is_named_by_its_BRANCH_and_records_its_form(tmp_path, text, name, kind, form):
    """`ia-cortex-60/lane/cortex-60` is an INTERNAL lane `cortex-60`, NOT external: a legacy
    `ia-<x>` prefix is a worktree, and the scanner must not guess that it belongs to another
    repo. The ruled form is how a sender says "another repo" (`cortex-ui/lane/cortex-60`); the
    census reports the legacy count so the sender can re-address."""
    got = parse_packet(_w(tmp_path, "a.md", f"# P\n\nto: {text}\n"))
    assert (got.addressee, got.kind, got.form) == (name, kind, form)


@pytest.mark.parametrize("text,name,kind,form", RULED, ids=[r[0] for r in RULED])
def test_the_ruled_form_parses_identically_through_TO_READ_BY_and_FROM(text, name, kind, form):
    for label, pattern in (("to", lane_packets._TO), ("read-by", lane_packets._READ_BY),
                           ("from", lane_packets._FROM)):
        m = pattern.search(f"{label}: {text}")
        assert m, f"`{label}: {text}` not accepted"
        assert lane_packets._addressed(m) == (name, kind), label
        assert lane_packets._form(m) == form, label


def test_a_ruled_form_stamp_reads_a_legacy_form_packet(tmp_path):
    got = parse_packet(_w(tmp_path, "a.md",
                          "# P\n\nto: ia-91/lane/91\n\nread-by: invincible-agent/lane/91 2026-10-07\n"))
    assert got.addressee == "91" and got.is_read


def test_form_is_recorded_for_every_address_kind(tmp_path):
    cases = {"invincible-agent/seat/architect": "seat", "OpenDDIL's agent": "prose",
             "openddil": "bare", "ia-74/lane/74": "worktree"}
    for i, (text, form) in enumerate(cases.items()):
        assert parse_packet(_w(tmp_path, f"{i}.md", f"# P\n\nto: {text}\n")).form == form
    assert parse_packet(_w(tmp_path, "t.md", "# Packet for lane 91\n\nbody\n")).form == "title"
    assert parse_packet(_w(tmp_path, "n.md", "# P\n\nbody\n")).form == "none"


def _census_subprocess(repo: Path) -> str:
    r = subprocess.run([sys.executable, str(_REPO / "scripts" / "_lane_census.py"), str(repo)],
                       capture_output=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_the_census_prints_ADDRESS_FORM_with_counts_and_branchless_legacy_names(tmp_path):
    s = tmp_path / "sessions"
    s.mkdir()
    _w(s, "2026-10-07-a.md", "# P\n\nto: ia-74/lane/74\n")
    _w(s, "2026-10-07-b.md", "# P\n\nto: ia-cortex-60/lane/cortex-60\n")
    _w(s, "2026-10-07-c.md", "# P\n\nto: openddil\n")
    _w(s, "2026-10-07-d.md", "# P\n\nto: invincible-agent/lane/gov\n")
    out = _census_subprocess(tmp_path)
    assert ("ADDRESS FORM: 2 packet(s) addressed by worktree (ia-<w>/lane/<b>), 1 by bare token "
            "-- the ruled form is <repo>/<branch> (2026-10-07).") in out, out
    line = [ln for ln in out.splitlines() if "bare-addressed, no origin/lane/* branch" in ln]
    assert line and all(n in line[0] for n in ("74", "cortex-60", "openddil")), out
    assert "gov" not in line[0], "a ruled-form addressee is not legacy-addressed"


def test_the_census_omits_ADDRESS_FORM_when_every_packet_is_ruled_form(tmp_path):
    s = tmp_path / "sessions"
    s.mkdir()
    _w(s, "2026-10-07-a.md", "# P\n\nto: invincible-agent/lane/gov\n")
    _w(s, "2026-10-07-b.md", "# P\n\nto: cortex-ui/lane/cortex-60\n")
    _w(s, "2026-10-07-c.md", "# P\n\nto: invincible-agent/seat/architect\n")
    out = _census_subprocess(tmp_path)
    assert "LANES:" in out and "ADDRESS FORM" not in out, out
