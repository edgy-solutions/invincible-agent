#!/usr/bin/env bash
# The sandbox roll lock — ConfigMap sandbox/roll-lock {lane, started, expected_end}.
#
#   usage: scripts/roll-lock.sh acquire [--minutes N]   # before any helm upgrade or roll
#          scripts/roll-lock.sh check                   # exit 0 if this lane may roll, 3 if not
#          scripts/roll-lock.sh release                 # once the roll's gates pass
#          scripts/roll-lock.sh show
#
# WHY THIS EXISTS (ruled 2026-10-24, the architect). Prime launches EVERY ontology ingest in the
# doc-tools code location, so a doc-tools roll during an iagent prime replaces the pod the ingest
# runs in and kills it. iagent rev 216 failed exactly that way: doc-tools rev 54 rolled inside it,
# the mesh_system run lost its worker, prime exited non-zero, and helm skipped every later hook.
# A packet asking the other lane to wait did not hold. A lock every roll script reads does.
#
# THE RULE. Before a helm upgrade on the sandbox the roller creates the lock. Every roll script
# refuses to start while it exists, is not yet stale, and names ANOTHER lane. The roller deletes
# it when the gates pass -- not when helm returns: the gates are part of the roll.
#
# STALE = max(90 minutes after creation, the holder's declared expected_end) (the architect,
# 2026-10-24). 90 minutes is the floor; a roll that declares a longer end -- upgrade-sandbox
# declares its helm timeout, 100m by default -- keeps its lock that long. A stale lock is taken
# over, loudly. An expected_end that is missing or unparseable leaves the floor alone in force,
# and says so.
#
# CREATE IS THE ATOMIC STEP. `kubectl create` fails on AlreadyExists, so two lanes acquiring at
# once get one winner; the loser re-reads the holder and refuses. Never `apply` (it overwrites).
#
# THE LANE is `<repo>/<branch>` (the address rule, 2026-10-07), derived from git, never typed.
# ROLL_LANE overrides it, for a roll run from a tree whose branch is not the roller's address.
#
# THE CLUSTER is the one helm will talk to: kubectl's current context, or HELM_KUBECONTEXT when
# set -- the same variable helm reads, so the lock and the upgrade cannot land on two clusters.
#
# This file is self-contained on purpose: doc-tools and the workbench copy it into their own
# roll scripts. Keep it free of anything specific to this repository.
set -euo pipefail

LOCK_NS="${ROLL_LOCK_NS:-sandbox}"
LOCK_NAME="roll-lock"
STALE_MIN=90

KUBECTL=(kubectl)
[ -n "${HELM_KUBECONTEXT:-}" ] && KUBECTL+=(--context "${HELM_KUBECONTEXT}")
KUBECTL+=(-n "${LOCK_NS}")

_lane() {
  if [ -n "${ROLL_LANE:-}" ]; then printf '%s' "${ROLL_LANE}"; return; fi
  local here url repo branch
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  url="$(git -C "${here}" remote get-url origin 2>/dev/null || true)"
  repo="$(basename "${url%.git}")"
  branch="$(git -C "${here}" branch --show-current 2>/dev/null || true)"
  if [ -z "${repo}" ] || [ -z "${branch}" ]; then
    echo "REFUSING: cannot derive this lane's <repo>/<branch> (detached HEAD or no origin)." >&2
    echo "  Name it:  ROLL_LANE=<repo>/<branch> $0 ..." >&2
    exit 2
  fi
  printf '%s/%s' "${repo}" "${branch}"
}

# Prints "lane<TAB>started<TAB>expected_end<TAB>age_minutes<TAB>seconds_until_stale", or nothing
# when there is no lock; the lock is stale when the last field is <= 0. Age is read from the
# server's creationTimestamp, not from `started`: the server's clock is the one every lane shares.
_read() {
  local out created_s end end_s stale_at now
  out="$("${KUBECTL[@]}" get configmap "${LOCK_NAME}" --ignore-not-found \
    -o jsonpath='{.data.lane}{"\t"}{.data.started}{"\t"}{.data.expected_end}{"\t"}{.metadata.creationTimestamp}')" || {
    echo "REFUSING: cannot read ${LOCK_NS}/${LOCK_NAME} -- an unreadable lock is not a free one." >&2
    exit 4
  }
  [ -z "${out}" ] && return 0
  created_s="$(date -u -d "$(printf '%s' "${out}" | cut -f4)" +%s)"
  end="$(printf '%s' "${out}" | cut -f3)"
  now="$(date -u +%s)"
  stale_at=$(( created_s + STALE_MIN * 60 ))
  # `date -d ""` parses as today's midnight, so an empty end is caught before it is parsed.
  if [ -n "${end}" ] && end_s="$(date -u -d "${end}" +%s 2>/dev/null)"; then
    [ "${end_s}" -gt "${stale_at}" ] && stale_at="${end_s}"
  else
    echo "note: ${LOCK_NS}/${LOCK_NAME} has no readable expected_end ('${end}'); the ${STALE_MIN}-minute floor alone applies." >&2
  fi
  printf '%s\t%s\t%s\n' "$(printf '%s' "${out}" | cut -f1-3)" "$(( (now - created_s) / 60 ))" "$(( stale_at - now ))"
}

