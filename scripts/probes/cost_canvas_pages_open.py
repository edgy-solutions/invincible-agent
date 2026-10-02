"""Open canvas-composed cost pages in a real browser and report what each one rendered.

WHY A BROWSER. The page's JavaScript renders only the sections a package carries (`HAS`), and
the builder cuts the others out of the markup. A block that ran for a missing section would
write into an element that is not there, throw, and the page's own catch would replace
"Verified" with "REFUSED". Nothing short of executing the page can see that, so this probe
executes it: headless Edge, `--dump-dom`, and the status line and rendered ids read back.

    uv run --frozen --with duckdb python scripts/probes/cost_canvas_pages_open.py --out DIR

Writes one page per case into DIR (never into dist/, which the test suite rewrites), opens
each, and prints one line per case. Exit 1 if any page failed to verify or to render.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import build_cost_dataset as D  # noqa: E402
import build_cost_package as B  # noqa: E402
from agent_fleet.cost_agent import canvas as C  # noqa: E402
from agent_fleet.cost_agent.seed import build_state, lots_for_recipient  # noqa: E402

EDGE = pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

#: One element each section fills when it renders. Read back from the dumped DOM: present
#: AND non-empty means the section's block ran.
FILLED = {
    "labor": "metrics", "program": "program-chart", "composition": "composition",
    "sepm": "sepm-metrics", "material": "material-table", "scenario": "scenario-metrics",
}


def _filled(dom: str, el_id: str) -> bool | None:
    m = re.search(r'id="' + re.escape(el_id) + r'"[^>]*>(.*?)</', dom, re.S)
    if m is None:
        return None
    return bool(m.group(1).strip())


def open_page(page: pathlib.Path, profile: pathlib.Path) -> str:
    out = subprocess.run(
        [str(EDGE), "--headless=new", "--disable-gpu", "--no-first-run",
         f"--user-data-dir={profile}", "--virtual-time-budget=90000",
         "--dump-dom", page.resolve().as_uri()],
        capture_output=True, timeout=240)
    return out.stdout.decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--recipient", default="notional-customer-alpha")
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    state = build_state()
    entitled = lots_for_recipient(a.recipient)
    runtime = ROOT / ".pyodide-cache"

    cases = [("all", C.SECTIONS)] + [(s, (s,)) for s in C.SECTIONS]
    failed = 0
    for name, sections in cases:
        lots = entitled[:1] if name != "all" else entitled
        db = out / f"cost-{a.recipient}.duckdb"
        D.build(a.recipient, db, state=state, lots=lots)
        html = B.build_html(a.recipient, runtime, duckdb_path=db, state=state,
                            lots=lots, sections=sections, canvas_answers=[f"probe-{name}"])
        page = out / f"page-{name}.html"
        page.write_bytes(html.encode("utf-8"))
        dom = open_page(page, out / "profile")
        status = re.search(r'id="status"[^>]*>([^<]*)', dom)
        status = status.group(1) if status else "(no status element)"
        rendered = {s: _filled(dom, el) for s, el in FILLED.items()}
        want = {s: (True if s in sections else None) for s in C.SECTIONS}
        ok = status.startswith("Verified") and rendered == want
        failed += not ok
        print(json.dumps({"case": name, "ok": ok, "lots": list(lots), "status": status,
                          "rendered": rendered}))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
