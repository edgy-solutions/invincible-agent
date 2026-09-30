"""The data identities of a cost validation package: what makes two packages the same document.

THE 09-06 ALPHA DOCUMENT IS THE ACCEPTANCE TEST for canvas exports (lane/74, 2026-09-30): a
canvas holding the alpha customer's cost questions, exported, must produce that document. This
module says what "that document" means, and extracts it from the HTML so the claim is
re-derivable rather than remembered.

SAME DOCUMENT = SAME DATA, SAME ALGORITHM, SAME SECTIONS. Compared:
  * program, lots, rate vintages: the disclosure
  * rows_sha256 and the row counts: the embedded dataset, hashed by the engine over the rows
  * the manifest's schema, composition, checks and module hashes: what the page reprices, and
    with which pricing.py
  * learning slope and unit-1 hours: the curve the program charts draw
  * the page sections, read from the headings the page carries

NOT compared, each for a stated reason:
  * the file's sha256, `locator`, `algorithm_sha`, `as_of`: they name WHEN and FROM WHICH
    COMMIT a package was built, and a canvas body also records its answers, so every one of
    them moves on a rebuild of the same data. They are kept in the fixture as provenance.
  * `duckdb_sha256`: the .duckdb file's bytes differ between two builds over identical rows
    (measured: 09-06 `8bfc9747...`, 09-30 `28acb9a0...`, same rows_sha256). The rows are the
    identity; the container is not.

    uv run --no-sync python scripts/cost_package_identities.py --html DOC.html --out FIXTURE.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from typing import Any

#: The heading each page section opens with, in page order. Read from the HTML rather than
#: from section markers, because the 09-06 document predates the markers.
HEADINGS: dict[str, str] = {
    "labor": "<h2>Labor ",
    "program": "<h2>Across the program ",
    "composition": "<h2>Price composition ",
    "sepm": "<h2>Program management effort ",
    "material": "<h2>Material ",
    "scenario": ">Your scenario ",
}


def _canon(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def package_from_html(text: str) -> dict[str, Any]:
    m = re.search(r'<script id="package-data" type="application/json">(.*?)</script>',
                  text, re.S)
    if m is None:
        raise ValueError("no package-data block: not a cost validation page")
    return json.loads(m.group(1))


def sections_from_html(text: str) -> list[str]:
    """The sections whose heading the page carries. Each heading must occur at most once."""
    out = []
    for name, heading in HEADINGS.items():
        n = text.count(heading)
        if n > 1:
            raise ValueError(f"heading {heading!r} occurs {n} times; cannot tell sections apart")
        if n == 1:
            out.append(name)
    return out


def identities(pkg: dict[str, Any]) -> dict[str, Any]:
    ds = pkg["dataset"]
    man = pkg["manifest"]
    return {
        "program": pkg["program"],
        "lots": list(pkg["lots"]),
        "rate_vintages": list(pkg["rate_vintages"]),
        "rows_sha256": ds["rows_sha256"],
        "row_counts": {k: len(v) for k, v in sorted(ds["rows"].items())},
        "learning_slope": ds["learning_slope"],
        "unit1_hours": ds["unit1_hours"],
        "manifest_schema": man["schema"],
        "manifest_composition": _canon(man["composition"]),
        "manifest_checks": _canon(man["checks"]),
        "manifest_modules": dict(man["modules"]),
    }


def extract(html_path: pathlib.Path) -> dict[str, Any]:
    raw = html_path.read_bytes()
    text = raw.decode("utf-8")
    pkg = package_from_html(text)
    return {
        "provenance": {
            "source_file": html_path.name,
            "source_file_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "recipient_scope": pkg["recipient_scope"],
            "algorithm_sha": pkg["algorithm_sha"],
            "as_of": pkg["as_of"],
            "locator": pkg["locator"],
            "extracted_by": "scripts/cost_package_identities.py",
        },
        "identities": identities(pkg),
        "sections": sections_from_html(text),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--html", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    fixture = extract(pathlib.Path(a.html))
    pathlib.Path(a.out).write_bytes(
        (json.dumps(fixture, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(json.dumps(fixture["provenance"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
