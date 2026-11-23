"""The chart-version seal: helm/** changed, so the version moved, or a pending bump is declared.

Run by .github/workflows/release-helm-charts.yml on every helm/** change (never on dispatch).

    python scripts/chart_version_seal.py helm/invincible-agent

THREE VERDICTS, decided on the Chart's version, the CHANGELOG, and which release tags exist:

  release  Chart.yaml's version is unpublished. The workflow publishes it.
  pending  Chart.yaml's version is published, but the CHANGELOG opens a
           `## <next> — not yet cut` entry for an unpublished, higher version. The change waits
           for that cut. The workflow publishes NOTHING and is green.
  refuse   Chart.yaml's version is published and no pending entry declares the bump, or the
           version being released still carries its `not yet cut` heading. Exit 1.

WHY `pending` EXISTS (the architect, via Chris, 2026-11-08). Before it, every helm/** PR merged
between cuts turned master red (#277, #262, #300, #294) until the next cut bumped the Chart.
That red taught people to wait for a cut or batch helm changes into it. The original failure
stays refused: contents moving under an UNCHANGED, published version with nothing saying a
bump is owed. That is what cost a work cluster at 0.3.36. A `not yet cut` entry is the
statement that the bump is owed, and it is checked to name a version that does not exist yet.

THE CUT DATES THE HEADING. A release whose CHANGELOG still says `## <version> — not yet cut`
is refused, so the pending entry cannot outlive the version it announced.

Writes `pending=true|false` to $GITHUB_OUTPUT when that is set.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

TAG_PREFIX = "invincible-agent-"
PENDING = re.compile(r"^## (\d+\.\d+\.\d+) [—–-] not yet cut[ \t]*$", re.MULTILINE)
VERSION = re.compile(r"^version:[ \t]*['\"]?([^'\"\s]+)", re.MULTILINE)


def _key(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def decide(version: str, changelog: str, is_published: Callable[[str], bool]) -> tuple[str, str]:
    """`(verdict, message)` for a helm/** change at Chart `version`."""
    pending = PENDING.findall(changelog)
    if not is_published(version):
        if version in pending:
            return "refuse", (
                f"Chart.yaml is at {version}, but CHANGELOG.md still heads it "
                f"'## {version} — not yet cut'. The cut dates that heading.")
        return "release", f"Chart version {version} is unpublished — proceeding to release."
    owed = [v for v in pending if _key(v) > _key(version) and not is_published(v)]
    if owed:
        return "pending", (
            f"Chart.yaml is at the published {version}; this helm/** change waits under "
            f"'## {owed[0]} — not yet cut'. Nothing is published by this run.")
    return "refuse", (
        f"helm/** changed but Chart.yaml is still at {version}, which is already published as "
        f"{TAG_PREFIX}{version}, and no CHANGELOG entry '## <next> — not yet cut' declares the "
        "bump. Bump helm/invincible-agent/Chart.yaml or open that entry. Publishing nothing "
        "with neither means a deployment installing 'the latest chart' silently gets the OLD "
        "contents — the failure mode that left engines unregistered.")


def _tag_exists(version: str) -> bool:
    r = subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{TAG_PREFIX}{version}"],
                       capture_output=True, text=True)
    return r.returncode == 0


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # the headings carry an em dash
    chart =Path(argv[1] if len(argv) > 1 else "helm/invincible-agent")
    m = VERSION.search((chart / "Chart.yaml").read_text(encoding="utf-8"))
    if not m:
        print(f"::error::no version: line in {chart / 'Chart.yaml'}")
        return 1
    changelog = (chart / "CHANGELOG.md").read_text(encoding="utf-8")
    verdict, message = decide(m.group(1), changelog, _tag_exists)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"pending={'true' if verdict == 'pending' else 'false'}\n")
    print({"release": "", "pending": "::notice::", "refuse": "::error::"}[verdict] + message)
    return 1 if verdict == "refuse" else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
