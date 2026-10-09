#!/usr/bin/env bash
# Which register rulings are cited outside the register -- and WHERE.
#
#   usage: scripts/ruling_citations.sh [FROM [TO]]     e.g. scripts/ruling_citations.sh 55 89
#
# Prints, per ruling R-NNN in docs/rulings/README.md (optionally limited to FROM..TO), how many
# TRACKED files cite it in ENFORCING places (code, tests, policy, helm, scripts, schemas, sql) and
# how many in PROSE (docs, sessions, everything else), then the uncited lists for both.
#
# A CITATION CENSUS IS NOT A CITATION. The 2026-09-28 census listed its ten uncited rulings by
# number; once committed, that document was the ONLY citation of all ten, and a naive re-run read
# them as cited (measured 2026-10-07). So any file that says "uncited" is excluded: a document that
# reports on citations is about the register, not a reader of it. Positive control: run with
# INCLUDE_CENSUS=1 and the count of uncited rulings drops.
#
# ⚠ AN UNCITED RULING IS NOT A DEAD ONE. From a grep it is indistinguishable between at least
# three states: invisible (governs nothing), universally obeyed (nothing needs to cite it), and
# enforced anonymously (a seal implements it without naming the number -- the commonest case
# here, and the one a citation grep cannot see). Telling them apart means reading each ruling and
# searching for its SUBJECT. Never report this script's uncited count as a count of dead rulings.
#
# Reads tracked files only (git grep), so an uncommitted packet's citation is not seen -- the
# inbox census's third state applies here too.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

REGISTER=docs/rulings/README.md
FROM="${1:-1}"
TO="${2:-999}"

# A census file says "uncited" AND names at least one ruling. The word alone also matches an
# ontology comment and a proposal's prose (2026-10-07), neither of which cites a ruling -- so the
# second condition is what makes this an exclusion of citation REPORTS and not of a vocabulary.
mapfile -t CENSUS < <(git grep -l -i -w 'uncited' -- . ":!${REGISTER}" \
  | while read -r f; do grep -q -w -E 'R-[0-9]{3}' "$f" && echo "$f"; done || true)
excludes=(":!${REGISTER}")
if [[ "${INCLUDE_CENSUS:-0}" != 1 ]]; then
  for f in "${CENSUS[@]}"; do excludes+=(":!${f}"); done
fi
ENFORCING='^(src|agent_fleet|tests|policy|helm|scripts|schemas|sql|baml_shared)/'

uncited_enf=()
uncited_all=()
total=0
printf '%-7s %9s %6s\n' ruling enforcing prose
while read -r r; do
  n=$((10#${r#R-}))
  (( n < FROM || n > TO )) && continue
  total=$((total + 1))
  files=$(git grep -l -w -e "$r" -- . "${excludes[@]}" || true)
  enf=$(grep -cE "$ENFORCING" <<<"$files" || true)
  all=$(grep -c . <<<"$files" || true)
  printf '%-7s %9d %6d\n' "$r" "$enf" "$((all - enf))"
  (( enf == 0 )) && uncited_enf+=("$r")
  (( all == 0 )) && uncited_all+=("$r")
done < <(grep -o '^## R-[0-9]\{3\}' "$REGISTER" | sed 's/^## //' | sort -u)

echo
echo "census files excluded (${#CENSUS[@]}): ${CENSUS[*]:-none}$([[ "${INCLUDE_CENSUS:-0}" == 1 ]] && echo '  [INCLUDED: INCLUDE_CENSUS=1]')"
echo "cited NOWHERE outside the register: ${#uncited_all[@]} of ${total}: ${uncited_all[*]:-none}"
echo "cited by NO enforcing file:         ${#uncited_enf[@]} of ${total}: ${uncited_enf[*]:-none}"
echo "(an uncited ruling is invisible, universally obeyed, or enforced anonymously -- see the header)"
