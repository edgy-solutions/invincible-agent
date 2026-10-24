"""The sandbox roll lock refuses a second lane's roll, and every roll script takes it first.

Ruled 2026-10-24 (the architect): before any helm upgrade on the sandbox the roller creates
ConfigMap sandbox/roll-lock {lane, started, expected_end}; every roll script refuses to start
while it exists and is younger than 90 minutes; the roller deletes it when the gates pass. The
occasion was iagent rev 216: doc-tools rolled inside iagent's prime, and prime's ingests run in the
doc-tools code location, so the roll killed one.

These arms RUN scripts/roll-lock.sh against a stub kubectl that keeps the ConfigMap in a temp
directory. The bash a bare subprocess gets on this box cannot `set -o pipefail` (see
test_helm_timeout_guard_reads_the_resolved_value.py), so Git for Windows' bash is named
explicitly there; elsewhere `bash` on PATH is used.

Run: uv run --frozen pytest tests/test_roll_lock.py -v
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "scripts" / "roll-lock.sh"
UPGRADE = ROOT / "scripts" / "upgrade-sandbox.sh"
LITANY = ROOT / "scripts" / "roll-litany.sh"


def _bash() -> str | None:
    if sys.platform == "win32":
        for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"):
            if Path(p).is_file():
                return p
        return None
    return shutil.which("bash")


BASH = _bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="no bash that can run the script")

# A kubectl that understands exactly the four calls roll-lock.sh makes, and logs every call.
STUB = r"""#!/usr/bin/env bash
d="$STUB_DIR"; echo "$*" >> "$d/calls"
[ -n "${STUB_FAIL_GET:-}" ] && [[ " $* " == *" get "* ]] && { echo "connection refused" >&2; exit 1; }
f="$d/cm"
case " $* " in
  *" get configmap roll-lock "*)
    [ -f "$f" ] && printf '%s\t%s\t%s\t%s' "$(sed -n 1p "$f")" "$(sed -n 2p "$f")" "$(sed -n 3p "$f")" "$(sed -n 4p "$f")"
    exit 0 ;;
  *" create configmap roll-lock "*)
    [ -f "$f" ] && { echo 'Error from server (AlreadyExists)' >&2; exit 1; }
    for a in "$@"; do case "$a" in
      --from-literal=lane=*) l="${a#--from-literal=lane=}" ;;
      --from-literal=started=*) s="${a#--from-literal=started=}" ;;
      --from-literal=expected_end=*) e="${a#--from-literal=expected_end=}" ;;
    esac; done
    printf '%s\n%s\n%s\n%s\n' "$l" "$s" "$e" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$f"; exit 0 ;;
  *" delete configmap roll-lock "*) rm -f "$f"; exit 0 ;;
