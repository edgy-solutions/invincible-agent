#!/usr/bin/env bash
# Refuses unless this tree IS the release its chart says it is. Ruled 2026-11-03 (the architect):
# upgrade-sandbox.sh runs from a worktree checked out at the release tag, never from master's
# working tree. A chart is read from whatever is on disk where the script lives, so a roll from a
# working tree renders that tree: other lanes' merges, a half-made edit, a version nobody cut.
#
#   usage: scripts/require-release-tree.sh <chart dir>
#   exit:  0 this tree is the release; 4 it is not, and stderr says why
#
# THE RELEASE IS WHAT THE CHART NAMES, `<name>-<version>` from its own Chart.yaml, so there is no
# tag to type. The script takes no ref on purpose: a ref argument would render one tree while
# reading the values of another. To roll a release, make the tree:
#
#   git worktree add --detach <path> <name>-<version>
#   cp <this tree's values-sandbox.secret.yaml> <path>/helm/invincible-agent/
#   <path>/scripts/upgrade-sandbox.sh
#
# A gitignored file is not in the question, because the secret overlay has to be one. An untracked
# file under the chart is: helm would render it, and the tag does not hold it.
chart="$1"
if [ ! -f "${chart}/Chart.yaml" ]; then
  echo "REFUSING: no Chart.yaml at '${chart}'." >&2
  exit 4
fi
name="$(sed -n 's/^name:[[:space:]]*//p' "${chart}/Chart.yaml" | tr -d '"\r')"
version="$(sed -n 's/^version:[[:space:]]*//p' "${chart}/Chart.yaml" | tr -d '"\r')"
want="${name}-${version}"

head_sha="$(git -C "${chart}" rev-parse HEAD 2>/dev/null)"
tag_sha="$(git -C "${chart}" rev-parse --verify --quiet "refs/tags/${want}^{commit}" 2>/dev/null)"
if [ -z "${tag_sha}" ]; then
  echo "REFUSING: this chart says ${version}, and tag ${want} does not exist here." >&2
  echo "  Fetch tags, or cut the release first. A roll runs from a release tag." >&2
  exit 4
fi
if [ "${head_sha}" != "${tag_sha}" ]; then
  echo "REFUSING: this tree is at ${head_sha:0:8}, and ${want} is at ${tag_sha:0:8}." >&2
  echo "  A roll runs from a worktree checked out at the release tag:" >&2
  echo "    git worktree add --detach <path> ${want}" >&2
  exit 4
fi
dirty="$(git -C "${chart}" status --porcelain --untracked-files=no 2>/dev/null; git -C "${chart}" status --porcelain -- . 2>/dev/null)"
if [ -n "${dirty}" ]; then
  echo "REFUSING: this tree is at ${want} but does not match it:" >&2
  echo "${dirty}" | sort -u | head -n 10 >&2
  exit 4
fi
echo "release tree: ${want} at ${head_sha:0:8}, clean"
