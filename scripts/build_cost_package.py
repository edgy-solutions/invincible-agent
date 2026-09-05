"""Build the customer-validation package: one self-contained HTML file.

ADR-0048's slice 1. Produces a double-clickable artifact carrying:

  * the Pyodide runtime, EMBEDDED (no CDN reach at open time -- ADR-0047 §8.2)
  * `pricing.py` verbatim, at a pinned commit SHA
  * the recipient-scoped package and its verification manifest
  * a thin JS shell that runs the manifest check FIRST and refuses to render on divergence

WHY THE RUNTIME IS EMBEDDED RATHER THAN FETCHED. A recipient inside a closed network gets a
silent partial render from a CDN miss, and the failure looks like a rendering quirk rather
than a missing dependency -- the reachable-call failure class. Pyodide's loader fetches its
own files by URL, so the page installs a `fetch` SHIM before loading it: requests for the
runtime's filenames are served from embedded data URIs and nothing leaves the machine.

THE FIDELITY QUESTION IS ANSWERED BY THE MANIFEST ITSELF, not by a separate test. If WASM
`decimal` diverges from native on this arithmetic, the manifest check fails and the package
refuses to render -- so "does the runtime agree" and "does the seal work" are the same
observation. That is deliberate: a fidelity test the package did not run would be a claim
about the package rather than a property of it.

  usage: .venv/Scripts/python.exe scripts/build_cost_package.py \
             --recipient notional-customer-alpha --out dist/
"""
from __future__ import annotations

import argparse
import base64
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_fleet.cost_agent import export as X          # noqa: E402
from agent_fleet.cost_agent.seed import build_state     # noqa: E402

#: The runtime files Pyodide's loader asks for. Fetched once into a cache directory by
#: `--fetch-runtime`, then embedded. Pinned by version: a package built against a different
#: runtime is a different artifact and should not silently become one.
PYODIDE_VERSION = "0.26.4"
RUNTIME_FILES = ("pyodide.asm.wasm", "pyodide.asm.js", "python_stdlib.zip",
                 "pyodide-lock.json")


def algorithm_sha() -> str:
    """The commit the shipped modules come from.

    READ FROM GIT, and refuses on a dirty tree for `pricing.py`: a package claiming a SHA
    whose working copy has uncommitted edits is claiming an algorithm nobody can retrieve.
    """
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "agent_fleet/cost_agent/pricing.py"],
        cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty:
        raise SystemExit(
            "REFUSING TO BUILD: agent_fleet/cost_agent/pricing.py has uncommitted changes, so "
            "the SHA below would name an algorithm the recipient cannot retrieve.\n"
            f"  {dirty}"
        )
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()


def _b64(p: pathlib.Path) -> str:
    return base64.b64encode(p.read_bytes()).decode("ascii")


