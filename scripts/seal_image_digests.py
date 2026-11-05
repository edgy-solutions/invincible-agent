#!/usr/bin/env python3
"""The image seal: every image a rendered chart runs is pinned by digest.

Reads a `helm template` stream (multi-document YAML) on stdin and checks every container and
initContainer `image` in a Deployment, StatefulSet, DaemonSet, Job, CronJob or Pod. Each must carry
`@sha256:` and 64 hex characters. Exit 0 when all do; exit 1 listing each image that does not.

ONE RULE, CHART-WIDE, NO LIST. There is no per-image allowance and no prefix test: an image this
repo builds, a third party's and a one-off helper are all held to the same line, so a new image
cannot be missed by being absent from a list nobody updated. The rule is the whole seal.

WHAT IT PRINTS: the image string of each failing container, and counts. Nothing else from the
render. The render holds Secrets, so a document is classified by its `kind:` line and a Secret is
skipped WITHOUT being parsed -- its data is never read, even to find out that it is a Secret.
Only workload documents are parsed at all.

Usage:  helm template ... | python scripts/seal_image_digests.py
"""
from __future__ import annotations

import re
import sys

import yaml

WORKLOADS = ("Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Pod")
_PINNED = re.compile(r"@sha256:[0-9a-f]{64}$")
_KIND = re.compile(r"^kind:[ \t]*['\"]?([A-Za-z]+)['\"]?[ \t]*(?:#.*)?$", re.M)
_SPLIT = re.compile(r"^---[ \t]*$", re.M)


def _pod_spec(doc: dict) -> dict:
    kind = doc.get("kind")
    spec = doc.get("spec") or {}
    if kind == "Pod":
        return spec
    if kind == "CronJob":
        spec = ((spec.get("jobTemplate") or {}).get("spec")) or {}
    return ((spec.get("template") or {}).get("spec")) or {}


def rendered_images(text: str) -> "list[str]":
    """Every container and initContainer image of every workload document, in render order."""
    out: "list[str]" = []
    for chunk in _SPLIT.split(text):
        m = _KIND.search(chunk)
        if not m or m.group(1) not in WORKLOADS:
            continue  # a Secret (or anything else) is never parsed
        doc = yaml.safe_load(chunk)
        if not isinstance(doc, dict):
            continue
        pod = _pod_spec(doc)
        for key in ("initContainers", "containers"):
            for c in pod.get(key) or []:
                image = c.get("image")
                out.append(image if isinstance(image, str) else "<no image>")
    return out


def is_pinned(image: str) -> bool:
    return bool(_PINNED.search(image))


def unpinned(text: str) -> "list[str]":
    return [i for i in rendered_images(text) if not is_pinned(i)]


def main() -> int:
    text = sys.stdin.read()
    images = rendered_images(text)
    bad = [i for i in images if not is_pinned(i)]
    if not images:
        # A seal over nothing is not a pass: an empty stream is a failed render, not a pinned one.
        print("seal: no workload images in the stream; refusing to call that sealed")
        return 1
    for i in bad:
        print(f"  TAG-ONLY  {i}")
    print(f"seal: {len(images)} image(s), {len(images) - len(bad)} pinned by digest, {len(bad)} not")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