esac
echo "stub kubectl: unexpected call: $*" >&2; exit 9
"""


@pytest.fixture
def stub(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    k = bindir / "kubectl"
    k.write_bytes(STUB.encode())
    k.chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    return bindir, state


def _run(stub, *args, lane="invincible-agent/lane/01", **env):
    bindir, state = stub
    e = dict(os.environ)
    e["PATH"] = str(bindir) + os.pathsep + e.get("PATH", "")
    e["STUB_DIR"] = state.as_posix() if sys.platform != "win32" else _posix(state)
    e.pop("HELM_KUBECONTEXT", None)
    if lane is not None:
        e["ROLL_LANE"] = lane
    e.update(env)
    return subprocess.run([BASH, LOCK.as_posix(), *args], capture_output=True, text=True, env=e, timeout=60)


def _posix(p: Path) -> str:
    s = p.as_posix()
    m = re.match(r"^([A-Za-z]):/(.*)$", s)
    return f"/{m.group(1).lower()}/{m.group(2)}" if m else s


def _hold(stub, lane: str, age_min: int):
    created = (datetime.now(timezone.utc) - timedelta(minutes=age_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (stub[1] / "cm").write_text(f"{lane}\n{created}\n{created}\n{created}\n", newline="\n")


def _holder(stub) -> str | None:
    f = stub[1] / "cm"
    return f.read_text().splitlines()[0] if f.exists() else None


@needs_bash
def test_acquire_on_a_free_sandbox_records_lane_started_and_expected_end(stub):
    r = _run(stub, "acquire", "--minutes", "100")
    assert r.returncode == 0, r.stderr
    lane, started, end, _ = (stub[1] / "cm").read_text().splitlines()
    assert lane == "invincible-agent/lane/01"
    t0 = datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ")
    t1 = datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ")
    assert timedelta(minutes=99) <= t1 - t0 <= timedelta(minutes=101)


@needs_bash
def test_another_lanes_live_lock_refuses_and_is_left_alone(stub):
    _hold(stub, "doc-tools/lane/7f", age_min=89)
    r = _run(stub, "acquire")
    assert r.returncode == 3
    assert "REFUSING TO ROLL" in r.stderr and "doc-tools/lane/7f" in r.stderr
    assert _holder(stub) == "doc-tools/lane/7f"
    assert _run(stub, "check").returncode == 3


@needs_bash
def test_a_lock_of_90_minutes_or_more_is_stale_and_taken_over_loudly(stub):
    _hold(stub, "doc-tools/lane/7f", age_min=91)
    assert _run(stub, "check").returncode == 0
    r = _run(stub, "acquire")
    assert r.returncode == 0, r.stderr
    assert "STALE" in r.stderr and "doc-tools/lane/7f" in r.stderr
    assert _holder(stub) == "invincible-agent/lane/01"


@needs_bash
def test_the_holders_own_lock_does_not_refuse_it_and_is_not_restarted(stub):
    _hold(stub, "invincible-agent/lane/01", age_min=40)
    before = (stub[1] / "cm").read_text()
    r = _run(stub, "acquire")
    assert r.returncode == 0, r.stderr
    assert (stub[1] / "cm").read_text() == before


@needs_bash
def test_release_deletes_only_this_lanes_lock(stub):
    _hold(stub, "doc-tools/lane/7f", age_min=10)
    r = _run(stub, "release")
    assert r.returncode == 3 and _holder(stub) == "doc-tools/lane/7f"
    _hold(stub, "invincible-agent/lane/01", age_min=10)
    assert _run(stub, "release").returncode == 0
    assert _holder(stub) is None


@needs_bash
def test_an_unreadable_lock_is_not_a_free_one(stub):
    r = _run(stub, "check", STUB_FAIL_GET="1")
    assert r.returncode == 4, (r.returncode, r.stderr)
    r = _run(stub, "acquire", STUB_FAIL_GET="1")
    assert r.returncode == 4
    assert _holder(stub) is None


@needs_bash
def test_create_is_the_atomic_step_never_apply_or_replace(stub):
    _run(stub, "acquire")
    calls = (stub[1] / "calls").read_text()
    assert " create configmap roll-lock " in f" {calls} "
    assert "apply" not in calls and "replace" not in calls


@needs_bash
def test_the_lock_follows_helms_context(stub):
    _run(stub, "show", HELM_KUBECONTEXT="some-ctx")
    first = (stub[1] / "calls").read_text().splitlines()[0]
    assert first.startswith("--context some-ctx -n sandbox ")


@needs_bash
def test_the_lane_is_derived_as_repo_slash_branch(stub):
    r = _run(stub, "acquire", lane=None)
    branch = subprocess.run(["git", "-C", str(ROOT), "branch", "--show-current"],
                            capture_output=True, text=True).stdout.strip()
    if not branch:
        assert r.returncode == 2  # detached: refuses rather than guessing
        return
    url = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"],
                         capture_output=True, text=True).stdout.strip()
    repo = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    assert r.returncode == 0, r.stderr
    assert _holder(stub) == f"{repo}/{branch}"


# ── the roll scripts take the lock before they roll anything ─────────────────────────────

def test_upgrade_sandbox_takes_the_lock_after_every_guard_and_before_helm():
    src = UPGRADE.read_text()
    acquire = src.index('roll-lock.sh"')
    acq_call = src.index('acquire --minutes', acquire)
    exec_helm = src.index("exec helm upgrade")
    assert acq_call < exec_helm
    # every refusal above must come first, so a refused upgrade never leaves a lock behind
    for guard in ("REFUSING: effective helm --timeout", "REFUSING: global.imageTag"):
        assert src.index(guard) < acq_call, guard
    assert "|| exit 3" in src[acq_call:exec_helm]


def test_upgrade_sandbox_dry_run_only_reports_the_lock():
    src = UPGRADE.read_text()
    block = src[src.index("_dry=\"\""):src.index("exec helm upgrade")]
    assert "--dry-run|--dry-run=*) _dry=1" in block
    dry_arm = block[block.index('if [ -n "${_dry}" ]'):block.index("else")]
    assert "show" in dry_arm and "acquire" not in dry_arm


def test_roll_litany_takes_the_lock_before_its_first_rollout():
    src = LITANY.read_text()
    acq = src.index("roll-lock.sh\" acquire")
    assert acq < src.index("kubectl -n \"$NS\" rollout restart")
    assert "|| exit 3" in src[acq:src.index("\n", acq)]


def test_the_stale_bound_is_the_ruled_90_minutes():
    assert re.search(r"^STALE_MIN=90$", LOCK.read_text(), re.M)
