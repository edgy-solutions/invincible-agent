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
0.3.77 got them, and how 0.4.68 and 0.4.69 were repaired (their push runs raced the build).

A RELEASE TAG NEVER MOVES. Every destination is read before anything is written: a `:<version>`
already at the commit's digest is left alone, and one at any OTHER digest stops the whole run with
nothing written (exit 4). A re-run is therefore safe, and an overwrite is impossible.

    uv run --frozen python scripts/retag_images_by_digest.py \\
        --chart-version 0.3.77 --sha <commit> [--dry-run]
    uv run --frozen python scripts/retag_images_by_digest.py \\
        --chart-version 0.3.77 --manifest image-digests.json --verify
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


#: What a registry says when a tag does not exist. Anything else that fails is UNREADABLE, never
#: absent: a transient read error must not license a create over a tag that is really there.
_ABSENT = re.compile(r"not found|manifest unknown|name unknown", re.I)


def tag_state(image: str) -> "tuple[str, str | None]":
    """``("absent", None)``, ``("present", digest)`` or ``("unreadable", None)`` for ``image``."""
    rc, out = _run(["docker", "buildx", "imagetools", "inspect", image, "--format", "{{.Manifest.Digest}}"])
    if rc == 0:
        m = re.search(r"sha256:[0-9a-f]{64}", out)
        return ("present", m.group(0)) if m else ("unreadable", None)
    return ("absent", None) if _ABSENT.search(out) else ("unreadable", None)


def plan(services: "list[str]", sha: str, version: str, resolve=None, read_dst=None) -> dict:
    """What the retag WOULD do, decided for every service before anything is written.

    A RELEASE TAG NEVER MOVES (ruling 2026-10-25). `:<version>` that already names the digest the
    commit built is done (`already`); one that names ANY OTHER digest is a `conflict`, and a
    conflict anywhere means nothing is tagged anywhere -- the run stops and reports, it does not
    overwrite. A destination that cannot be read is `unreadable` and refuses the same way.

    `resolve` (source tag -> digest or None) and `read_dst` (destination -> `tag_state`) are
    parameters so the decision is measured without a registry.
    """
    resolve, read_dst = resolve or digest_of, read_dst or tag_state
    out: dict = {"tag": {}, "already": {}, "missing": [], "conflicts": {}, "unreadable": []}
    for svc in services:
        dig = resolve(f"{REGISTRY}/{PREFIX}/{svc}:{sha}")
        if dig is None:
            out["missing"].append(svc)
            continue
        state, have = read_dst(f"{REGISTRY}/{PREFIX}/{svc}:{version}")
        if state == "absent":
            out["tag"][svc] = dig
        elif state == "present" and have == dig:
            out["already"][svc] = dig
        elif state == "present":
            out["conflicts"][svc] = {"tagged": have, "built": dig}
        else:
            out["unreadable"].append(svc)
    return out


def refusal(p: dict) -> "int | None":
    """The exit code a plan refuses with, or None when every service may be tagged.

    4 = a release tag already names another digest; 1 = a destination could not be read;
    3 = an image of the commit does not exist. ALL THREE ARE FATAL to a release (ruling
    2026-10-25: a release that references images that do not exist is not a release); the codes
    stay distinct so the log says which.
    """
    if p["conflicts"]:
        return 4
    if p["unreadable"]:
        return 1
    if p["missing"]:
        return 3
    return None


FAKE_DIGEST = "sha256:" + "0" * 64


def mismatches(manifest: dict, resolve) -> "list[str]":
    """Every way the release's `:<chart_version>` tags differ from the manifest; empty when none.

    `resolve` maps an image reference to its digest or None. It is a parameter so that the
    comparison itself can be shown to say no (`verify`'s wrong-digest control, and the tests).
    """
    ver, probs = manifest["chart_version"], []
    for svc, want in manifest["images"].items():
        got = resolve(f"{manifest['registry']}/{svc}:{ver}")
        if got != want:
            probs.append(f"{svc}:{ver} resolves to {got}, not {want}")
    return probs


