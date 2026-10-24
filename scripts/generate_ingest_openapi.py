#!/usr/bin/env python3
"""Generate the ingest-v1 OpenAPI document and seal its shape (docs/api/).

    python scripts/generate_ingest_openapi.py          # write the document, append the lock row
    python scripts/generate_ingest_openapi.py --check  # exit 1 if the document or lock is stale

Only operations tagged `ingest-v1` (src/iagent/ingest_api.py) are published. The SHAPE HASH is a
sha256 over the stable (non-preview) operations with annotation keywords removed, so wording
changes do not move it but a type, field, route or status change does. The lock file
docs/api/ingest-v1.shapes.lock is append-only: if the shape moves under an existing version the
script writes NOTHING and exits 2; bump INGEST_API_VERSION and add a docs/api/CHANGELOG.md entry.

Unknown args and --help never write (see generate_canvas_schema.py for why).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "api" / "ingest-v1.openapi.json"
LOCK_PATH = ROOT / "docs" / "api" / "ingest-v1.shapes.lock"
_USAGE = __doc__.split("\n\n")[1].rstrip()

LOCK_HEADER = (
    "# ingest-v1 shape lock: one row per API version, `<version> <sha256 of the stable shape>`.\n"
    "# Append-only. Written by scripts/generate_ingest_openapi.py; a changed shape under an\n"
    "# existing version is refused (bump INGEST_API_VERSION, add a docs/api/CHANGELOG.md entry).\n"
)

_ANNOTATIONS = frozenset({"description", "summary", "title", "example", "examples"})
# Mappings whose KEYS are names: keep every key verbatim, recurse into the values.
_NAME_MAPS = frozenset({"properties", "patternProperties", "schemas", "paths", "responses",
                        "content", "securitySchemes", "$defs", "definitions"})
_REF = re.compile(r"^#/components/(schemas|securitySchemes)/(.+)$")

REFUSAL = ("the v1 shape changed under version {v}; bump INGEST_API_VERSION in "
           "src/iagent/ingest_api.py and add a docs/api/CHANGELOG.md entry")


def _refs(node, out: set) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                m = _REF.match(v)
                if m:
                    out.add((m.group(1), m.group(2)))
            else:
                _refs(v, out)
    elif isinstance(node, list):
        for v in node:
            _refs(v, out)


def _security_names(paths: dict) -> set:
    names: set = set()
    for item in paths.values():
        for op in item.values():
            if isinstance(op, dict):
                for req in op.get("security", []) or []:
                    names.update(req.keys())
    return names


def _close_components(paths: dict, components: dict) -> dict:
    """Components reachable from `paths`: transitive $ref closure; securitySchemes if used."""
    schemas = components.get("schemas", {})
    seen: set = set()
    todo: set = set()
    _refs(paths, todo)
    while todo:
        ref = todo.pop()
        if ref in seen:
            continue
        seen.add(ref)
        if ref[0] == "schemas" and ref[1] in schemas:
            more: set = set()
            _refs(schemas[ref[1]], more)
            todo |= more - seen
    out: dict = {}
    kept = {n: schemas[n] for kind, n in seen if kind == "schemas" and n in schemas}
    if kept:
        out["schemas"] = kept
    sec = components.get("securitySchemes", {})
    used = _security_names(paths) | {n for kind, n in seen if kind == "securitySchemes"}
    kept_sec = {n: sec[n] for n in used if n in sec}
    if kept_sec:
        out["securitySchemes"] = kept_sec
    return out


def _filter_ops(doc: dict, keep) -> dict:
    paths: dict = {}
    for path, item in doc.get("paths", {}).items():
        ops = {k: v for k, v in item.items() if isinstance(v, dict) and keep(v)}
        if ops:
            paths[path] = ops
    out = {"openapi": doc["openapi"], "paths": paths}
    comps = _close_components(paths, doc.get("components", {}))
    if comps:
        out["components"] = comps
    return out


def filter_openapi(full: dict, tag: str, version: str) -> dict:
    """The published document: only `tag`-ed operations plus the components they reach."""
    out = _filter_ops(full, lambda op: tag in (op.get("tags") or []))
    out["info"] = {"title": "Cortex ingest API", "version": version}
    return out


def strip_annotations(node, _names: bool = False):
    """Drop annotation keywords where they are keywords; keep them where they are NAMES."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if not _names and k in _ANNOTATIONS:
                continue
            out[k] = strip_annotations(v, _names=(not _names and k in _NAME_MAPS))
        return out
    if isinstance(node, list):
        return [strip_annotations(v) for v in node]
    return node


def shape_hash(doc: dict) -> str:
    stable = _filter_ops(doc, lambda op: op.get("x-stability") != "preview")
    canon = json.dumps(strip_annotations(stable), sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def serialise(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def read_lock(text: str) -> dict:
    rows: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            ver, sha = line.split()[:2]
            rows[ver] = sha
    return rows


def plan_lock(text: str | None, version: str, sha: str) -> tuple[str, str | None]:
    """-> (action, new_text); action is 'append', 'noop' or 'refuse'. Never edits a row."""
    if text is None:
        return "append", LOCK_HEADER + f"{version} {sha}\n"
    rows = read_lock(text)
    if version not in rows:
        sep = "" if (text.endswith("\n") or not text) else "\n"
        return "append", text + sep + f"{version} {sha}\n"
    if rows[version] == sha:
        return "noop", None
    return "refuse", None


def build():
    sys.path.insert(0, str(ROOT))
    from src.iagent import gateway
    from src.iagent.ingest_api import INGEST_API_VERSION, INGEST_V1_TAG
    doc = filter_openapi(gateway.app.openapi(), INGEST_V1_TAG, INGEST_API_VERSION)
    return doc, INGEST_API_VERSION


def _read(path: pathlib.Path) -> str | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write() -> int:
    doc, version = build()
    sha = shape_hash(doc)
    action, new_lock = plan_lock(_read(LOCK_PATH), version, sha)
    if action == "refuse":
        print(REFUSAL.format(v=version), file=sys.stderr)
        return 2
    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DOC_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(serialise(doc))
    if action == "append":
        with open(LOCK_PATH, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_lock)
    print(f"wrote {DOC_PATH.name}; lock {action} {version} {sha[:12]}")
    return 0


def check() -> int:
    doc, version = build()
    sha = shape_hash(doc)
    rc = 0
    if _read(DOC_PATH) != serialise(doc):
        print(f"STALE: {DOC_PATH} differs from regenerated; run the generator", file=sys.stderr)
        rc = 1
    lock = _read(LOCK_PATH)
    rows = read_lock(lock) if lock is not None else {}
    if version not in rows:
        print(f"STALE: {LOCK_PATH.name} has no row for {version}; run the generator",
              file=sys.stderr)
        rc = 1
    elif rows[version] != sha:
        print(f"STALE: {LOCK_PATH.name} row for {version} has a different sha; "
              + REFUSAL.format(v=version), file=sys.stderr)
        rc = 1
    if rc == 0:
        print(f"ok: {version} {sha[:12]}")
    return rc


def main(argv: list[str]) -> int:
    if argv == []:
        return write()
    if argv == ["--check"]:
        return check()
    helped = argv in (["--help"], ["-h"])
    print(_USAGE, file=sys.stdout if helped else sys.stderr)
    return 0 if helped else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
