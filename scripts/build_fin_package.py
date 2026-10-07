"""Build engine-fin's customer-validation package: one self-contained HTML file plus a
sibling `.duckdb` (item 3, ADR-0047/0048 carried from engine-cost).

REUSE BY IMPORT, NEVER BY COPY. The Pyodide embedding (`embedded_runtime`), the pinned
runtime file list (`RUNTIME_FILES`, `PYODIDE_VERSION`), the commit attestation
(`algorithm_sha`) and the no-blank-page gate (`check_javascript`) are the SAME functions
`build_cost_package.py` uses for its own artifact — imported here, not reimplemented. Cost's
own output is unaffected: this module adds a caller, it does not change the one it calls.

WHAT IS DIFFERENT FROM COST'S BUILDER, AND WHY:
  * one template, not two — every finance package carries its `.duckdb` half; there is no
    bare-HTML slice here to narrow between.
  * the DDL is DERIVED from `FinanceState`'s own dataclass field types (see `_sql_type`),
    never hand-typed beside the model a second time.
  * three named, build-time refusals (`SourceUnavailable`), each BEFORE a byte is written:
    the embedded page's own `page.verify` failing to reproduce a served panel over the
    NARROWED state; the `.duckdb` tables disagreeing with the embedded state; the produced
    page's JavaScript failing to parse.

  usage: .venv/Scripts/python.exe scripts/build_fin_package.py \
             --recipient program_office.NP-MERIDIAN --out dist/
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import enum
import hashlib
import json
import pathlib
import sys
import typing
from decimal import Decimal
from typing import Any, Optional

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from build_cost_package import (  # noqa: E402  (same repo root; see module docstring)
    PYODIDE_VERSION, RUNTIME_FILES, algorithm_sha, check_javascript, embedded_runtime,
)

from agent_fleet.finance_agent import export as fin_export                     # noqa: E402
from agent_fleet.finance_agent import page as fin_page                         # noqa: E402
from agent_fleet.finance_agent import state_codec                              # noqa: E402
from agent_fleet.finance_agent.entities import FinanceState, SourceUnavailable  # noqa: E402
from agent_fleet.finance_agent.seed import build_seed                          # noqa: E402

#: Every module the exported page embeds, with the PATH it is written to inside the
#: recipient's Pyodide filesystem — `measure_modules` is a PACKAGE, so its `__init__.py` and
#: every sibling must land under that directory for `import measures` to resolve its own
#: `from measure_modules import ...` once it is running inside the embedded runtime.
_PACKAGE_DIR = ROOT / "agent_fleet" / "finance_agent"


def _embedded_sources() -> dict[str, str]:
    """`{fs_path: source_text}` for every module `page.verify` needs at runtime, INSIDE the
    package — the same set `export.module_hashes` hashes, read here as TEXT for embedding
    rather than as a hash. One population, two uses; see `export.module_hashes`'s docstring
    for why this must never become two separately maintained lists."""
    out = {
        "entities.py": (_PACKAGE_DIR / "entities.py").read_text(encoding="utf-8"),
        "state_codec.py": (_PACKAGE_DIR / "state_codec.py").read_text(encoding="utf-8"),
        "measures.py": (_PACKAGE_DIR / "measures.py").read_text(encoding="utf-8"),
        "page.py": (_PACKAGE_DIR / "page.py").read_text(encoding="utf-8"),
    }
    mm_dir = _PACKAGE_DIR / "measure_modules"
    out["measure_modules/__init__.py"] = (mm_dir / "__init__.py").read_text(encoding="utf-8")
    for sub in sorted(mm_dir.glob("*.py")):
        if sub.name == "__init__.py":
            continue
        out[f"measure_modules/{sub.name}"] = sub.read_text(encoding="utf-8")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# The .duckdb half — DDL derived from FinanceState's own dataclass field types
# ─────────────────────────────────────────────────────────────────────────────

_SIMPLE_SQL_TYPES: dict[type, str] = {
    str: "VARCHAR",
    int: "INTEGER",
    float: "DOUBLE",
    Decimal: "DECIMAL(20,2)",
}


def _sql_type(py_type: Any, owner: str, field_name: str) -> str:
    """One column's SQL type, DERIVED from its dataclass field annotation.

    An `Optional[X]` unwraps to `X`'s mapping (nullability is a column property, not a type
    this engine's model ever branches SQL on). Anything else this table does not name is a
    REFUSAL BY NAME — never a silently-dropped column, which is the same discipline
    `state_codec._collection_item_type` holds for the collection fields themselves.
    """
    origin = typing.get_origin(py_type)
    if origin is typing.Union:
        args = [a for a in typing.get_args(py_type) if a is not type(None)]
        if len(args) == 1:
            return _sql_type(args[0], owner, field_name)
    if origin is typing.Literal:
        # `EVTechnique`/`EACMethod` are `Literal[str, ...]`, not real Enum subclasses (see
        # `entities.py`'s own docstring on the two) — a Literal of strings is a VARCHAR with
        # a closed value set this table does not itself enforce.
        args = typing.get_args(py_type)
        if args and all(isinstance(a, str) for a in args):
            return "VARCHAR"
    if py_type in _SIMPLE_SQL_TYPES:
        return _SIMPLE_SQL_TYPES[py_type]
    if isinstance(py_type, type) and issubclass(py_type, enum.Enum):
        return "VARCHAR"
    raise ValueError(
        f"build_fin_package has no SQL mapping for {owner}.{field_name}: {py_type!r}"
    )


def _table_ddl(table_name: str, row_type: type) -> tuple[str, list[tuple[str, str]]]:
    """`(ddl, [(column, sql_type), ...])` — the type is returned alongside the name so a
    caller comparing rows back out can normalize a value the SAME way SQL will have coerced
    it (see `_normalize_value`), rather than comparing a value against the differently-typed
    Python literal it was built from."""
    hints = typing.get_type_hints(row_type)
    cols = [(f.name, _sql_type(hints[f.name], row_type.__name__, f.name))
            for f in dataclasses.fields(row_type)]
    cols_sql = ", ".join(f'"{name}" {sqltype}' for name, sqltype in cols)
    return f'CREATE TABLE "{table_name}" ({cols_sql})', cols


def _normalize_value(value: Any, sql_type: str) -> Any:
    """Coerce `value` the way DuckDB's column type will have coerced it, so a Python `int`
    inserted into a `DOUBLE` column (e.g. a whole-number BAC) compares equal to the `float`
    that column reads back — content equality, not incidental-literal-type equality."""
    if value is None:
        return None
    if sql_type == "DOUBLE":
        return float(value)
    if sql_type.startswith("DECIMAL"):
        return Decimal(str(value))
    return value


def _normalize_row(row: dict[str, Any], cols: list[tuple[str, str]]) -> dict[str, Any]:
    return {name: _normalize_value(row.get(name), sqltype) for name, sqltype in cols}


#: `panels` is NOT one of `FinanceState`'s collections — it is this disclosure's OWN record
#: of what was served, so the DDL is spelled once here rather than derived from a dataclass
#: that does not exist for it.
_PANELS_DDL = (
    'CREATE TABLE "panels" (panel INTEGER, verb VARCHAR, fn VARCHAR, '
    'params_json VARCHAR, artifact_id VARCHAR, rows_sha256 VARCHAR)'
)


def build_duckdb(path: pathlib.Path, state_dict: dict[str, Any],
                 panels: list[dict[str, Any]]) -> None:
    """Write the `.duckdb` half. NO ARITHMETIC IN SQL — every value is inserted as computed
    in Python; the database is an AUTHORING AND INTERCHANGE format here, never a runtime one
    (ADR-0048 slice 2's ruling, carried over).

    EVERY BUILD STARTS FROM NOTHING: a stale file from a previous build (this recipient's own
    prior package, or a crashed attempt) is removed first, so a rebuild can never leave one
    run's tables beside another's rather than replacing them."""
    import duckdb

    if path.exists():
        path.unlink()

    row_types = state_codec._row_types()
    conn = duckdb.connect(str(path))
    try:
        for table_name, row_type in row_types.items():
            ddl, cols = _table_ddl(table_name, row_type)
            conn.execute(ddl)
            rows = state_dict.get(table_name) or []
            if rows:
                placeholders = ", ".join("?" for _ in cols)
                conn.executemany(
                    f'INSERT INTO "{table_name}" VALUES ({placeholders})',
                    [[r.get(name) for name, _ in cols] for r in rows],
                )
        conn.execute(_PANELS_DDL)
        panel_rows = [[
            p["panel"], p["verb"], p["fn"],
            json.dumps(p["params"], sort_keys=True, separators=(",", ":")),
            p["artifact_id"], fin_export.content_hash(p["rows"]),
        ] for p in panels]
        if panel_rows:
            conn.executemany(
                'INSERT INTO "panels" VALUES (?, ?, ?, ?, ?, ?)', panel_rows,
            )
    finally:
        conn.close()


def tables_agree(state_dict: dict[str, Any], panels: list[dict[str, Any]],
                 path: pathlib.Path) -> list[str]:
    """Whether the `.duckdb` on disk at `path` holds the SAME rows the embedded state and
    panel list hold. Mirrors cost's `datasets_agree` — a package whose page and whose
    database disagree would verify against data the shipped file does not contain."""
    import duckdb

    problems: list[str] = []
    row_types = state_codec._row_types()
    conn = duckdb.connect(str(path), read_only=True)
    try:
        for table_name, row_type in row_types.items():
            _ddl, cols = _table_ddl(table_name, row_type)
            col_names = [name for name, _ in cols]
            got = conn.execute(
                f'SELECT {", ".join(col_names)} FROM "{table_name}"'
            ).fetchall()
            got_rows = [dict(zip(col_names, r)) for r in got]
            want_rows = state_dict.get(table_name) or []
            # NORMALIZE BOTH SIDES THROUGH THE SAME COLUMN TYPES — a whole-number BAC
            # inserted as a Python `int` reads back from a DOUBLE column as a `float`, and
            # the two must compare EQUAL on CONTENT, not on which literal type Python
            # happened to hold before the round trip (see `_normalize_value`).
            got_sorted = sorted(
                json.dumps(_normalize_row(r, cols), sort_keys=True, default=str)
                for r in got_rows
            )
            want_sorted = sorted(
                json.dumps(_normalize_row(r, cols), sort_keys=True, default=str)
                for r in want_rows
            )
            if got_sorted != want_sorted:
                problems.append(
                    f"table {table_name!r}: duckdb holds {len(got_rows)} row(s), embedded "
                    f"state holds {len(want_rows)} row(s), or they differ in content"
                )
        got_panels = conn.execute(
            "SELECT panel, verb, fn, artifact_id, rows_sha256 FROM panels"
        ).fetchall()
        want_panels = sorted(
            (p["panel"], p["verb"], p["fn"], p["artifact_id"], fin_export.content_hash(p["rows"]))
            for p in panels
        )
        if sorted(got_panels) != want_panels:
            problems.append("table 'panels': duckdb's panel rows disagree with the served panels")
    finally:
        conn.close()
    return problems


# ─────────────────────────────────────────────────────────────────────────────
# The HTML half
# ─────────────────────────────────────────────────────────────────────────────

def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Program finance validation package - {recipient}</title>
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
 <h1>Program finance validation package - {recipient}</h1>
 <div class="meta">algorithm {sha} &middot; template {template_id} &middot; as of {as_of}</div>
</header>
<main>
 <div id="status" class="checking">Verifying against the producing engine...</div>
 <div id="body" hidden>
  <p class="note"><strong>{program_id}</strong>. Every panel below was recomputed in your
  browser from the embedded, narrowed program data by the same measures.py the engine ran,
  at the pinned commit above. A panel is shown only if the recomputation matched.</p>
  <div id="panels"></div>
 </div>
 <div id="divergence" hidden>
  <p class="note">This package refuses to display a panel it could not reproduce. The
  algorithm is pinned and identical, so a divergence here means <strong>data or runtime</strong>,
  never algorithm.</p>
  <pre id="problems"></pre>
 </div>
</main>

<script id="embedded-runtime" type="application/json">{embedded_json}</script>
<script id="package-data" type="application/json">{package_json}</script>
<script id="module-sources" type="application/json">{sources_json}</script>

<script>
// NO NETWORK. Same shim as engine-cost's package: Pyodide's loader fetches its files by
// URL, and this answers those requests from the embedded base64 above.
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
  const sources = JSON.parse(document.getElementById('module-sources').textContent);
  try {{
    const pyodide = await loadPyodide({{indexURL: './'}});
    pyodide.FS.mkdirTree('/measure_modules');
    for (const path of Object.keys(sources)) {{
      pyodide.FS.writeFile('/' + path, sources[path]);
    }}
    pyodide.globals.set('PACKAGE_JSON', JSON.stringify(pkg));
    const resultsJson = pyodide.runPython(`
import json
import page

pkg = json.loads(PACKAGE_JSON)
results = page.verify(pkg["state"], pkg["panels"])
json.dumps(results)
`);
    const results = JSON.parse(resultsJson);
    const bad = results.filter(function (r) {{ return !r.reproduced; }});
    if (bad.length) {{
      statusEl.className = 'refused';
      statusEl.textContent = 'REFUSED - ' + bad.length +
        ' panel(s) could not be reproduced. Nothing is displayed.';
      document.getElementById('problems').textContent =
        bad.map(function (r) {{ return 'panel ' + r.panel + ' (' + r.verb + '): ' + r.detail; }}).join('\\n');
      document.getElementById('divergence').hidden = false;
      return;
    }}
    statusEl.className = 'ok';
    statusEl.textContent = 'Verified - every panel reproduced exactly, ' +
      results.length + ' panel(s) checked.';
    render(pkg, results);
    document.getElementById('body').hidden = false;
  }} catch (e) {{
    statusEl.className = 'refused';
    statusEl.textContent = 'REFUSED - the verification could not be completed: ' + e;
  }}
}})();

function render(pkg, results) {{
  const host = document.getElementById('panels');
  for (const p of pkg.panels) {{
    const h = document.createElement('h2');
    h.textContent = 'Panel ' + p.panel + ' - ' + p.verb;
    host.appendChild(h);
    const rows = Array.isArray(p.rows) ? p.rows : [];
    const cols = rows.length ? Object.keys(rows[0]) : [];
    const t = document.createElement('table');
    t.innerHTML = '<tr>' + cols.map(function (c) {{ return '<th>' + c + '</th>'; }}).join('') + '</tr>' +
      rows.map(function (row) {{
        return '<tr>' + cols.map(function (c) {{ return '<td>' + row[c] + '</td>'; }}).join('') + '</tr>';
      }}).join('');
    host.appendChild(t);
  }}
}}
</script>
</body></html>
"""


def build_html(recipient_scope: str, program_id: str, runtime_dir: pathlib.Path,
               state_dict: dict[str, Any], panels: list[dict[str, Any]], *,
               template_id: str, as_of: str, sha: str) -> str:
    """Build the page. `panels` carries the SERVED rows (`_measure_envelope`'s output),
    never recomputed here — recomputation is `page.verify`'s job, inside the browser."""
    embedded, loader_js = embedded_runtime(runtime_dir)
    package_json = json.dumps({"state": state_dict, "panels": panels}, default=str)
    return _TEMPLATE.format(
        recipient=recipient_scope, program_id=program_id, sha=sha,
        template_id=template_id, as_of=as_of,
        embedded_json=json.dumps(embedded),
        package_json=package_json,
        sources_json=json.dumps(_embedded_sources()),
        loader_js=loader_js,
    )


def build(*, recipient_scope: str, program_id: str, state: FinanceState,
         template_id: str, template_hash: str, panels: list[dict[str, Any]],
         runtime_dir: pathlib.Path, sha: str, html_path: pathlib.Path,
         duckdb_path: pathlib.Path) -> dict[str, Any]:
    """Produce one recipient's package. Three named refusals, each before anything after it
    is built — see the module docstring."""
    narrowed = state_codec.narrow(state, program_id)
    state_dict = state_codec.state_to_dict(narrowed)

    # (1) THE NARROWED STATE MUST STILL REPRODUCE EVERY SERVED PANEL. If a panel's rows
    # depended on something `narrow` dropped, this package would ship a page that refuses to
    # verify itself the moment the recipient opens it — caught here, before a byte is written.
    results = fin_page.verify(state_dict, panels)
    bad = [r for r in results if not r["reproduced"]]
    if bad:
        raise SourceUnavailable(
            "packageExport refuses: re-running the pinned algorithm over the narrowed state "
            f"did not reproduce {len(bad)} panel(s): " +
            "; ".join(f"panel {r['panel']} ({r['verb']}): {r['detail']}" for r in bad)
        )

    duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    build_duckdb(duckdb_path, state_dict, panels)
    duckdb_sha256 = "sha256:" + hashlib.sha256(duckdb_path.read_bytes()).hexdigest()

    # (2) THE .duckdb MUST AGREE WITH THE EMBEDDED STATE.
    disagreements = tables_agree(state_dict, panels, duckdb_path)
    if disagreements:
        raise SourceUnavailable(
            "packageExport refuses: the .duckdb tables disagree with the embedded state: "
            + "; ".join(disagreements[:6])
        )

    manifest = fin_export.build_manifest(
        narrowed, recipient_scope=recipient_scope, program_id=program_id,
        algorithm_sha=sha, template_id=template_id, template_hash=template_hash,
        panels=panels, duckdb_sha256=duckdb_sha256,
    )

    html = build_html(
        recipient_scope, program_id, runtime_dir, state_dict, panels,
        template_id=template_id, as_of=manifest["as_of"], sha=sha,
    )

    # (3) THE PRODUCED PAGE'S JAVASCRIPT MUST PARSE.
    problems = check_javascript(html)
    if problems:
        raise SourceUnavailable(
            "the produced page's JavaScript does not parse: " + "; ".join(problems)
        )

    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_bytes(html.encode("utf-8"))
    written = html_path.read_bytes()
    html_sha256 = "sha256:" + hashlib.sha256(written).hexdigest()
    intended_sha256 = "sha256:" + hashlib.sha256(html.encode("utf-8")).hexdigest()
    if html_sha256 != intended_sha256:
        raise SourceUnavailable(
            f"the written artifact does not match what was produced: wrote {len(written)} "
            f"bytes hashing {html_sha256}, produced content hashing {intended_sha256}. "
            f"The package has NOT been emitted."
        )

    return {
        "manifest": manifest,
        "html_bytes": len(written),
        "html_sha256": html_sha256,
        "duckdb_sha256": duckdb_sha256,
    }


def main() -> int:  # pragma: no cover - CLI entry, exercised manually like cost's
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipient", required=True)
    ap.add_argument("--out", default="dist")
    args = ap.parse_args()

    from agent_fleet.finance_agent import export as _export

    program_id = _export.program_for_recipient(args.recipient)
    state = build_seed()
    sha = algorithm_sha()
    runtime_dir = ROOT / ".pyodide-cache"
    out_dir = ROOT / args.out
    html_name, duckdb_name = _export.artifact_filenames(args.recipient)

    # The CLI has no canvas; it packages every verb against the one program, same posture
    # cost's CLI takes with "no lots narrowing" for its own slice-1 page.
    from agent_fleet.finance_agent.measures import OUTPUT_URI

    panels = []
    for i, fn in enumerate(sorted(OUTPUT_URI)):
        func = getattr(__import__("agent_fleet.finance_agent.measures",
                                   fromlist=["measures"]), fn)
        try:
            rows = func(state, program_id=program_id)
        except TypeError:
            continue  # a verb needing a method or ca_id is skipped by the CLI, not guessed
        panels.append({
            "panel": i, "verb": fn, "fn": fn, "params": {"program_id": program_id},
            "artifact_id": f"fin:{fn}:cli", "rows": rows,
        })

    result = build(
        recipient_scope=args.recipient, program_id=program_id, state=state,
        template_id="cli", template_hash="cli", panels=panels, runtime_dir=runtime_dir,
        sha=sha, html_path=out_dir / html_name, duckdb_path=out_dir / duckdb_name,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "manifest"}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
