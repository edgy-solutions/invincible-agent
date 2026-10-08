"""The cross-repo inbox census: canonical addresses, the cross-repo reply join, filename-date age."""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from iagent_pure.inbox_repos import Rec, analyze, canonical, is_over  # noqa: E402

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)


# ---- canonical -------------------------------------------------------------------------------
def test_canonical_rules():
    assert canonical(None, "lane", "none", "x") == (None, False)
    assert canonical("architect", "seat", "seat", "doc-tools") == ("seat/architect", False)
    assert canonical("doc-tools/lane/7f", "external", "repo", "x") == ("doc-tools/lane/7f", False)
    assert canonical("openddil", "external", "prose", "x") == ("openddil", False)
    assert canonical("01", "lane", "repo", "cortex-ui") == ("invincible-agent/lane/01", False)
    # legacy worktree form
    assert canonical("74-x", "lane", "worktree", "doc-tools") == ("invincible-agent/lane/74-x", False)
    assert canonical("7f", "lane", "bare", "doc-tools") == ("doc-tools/lane/7f", True)
    assert canonical("7f", "lane", "title", "doc-tools") == ("doc-tools/lane/7f", True)


def test_bare_in_cortex_ui_resolves_to_cortex_ui_and_is_assumed():
    assert canonical("cortex-60", "lane", "bare", "cortex-ui") == ("cortex-ui/lane/cortex-60", True)


# ---- replies ---------------------------------------------------------------------------------
def _rec(name, home, to, frm, to_kind="external", to_form="repo", frm_kind="external",
         frm_form="repo", read=False):
    return Rec(name=name, home_repo=home, addressee=to, kind=to_kind, form=to_form, sender=frm,
               sender_kind=frm_kind, sender_form=frm_form, is_read=read)


def _orig(home="doc-tools"):
    return _rec("2026-09-01-ask.md", home, "cortex-ui/lane/ui", "doc-tools/lane/7f")


def test_reply_in_another_repo_answers():
    reply = _rec("2026-09-02-ans.md", "cortex-ui", "doc-tools/lane/7f", "cortex-ui/lane/ui")
    assert "cortex-ui/lane/ui" not in analyze([_orig(), reply], NOW).unanswered


def test_no_reply_is_unanswered():
    r = analyze([_orig()], NOW)
    assert list(r.unanswered) == ["cortex-ui/lane/ui"]


def test_earlier_filename_reply_does_not_answer():
    reply = _rec("2026-08-01-ans.md", "cortex-ui", "doc-tools/lane/7f", "cortex-ui/lane/ui")
    assert "cortex-ui/lane/ui" in analyze([_orig(), reply], NOW).unanswered


def test_reply_to_wrong_addressee_does_not_answer():
    reply = _rec("2026-09-02-ans.md", "cortex-ui", "doc-tools/lane/OTHER", "cortex-ui/lane/ui")
    assert "cortex-ui/lane/ui" in analyze([_orig(), reply], NOW).unanswered


def test_bare_sender_canonicalises_with_its_own_home_repo():
    # original is addressed to cortex-ui/lane/cortex-60; the reply is a bare `cortex-60` sender
    orig = _rec("2026-09-01-ask.md", "doc-tools", "cortex-ui/lane/cortex-60", "doc-tools/lane/7f")
    reply_in_ui = _rec("2026-09-02-ans.md", "cortex-ui", "doc-tools/lane/7f", "cortex-60",
                       frm_kind="lane", frm_form="bare")
    assert "cortex-ui/lane/cortex-60" not in analyze([orig, reply_in_ui], NOW).unanswered
    # the same bare sender homed in the ORIGINAL packet's repo is doc-tools/lane/cortex-60: no match
    reply_elsewhere = _rec("2026-09-02-ans.md", "doc-tools", "doc-tools/lane/7f", "cortex-60",
                           frm_kind="lane", frm_form="bare")
    assert "cortex-ui/lane/cortex-60" in analyze([orig, reply_elsewhere], NOW).unanswered


def test_read_by_answers_and_unparsed_sender_is_undecided():
    assert analyze([_rec("2026-09-01-a.md", "r", "x/lane/a", "y/lane/b", read=True)], NOW).unanswered == {}
    r = analyze([_rec("2026-09-01-a.md", "r", "x/lane/a", None)], NOW)
    assert r.unanswered == {} and r.undecided[0][1].startswith("from:")
    r = analyze([_rec("2026-09-01-a.md", "r", None, "y/lane/b")], NOW)
    assert len(r.unaddressed) == 1


# ---- age -------------------------------------------------------------------------------------
def test_age_boundary_and_undated():
    assert is_over("2026-10-06-x.md", NOW, 48) is False        # exactly 48h
    assert is_over("2026-10-05-x.md", NOW, 48) is True
    assert is_over("notes.md", NOW, 48) is None
    r = analyze([_rec("notes.md", "r", "x/lane/a", "y/lane/b")], NOW)
    assert r.unanswered == {} and r.undecided[0][1] == "no date in filename"