_say() { # holder line, for a human
  local left; left="$(cut -f5 <<<"$1")"
  if [ "${left}" -gt 0 ]; then left="stale in $(( (left + 59) / 60 )) min"; else left="stale"; fi
  printf '%s held by %s, started %s, expected end %s, age %s min, %s\n' \
    "${LOCK_NS}/${LOCK_NAME}" "$(cut -f1 <<<"$1")" "$(cut -f2 <<<"$1")" "$(cut -f3 <<<"$1")" "$(cut -f4 <<<"$1")" "${left}"
}

# 0 = this lane may roll (free, ours, or stale); 3 = another lane holds a live lock.
_check() {
  local me="$1" cur
  cur="$(_read)" || exit 4
  [ -z "${cur}" ] && return 0
  [ "$(cut -f1 <<<"${cur}")" = "${me}" ] && return 0
  [ "$(cut -f5 <<<"${cur}")" -le 0 ] && return 0
  return 3
}

cmd="${1:-}"; shift || true
minutes=90
while [ $# -gt 0 ]; do
  case "$1" in
    --minutes) minutes="$2"; shift 2 ;;
    --minutes=*) minutes="${1#--minutes=}"; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

me="$(_lane)"
case "${cmd}" in
  show)
    cur="$(_read)" || exit 4
    if [ -z "${cur}" ]; then echo "${LOCK_NS}/${LOCK_NAME}: free"; else _say "${cur}"; fi
    ;;
  check)
    if _check "${me}"; then exit 0; fi
    echo "REFUSING TO ROLL: $(_say "$(_read)")" >&2
    exit 3
    ;;
  acquire)
    cur="$(_read)" || exit 4
    if [ -n "${cur}" ]; then
      holder="$(cut -f1 <<<"${cur}")"; left="$(cut -f5 <<<"${cur}")"
      if [ "${holder}" = "${me}" ]; then
        echo "roll lock already held by this lane: $(_say "${cur}")"
        exit 0
      fi
      if [ "${left}" -gt 0 ]; then
        echo "REFUSING TO ROLL: $(_say "${cur}")" >&2
        echo "  Another lane is rolling. Wait for it to release, or for the lock to go stale" \
             "(the later of ${STALE_MIN} min and its expected end)." >&2
        exit 3
      fi
      echo "TAKING OVER A STALE LOCK (past both ${STALE_MIN} min and its expected end): $(_say "${cur}")" >&2
      "${KUBECTL[@]}" delete configmap "${LOCK_NAME}" --ignore-not-found >/dev/null
    fi
    started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    end="$(date -u -d "+${minutes} minutes" +%Y-%m-%dT%H:%M:%SZ)"
    if ! "${KUBECTL[@]}" create configmap "${LOCK_NAME}" \
         --from-literal=lane="${me}" --from-literal=started="${started}" \
         --from-literal=expected_end="${end}" >/dev/null 2>&1; then
      cur="$(_read)"
      echo "REFUSING TO ROLL: lost the race for the lock. ${cur:+$(_say "${cur}")}" >&2
      exit 3
    fi
    echo "roll lock acquired: ${LOCK_NS}/${LOCK_NAME} lane=${me} started=${started} expected_end=${end}"
    echo "  Release it when the gates pass:  scripts/roll-lock.sh release"
    ;;
  release)
    cur="$(_read)" || exit 4
    if [ -z "${cur}" ]; then echo "${LOCK_NS}/${LOCK_NAME}: already free"; exit 0; fi
    if [ "$(cut -f1 <<<"${cur}")" != "${me}" ]; then
      echo "REFUSING TO RELEASE another lane's lock: $(_say "${cur}")" >&2
      exit 3
    fi
    "${KUBECTL[@]}" delete configmap "${LOCK_NAME}" >/dev/null
    echo "roll lock released: lane=${me}"
    ;;
  *)
    echo "usage: $0 {acquire [--minutes N]|check|release|show}" >&2
    exit 2
    ;;
esac
