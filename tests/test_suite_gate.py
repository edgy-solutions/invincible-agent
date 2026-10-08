"""Seal for scripts/suite-gate.sh (one suite at a time; refuse under the free-commit floor).

Runs the script under Git Bash with a temp HOME and stub powershell.exe / uv on PATH.
"""
import os
import re
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
    for rel in ("bin/bash.exe", "usr/bin/bash.exe"):
        p = root / rel
        if p.exists():
            return p
    return None


BASH = _git_bash()
pytestmark = [
    pytest.mark.skipif(sys.platform != "win32", reason="gate stubs powershell.exe; Windows/Git Bash only"),
    pytest.mark.skipif(BASH is None, reason="Git Bash not found via `git --exec-path`"),
]

SCRIPT_TEXT = SCRIPT.read_text(encoding="utf-8")
FLOOR_ASSIGNS = re.findall(r"^FLOOR_MB=(\d+)\s*$", SCRIPT_TEXT, re.M)
FLOOR = int(FLOOR_ASSIGNS[0]) if FLOOR_ASSIGNS else None


def test_bash_is_not_wsl_and_floor_assigned_once():
    assert "system32" not in str(BASH).lower()
    assert len(re.findall(r"FLOOR_MB=", SCRIPT_TEXT)) == 1
    assert len(FLOOR_ASSIGNS) == 1


PS_STUB = """#!/usr/bin/env bash
D="$(dirname "$0")"
case "$*" in
  *Win32_Process*) cat "$D/procs.txt" ;;
  *Win32_OperatingSystem*) cat "$D/mem.txt" ;;
esac
"""
UV_STUB = """#!/usr/bin/env bash
D="$(dirname "$0")"
echo "$*" > "$D/uv.marker"
exit "$(cat "$D/uv.exit")"
"""


def run_gate(tmp_path, procs="", mem=None, uv_exit=0, args=(), precreate_lock=False):
    mem = str(FLOOR + 1000) if mem is None else mem
    stubs = tmp_path / "stubs"
    home = tmp_path / "home"
    stubs.mkdir()
    home.mkdir()
    (stubs / "powershell.exe").write_text(PS_STUB, newline="\n")
    (stubs / "uv").write_text(UV_STUB, newline="\n")
    (stubs / "procs.txt").write_text(procs)
    (stubs / "mem.txt").write_text(mem)
    (stubs / "uv.exit").write_text(str(uv_exit))
    lock = home / ".iagent-suite-gate.lock"
    if precreate_lock:
        lock.mkdir()
        (lock / "info").write_text("pid=1\n")
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = str(stubs) + os.pathsep + env["PATH"]
    p = subprocess.run([str(BASH), str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=120)
    out = p.stdout + p.stderr
    return p.returncode, out, (stubs / "uv.marker"), lock, home


def test_pytest_process_present_is_busy(tmp_path):
    rc, out, marker, lock, _ = run_gate(tmp_path, procs="4242 python.exe -m pytest tests/\n")
    assert rc == 2 and "GATE BUSY" in out and "1 pytest process" in out
    assert not marker.exists()


def test_free_below_floor_refused(tmp_path):
    rc, out, marker, _, _ = run_gate(tmp_path, mem=str(FLOOR - 1))
    assert rc == 3 and "GATE REFUSED" in out
    assert not marker.exists()


def test_free_at_floor_runs(tmp_path):
    rc, out, marker, _, _ = run_gate(tmp_path, mem=str(FLOOR))
    assert rc == 0 and "REAL_EXIT=0" in out
    assert marker.exists()


def test_non_integer_memory_refused(tmp_path):
    rc, out, marker, _, _ = run_gate(tmp_path, mem="")
    assert rc == 3 and "GATE REFUSED" in out
    assert not marker.exists()


def test_lock_held_is_busy_and_left_in_place(tmp_path):
    rc, out, marker, lock, _ = run_gate(tmp_path, precreate_lock=True)
    assert rc == 2 and "GATE BUSY" in out
    assert not marker.exists()
    assert lock.is_dir() and (lock / "info").exists()


def test_uv_failure_propagates_and_cleans_up(tmp_path):
    rc, out, marker, lock, home = run_gate(tmp_path, uv_exit=1)
    assert rc == 1 and "REAL_EXIT=1" in out
    assert marker.read_text().startswith("run pytest tests/")
    assert not lock.exists()
    assert list((home / "iagent-gate-logs").glob("gate-*.log"))


def test_uv_success_propagates(tmp_path):
    rc, out, marker, lock, _ = run_gate(tmp_path, uv_exit=0)
    assert rc == 0 and "REAL_EXIT=0" in out
    assert marker.exists()
    assert not lock.exists()


def test_extra_args_pass_through(tmp_path):
    rc, out, marker, _, _ = run_gate(tmp_path, args=("-x", "-q"))
    assert rc == 0
    assert marker.read_text().split() == ["run", "pytest", "tests/", "-x", "-q"]


def test_lock_released_after_busy_on_pytest(tmp_path):
    rc, out, marker, lock, _ = run_gate(tmp_path, procs="1 python pytest\n")
    assert rc == 2
    assert not lock.exists()
