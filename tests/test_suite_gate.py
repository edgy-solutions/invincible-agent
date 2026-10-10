"""Seal for scripts/suite-gate.sh (one suite at a time; refuse under the free-commit floor).

Windows arms run the script under Git Bash with a temp HOME and stub powershell.exe / uv on PATH.
Linux arms run a COPY of the script (only the MEMINFO= constant line rewritten) with stub
uname / pgrep / uv on PATH and a fake meminfo file; they run wherever a bash is found.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "suite-gate.sh"


def _git_bash():
    try:
        ep = subprocess.run(["git", "--exec-path"], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return None
    root = Path(ep).parent.parent.parent  # .../mingw64/libexec/git-core -> Git root
    # usr/bin first: it honours PATH order; bin/bash.exe prepends /usr/bin and shadows the stubs
    for rel in ("usr/bin/bash.exe", "bin/bash.exe"):
        p = root / rel
        if p.exists():
            return p
    return None


def _find_bash():
    if sys.platform == "win32":
        return _git_bash()  # never the System32 bash.exe (WSL)
    w = shutil.which("bash")
    return Path(w) if w else None


BASH = _find_bash()
pytestmark = [pytest.mark.skipif(BASH is None, reason="no usable bash found")]
win_only = pytest.mark.skipif(
    sys.platform != "win32", reason="gate stubs powershell.exe; Windows/Git Bash only"
)

SCRIPT_TEXT = SCRIPT.read_text(encoding="utf-8")
FLOOR_ASSIGNS = re.findall(r"^FLOOR_MB=(\d+)\s*$", SCRIPT_TEXT, re.M)
FLOOR = int(FLOOR_ASSIGNS[0]) if FLOOR_ASSIGNS else None
MEMINFO_LINE = "\nMEMINFO=/proc/meminfo\n"


def test_bash_is_not_wsl_and_floor_assigned_once():
    assert "system32" not in str(BASH).lower()
    assert len(re.findall(r"FLOOR_MB=", SCRIPT_TEXT)) == 1
    assert len(FLOOR_ASSIGNS) == 1


PS_STUB = """#!/usr/bin/env bash
D="$(dirname "$0")"
case "$*" in
  *Win32_Process*) cat "$D/procs.txt"; exit "$(cat "$D/ps_proc.exit")" ;;
  *Win32_OperatingSystem*) cat "$D/mem.txt" ;;
