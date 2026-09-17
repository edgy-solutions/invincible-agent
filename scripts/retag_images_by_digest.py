#!/usr/bin/env python
"""Retag every fleet image to the chart version, BY DIGEST, and emit the manifest.

WHY BY DIGEST AND NOT BY TAG. `docker tag a:sha a:0.3.77` re-points a name; a digest names the
bytes. A retag that resolves `:<sha>` to its digest and creates `:<chart-version>` pointing at
THAT digest is a statement about an artifact rather than about a label — and the manifest it emits
is checkable afterwards by anyone, against a registry, without trusting this script's own report.

WHAT IT CLOSES. `global.defaultImageTag` was `latest`, so an unpinned deploy got whatever `latest`
happened to be at pull time — which is a different artifact on Tuesday than on Monday, with the
same chart. A chart version that resolves to its OWN images makes "install chart 0.3.77" mean one
thing forever.

THE POPULATION IS DERIVED FROM THE BUILD MATRIX, never listed here. A hand-kept service list in a
second file is the shape this repo has paid for repeatedly: it is right on the day it is written
and silently short on the day a service is added. If `build-containers.yml`'s matrix is the thing
that decides what gets built, it is the thing that decides what gets retagged.

RUNS RETROACTIVELY. `--chart-version` and `--sha` are arguments rather than environment reads, so
a release that shipped before this existed can be given its tags after the fact — which is how
0.3.77 got them.

    uv run --frozen python scripts/retag_images_by_digest.py \\
        --chart-version 0.3.77 --sha <commit> [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_BUILD_WF = _REPO / ".github" / "workflows" / "build-containers.yml"

REGISTRY = "ghcr.io"
PREFIX = "edgy-solutions/invincible-agent"


def services_from_matrix(workflow: Path = _BUILD_WF) -> "list[str]":
    """Every `- service: <name>` in the build matrix.

    PARSED FROM THE WORKFLOW, not from a list here. Read as text rather than as YAML because the
    workflow is not importable and a YAML dependency for one field is a dependency that has to be
    installed wherever this runs — including a release runner that has nothing.
    """
    text = workflow.read_text(encoding="utf-8")
    names = re.findall(r"^\s*-\s*service:\s*([A-Za-z0-9._-]+)\s*$", text, re.M)
    return list(dict.fromkeys(names))


def _run(cmd: "list[str]") -> "tuple[int, str]":
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def digest_of(image: str) -> "str | None":
    """The manifest digest `:tag` currently resolves to, or None when it cannot be read.

    NONE IS NOT AN EMPTY DIGEST. A service whose image is missing for this sha is a REPORTED
    fact — the build may still be running, or the matrix may have gained a row whose first build
    has not happened. Treating it as absent-and-fine is how a manifest comes to describe eleven
    images when twelve were expected.
    """
    rc, out = _run(["docker", "buildx", "imagetools", "inspect", image, "--format", "{{.Manifest.Digest}}"])
    if rc != 0:
        return None
    m = re.search(r"sha256:[0-9a-f]{64}", out)
    return m.group(0) if m else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chart-version", required=True, help="e.g. 0.3.77 — the tag to create")
    ap.add_argument("--sha", required=True, help="the commit whose images are being retagged")
    ap.add_argument("--manifest", default="image-digests.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    services = services_from_matrix()
    if not services:
        # A FLOOR, because an empty population would "succeed" at retagging nothing and emit a
        # manifest describing a fleet of zero services.
        print("REFUSING: no services parsed from the build matrix — the derivation is broken, "
              "and an empty population would report success over nothing.", file=sys.stderr)
        return 2

    print(f"{len(services)} service(s) from {_BUILD_WF.name}")
    rows, missing, failed = {}, [], []
    for svc in services:
        src = f"{REGISTRY}/{PREFIX}/{svc}:{args.sha}"
        dst = f"{REGISTRY}/{PREFIX}/{svc}:{args.chart_version}"
        dig = digest_of(src)
        if dig is None:
            missing.append(svc)
            print(f"  MISSING   {svc}  ({src} does not resolve)")
            continue
        if args.dry_run:
            print(f"  would tag {svc}  {dig[:19]}…  -> :{args.chart_version}")
            rows[svc] = dig
            continue
        # BY DIGEST: the new tag points at the bytes the sha tag points at, not at the sha tag.
        rc, out = _run(["docker", "buildx", "imagetools", "create", "-t", dst,
                        f"{REGISTRY}/{PREFIX}/{svc}@{dig}"])
        if rc != 0:
            failed.append(svc)
            print(f"  FAILED    {svc}: {out.strip()[:200]}")
            continue
        rows[svc] = dig
        print(f"  tagged    {svc}  {dig[:19]}…  -> :{args.chart_version}")

    manifest = {
        "chart_version": args.chart_version,
        "commit": args.sha,
        "registry": f"{REGISTRY}/{PREFIX}",
        "images": rows,
        # NAMED, NOT OMITTED. A manifest that silently lists only what worked is a claim that
        # what it lists is everything.
        "missing": sorted(missing),
        "failed": sorted(failed),
        "expected": len(services),
    }
    Path(args.manifest).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.manifest}: {len(rows)}/{len(services)} tagged")

    if failed:
        return 1
    if missing:
        # EXIT 3, NOT 1: nothing broke, and some images are not there. Distinguishing them lets a
        # release fail on a retag error while a still-building matrix is visible without being
        # fatal — the same three-state discipline the census uses.
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
