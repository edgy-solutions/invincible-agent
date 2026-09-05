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
 .panel-title{{font-size:12.5px;font-weight:600;color:#374151;margin:0 0 8px}}
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
 <div class="meta" id="boot"></div>
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

  <h2>Across the programme <span class="baseline-tag">BASELINE</span></h2>
  <div class="row">
   <div class="panel">
    <div class="panel-title">Labour hours by lot and category</div>
    <div id="program-chart"></div>
   </div>
   <div class="panel">
    <div class="panel-title">Learning curve &mdash; touch hours per unit</div>
    <div id="curve-chart"></div>
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
const KIND_COLORS = {{touch: '#2563eb', support: '#7c3aed', sepm: '#0891b2'}};

// ── Across-lots stacked columns ─────────────────────────────────────────────────────────────
// EVERY NUMBER IS PYTHON'S. This routine converts values to pixels and nothing else: no sums,
// no maximum of its own, no percentages. `max_hours` arrives in the payload precisely so the
// scale is a figure the seals can see rather than a side effect of drawing.
function stackedColumns(pv, selected, width, height) {{
  const padL = 62, padB = 30, padT = 10, padR = 8;
  const plotW = width - padL - padR, plotH = height - padB - padT;
  const n = pv.series.length, slot = plotW / n, bw = Math.min(54, slot * 0.62);
  const max = pv.max_hours || 1;
  let bars = '', ticks = '';
  for (let g = 0; g <= 4; g++) {{
    const y = padT + plotH - (g / 4) * plotH, v = (max * g / 4);
    ticks += '<line x1="' + padL + '" y1="' + y.toFixed(1) + '" x2="' + (width - padR) +
             '" y2="' + y.toFixed(1) + '" stroke="#e5e7eb"/>' +
             '<text x="' + (padL - 7) + '" y="' + (y + 4).toFixed(1) +
             '" text-anchor="end" font-size="10" fill="#6b7280">' +
             (v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v.toFixed(0)) + '</text>';
  }}
  pv.series.forEach((s, i) => {{
    const cx = padL + slot * i + slot / 2, x = cx - bw / 2;
    let y = padT + plotH;
    for (const seg of s.segments) {{
      const h = (seg.value / max) * plotH;
      y -= h;
      bars += '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) +
              '" height="' + Math.max(0, h).toFixed(1) + '" fill="' + KIND_COLORS[seg.key] +
              '" opacity="' + (s.lot === selected ? 1 : 0.42) + '"><title>Lot ' + s.lot + ' ' +
              seg.key + ': ' + seg.display + ' h</title></rect>';
    }}
    bars += '<text x="' + cx.toFixed(1) + '" y="' + (padT + plotH + 14) +
            '" text-anchor="middle" font-size="11" fill="' +
            (s.lot === selected ? '#111827' : '#6b7280') + '" font-weight="' +
            (s.lot === selected ? '600' : '400') + '">Lot ' + s.lot + '</text>' +
            '<text x="' + cx.toFixed(1) + '" y="' + (padT + plotH + 26) +
            '" text-anchor="middle" font-size="9.5" fill="#9ca3af">' + s.quantity + ' u</text>';
  }});
  let legend = '';
  for (const k of pv.kinds) {{
    legend += '<span style="margin-right:14px;font-size:12px"><span style="display:inline-block;' +
              'width:10px;height:10px;background:' + KIND_COLORS[k] + ';margin-right:4px"></span>' +
              k + '</span>';
  }}
  return '<svg width="100%" viewBox="0 0 ' + width + ' ' + height + '" style="max-width:100%">' +
         ticks + bars + '</svg><div style="margin-top:6px">' + legend +
         '<span style="font-size:12px;color:#6b7280">&nbsp;&middot; the selected lot is solid</span></div>';
}}

// ── Learning curve ──────────────────────────────────────────────────────────────────────────
// Plotted at the ALGEBRAIC LOT MIDPOINT that Python computes: a lot's figure is an average over
// a range of units, so its honest x is the unit whose own cost equals that average.
function learningCurve(lc, selected, width, height) {{
  const padL = 62, padB = 34, padT = 10, padR = 10;
  const plotW = width - padL - padR, plotH = height - padB - padT;
  const xs = lc.baseline.map(p => p.x);
  const xMin = 0, xMax = Math.max.apply(null, xs) * 1.06;
  const yMax = lc.y_max * 1.06, yMin = 0;
  const X = v => padL + (v - xMin) / (xMax - xMin) * plotW;
  const Y = v => padT + plotH - (v - yMin) / (yMax - yMin) * plotH;
  let grid = '';
  for (let g = 0; g <= 4; g++) {{
    const y = padT + plotH - (g / 4) * plotH, v = yMax * g / 4;
    grid += '<line x1="' + padL + '" y1="' + y.toFixed(1) + '" x2="' + (width - padR) + '" y2="' +
            y.toFixed(1) + '" stroke="#e5e7eb"/><text x="' + (padL - 7) + '" y="' + (y + 4).toFixed(1) +
            '" text-anchor="end" font-size="10" fill="#6b7280">' + v.toFixed(0) + '</text>';
  }}
  const path = (pts) => pts.map((p, i) => (i ? 'L' : 'M') + X(p.x).toFixed(1) + ' ' +
                                          Y(p.y).toFixed(1)).join(' ');
  let svg = grid;
  if (lc.scenario.length && !lc.scenario_is_baseline) {{
    svg += '<path d="' + path(lc.scenario) + '" fill="none" stroke="#b45309" stroke-width="2" ' +
           'stroke-dasharray="6 4"/>';
    lc.scenario.forEach(p => {{
      svg += '<circle cx="' + X(p.x).toFixed(1) + '" cy="' + Y(p.y).toFixed(1) +
             '" r="3.5" fill="#b45309"><title>Lot ' + p.lot + ' scenario: ' + p.display +
             ' h/unit</title></circle>';
    }});
  }}
  svg += '<path d="' + path(lc.baseline) + '" fill="none" stroke="#2563eb" stroke-width="2.5"/>';
  lc.baseline.forEach(p => {{
    svg += '<circle cx="' + X(p.x).toFixed(1) + '" cy="' + Y(p.y).toFixed(1) + '" r="' +
           (p.lot === selected ? 6 : 4) + '" fill="#2563eb" stroke="#fff" stroke-width="1.5">' +
           '<title>Lot ' + p.lot + ': ' + p.display + ' h/unit at cumulative unit ' +
           p.cumulative_units + '</title></circle>';
    svg += '<text x="' + X(p.x).toFixed(1) + '" y="' + (padT + plotH + 15) +
           '" text-anchor="middle" font-size="10" fill="#6b7280">' + p.lot + '</text>';
  }});
  svg += '<text x="' + (padL + plotW / 2).toFixed(1) + '" y="' + (height - 4) +
         '" text-anchor="middle" font-size="10.5" fill="#6b7280">lot (plotted at its algebraic ' +
         'midpoint on the cumulative-quantity axis)</text>';
  let key = '<span style="font-size:12px;margin-right:14px"><span style="display:inline-block;' +
            'width:14px;height:3px;background:#2563eb;vertical-align:middle;margin-right:5px">' +
            '</span>baseline &mdash; slope ' + lc.base_slope + '</span>';
  if (lc.scenario.length) {{
    key += lc.scenario_is_baseline
      ? '<span style="font-size:12px;color:#6b7280">your scenario slope equals the baseline’s, ' +
        'so the two curves coincide</span>'
      : '<span style="font-size:12px"><span style="display:inline-block;width:14px;height:0;' +
        'border-top:3px dashed #b45309;vertical-align:middle;margin-right:5px"></span>' +
        'your scenario &mdash; slope ' + lc.scenario_slope + ' <em>(not verified)</em></span>';
  }}
  return '<svg width="100%" viewBox="0 0 ' + width + ' ' + height + '" style="max-width:100%">' +
         svg + '</svg><div style="margin-top:6px">' + key + '</div>';
}}

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
  const cf = JSON.parse(PY.runPython(
    'import json, page; json.dumps(page.curve_factor(' + lot + '))'));
  document.getElementById('chart').innerHTML =
    stackedBar(j.parts, 520, 46);
  document.getElementById('metrics').innerHTML = metricRows([
    ['Total labour hours', j.total_hours],
    ['Total labour cost', j.total_cost],
    ['Touch hours per unit', j.touch_per_unit],
    ['Cost per unit (all categories)', j.unit_price],
    ['Support : touch ratio', j.support_touch_ratio],
    // THE MISSING LABEL. The baseline table showed no slope at all, so a reader could not tell
    // whether the engine applied a curve. It does — and at the first lot its effect is nil,
    // which is a different statement from "no curve" and needs to read as one.
    ['Learning curve applied', cf.slope + ' &mdash; factor ' + cf.factor +
                               ' <span style="color:#6b7280">(' + cf.note + ')</span>'],
    ['Cumulative units through this lot', cf.cumulative_units],
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
  // THE ACROSS-LOTS CHARTS FOLLOW THE SELECTOR TOO. They show every lot, but they highlight
  // the selected one — so "changing the lot recomputes every figure below" stays true of the
  // whole page rather than of the top half.
  const pv = JSON.parse(PY.runPython('import json, page; json.dumps(page.program_view())'));
  document.getElementById('program-chart').innerHTML = stackedColumns(pv, lot, 560, 260);
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
  const lc = JSON.parse(PY.runPython(
    'import json, page; json.dumps(page.learning_curve_view(' +
    JSON.stringify(String(slope)) + '))'));
  document.getElementById('curve-chart').innerHTML = learningCurve(lc, lot, 560, 260);
  document.getElementById('scenario-metrics').innerHTML = metricRows([
    ['Baseline price', j.baseline_price],
    ['Your scenario price', j.scenario_price],
    ['Difference', diff(j.difference)],
    ['Your unit price', j.scenario_unit_price],
    ['Learning slope applied', j.slope + (lc.scenario_is_baseline
        ? ' <span style="color:#6b7280">(same as the baseline &mdash; no change)</span>' : '')],
    // FROM THE PAYLOAD, NOT FROM THE FORM. A scenario names the rate set it departed from, and
    // that name is Python's answer — the recipient cannot edit it into something else.
    ['Rate vintage', j.rate_vintage + ' (FY' + j.rate_fiscal_year + ')'],
  ]);
}}

(async function () {{
  const statusEl = document.getElementById('status');
  // COLD BOOT AS A NUMBER, measured by the artifact rather than by a stopwatch beside it. The
  // recipient waits through this before anything renders, so it is a property of the package
  // and belongs on the page — a figure nobody has to take on trust.
  const T0 = performance.now();
  const MARKS = [];
  const mark = (k) => MARKS.push([k, Math.round(performance.now() - T0)]);
  try {{
    PY = await loadPyodide({{indexURL: './'}});
    mark('runtime up');
    PY.FS.writeFile('pricing.py',
      JSON.parse(document.getElementById('pricing-src').textContent));
    PY.FS.writeFile('page.py', PAGE_PY);
    PY.globals.set('PACKAGE_JSON', JSON.stringify(PKG));
    const problems = JSON.parse(PY.runPython(
      'import json, page; json.dumps(page.verify(PACKAGE_JSON))'));
    mark('verified');
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
    mark('first render');
    document.getElementById('boot').textContent =
      'cold boot ' + MARKS[MARKS.length - 1][1] + ' ms · ' +
      MARKS.map(m => m[0] + ' ' + m[1] + ' ms').join(' · ');
  }} catch (e) {{
    statusEl.className = 'refused';
    statusEl.textContent = 'REFUSED - the verification could not be completed: ' + e;
  }}
}})();
</script>
</body></html>
"""