# ---- integration -----------------------------------------------------------------------------
def _g(cwd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(cwd), *a],
                   check=True, capture_output=True)


def _mkrepo(root, name):
    d = root / name
    d.mkdir()
    _g(d, "init", "-q")
    (d / "README").write_text("x")
    _g(d, "add", "README")
    _g(d, "commit", "-q", "-m", "init")
    return d


def test_integration(tmp_path):
    a, b, c = (_mkrepo(tmp_path, n) for n in ("repoa", "repob", "repoc"))
    _g(a, "branch", "lane/y")
    wt = tmp_path / "repob-wt"
    _g(b, "worktree", "add", "-q", str(wt), "-b", "lane/other")
    for d in (a, b):
        (d / "sessions").mkdir()
    (wt / "sessions").mkdir()
    ask = ("# ask\nfrom: repoa/lane/y\nto: repob/lane/x\n\nhi\n")
    (a / "sessions" / "2026-09-01-ask.md").write_text(ask)
    _g(a, "add", "sessions/2026-09-01-ask.md")
    _g(a, "commit", "-q", "-m", "p")
    (b / "sessions" / "2026-09-01-ask.md").write_text(ask + "different\n")   # divergent, untracked
    (wt / "sessions" / "2026-09-05-other.md").write_text("from: repob/lane/other\nto: repoa/lane/y\n")
    out = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "inbox_census_repos.py"), str(a), str(b), str(c),
         "--now", "2026-10-08"], capture_output=True, text=True, check=True).stdout
    assert "repoc: no sessions/ in any worktree" in out
    assert "REPOS: repoa 1 packet(s) in 1 worktree(s) [1 tracked, 0 placed-not-committed]" in out
    assert "REPOS: repob 2 packet(s) in 2 worktree(s) [0 tracked, 2 placed-not-committed]" in out
    assert "POPULATION: 2 distinct packets, 1 divergent copies" in out
    assert "repob/lane/x  1 unanswered" in out and "NO SUCH BRANCH" in out
    assert "repoa/lane/y  1 unanswered" in out
    div = out.split("DIVERGENT COPIES:")[1]
    assert "2026-09-01-ask.md" in div and div.count("sessions") == 2
    assert out.isascii()


# ---- canonical copy choice (provenance, not mtime) -------------------------------------------
def _two_copies(tmp_path, main_text, wt_text):
    import os
    a = _mkrepo(tmp_path, "ra")
    wt = tmp_path / "ra-wt"
    _g(a, "worktree", "add", "-q", str(wt), "-b", "lane/w")
    for d in (a, wt):
        (d / "sessions").mkdir()
    fm, fw = a / "sessions" / "2026-09-01-p.md", wt / "sessions" / "2026-09-01-p.md"
    fm.write_text(main_text)
    fw.write_text(wt_text)
    os.utime(fm, (1_000_000_000, 1_000_000_000))
    os.utime(fw, (1_900_000_000, 1_900_000_000))      # the worktree copy is NEWER
    return subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "inbox_census_repos.py"), str(a), "--now", "2026-10-08"],
        capture_output=True, text=True, check=True).stdout


_HDR = "from: rz/lane/q\nto: ra/lane/x\n"
_STAMP = "read-by: ra/lane/x 2026-09-02\n"


def test_read_by_stamp_is_additive_across_copies(tmp_path):
    # main stamped, newer worktree copy unstamped -> read
    (tmp_path / "1").mkdir()
    out = _two_copies(tmp_path / "1", _HDR + _STAMP, _HDR)
    assert "UNANSWERED >48h BY ADDRESSEE: 0 packet(s)" in out
    # stamp removed from both -> unanswered
    (tmp_path / "2").mkdir()
    out = _two_copies(tmp_path / "2", _HDR, _HDR + "x\n")
    assert "ra/lane/x  1 unanswered" in out
    # CANONICAL (main) copy lacks the stamp, a non-canonical copy has it -> still read (additive)
    (tmp_path / "3").mkdir()
    out = _two_copies(tmp_path / "3", _HDR, _HDR + _STAMP)
    assert "UNANSWERED >48h BY ADDRESSEE: 0 packet(s)" in out


def test_main_tree_address_wins_and_disagreement_is_listed(tmp_path):
    out = _two_copies(tmp_path, _HDR, "from: rz/lane/q\nto: ra/lane/z\n")
    assert "ra/lane/x  1 unanswered" in out and "ra/lane/z  " not in out.split("UNDECIDED")[0]
    sec = out.split("DIVERGENT AND DISAGREEING:")[1]
    assert sec.startswith(" 1") and "2026-09-01-p.md" in sec
    assert "to=ra/lane/x" in sec and "to=ra/lane/z" in sec