esac
"""
UNAME_STUB = """#!/usr/bin/env bash
echo Linux
"""
PGREP_STUB = """#!/usr/bin/env bash
D="$(dirname "$0")"
cat "$D/procs.txt"
exit "$(cat "$D/pgrep.exit")"
"""
UV_STUB = """#!/usr/bin/env bash
D="$(dirname "$0")"
echo "$*" > "$D/uv.marker"
exit "$(cat "$D/uv.exit")"
"""


def meminfo_for(free_mb):
    """A fake /proc/meminfo whose CommitLimit - Committed_AS is exactly free_mb MB (kB lines)."""
    committed = 5_000_000
    return f"MemTotal:  999999999 kB\nCommitLimit: {committed + free_mb * 1024} kB\nCommitted_AS: {committed} kB\n"


def _no_pgrep_path(stubs):
    """PATH with the stubs plus only the Git Bash dirs; pgrep must not be resolvable in it."""
    root = BASH.parent.parent
    if root.name == "usr":
        root = root.parent
    cands = (BASH.parent, root / "usr" / "bin", root / "mingw64" / "bin", root / "bin")
    dirs = [str(stubs)] + [str(d) for d in cands if d.exists()]
    path = os.pathsep.join(dict.fromkeys(dirs))
    probe = subprocess.run([str(BASH), "-c", "command -v pgrep"], capture_output=True, text=True,
                           env={**os.environ, "PATH": path})
    assert probe.returncode != 0, f"pgrep is resolvable in the restricted PATH: {probe.stdout!r}"
    return path


def run_gate(tmp_path, procs="", mem=None, uv_exit=0, args=(), precreate_lock=False,
             linux=False, pgrep_exit=0, meminfo=None, ps_proc_exit=0, no_pgrep=False):
    mem = str(FLOOR + 1000) if mem is None else mem
    stubs = tmp_path / "stubs"
    home = tmp_path / "home"
    stubs.mkdir()
    home.mkdir()
    (stubs / "uv").write_text(UV_STUB, newline="\n")
    (stubs / "procs.txt").write_text(procs)
    (stubs / "uv.exit").write_text(str(uv_exit))
    script = SCRIPT
    if linux:
        (stubs / "uname").write_text(UNAME_STUB, newline="\n")
        if not no_pgrep:
            (stubs / "pgrep").write_text(PGREP_STUB, newline="\n")
        (stubs / "pgrep.exit").write_text(str(pgrep_exit))
        fake = tmp_path / "meminfo"
        fake.write_text(meminfo if meminfo is not None else meminfo_for(int(mem)), newline="\n")
        assert SCRIPT_TEXT.count(MEMINFO_LINE) == 1, "MEMINFO= constant line renamed or duplicated"
        (tmp_path / "scripts").mkdir()
        script = tmp_path / "scripts" / "suite-gate.sh"
        script.write_text(SCRIPT_TEXT.replace(MEMINFO_LINE, f'\nMEMINFO="{fake.as_posix()}"\n'), newline="\n")
    else:
        (stubs / "powershell.exe").write_text(PS_STUB, newline="\n")
        (stubs / "mem.txt").write_text(mem)
        (stubs / "ps_proc.exit").write_text(str(ps_proc_exit))
    lock = home / ".iagent-suite-gate.lock"
    if precreate_lock:
        lock.mkdir()
        (lock / "info").write_text("pid=1\n")
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = _no_pgrep_path(stubs) if no_pgrep else str(stubs) + os.pathsep + env["PATH"]
    p = subprocess.run([str(BASH), str(script), *args], capture_output=True, text=True, env=env, timeout=120)
    out = p.stdout + p.stderr
    return p.returncode, out, (stubs / "uv.marker"), lock, home


@win_only
def test_pytest_process_present_is_busy(tmp_path):
    rc, out, marker, lock, _ = run_gate(tmp_path, procs="4242 python.exe -m pytest tests/\n")
    assert rc == 2 and "GATE BUSY" in out and "1 pytest process" in out
    assert not marker.exists()


@win_only
def test_free_below_floor_refused(tmp_path):
    rc, out, marker, _, _ = run_gate(tmp_path, mem=str(FLOOR - 1))
    assert rc == 3 and "GATE REFUSED" in out
    assert not marker.exists()


@win_only
def test_free_at_floor_runs(tmp_path):
    rc, out, marker, _, _ = run_gate(tmp_path, mem=str(FLOOR))
    assert rc == 0 and "REAL_EXIT=0" in out
    assert marker.exists()


@win_only
def test_non_integer_memory_refused(tmp_path):
    rc, out, marker, _, _ = run_gate(tmp_path, mem="")
    assert rc == 3 and "GATE REFUSED" in out
    assert not marker.exists()


@win_only
def test_lock_held_is_busy_and_left_in_place(tmp_path):
    rc, out, marker, lock, _ = run_gate(tmp_path, precreate_lock=True)
    assert rc == 2 and "GATE BUSY" in out
    assert not marker.exists()
    assert lock.is_dir() and (lock / "info").exists()


@win_only
def test_uv_failure_propagates_and_cleans_up(tmp_path):
    rc, out, marker, lock, home = run_gate(tmp_path, uv_exit=1)
    assert rc == 1 and "REAL_EXIT=1" in out
    assert marker.read_text().startswith("run pytest tests/")
    assert not lock.exists()
    assert list((home / "iagent-gate-logs").glob("gate-*.log"))


@win_only
def test_uv_success_propagates(tmp_path):
    rc, out, marker, lock, _ = run_gate(tmp_path, uv_exit=0)
    assert rc == 0 and "REAL_EXIT=0" in out
    assert marker.exists()
    assert not lock.exists()


@win_only
def test_extra_args_pass_through(tmp_path):
    rc, out, marker, _, _ = run_gate(tmp_path, args=("-x", "-q"))
    assert rc == 0
    assert marker.read_text().split() == ["run", "pytest", "tests/", "-x", "-q"]


@win_only
def test_lock_released_after_busy_on_pytest(tmp_path):
    rc, out, marker, lock, _ = run_gate(tmp_path, procs="1 python pytest\n")
    assert rc == 2
    assert not lock.exists()


@win_only
def test_win_process_probe_failure_refused(tmp_path):
    rc, out, marker, lock, _ = run_gate(tmp_path, ps_proc_exit=1)
    assert rc == 3 and "GATE REFUSED" in out and "probe failed" in out
    assert not marker.exists()
    assert not lock.exists()


# ---- Linux branch (stub uname/pgrep, fake meminfo, copy of the script) ----


def test_linux_pytest_process_present_is_busy(tmp_path):
    rc, out, marker, lock, _ = run_gate(tmp_path, linux=True, procs="4242 python -m pytest tests/\n")
    assert rc == 2 and "GATE BUSY" in out and "1 pytest process" in out
    assert not marker.exists()
    assert not lock.exists()


def test_linux_free_below_floor_refused(tmp_path):
    rc, out, marker, _, _ = run_gate(tmp_path, linux=True, mem=str(FLOOR - 1))
    assert rc == 3 and "GATE REFUSED" in out
    assert not marker.exists()


def test_linux_free_at_floor_runs(tmp_path):
    rc, out, marker, _, _ = run_gate(tmp_path, linux=True, mem=str(FLOOR))
    assert rc == 0 and "REAL_EXIT=0" in out
    assert marker.exists()


def test_linux_meminfo_without_committed_as_refused(tmp_path):
    rc, out, marker, _, _ = run_gate(tmp_path, linux=True, meminfo="CommitLimit: 99999999 kB\n")
    assert rc == 3 and "GATE REFUSED" in out and "not an integer" in out
    assert not marker.exists()


def test_linux_pgrep_no_match_runs(tmp_path):
    rc, out, marker, _, _ = run_gate(tmp_path, linux=True, pgrep_exit=1)
    assert rc == 0 and "REAL_EXIT=0" in out
    assert marker.exists()


def test_linux_pgrep_error_refused(tmp_path):
    rc, out, marker, lock, _ = run_gate(tmp_path, linux=True, pgrep_exit=2)
    assert rc == 3 and "GATE REFUSED" in out and "probe failed (exit 2)" in out
    assert not marker.exists()
    assert not lock.exists()


def test_linux_pgrep_missing_refused(tmp_path):
    rc, out, marker, _, _ = run_gate(tmp_path, linux=True, no_pgrep=True)
    assert rc == 3 and "GATE REFUSED" in out and "probe failed (exit 127)" in out
    assert not marker.exists()
