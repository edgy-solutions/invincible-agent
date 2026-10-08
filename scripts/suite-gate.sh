#!/usr/bin/env bash
# suite-gate.sh -- run the FULL test suite (uv run pytest tests/) only when the box is clear.
#
# The full suite is Lane 1's (CLAUDE.md); other lanes run their own area's tests.
# Rule (ruled 2026-10-07): one suite at a time, machine-wide; refuse under 2 GB free commit.
#
# Exit codes:
#   2  GATE BUSY     another gate holds the lock, or another pytest process is running
#   3  GATE REFUSED  free commit memory is below FLOOR_MB, or the probe did not return an integer
#   otherwise        pytest's own exit code
#
# Extra arguments are passed through to pytest. There is deliberately no environment
# variable or flag that bypasses a check or the floor.
set -u

FLOOR_MB=2048

LOCK="$HOME/.iagent-suite-gate.lock"
cd "$(dirname "$0")/.." || exit 3

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) WIN=1 ;;
  *) WIN=0 ;;
esac

# 1. Lock (atomic, machine-wide; $HOME is stable across sessions, TMP/TMPDIR are not)
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "GATE BUSY: another gate holds the lock"
  echo "holder info ($LOCK/info):"
  cat "$LOCK/info" 2>/dev/null || echo "  (no info file)"
  echo "if the holder is dead, clear the stale lock with: rm -r \"$LOCK\""
  exit 2
fi
trap 'rm -rf "$LOCK"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
{
  echo "pid=$$"
  echo "worktree=$(git rev-parse --show-toplevel 2>/dev/null)"
  echo "sha=$(git rev-parse HEAD 2>/dev/null)"
  echo "started_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$LOCK/info"

# 2. Other pytest processes
if [ "$WIN" = 1 ]; then
  procs=$(powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { (\$_.Name -like 'python*' -or \$_.Name -like 'pytest*') -and \$_.CommandLine -match 'pytest' } | ForEach-Object { \"\$(\$_.ProcessId) \$(\$_.CommandLine)\" }" | tr -d '\r' | grep -v '^[[:space:]]*$')
else
  procs=$(pgrep -af pytest | grep -v "^$$ " | grep -v '^[[:space:]]*$')
fi
if [ -n "$procs" ]; then
  n=$(printf '%s\n' "$procs" | wc -l | tr -d ' ')
else
  n=0
fi
if [ "$n" -gt 0 ]; then
  echo "GATE BUSY: $n pytest process(es) running"
  printf '%s\n' "$procs" | while IFS= read -r line; do
    echo "  ${line:0:160}"
  done
  exit 2
fi

# 3. Free commit memory (MB)
if [ "$WIN" = 1 ]; then
  m=$(powershell.exe -NoProfile -Command '[int]((Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory/1KB)' | tr -d '\r[:space:]')
else
  m=$(awk '/^CommitLimit:/{l=$2} /^Committed_AS:/{c=$2} END{ if (l!="" && c!="") print int((l-c)/1024) }' /proc/meminfo 2>/dev/null)
fi
case "$m" in
  ''|*[!0-9]*)
    echo "GATE REFUSED: free commit probe returned '$m', not an integer -- cannot tell the run would be safe"
    exit 3 ;;
esac
if [ "$m" -lt "$FLOOR_MB" ]; then
  echo "GATE REFUSED: free commit $m MB < $FLOOR_MB MB — the run would be neither red nor green"
  exit 3
fi

# 4. Run
sha=$(git rev-parse HEAD)
if [ -n "$(git status --porcelain)" ]; then dirty=yes; else dirty=no; fi
echo "gate: sha=$sha dirty=$dirty pytest_procs=0 free_commit_MB=$m"
logdir="$HOME/iagent-gate-logs"
mkdir -p "$logdir"
log="$logdir/gate-${sha:0:8}-$(date -u +%Y%m%dT%H%M%S).log"
uv run pytest tests/ "$@" 2>&1 | tee "$log"
rc=${PIPESTATUS[0]}
echo "log: $log"
grep -v '^[[:space:]]*$' "$log" | tail -n 1
echo "REAL_EXIT=$rc"
exit "$rc"
