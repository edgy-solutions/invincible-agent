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
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_fleet.cost_agent import export as X          # noqa: E402
from scripts.build_cost_dataset import build as build_dataset, file_hash  # noqa: E402
from scripts.labor_tab_template import TEMPLATE as SLICE2_TEMPLATE       # noqa: E402
from agent_fleet.cost_agent.seed import LEARNING_SLOPE, UNIT1_HOURS, build_state     # noqa: E402

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


def strip_sourcemaps(text: str) -> str:
    """Remove `//# sourceMappingURL=` from embedded runtime JS.

    Pyodide ships one pointing at `pyodide.js.map`, which is not embedded. The browser resolves
    it against the page and issues a fetch that fails. It is not a CDN call and it costs
    nothing, but the no-external-reference seal matches on `https?://` and would never have
    seen it — so the artifact carried a reference the seal was not looking for.

    A package whose claim is "everything it needs is inside it" should not emit a request for
    something that is not.
    """
    return re.sub(r"(?m)^[ 	]*//[#@] source(Mapping)?URL=.*$", "", text)


def check_javascript(html: str) -> list[str]:
    """Parse every inline script in the built page. REFUSES THE BUILD on a syntax error.

    A JS syntax error takes the whole page down — no verification banner, no refusal, no
    figures, just a blank body and a line number in a console the recipient will not open. It
    is the one failure mode that defeats every other seal at once, and nothing in the suite
    could see it: the seals test Python, and the page's Python is fine.

    WHAT GOT THROUGH: `src.split('\n')`. This template is itself a Python triple-quoted
    string, so the escape collapsed into a REAL newline inside a JS string literal. Structural
    checks passed, 90 seals passed, and the artifact was dead on open.

    Skipped, loudly, when node is unavailable — a check that quietly does nothing is worse
    than one that is absent.
    """
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        print("  WARNING: node not found - the page's JavaScript was NOT parsed")
        return []
    problems = []
    # MATCH EVERY SCRIPT, THEN SKIP THE TYPED ONES IN PYTHON. The first version excluded
    # them with a negative lookahead containing a word-boundary escape, which reached this
    # file as a literal BACKSPACE byte (0x08). The lookahead could never fire, so the
    # checker fed 17 MB of base64 to node as JavaScript and reported three failures that
    # were entirely its own. A filter that is wrong in the permissive direction does not
    # look wrong - it looks like a finding.
    for i, m in enumerate(re.finditer(r"<script([^>]*)>(.*?)</script>", html, re.S)):
        if "type=" in m.group(1):
            continue
        body = m.group(2)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(body)
            tmp = fh.name
        try:
            r = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
            if r.returncode != 0:
                # ANCHOR THE MATCH AT LINE START and cap it. node echoes the offending
                # source line first, and here that line is an entire embedded module — a
                # substring test for 'Error' picked `except ImportError:` out of the echo
                # and reported 52 KB of Python as the JavaScript diagnostic.
                err = re.search(r"(?m)^\w*Error: .*$", r.stderr)
                detail = err.group(0)[:180] if err else r.stderr.strip()[-180:]
                line = html[:m.start(2)].count(chr(10)) + 1
                problems.append(f"inline script #{i + 1} (page line ~{line}): {detail}")
        finally:
            pathlib.Path(tmp).unlink(missing_ok=True)
    return problems


