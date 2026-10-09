"""Rebuild the alpha cost validation document, and say whether it is the 09-06 one.

WHAT "REPRODUCE" MEANS HERE: the built page carries the same DATA IDENTITIES as the 09-06
`cost-validation-notional-customer-alpha.html` -- the same disclosure, rows, manifest, pricing
module hashes and page sections, exactly as `scripts/cost_package_identities.py` defines them
and as `tests/fixtures/cost_alpha_2026_09_06_identities.json` records them. The comparison runs
on the FILE THIS SCRIPT WROTE, read back off the disk, and any difference exits nonzero naming
each differing key.

WHY THE FILE'S OWN SHA256 DIFFERS FROM 09-06: `algorithm_sha` (the commit the build ran at) and
the .duckdb container's bytes are INPUTS, not identities. Both are in the exclusion list in
`cost_package_identities.py`, with the measurement behind each. So this build is byte-identical
to ITSELF (same commit, same duckdb file, same canvas, same as_of) and identity-identical to
09-06, and it is not claimed to be byte-identical to 09-06.

THE PINNED INPUTS, none of them typed here: the recipient is the alpha customer; the canvas is
`tests/fixtures/cost_alpha_canvas.json`, the file the canvas acceptance test loads too; and
`as_of` is read from the fixture's provenance, so the page claims the 09-06 date and not today's.

THE DUCKDB IS BUILT AT MOST ONCE. Its bytes differ between builds over identical rows and its
sha256 is embedded in the page, so every rebuild would move the page. It is built if absent,
saying so, and reused on every later run. Delete it on purpose to take a new container.

    uv run python scripts/build_alpha_document.py [--duckdb PATH] [--out-dir DIR] [--runtime-dir DIR]

A second run prints `unchanged <sha256>` and leaves the file's mtime alone.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build_cost_package as B  # noqa: E402
import cost_package_identities as I  # noqa: E402
from scripts.build_cost_dataset import build as build_dataset  # noqa: E402

RECIPIENT = "notional-customer-alpha"
CANVAS = ROOT / "tests" / "fixtures" / "cost_alpha_canvas.json"
FIXTURE = ROOT / "tests" / "fixtures" / "cost_alpha_2026_09_06_identities.json"


def differing_keys(built: dict, fixture: dict) -> list[str]:
    """Every key of `identities` that differs, plus `sections`; empty means the same document."""
    out = [k for k in sorted(set(built["identities"]) | set(fixture["identities"]))
           if built["identities"].get(k) != fixture["identities"].get(k)]
    if built["sections"] != fixture["sections"]:
        out.append("sections")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--duckdb", default=str(ROOT / "dist" / f"cost-{RECIPIENT}.duckdb"))
    ap.add_argument("--out-dir", default=str(ROOT / "dist"))
    ap.add_argument("--runtime-dir", default=str(ROOT / ".pyodide-cache"))
    a = ap.parse_args(argv)

    fixture = json.loads(FIXTURE.read_text("utf-8"))
    as_of = fixture["provenance"]["as_of"]

    db = pathlib.Path(a.duckdb)
    if db.is_file():
        print(f"reusing {db}")
    else:
        db.parent.mkdir(parents=True, exist_ok=True)
        print(f"{db} is absent: building it ONCE")
        build_dataset(RECIPIENT, db)

    # The same argv the CLI takes, so the script and `build_cost_package.py` cannot disagree.
    rc = B.main([
        "--recipient", RECIPIENT, "--duckdb", str(db), "--canvas", str(CANVAS),
        "--as-of", as_of, "--out-dir", a.out_dir, "--runtime-dir", a.runtime_dir])
    if rc:
        return rc

    dest = pathlib.Path(a.out_dir) / f"cost-validation-{RECIPIENT}.html"
    diff = differing_keys(I.extract(dest), fixture)
    if diff:
        print(f"NOT the 09-06 document: differing keys {diff}", file=sys.stderr)
        return 1
    print("identities and sections equal the 09-06 fixture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