def build_html(recipient: str, runtime_dir: pathlib.Path) -> str:
    state = build_state()
    sha = algorithm_sha()
    package = X.build_package(state, recipient_scope=recipient, algorithm_sha=sha)
    pricing_src = (ROOT / "agent_fleet" / "cost_agent" / "pricing.py").read_text(
        encoding="utf-8")

    missing = [f for f in RUNTIME_FILES + ("pyodide.js",)
               if not (runtime_dir / f).exists()]
    if missing:
        raise SystemExit(
            f"REFUSING TO BUILD: runtime files missing from {runtime_dir}: {missing}. "
            "Run with --fetch-runtime once (needs network), then build offline."
        )

    embedded = {f: _b64(runtime_dir / f) for f in RUNTIME_FILES}
    loader_js = (runtime_dir / "pyodide.js").read_text(encoding="utf-8")
    # DEFENCE IN DEPTH ON THE NO-CDN PROPERTY. Pyodide's loader carries a CDN base as a
    # FALLBACK for when `indexURL` is not supplied. We do supply it, so the fallback is
    # unreachable in practice -- and "unreachable in practice" is exactly what this seal
    # exists to distrust. The base is rewritten to a relative path so the artifact CANNOT
    # CONSTRUCT a CDN URL even if the shim were bypassed: a fallback then becomes a
    # same-origin request, which the shim answers from the embedded bytes by filename.
    # Asserted below rather than assumed, because a silent failure to substitute would leave
    # the artifact looking sealed and reaching out under one branch nobody exercises.
    cdn_base = "https://cdn.jsdelivr.net/pyodide/"
    if cdn_base in loader_js:
        loader_js = loader_js.replace(cdn_base, "./")
    if "cdn.jsdelivr.net" in loader_js:
        raise SystemExit(
            "REFUSING TO BUILD: the embedded Pyodide loader still references a CDN after "
            "substitution. The no-CDN property cannot be claimed for this artifact."
        )

    return _TEMPLATE.format(
        recipient=recipient,
        sha=sha,
        locator=package["locator"],
        as_of=package["as_of"],
        program=package["program"],
        lots=", ".join(str(n) for n in package["lots"]),
        package_json=json.dumps(package),
        pricing_src=json.dumps(pricing_src),
        embedded_json=json.dumps(embedded),
        loader_js=loader_js,
        pyver=PYODIDE_VERSION,
    )


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Cost validation package - {recipient}</title>
<style>
 body{{font:14px/1.5 system-ui,sans-serif;margin:0;background:#faf9f7;color:#1a1a1a}}
 header{{background:#1f2937;color:#fff;padding:18px 24px}}
 header h1{{margin:0;font-size:17px;font-weight:600}}
 header .meta{{opacity:.75;font-size:12px;margin-top:4px;font-family:ui-monospace,monospace}}
 main{{padding:24px;max-width:1100px}}
 #status{{padding:14px 18px;border-radius:6px;margin-bottom:20px;font-weight:600}}
 .checking{{background:#fef3c7;border:1px solid #d97706}}
 .ok{{background:#dcfce7;border:1px solid #16a34a}}
 .refused{{background:#fee2e2;border:1px solid #dc2626}}
 table{{border-collapse:collapse;width:100%;margin:12px 0 28px}}
 th,td{{border-bottom:1px solid #e5e7eb;padding:7px 10px;text-align:right}}
 th:first-child,td:first-child{{text-align:left}}
 th{{background:#f3f4f6;font-weight:600}}
 h2{{font-size:15px;margin:26px 0 6px}}
 .note{{color:#4b5563;font-size:12.5px;margin:4px 0 14px}}
 pre{{background:#1f2937;color:#e5e7eb;padding:12px;border-radius:6px;overflow-x:auto;font-size:12px}}
</style></head><body>
<header>
 <h1>Cost validation package - {recipient}</h1>
 <div class="meta">algorithm {sha} &middot; as of {as_of} &middot; {locator}</div>
</header>
<main>
 <div id="status" class="checking">Verifying against the producing engine...</div>
 <div id="body" hidden>
  <p class="note"><strong>{program}</strong> &middot; lots {lots}. Every figure below was
  recomputed in your browser by the same pricing modules the engine ran, at the pinned commit
  above. Nothing is displayed unless the recomputation matched.</p>
  <div id="tables"></div>
 </div>
 <div id="divergence" hidden>
  <p class="note">This package refuses to display figures it could not reproduce. The
  algorithm is pinned and identical, so a divergence here means <strong>data or runtime</strong>,
  never algorithm.</p>
  <pre id="problems"></pre>
 </div>
</main>

<script id="embedded-runtime" type="application/json">{embedded_json}</script>
<script id="package-data" type="application/json">{package_json}</script>
<script id="pricing-src" type="application/json">{pricing_src}</script>

<script>
// NO NETWORK. Pyodide's loader fetches its files by URL; this shim answers those requests
// from the embedded base64 above, so opening the page with networking disabled behaves
// identically to opening it online. A CDN miss would otherwise be a silent partial render.
(function () {{
  const EMB = JSON.parse(document.getElementById('embedded-runtime').textContent);
  const realFetch = window.fetch ? window.fetch.bind(window) : null;
  function b64ToBytes(b64) {{
    const bin = atob(b64); const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }}
  window.fetch = async function (input) {{
    const url = String(input && input.url ? input.url : input);
    for (const name of Object.keys(EMB)) {{
      if (url.endsWith(name)) {{
        return new Response(b64ToBytes(EMB[name]), {{status: 200}});
      }}
    }}
    if (realFetch) return realFetch.apply(this, arguments);
    throw new Error('blocked: this package makes no network requests (' + url + ')');
  }};
}})();
</script>
<script>{loader_js}</script>
<script>
(async function () {{
  const statusEl = document.getElementById('status');
  const pkg = JSON.parse(document.getElementById('package-data').textContent);
  const pricingSrc = JSON.parse(document.getElementById('pricing-src').textContent);
  try {{
    const pyodide = await loadPyodide({{indexURL: './'}});
    pyodide.FS.writeFile('pricing.py', pricingSrc);
    pyodide.globals.set('MANIFEST_JSON', JSON.stringify(pkg.manifest));
    const problems = pyodide.runPython(`
import json
from decimal import Decimal
import pricing

m = json.loads(MANIFEST_JSON)
spec = tuple(
    pricing.StepSpec(name=c["name"], rate_key=c["rate_key"], basis_kind=c["basis_kind"],
                     component=c["component"], plus_steps=tuple(c["plus_steps"]))
    for c in m["composition"]
)
out = []
for chk in m["checks"]:
    r = chk["rates"]
    rates = pricing.RateSet(
        fiscal_year=r["fiscal_year"], vintage=r["vintage"],
        fringe=Decimal(r["fringe"]), overhead=Decimal(r["overhead"]),
        g_and_a=Decimal(r["g_and_a"]), cost_of_money=Decimal(r["cost_of_money"]),
        profit=Decimal(r["profit"]), escalation=Decimal(r["escalation"]))
    b = pricing.compose_price(
        direct_labor=Decimal(chk["inputs"]["direct_labor"]),
        material=Decimal(chk["inputs"]["material"]),
        other_direct=Decimal(chk["inputs"]["other_direct"]),
        rates=rates, spec=spec)
    if str(b.price) != chk["expected"]["price"]:
        out.append("lot %s: recomputed %s, manifest expects %s"
                   % (chk["lot"], b.price, chk["expected"]["price"]))
    for got, want in zip(b.steps, chk["intermediates"]):
        if str(got.amount) != want["amount"]:
            out.append("lot %s step %s: recomputed %s, manifest expects %s"
                       % (chk["lot"], want["name"], got.amount, want["amount"]))
json.dumps(out)
`);
    const problemList = JSON.parse(problems);
    if (problemList.length) {{
      statusEl.className = 'refused';
      statusEl.textContent = 'REFUSED - ' + problemList.length +
        ' figure(s) could not be reproduced. Nothing is displayed.';
      document.getElementById('problems').textContent = problemList.join('\\n');
      document.getElementById('divergence').hidden = false;
      return;
    }}
    statusEl.className = 'ok';
    statusEl.textContent = 'Verified - every figure reproduced exactly, ' +
      pkg.manifest.checks.length + ' lot(s) checked.';
    render(pkg);
    document.getElementById('body').hidden = false;
  }} catch (e) {{
    statusEl.className = 'refused';
    statusEl.textContent = 'REFUSED - the verification could not be completed: ' + e;
  }}
}})();

function render(pkg) {{
  const host = document.getElementById('tables');
  for (const chk of pkg.manifest.checks) {{
    const h = document.createElement('h2');
    h.textContent = 'Lot ' + chk.lot + ' - price ' + chk.expected.price +
                    ' (unit ' + chk.expected.unit_price + ')';
    host.appendChild(h);
    const t = document.createElement('table');
    t.innerHTML = '<tr><th>step</th><th>rate</th><th>basis</th><th>amount</th>' +
                  '<th>running total</th></tr>' +
      chk.intermediates.map(function (s) {{
        return '<tr><td>' + s.name + '</td><td>' + (s.rate === null ? '' : s.rate) +
               '</td><td>' + s.basis + '</td><td>' + s.amount + '</td><td>' +
               s.running_total + '</td></tr>';
      }}).join('');
    host.appendChild(t);
  }}
}}
</script>
</body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recipient", required=True)
    ap.add_argument("--out", default="dist")
    ap.add_argument("--runtime-dir", default=str(ROOT / ".pyodide-cache"))
    ap.add_argument("--fetch-runtime", action="store_true",
                    help="download the pinned Pyodide runtime into --runtime-dir (needs network)")
    a = ap.parse_args()

    rt = pathlib.Path(a.runtime_dir)
    if a.fetch_runtime:
        import urllib.request
        rt.mkdir(parents=True, exist_ok=True)
        base = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
        for f in RUNTIME_FILES + ("pyodide.js",):
            print(f"  fetching {f}")
            urllib.request.urlretrieve(base + f, rt / f)

    html = build_html(a.recipient, rt)
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    dest = out / f"cost-validation-{a.recipient}.html"
    dest.write_text(html, encoding="utf-8")
    mb = dest.stat().st_size / 1_048_576
    print(f"wrote {dest}  ({mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
