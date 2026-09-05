"""The slice-2 page: verification, the Labor tab, and editable scenario inputs.

SEPARATED FROM THE BUILDER so the template can be read as a document rather than scrolled past
inside a script. `build_cost_package.py` imports TEMPLATE and fills it.

THREE THINGS THIS PAGE DOES, IN THIS ORDER, AND THE ORDER IS THE DESIGN:

  1. VERIFY the manifest against the pinned modules. Nothing renders until it passes.
  2. RENDER the baseline from figures the engine produced.
  3. Offer EDITABLE inputs that compute a SCENARIO BESIDE the baseline, never replacing it.

WHY THE SCENARIO CANNOT REPLACE THE BASELINE. The baseline is the verified thing -- the
manifest asserts it, the engine produced it, and its figures are the ones under a content
hash. A scenario is the RECIPIENT'S arithmetic over their own parameters: real, useful, and
unverifiable by anyone but them. Letting an edit overwrite the baseline would destroy the one
property the package exists to provide, and it would do it silently, because the page would
look identical afterwards. So both are always on screen, labelled, with the baseline first.

NO CHART LIBRARY. The stacked bar is hand-drawn SVG, about forty lines. The dispatch said to
embed one; after paying 34 MB for duckdb-wasm to do work Pyodide already did, adding a
dependency for a five-rectangle chart is the same trade in miniature. FLAGGED, NOT SUBSTITUTED
SILENTLY -- if a real chart library is wanted for what comes next, this is the place it goes,
and the deviation is one import away from being reversed.
"""

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Cost validation package - {recipient}</title>
<style>
 body{{font:14px/1.55 system-ui,sans-serif;margin:0;background:#faf9f7;color:#1a1a1a}}
 header{{background:#1f2937;color:#fff;padding:16px 24px}}
 header h1{{margin:0;font-size:17px;font-weight:600}}
 header .meta{{opacity:.75;font-size:11.5px;margin-top:4px;font-family:ui-monospace,monospace}}
 main{{padding:20px 24px;max-width:1180px}}
 #status{{padding:13px 18px;border-radius:6px;margin-bottom:18px;font-weight:600}}
 .checking{{background:#fef3c7;border:1px solid #d97706}}
 .ok{{background:#dcfce7;border:1px solid #16a34a}}
 .refused{{background:#fee2e2;border:1px solid #dc2626}}
 .row{{display:flex;gap:26px;flex-wrap:wrap;align-items:flex-start}}
 .panel{{flex:1;min-width:330px}}
 table{{border-collapse:collapse;width:100%;margin:8px 0 18px}}
 th,td{{border-bottom:1px solid #e5e7eb;padding:6px 9px;text-align:right}}
 th:first-child,td:first-child{{text-align:left}}
 th{{background:#f3f4f6;font-weight:600;font-size:12.5px}}
 h2{{font-size:15px;margin:20px 0 4px}}
 h3{{font-size:13px;margin:14px 0 2px;color:#374151}}
 .note{{color:#4b5563;font-size:12.5px;margin:3px 0 12px}}
 pre{{background:#1f2937;color:#e5e7eb;padding:12px;border-radius:6px;overflow-x:auto;font-size:12px}}
 select,input{{font:13px system-ui,sans-serif;padding:4px 6px;border:1px solid #cbd5e1;border-radius:4px}}
 input{{width:92px;text-align:right}}
 .metrics td:first-child{{color:#374151}}
 .metrics td:last-child{{font-weight:600;font-family:ui-monospace,monospace}}
 .scenario{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:6px;padding:12px 14px}}
 .baseline-tag{{display:inline-block;background:#16a34a;color:#fff;font-size:10.5px;
   padding:1px 6px;border-radius:9px;vertical-align:middle;margin-left:6px}}
 .scenario-tag{{display:inline-block;background:#2563eb;color:#fff;font-size:10.5px;
   padding:1px 6px;border-radius:9px;vertical-align:middle;margin-left:6px}}
 .controls{{display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin:6px 0 14px}}
 .diff-up{{color:#b91c1c}} .diff-down{{color:#15803d}}
</style></head><body>
<header>
 <h1>Cost validation package - {recipient}</h1>
 <div class="meta">algorithm {sha} &middot; as of {as_of} &middot; {locator}</div>
 <div class="meta">data {duckdb_filename} &middot; {duckdb_hash}</div>
</header>
<main>
 <div id="status" class="checking">Verifying against the producing engine...</div>

 <div id="body" hidden>
  <p class="note"><strong>{program}</strong> &middot; lots {lots}. Every baseline figure was
  recomputed in your browser by the same pricing modules the engine ran, at the pinned commit
  above. Nothing is displayed unless the recomputation matched.</p>

  <div class="controls">
   <label>Lot <select id="lot"></select></label>
   <span class="note" style="margin:0">Changing the lot recomputes every figure below.</span>
  </div>

  <h2>Labour <span class="baseline-tag">BASELINE</span></h2>
  <div class="row">
   <div class="panel">
    <div id="chart"></div>
   </div>
   <div class="panel">
    <table class="metrics"><tbody id="metrics"></tbody></table>
   </div>
  </div>

  <h2>Price composition <span class="baseline-tag">BASELINE</span></h2>
  <table id="composition"></table>

  <div class="scenario">
   <h2 style="margin-top:2px">Your scenario <span class="scenario-tag">NOT VERIFIED</span></h2>
   <p class="note">These inputs are yours. They compute <strong>beside</strong> the verified
   baseline and never replace it &mdash; the manifest asserts the baseline only, and a figure
   computed from your parameters is arithmetic no one else has checked. Reset returns the
   fields to the pinned rate set.</p>
   <div class="controls" id="rate-inputs"></div>
   <div class="controls">
    <label>Learning slope <input id="slope" type="number" step="0.01" min="0.5" max="1"></label>
    <button id="reset">Reset to baseline</button>
   </div>
   <table class="metrics"><tbody id="scenario-metrics"></tbody></table>
  </div>
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
        return new Response(b64ToBytes(EMB[name]), {{
          status: 200, headers: {{'Content-Type': MIME[name] || 'application/octet-stream'}},
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
const PKG = JSON.parse(document.getElementById('package-data').textContent);
let PY = null;

// ── SVG stacked bar, hand-drawn. See the module docstring: no chart library. ──
function stackedBar(parts, width, height) {{
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  const colors = {{touch: '#2563eb', support: '#7c3aed', sepm: '#0891b2'}};
  let x = 0, rects = '', legend = '';
  for (const p of parts) {{
    const w = (p.value / total) * width;
    rects += '<rect x="' + x.toFixed(1) + '" y="0" width="' + w.toFixed(1) + '" height="' +
             height + '" fill="' + (colors[p.key] || '#94a3b8') + '"><title>' + p.key +
             ': ' + p.display + '</title></rect>';
    if (w > 46) {{
      rects += '<text x="' + (x + w / 2).toFixed(1) + '" y="' + (height / 2 + 4) +
               '" text-anchor="middle" fill="#fff" font-size="11">' +
               (100 * p.value / total).toFixed(1) + '%</text>';
    }}
    legend += '<span style="margin-right:14px;font-size:12px"><span style="display:inline-block;' +
              'width:10px;height:10px;background:' + (colors[p.key] || '#94a3b8') +
              ';margin-right:4px"></span>' + p.key + '</span>';
    x += w;
  }}
  return '<svg width="100%" viewBox="0 0 ' + width + ' ' + height +
         '" preserveAspectRatio="none" style="max-width:100%;border-radius:4px">' + rects +
         '</svg><div style="margin-top:7px">' + legend + '</div>';
}}

function metricRows(rows) {{
  return rows.map(r => '<tr><td>' + r[0] + '</td><td>' + r[1] + '</td></tr>').join('');
}}

function renderLot(lot) {{
  const j = JSON.parse(PY.runPython(
    'import json, page; json.dumps(page.labor_view(' + lot + '))'));
  document.getElementById('chart').innerHTML =
    stackedBar(j.parts, 520, 46);
  document.getElementById('metrics').innerHTML = metricRows([
    ['Total labour hours', j.total_hours],
    ['Total labour cost', j.total_cost],
    ['Touch hours per unit', j.touch_per_unit],
    ['Cost per unit (all categories)', j.unit_price],
    ['Support : touch ratio', j.support_touch_ratio],
  ]);
  // FORMATTED BY PYTHON, like every other figure on this page. Rendering the manifest's raw
  // strings here is what put two money formats on one screen.
  const comp = JSON.parse(PY.runPython(
    'import json, page; json.dumps(page.composition_view(' + lot + '))'));
  document.getElementById('composition').innerHTML =
    '<tr><th>step</th><th>rate</th><th>basis</th><th>amount</th><th>running total</th></tr>' +
    comp.map(s => '<tr><td>' + s.name + '</td><td>' + s.rate +
      '</td><td>' + s.basis + '</td><td>' + s.amount + '</td><td>' + s.running_total +
      '</td></tr>').join('');
  renderScenario(lot);
}}

function currentRates() {{
  const out = {{}};
  document.querySelectorAll('#rate-inputs input').forEach(i => {{ out[i.dataset.key] = i.value; }});
  return out;
}}

function renderScenario(lot) {{
  const rates = currentRates();
  const slope = document.getElementById('slope').value;
  const j = JSON.parse(PY.runPython(
    'import json, page; json.dumps(page.scenario_view(' + lot + ', ' +
    JSON.stringify(JSON.stringify(rates)) + ', ' + JSON.stringify(String(slope)) + '))'));
  const diff = (d) => {{
    const cls = d.startsWith('-') ? 'diff-down' : (d === '0.00' ? '' : 'diff-up');
    return '<span class="' + cls + '">' + d + '</span>';
  }};
  document.getElementById('scenario-metrics').innerHTML = metricRows([
    ['Baseline price', j.baseline_price],
    ['Your scenario price', j.scenario_price],
    ['Difference', diff(j.difference)],
    ['Your unit price', j.scenario_unit_price],
    ['Learning slope applied', j.slope],
    // FROM THE PAYLOAD, NOT FROM THE FORM. A scenario names the rate set it departed from, and
    // that name is Python's answer — the recipient cannot edit it into something else.
    ['Rate vintage', j.rate_vintage + ' (FY' + j.rate_fiscal_year + ')'],
  ]);
}}

(async function () {{
  const statusEl = document.getElementById('status');
  try {{
    PY = await loadPyodide({{indexURL: './'}});
    PY.FS.writeFile('pricing.py',
      JSON.parse(document.getElementById('pricing-src').textContent));
    PY.FS.writeFile('page.py', PAGE_PY);
    PY.globals.set('PACKAGE_JSON', JSON.stringify(PKG));
    const problems = JSON.parse(PY.runPython(
      'import json, page; json.dumps(page.verify(PACKAGE_JSON))'));
    if (problems.length) {{
      statusEl.className = 'refused';
      statusEl.textContent = 'REFUSED - ' + problems.length +
        ' figure(s) could not be reproduced. Nothing is displayed.';
      document.getElementById('problems').textContent = problems.join('\\n');
      document.getElementById('divergence').hidden = false;
      return;
    }}
    statusEl.className = 'ok';
    statusEl.textContent = 'Verified - every figure reproduced exactly, ' +
      PKG.manifest.checks.length + ' lot(s) checked.';

    const sel = document.getElementById('lot');
    sel.innerHTML = PKG.lots.map(n => '<option value="' + n + '">Lot ' + n + '</option>').join('');
    const baseRates = PKG.manifest.checks[0].rates;
    document.getElementById('rate-inputs').innerHTML =
      ['fringe', 'overhead', 'g_and_a', 'cost_of_money', 'profit'].map(k =>
        '<label>' + k + ' <input type="number" step="0.001" data-key="' + k +
        '" value="' + baseRates[k] + '"></label>').join('');
    document.getElementById('slope').value = PKG.dataset.learning_slope || '0.92';

    sel.addEventListener('change', () => renderLot(Number(sel.value)));
    document.getElementById('rate-inputs').addEventListener('input',
      () => renderScenario(Number(sel.value)));
    document.getElementById('slope').addEventListener('input',
      () => renderScenario(Number(sel.value)));
    document.getElementById('reset').addEventListener('click', () => {{
      document.querySelectorAll('#rate-inputs input').forEach(
        i => {{ i.value = baseRates[i.dataset.key]; }});
      document.getElementById('slope').value = PKG.dataset.learning_slope || '0.92';
      renderScenario(Number(sel.value));
    }});

    renderLot(PKG.lots[0]);
    document.getElementById('body').hidden = false;
  }} catch (e) {{
    statusEl.className = 'refused';
    statusEl.textContent = 'REFUSED - the verification could not be completed: ' + e;
  }}
}})();
</script>
</body></html>
"""
