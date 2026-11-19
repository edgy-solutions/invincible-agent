"""Seal scripts/suite_advisory.py by running it as a subprocess on small files."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "suite_advisory.py"


def _run(tmp_path, reds, known, code=1):
    log = tmp_path / "log.txt"
    log.write_text("".join(f"{r}\n" for r in reds), encoding="utf-8")
    kf = tmp_path / "known.txt"
    kf.write_text(known, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(_SCRIPT), str(log), str(kf), "--exit", str(code)],
        capture_output=True, text=True,
    )


def _section(out, head):
    return out.split(head, 1)[1].split("###", 1)[0]


def test_exact_match_is_known(tmp_path):
    p = _run(tmp_path, ["FAILED tests/x.py::test_a - boom"], "tests/x.py::test_a  # g: c (o)\n")
    assert p.returncode == 0
    assert "`tests/x.py::test_a` - g: c (o)" in _section(p.stdout, "### Known reds")
    assert "none" in _section(p.stdout, "### New reds")


def test_parametrized_matches_bare_entry(tmp_path):
    p = _run(tmp_path, ["FAILED tests/x.py::test_a[1-2] - e"], "tests/x.py::test_a  # g: c (o)\n")
    assert "none" in _section(p.stdout, "### New reds")
    assert "test_a[1-2]" in _section(p.stdout, "### Known reds")


def test_file_level_entry_matches_node(tmp_path):
    p = _run(tmp_path, ["FAILED tests/x.py::test_a"], "tests/x.py  # g: c (o)\n")
    assert "none" in _section(p.stdout, "### New reds")


def test_new_red_warning_names_file(tmp_path):
    p = _run(tmp_path, ["FAILED tests/y.py::test_b - e"], "")
    assert "`tests/y.py::test_b`" in _section(p.stdout, "### New reds")
    assert "::warning file=tests/y.py,title=new red::tests/y.py::test_b" in p.stderr


def test_entry_without_red_is_listed(tmp_path):
    p = _run(tmp_path, [], "tests/x.py::test_a  # g: c (o)\n")
    assert "`tests/x.py::test_a`" in _section(p.stdout, "### Known entries not red")
    assert "::notice title=known red not seen::tests/x.py::test_a" in p.stderr


def test_incomplete_run_line_is_first(tmp_path):
    p = _run(tmp_path, [], "", code=2)
    assert p.stdout.startswith("**The suite did not run to completion (pytest exit 2)")
    assert "::warning" in p.stderr


def test_uncommented_entry_exits_2(tmp_path):
    p = _run(tmp_path, [], "tests/x.py::test_a\n")
    assert p.returncode == 2
    assert p.stderr


def test_control_bare_prefix_does_not_match(tmp_path):
    p = _run(tmp_path, ["FAILED tests/x.py::test_ab - e"], "tests/x.py::test_a  # g: c (o)\n")
    assert "`tests/x.py::test_ab`" in _section(p.stdout, "### New reds")


def test_a_parametrized_id_with_spaces_is_one_whole_red(tmp_path):
    # Two cases sharing a first word are two reds, each printed whole (not cut at the first space).
    p = _run(tmp_path, ["FAILED tests/x.py::test_a[how is it used] - e",
                        "FAILED tests/x.py::test_a[how many] - e"], "")
    new = _section(p.stdout, "### New reds")
    assert "`tests/x.py::test_a[how is it used]`" in new
    assert "`tests/x.py::test_a[how many]`" in new


def test_exit_zero_with_new_reds(tmp_path):
    p = _run(tmp_path, ["ERROR tests/z.py"], "")
    assert p.returncode == 0
    assert "`tests/z.py`" in _section(p.stdout, "### New reds")


def _module():
    spec = importlib.util.spec_from_file_location("suite_advisory_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cited_fix_reads_only_a_fixed_by_citation():
    cited_fix = _module().cited_fix
    assert cited_fix("fixed by PR 434, delete there") == 434
    assert cited_fix("fixed by #434") == 434
    assert cited_fix("Fixed By pr 12") == 12
    assert cited_fix("see PR 434") is None
    assert cited_fix("") is None


def test_merged_prs_counts_merge_commits_and_squash_subjects_only():
    subjects = ["Merge pull request #434 from org/branch", "Some change (#99)",
                "Revert part of #77 work", "Merge branch 'master' into x"]
    assert _module().merged_prs(subjects) == {434, 99}


_STALE_KNOWN = ("tests/a.py::test_a  # g: broken; fixed by PR 434, delete there (o)\n"
                "tests/b.py::test_b  # g: broken; fixed by PR 444 (o)\n")


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@example.invalid"],
                 ["commit", "-q", "--allow-empty", "-m", "Merge pull request #434 from org/branch"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    return repo


def _main(tmp_path, monkeypatch, capsys, extra):
    repo = _repo(tmp_path)
    log = tmp_path / "log.txt"
    log.write_text("", encoding="utf-8")
    kf = tmp_path / "known.txt"
    kf.write_text(_STALE_KNOWN, encoding="utf-8")
    monkeypatch.chdir(repo)
    rc = _module().main([str(log), str(kf), "--exit", "0", *extra])
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def test_a_known_line_citing_a_merged_pr_is_reported_stale(tmp_path, monkeypatch, capsys):
    rc, out, err = _main(tmp_path, monkeypatch, capsys, ["--merged-ref", "HEAD"])
    assert rc == 0
    sect = _section(out, "### Known entries whose cited fix is merged")
    assert "`tests/a.py::test_a` - PR 434" in sect
    assert "test_b" not in sect
    warns = [ln for ln in err.splitlines() if "title=stale known red" in ln]
    assert len(warns) == 1 and "tests/a.py::test_a" in warns[0]


def test_control_without_merged_ref_the_citation_check_is_off(tmp_path, monkeypatch, capsys):
    rc, out, err = _main(tmp_path, monkeypatch, capsys, [])
    assert rc == 0
    assert "not checked (no --merged-ref)" in out
    assert "stale known red" not in err


def test_an_unreadable_merged_ref_exits_2(tmp_path, monkeypatch, capsys):
    rc, out, err = _main(tmp_path, monkeypatch, capsys, ["--merged-ref", "no-such-ref"])
    assert rc == 2
    assert err.startswith("suite_advisory:")