def verify(manifest_path: str, chart_version: str, resolve=None) -> int:
    """Read the tags back from the registry. The retag's own report is not the evidence.

    THE CONTROLS MUST FAIL. A fake digest, the commit's short form as a tag, and a tag nobody
    pushed must not resolve, and a wrong digest must be reported as a mismatch. A resolver that
    cannot say no would read every tag as proven.
    """
    resolve = resolve or digest_of
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    missing = manifest.get("missing") or []
    if manifest.get("chart_version") != chart_version or not (manifest.get("images") or missing):
        print(f"REFUSING: {manifest_path} is for {manifest.get('chart_version')!r} with "
              f"{len(manifest.get('images') or {})} image(s); expected {chart_version!r} and at "
              "least one", file=sys.stderr)
        return 2
    for svc in missing:
        print(f"  UNVERIFIED {svc}: missing from the manifest, so no tag was cut")
    if not manifest["images"]:
        # EXIT 3, as the retag does: an image is missing, nothing was tagged to check, and the
        # release fails on it (since 2026-10-25 the release waits for the build, so it is a fault).
        print(f"verify {chart_version}: 0 image(s) tagged, {len(missing)} missing")
        return 3
    probs = mismatches(manifest, resolve)
    svc, want = next(iter(manifest["images"].items()))
    repo = f"{manifest['registry']}/{svc}"
    controls = {
        "a fake digest": f"{repo}@{FAKE_DIGEST}",
        "the short commit as a tag": f"{repo}:{manifest['commit'][:8]}",
        "a tag nobody pushed": f"{repo}:{chart_version}-control-never-pushed",
    }
    for what, ref in controls.items():
        if resolve(ref) is not None:
            probs.append(f"control RESOLVED: {what} ({ref})")
    wrong = dict(manifest, images={svc: "sha256:" + ("1" if want[7] != "1" else "2") + want[8:]})
    if not mismatches(wrong, resolve):
        probs.append("control ACCEPTED a wrong digest: the comparison cannot fail")
    for p in probs:
        print(f"  FAILED    {p}")
    print(f"verify {chart_version}: {len(manifest['images'])} image(s), "
          f"{len(controls) + 1} control(s), {len(probs)} failure(s), {len(missing)} missing")
    return 1 if probs else (3 if missing else 0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chart-version", required=True, help="e.g. 0.3.77 — the tag to create")
    ap.add_argument("--sha", help="the commit whose images are being retagged")
    ap.add_argument("--manifest", default="image-digests.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--summary-file", help="append a markdown record of the run (e.g. $GITHUB_STEP_SUMMARY)")
    ap.add_argument("--verify", action="store_true",
                    help="read --manifest back from the registry instead of retagging")
    args = ap.parse_args()
    if args.verify:
        return verify(args.manifest, args.chart_version)
    if not args.sha:
        ap.error("--sha is required unless --verify")

    services = services_from_matrix()
    if not services:
        # A FLOOR, because an empty population would "succeed" at retagging nothing and emit a
        # manifest describing a fleet of zero services.
        print("REFUSING: no services parsed from the build matrix — the derivation is broken, "
              "and an empty population would report success over nothing.", file=sys.stderr)
        return 2

    print(f"{len(services)} service(s) from {_BUILD_WF.name}")
    # DECIDE EVERYTHING, THEN WRITE. A refusal found at service 12 must not leave 11 tags behind.
    p = plan(services, args.sha, args.chart_version)
    for svc in p["missing"]:
        print(f"  MISSING   {svc}  ({REGISTRY}/{PREFIX}/{svc}:{args.sha} does not resolve)")
    for svc, c in p["conflicts"].items():
        print(f"  CONFLICT  {svc}:{args.chart_version} names {c['tagged']}, the commit built "
              f"{c['built']} -- not overwritten")
    for svc in p["unreadable"]:
        print(f"  UNREADABLE {svc}:{args.chart_version} -- cannot tell absent from present")
    for svc, dig in p["already"].items():
        print(f"  already   {svc}  {dig[:19]}…  = :{args.chart_version}")
    rc = refusal(p)
    rows, failed = dict(p["already"]), []
    if rc is None:
        for svc, dig in p["tag"].items():
            if args.dry_run:
                print(f"  would tag {svc}  {dig[:19]}…  -> :{args.chart_version}")
                rows[svc] = dig
                continue
            # BY DIGEST: the new tag points at the bytes the sha tag points at, not at the sha tag.
            out_rc, out = _run(["docker", "buildx", "imagetools", "create", "-t",
                                f"{REGISTRY}/{PREFIX}/{svc}:{args.chart_version}",
                                f"{REGISTRY}/{PREFIX}/{svc}@{dig}"])
            if out_rc != 0:
                failed.append(svc)
                print(f"  FAILED    {svc}: {out.strip()[:200]}")
                continue
            rows[svc] = dig
            print(f"  tagged    {svc}  {dig[:19]}…  -> :{args.chart_version}")
    else:
        print(f"REFUSING to tag anything (exit {rc}): see the lines above")

    manifest = {
        "chart_version": args.chart_version,
        "commit": args.sha,
        "registry": f"{REGISTRY}/{PREFIX}",
        # On a refusal this lists only the tags that ALREADY named the commit's digests.
        "images": rows,
        # NAMED, NOT OMITTED. A manifest that silently lists only what worked is a claim that
        # what it lists is everything.
        "missing": sorted(p["missing"]),
        "failed": sorted(failed + p["unreadable"]),
        "conflicts": p["conflicts"],
        "already_tagged": sorted(p["already"]),
        "expected": len(services),
    }
    Path(args.manifest).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    line = (f"retag {args.chart_version} at {args.sha}: {len(rows)}/{len(services)} tagged "
            f"({len(p['already'])} already), {len(p['missing'])} missing, "
            f"{len(p['conflicts'])} conflict(s), {len(failed) + len(p['unreadable'])} failed")
    print(f"wrote {args.manifest}: {line}")
    if args.summary_file:
        # THE LOG OF A DISPATCH: the run's job summary carries what it did, by count and by name.
        with open(args.summary_file, "a", encoding="utf-8") as f:
            f.write(f"### {line}\n\n")
            for svc, c in p["conflicts"].items():
                f.write(f"- CONFLICT `{svc}:{args.chart_version}` names `{c['tagged']}`, "
                        f"built `{c['built']}`; not overwritten\n")
            for svc in sorted(p["missing"]):
                f.write(f"- MISSING `{svc}:{args.sha}`\n")
            f.write("\n")

    if rc is not None:
        return rc
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
