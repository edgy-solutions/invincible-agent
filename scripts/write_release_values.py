#!/usr/bin/env python3
"""Write `values-release-<version>.yaml`: every image the chart runs, by digest.

THE RULE (ruled by the architect, 2026-11-04): digests are generated at PUBLISH time only. The chart
release workflow writes this file and attaches it to the chart release as the artifact of record;
the seal runs on the render WITH this file; `scripts/upgrade-sandbox.sh` reads the artifact for the
version it rolls and never resolves a tag at roll time.

WHAT GOES IN `global.imageDigests` (keyed `<registry>/<repository>`, no tag):

  * OURS -- `<manifest registry>/<service>` -> the digest `scripts/retag_images_by_digest.py`
    recorded in `image-digests.json`, for every service in the manifest. The population is the
    build matrix (`services_from_matrix()`), never a list here. A manifest short of the matrix, or
    one that names any `missing` or `failed`, is refused (exit 3): a release file that pinned
    eleven of twelve images would seal clean over a twelfth that floats.
  * THIRD PARTY -- the chart is rendered from its own values with every optional workload on, and
    every rendered image that is not ours already carries a digest from `values.yaml`. That digest
    is confirmed in its registry BY DIGEST (a HEAD answering 200 with the same
    `Docker-Content-Digest`) and written out. A third-party image with no digest is refused
    (exit 4), naming it; a digest the registry does not hold, or holds as another, is refused
    (exit 5). THIS NEVER RESOLVES A TAG TO A DIGEST: a tag read at publish time would put whatever
    the tag pointed at that minute into a file that then calls it reviewed.

The registry client is injectable (`head`) so the tests run offline; the default one asks anonymously
and never prints the token it is given.

Exit: 0 written; 2 the render failed; 3 manifest short or carrying missing/failed; 4 a third-party
image rendered without a digest; 5 a digest the registry did not confirm.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import retag_images_by_digest as _retag  # noqa: E402
import seal_image_digests as _seal  # noqa: E402

_ACCEPT = ",".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class Refused(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def registry_head(registry: str, repo: str, digest: str) -> "tuple[int, str | None]":
    """HEAD `<registry>/<repo>@<digest>` anonymously. Returns (status, Docker-Content-Digest).

    The pull token is discovered from the registry's own challenge and held in a local variable;
    it is not printed, logged or returned.
    """
    host = "registry-1.docker.io" if registry == "docker.io" else registry
    url = f"https://{host}/v2/{repo}/manifests/{digest}"

    def _head(token: "str | None"):
        headers = {"Accept": _ACCEPT}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(url, headers=headers, method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.headers

    status, headers = _head(None)
    if status == 401:
        challenge = headers.get("WWW-Authenticate", "")
        realm = re.search(r'realm="([^"]+)"', challenge)
        service = re.search(r'service="([^"]+)"', challenge)
        if realm:
            q = f"?scope=repository:{repo}:pull" + (f"&service={service.group(1)}" if service else "")
            with urllib.request.urlopen(realm.group(1) + q, timeout=30) as r:
                body = json.load(r)
            token = body.get("token") or body.get("access_token")
            status, headers = _head(token)
    return status, headers.get("Docker-Content-Digest")


def helm_render(chart: str, values: "list[str]") -> str:
    cmd = ["helm", "template", "invincible-agent", chart]
    for v in values:
        cmd += ["-f", v]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        # helm's error can quote a value; its last line is enough to say what failed.
        last = (done.stderr.strip().splitlines() or ["?"])[-1]
        raise Refused(2, f"helm template failed (exit {done.returncode}): {last}")
    return done.stdout


def split_image(image: str) -> "tuple[str, str, str | None]":
    """`registry/repo[:tag][@digest]` -> (registry, repo, digest or None)."""
    ref, _, digest = image.partition("@")
    registry, _, rest = ref.partition("/")
    last = rest.rsplit("/", 1)[-1]
    repo = rest.rsplit(":", 1)[0] if ":" in last else rest
    return registry, repo, (digest or None)


def ours_rows(manifest: dict, services: "list[str]") -> "dict[str, str]":
    images = manifest.get("images") or {}
    problems = []
    if manifest.get("missing"):
        problems.append(f"missing: {', '.join(sorted(manifest['missing']))}")
    if manifest.get("failed"):
        problems.append(f"failed: {', '.join(sorted(manifest['failed']))}")
    short = [s for s in services if s not in images]
    if short or len(images) < len(services):
        problems.append(f"{len(images)} image(s) for {len(services)} service(s) in the build matrix"
                        + (f"; absent: {', '.join(short)}" if short else ""))
    bad = [s for s, d in images.items() if not _DIGEST.match(str(d))]
    if bad:
        problems.append(f"not a digest: {', '.join(sorted(bad))}")
    if problems:
        raise Refused(3, "the manifest cannot pin the release: " + "; ".join(problems))
    reg = manifest["registry"]
    return {f"{reg}/{svc}": images[svc] for svc in sorted(images)}


def third_party_rows(rendered: str, ours_prefix: str, head) -> "dict[str, str]":
    rows: "dict[str, str]" = {}
    for image in dict.fromkeys(_seal.rendered_images(rendered)):
        registry, repo, digest = split_image(image)
        if f"{registry}/{repo}".startswith(ours_prefix + "/"):
            continue
        if not digest:
            raise Refused(4, f"{image} is rendered without a digest: pin it in values.yaml "
                             f"global.imageDigests. This script never resolves a tag.")
        status, got = head(registry, repo, digest)
        if status != 200 or got != digest:
            raise Refused(5, f"{registry}/{repo}@{digest[:19]}... was not confirmed by its registry "
                             f"(HTTP {status}, Docker-Content-Digest "
                             f"{'matches' if got == digest else 'differs or absent'})")
        rows[f"{registry}/{repo}"] = digest
    return rows


def render_file(version: str, commit: str, now: str, rows: "dict[str, str]") -> str:
    lines = [
        f"# values-release-{version}.yaml -- every image of chart invincible-agent {version}, by digest.",
        f"# Chart version {version}, commit {commit}, written {now} by scripts/write_release_values.py.",
        "# Ours: from the build (image-digests.json). Third party: the digest values.yaml pins, confirmed",
        "# in its registry by digest. Nothing here was resolved from a tag.",
        "global:",
        "  imageDigests:",
    ]
    for key in sorted(rows):
        lines.append(f'    "{key}": "{rows[key]}"')
    return "\n".join(lines) + "\n"


def generate(manifest_path, chart, chart_version, out, workload_values, *, head=registry_head,
             render=helm_render, services=None, now=None) -> dict:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest.get("chart_version") != chart_version:
        raise Refused(3, f"the manifest is for chart {manifest.get('chart_version')!r}, not {chart_version!r}")
    services = _retag.services_from_matrix() if services is None else services
    rows = ours_rows(manifest, services)
    rendered = render(chart, [str(workload_values)] if workload_values else [])
    rows.update(third_party_rows(rendered, manifest["registry"], head))
    stamp = now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    Path(out).write_text(render_file(chart_version, manifest.get("commit", "?"), stamp, rows),
                         encoding="utf-8", newline="\n")
    return rows


def main(argv=None, **kw) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--manifest", required=True, help="image-digests.json from retag_images_by_digest.py")
    ap.add_argument("--chart-version", required=True)
    ap.add_argument("--out", required=True, help="values-release-<version>.yaml")
    ap.add_argument("--chart", default=str(_HERE.parent / "helm" / "invincible-agent"))
    ap.add_argument("--workload-values", default=str(_HERE / "values-every-workload.yaml"),
                    help="values that switch on every optional workload, so every image renders")
    a = ap.parse_args(argv)
    try:
        rows = generate(a.manifest, a.chart, a.chart_version, a.out, a.workload_values, **kw)
    except Refused as r:
        print(f"REFUSED (exit {r.code}): {r}", file=sys.stderr)
        return r.code
    print(f"wrote {a.out}: {len(rows)} image digest(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
