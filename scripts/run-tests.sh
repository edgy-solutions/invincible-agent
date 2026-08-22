#!/usr/bin/env bash
# Run the suite in the RIGHT environment, whichever side you are on.
#
# WHY THIS EXISTS. This tree carries TWO virtualenvs — `.venv` (Windows) and `.venv.wsl`
# (Linux) — and `UV_PROJECT_ENVIRONMENT` is unset on both sides. So from WSL a bare
# `uv run` targets `.venv`, the WINDOWS venv, and rebuilds it with Linux wheels. The Windows
# side then breaks in a way that looks like nothing to do with whoever ran the tests.
#
# That hazard is the reason `.venv.wsl` exists, and remembering it correctly every time is
# exactly the kind of thing that gets remembered wrong at 2am. This script removes the choice.
#
#   ./scripts/run-tests.sh                 # everything
#   ./scripts/run-tests.sh tests/planning  # a subset — extra args pass through to pytest
#
# CI runs ubuntu-latest / CPython 3.12, which is what `.venv.wsl` is. A green from the Windows
# side is real and is NOT a CI signal; when the two disagree, WSL is the one that matches
# what deploys.
set -uo pipefail
cd "$(dirname "$0")/.."

# `--extra agent-fleet` is NOT optional: rdflib, restate-sdk and smolagents live there, and
# without it several files collect as import errors that read like repo breakage.
# See AGENTS.md, "Running the tests".
EXTRA=(--frozen --extra agent-fleet)

case "$(uname -s)" in
  Linux*)
    # THE LOAD-BEARING LINE. Without it uv rebuilds the Windows venv from Linux.
    export UV_PROJECT_ENVIRONMENT=.venv.wsl
    WHERE="WSL / Linux — matches CI (ubuntu-latest, 3.12)"
    ;;
  *)
    WHERE="Windows — real signal, NOT a CI signal (CPython 3.11 vs CI's 3.12)"
    ;;
esac

# PREFLIGHT. A non-login shell (`wsl bash script.sh`, most CI shells, anything an agent
# spawns) does not read .bashrc, so uv's install dir is off PATH and `uv` is simply absent.
# Found 2026-08-22 when a "CI-equivalent" run printed its scope banner, ran ZERO tests, and
# exited 0 through a pipe to tail.
for d in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
  [ -x "$d/uv" ] && case ":$PATH:" in *":$d:"*) ;; *) PATH="$d:$PATH" ;; esac
done
export PATH

if ! command -v uv >/dev/null 2>&1; then
  echo "!! NO RESULT — uv is not on PATH, so no tests ran." >&2
  echo "   Looked in: PATH, \$HOME/.local/bin, \$HOME/.cargo/bin" >&2
  echo "   This is NOT a test failure and NOT a green. Nothing was measured." >&2
  exit 127
fi

echo "── running in: ${WHERE}"
echo "── env:        ${UV_PROJECT_ENVIRONMENT:-.venv (uv default)}"
echo

uv run "${EXTRA[@]}" python -m pytest "${@:-tests/}" -q
rc=$?

# A SCOPE CLAIM IS ONLY HONEST WHEN TESTS ACTUALLY RAN.
#
# pytest: 0 = passed, 1 = failures — both are real results and deserve the scope line.
# 2 interrupted / 3 internal / 4 usage / 5 nothing-collected, and 127 command-not-found, are
# NON-RESULTS. Printing "that result is scoped to CI-matching Linux" over one of those invites
# quoting a green that never happened, which is the guard-gone-quiet shape this repo keeps
# paying for — here in the very tool used to quote greens.
echo
case "$rc" in
  0|1) echo "── that result is scoped to: ${WHERE}" ;;
  5)   echo "!! NO RESULT — pytest collected ZERO tests (exit 5). Nothing was measured." >&2 ;;
  *)   echo "!! NO RESULT — pytest exited ${rc} before producing a result (interrupted," >&2
       echo "   internal error, or bad usage). This is neither a pass nor a failure." >&2 ;;
esac
exit $rc