def _b64(p: pathlib.Path) -> str:
    raw = p.read_bytes()
    if p.suffix == ".js":
        # STRIP BEFORE EMBEDDING, for the base64'd runtime too — not only the loader. Both
        # carry source-map comments, and a package that emits a request for a file it does not
        # contain has not delivered on "everything is inside it".
        raw = strip_sourcemaps(raw.decode("utf-8")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def build_html(recipient: str, runtime_dir: pathlib.Path,
               duckdb_path: pathlib.Path | None = None) -> str:
    state = build_state()
    sha = algorithm_sha()
    if duckdb_path is None:
        package = X.build_package(state, recipient_scope=recipient, algorithm_sha=sha)
    else:
        # SLICE 2. The .duckdb ships BESIDE this file; the page embeds the same rows and the
        # manifest carries both hashes, so a recipient holding only the HTML still gets a
        # verifying page and one holding both can prove the file matches what the page
        # computed from. duckdb-wasm is deliberately absent — 34 MB, and its reader returns
        # DECIMAL as an unscaled BigInt (measured: every value exactly 100x).
        package = X.build_dataset_package(
            state, recipient_scope=recipient, algorithm_sha=sha,
            duckdb_path=str(duckdb_path), duckdb_hash=file_hash(duckdb_path))
        # FROM THE ENGINE, NOT A LITERAL. This read `"0.92"` and meant "the field's default",
        # while the page treated it as "the scenario's identity point" — two meanings for one
        # number, and the untouched scenario came out $732k below the baseline it sat next to.
        # The curve (slope + first-unit hours) is set by build_dataset_package, not here —
        # assigning it after the fact is what let a package exist without it.
        drift = X.datasets_agree(package["dataset"]["rows"], str(duckdb_path))
        if drift:
            raise SystemExit(
                "REFUSING TO BUILD: the embedded rows and the .duckdb hold different "
                "tables, so the page would verify against data the shipped file does "
                "not contain -- " + "; ".join(drift[:6]))
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
    loader_js = strip_sourcemaps(
        (runtime_dir / "pyodide.js").read_text(encoding="utf-8"))
    # DEFENSE IN DEPTH ON THE NO-CDN PROPERTY. Pyodide's loader carries a CDN base as a
    # FALLBACK for when `indexURL` is not supplied. We do supply it, so the fallback is
    # unreachable in practice -- and "unreachable in practice" is exactly what this seal
    # exists to distrust. The base is rewritten to a relative path so the artifact CANNOT
    # CONSTRUCT a CDN URL even if the shim were bypassed: a fallback then becomes a
    # same-origin request, which the shim answers from the embedded bytes by filename.
    # Asserted below rather than assumed, because a silent failure to substitute would leave
    # the artifact looking sealed and reaching out under one branch nobody exercises.
    # THE DYNAMIC-IMPORT HOLE, found by opening the file rather than by any seal here.
    # Pyodide loads `pyodide.asm.js` with `await import(url)`. A `fetch` shim CANNOT intercept
    # an ES module import — the browser's module loader does not route through window.fetch —
    # so the first build embedded every runtime file, passed a structural no-CDN check, and
    # then failed at open with "error loading dynamically imported module". The .wasm and the
    # stdlib go through fetch and were fine; only the module import escaped.
    #
    # The fix has to give `import()` something it will accept, which means a real URL: the
    # shim now publishes embedded JS as BLOB URLs and the loader's browser branch is rewritten
    # to resolve through it. Asserted below, because a substitution that silently did not
    # match would restore exactly the artifact that looked sealed and could not run.
    import_branch = 'I=c(async e=>await import(/* webpackIgnore */e),"loadScript")'
    if import_branch not in loader_js:
        raise SystemExit(
            "REFUSING TO BUILD: the Pyodide loader's dynamic-import branch was not found, so "
            "the embedded-module patch cannot be applied. This artifact would embed the "
            "runtime, pass a structural no-CDN check, and fail to load at open — the exact "
            f"defect this substitution exists to prevent. Pinned version {PYODIDE_VERSION}."
        )
    loader_js = loader_js.replace(
        import_branch,
        'I=c(async e=>await import(globalThis.__embeddedModuleURL(e)),"loadScript")',
    )

    # The WORKER branch carries its own bare import as an importScripts fallback. It does not
    # execute on a main-thread page load, and "does not execute here" is the reasoning this
    # build already refused to accept for the CDN base — so it gets the same treatment rather
    # than a caveat. After this, the artifact contains NO bare dynamic import at all, and the
    # seal below can assert that flatly instead of excepting a branch.
    worker_branch = "await import(/* webpackIgnore */e);else throw t"
    if worker_branch in loader_js:
        loader_js = loader_js.replace(
            worker_branch,
            "await import(globalThis.__embeddedModuleURL(e));else throw t",
        )

    cdn_base = "https://cdn.jsdelivr.net/pyodide/"
    if cdn_base in loader_js:
        loader_js = loader_js.replace(cdn_base, "./")
    if "cdn.jsdelivr.net" in loader_js:
        raise SystemExit(
            "REFUSING TO BUILD: the embedded Pyodide loader still references a CDN after "
            "substitution. The no-CDN property cannot be claimed for this artifact."
        )

    tmpl = SLICE2_TEMPLATE if duckdb_path is not None else _TEMPLATE
    if duckdb_path is not None:
        page_src = (ROOT / "agent_fleet" / "cost_agent" / "page.py").read_text(encoding="utf-8")
        return tmpl.format(
            recipient=recipient, sha=sha, locator=package["locator"],
            as_of=package["as_of"], program=package["program"],
            lots=", ".join(str(n) for n in package["lots"]),
            duckdb_filename=package["dataset"]["duckdb_filename"],
            duckdb_hash=package["dataset"]["duckdb_sha256"],
            package_json=json.dumps(package),
            pricing_src=json.dumps(pricing_src),
            embedded_json=json.dumps(embedded),
            loader_js=loader_js, pyver=PYODIDE_VERSION,
        ).replace("PAGE_PY", json.dumps(page_src), 1)
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
  const MIME = {{
    'pyodide.asm.wasm': 'application/wasm',
    'pyodide.asm.js': 'text/javascript',
    'pyodide-lock.json': 'application/json',
    'python_stdlib.zip': 'application/octet-stream',
  }};
  const realFetch = window.fetch ? window.fetch.bind(window) : null;
  function b64ToBytes(b64) {{
    const bin = atob(b64); const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }}
  // Dynamic `import()` cannot be shimmed, so embedded JS is published as a BLOB URL and the
  // loader is rewritten to ask for it by name. Cached so repeated asks give one object URL.
  const BLOBS = {{}};
  globalThis.__embeddedModuleURL = function (url) {{
    const u = String(url);
    for (const name of Object.keys(EMB)) {{
      if (u.endsWith(name) && name.endsWith('.js')) {{
        if (!BLOBS[name]) {{
          BLOBS[name] = URL.createObjectURL(
            new Blob([b64ToBytes(EMB[name])], {{type: 'text/javascript'}}));
        }}
        return BLOBS[name];
      }}
    }}
    return u;
  }};
  window.fetch = async function (input) {{
    const url = String(input && input.url ? input.url : input);
    for (const name of Object.keys(EMB)) {{
      if (url.endsWith(name)) {{
        // THE MIME TYPE IS LOAD-BEARING, not politeness. WebAssembly's streaming
        // instantiation REFUSES a response whose Content-Type is not application/wasm --
        // "Response has unsupported MIME type '' expected 'application/wasm'". A shim that
        // returns the right BYTES with no type produces a runtime that loads its loader,
        // fetches its wasm, and then refuses to instantiate it.
        return new Response(b64ToBytes(EMB[name]), {{
          status: 200,
          headers: {{'Content-Type': MIME[name] || 'application/octet-stream'}},
        }});
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
    ap.add_argument("--out-dir", "--out", dest="out_dir", default="dist",
                    help="DIRECTORY the package is written into (note: build_cost_dataset.py's --out is a FILE)")
    ap.add_argument("--runtime-dir", default=str(ROOT / ".pyodide-cache"))
    ap.add_argument("--corrupt-intermediate", action="store_true",
                    help=("DEMO ONLY: corrupt one embedded intermediate so the package "
                          "refuses to render. ADR-0048 §6's trust beat — hand it to someone "
                          "and let them watch it refuse. Output is named -CORRUPTED so it "
                          "cannot be mistaken for a real package."))
    ap.add_argument("--with-dataset", action="store_true",
                    help="slice 2: also build the .duckdb and embed its rows")
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

    db = None
    if a.with_dataset:
        db = pathlib.Path(a.out_dir) / f"cost-{a.recipient}.duckdb"
        build_dataset(a.recipient, db)
    html = build_html(a.recipient, rt, db)
    suffix = ""
    if a.corrupt_intermediate:
        # Alter ONE intermediate in the embedded manifest, leaving everything else — the
        # pinned modules, the inputs, the other figures — untouched. The recipient's browser
        # recomputes it, disagrees, and the package refuses. This is the demonstration ADR-0048
        # §6 scripts, and it costs one byte.
        import re as _re
        m = _re.search(r'id="package-data" type="application/json">(.*?)</script>', html, _re.S)
        pkg = json.loads(m.group(1))
        victim = pkg["manifest"]["checks"][2]["intermediates"][1]
        original = victim["amount"]
        victim["amount"] = "999999.99"
        html = html[:m.start(1)] + json.dumps(pkg) + html[m.end(1):]
        suffix = "-CORRUPTED"
        print(f"  corrupted lot {pkg['manifest']['checks'][2]['lot']} step "
              f"{victim['name']!r}: {original} -> {victim['amount']}")
    out = pathlib.Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    dest = out / f"cost-validation-{a.recipient}{suffix}.html"
    js_problems = check_javascript(html)
    if js_problems:
        raise SystemExit(
            "REFUSING TO WRITE: the page's JavaScript does not parse."
            + chr(10) + "  " + (chr(10) + "  ").join(js_problems))
    dest.write_text(html, encoding="utf-8")
    mb = dest.stat().st_size / 1_048_576
    print(f"wrote {dest}  ({mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
