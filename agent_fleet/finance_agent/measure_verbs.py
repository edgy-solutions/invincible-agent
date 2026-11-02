"""A finance MEASURE as an overlay row. Proposal `docs/proposals/a-measure-is-an-overlay-row-and-a-cdrl-is-an-export-profile.md`, Part 1.

The platform's seven finance verbs are code (`VERBS` in `main.py`). A deployment that wants an
eighth declares it as a ROW under `policy/overlays/<name>/measure_verbs/`, composed by the SDK's
`compose_rows` (ADR-0036: an overlay row replaces a seed row whole, `deleted: true` tombstones one).
The row joins four parts: INPUTS (named from a CLOSED vocabulary of engine quantities), COMPUTATION
(a pure, versioned module, ADR-0053 section 3), OUTPUTS (a PERIOD_SERIES, one unit) and POLICY.

── WHAT A ROW MAY NOT SAY, AND WHERE IT IS REFUSED ──────────────────────────────────────────
Every refusal is at LOAD, names the FILE, and stops the engine booting: a row set that loaded
half would be a verb that exists for some deployments and not others, with no symptom.

* a formula, expression or query (`inputs` carries `params` and `state` only);
* a top-level key the engine does not read (`_TOP_KEYS`): a `formula` written there would be
  ignored, and its author would believe it took effect;
* a quantity outside `STATE_VOCABULARY` (extending it is a code change, reviewed as one);
* a built-in's `measure_id` or verb name;
* a module that does I/O: its source is parsed and every import must be in `PURE_IMPORTS`;
* a module whose `VERSION` is not the row's, or whose keyword-only parameters are not exactly the
  row's `inputs.state` keys (a function wired to a quantity the row does not name is a figure
  computed from something nobody declared);
* any `policy.visibility` key. A row cannot loosen program visibility: the route runs the program
  check (`_require_visible`) BEFORE the executor, for every declared verb, and nothing in a row
  reaches it.

── THE CUMULATIVE BASIS ─────────────────────────────────────────────────────────────────────
`cumulative.*` means what the built-in `cum_*` columns mean: summed from the FIRST PERIOD OF THE
WINDOW, skipping a period with nothing reported (`index_series.build` accumulates over the periods
it is handed and skips `(0, 0, 0)`). Measured, not assumed; the seal compares the two.

── THE MODULE PATH, AND THE FLAT IMAGE ──────────────────────────────────────────────────────
The engine image flattens `agent_fleet/finance_agent/` to `/app`, so `agent_fleet.finance_agent.
measure_modules.tcpi` does not exist there and `measure_modules.tcpi` does (the same duality
`measures.py` handles with a try/except around its imports). A row written in the packaged form is
resolved in the flat form when the packaged one is absent -- `_resolve_module`. A row can only name
one spelling; this is what lets the same row load in the repo and in the image.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib
import importlib.util
import inspect
import os
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Optional

from iagent_mesh.declarations import DeclarationError, compose_rows

try:  # flat in the image (/app), packaged in the repo -- see `measures.py`
    import measures as _measures
    from entities import periods_in
except ImportError:
    from agent_fleet.finance_agent import measures as _measures
    from agent_fleet.finance_agent.entities import periods_in

def _default_seed_dir() -> Path:
    """`<repo>/policy/measure_verbs`, found by walking up rather than counting levels: in the
    flattened image this file is `/app/<module>.py`, whose `parents` are `('/app', '/')`, so a
    fixed `parents[2]` raises IndexError at import."""
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / "policy" / "measure_verbs"
        if candidate.is_dir():
            return candidate
    return Path("/app/policy/measure_verbs")


MEASURE_VERB_POLICY_DIR_DEFAULT = _default_seed_dir()
_SEED_ENV = "MEASURE_VERB_POLICY_DIR"
_OVERLAY_ENV = "MEASURE_VERB_OVERLAY_DIRS"


def MEASURE_VERB_POLICY_DIR() -> Path:  # noqa: N802 -- named like the constants it parallels
    """The seed directory. Read from the environment at CALL time, so a test (or a deployment
    that moves it) does not depend on import order."""
    return Path(os.getenv(_SEED_ENV) or str(MEASURE_VERB_POLICY_DIR_DEFAULT))


def MEASURE_VERB_OVERLAY_DIRS() -> list[Path]:  # noqa: N802
    return [Path(p) for p in os.getenv(_OVERLAY_ENV, "").split(os.pathsep) if p]


#: The engine quantities a row may name. CLOSED: a name outside it is a refusal.
STATE_VOCABULARY = frozenset({
    "program.bac",
    "period.bcws", "period.bcwp", "period.acwp",
    "cumulative.bcws", "cumulative.bcwp", "cumulative.acwp",
})

#: What a measure module may import. Source is parsed with `ast`; anything else is I/O or a
#: dependency on the engine it is meant to be liftable out of.
PURE_IMPORTS = frozenset({"decimal", "typing", "__future__", "math", "fractions"})

_STATUSES = frozenset({"sample", "proposed", "ratified"})
_PARAMS = frozenset({"program_id", "window"})
_ID_RE = re.compile(r"^fin_[a-z0-9_]+$")
# Every top-level key `_build` reads, and so every key a row may carry. `deleted` is not here: a
# tombstone never reaches `_build` (`compose_rows` pops it), and `deleted: false` is not a key an
# author writes. Docs: `docs/contracts/finance-overlays.md` section 2; the seal compares the two.
_TOP_KEYS = frozenset({
    "measure_id", "verb", "name", "description", "synonyms", "anti_synonyms",
    "inputs", "computation", "outputs", "render", "policy",
})
#: The render shapes this engine's runner fills: one declared series per period. A MECHANISM list,
#: not a vocabulary: the archetype vocabulary is `capability_admission.KNOWN_ARCHETYPES`, which the
#: flattened image cannot import, so a test ties this set to it (this set must be a subset).
COMPUTED_SHAPES = frozenset({"MULTI_SERIES"})
#: Old layout key -> the key that replaced it. Refused, never silently accepted.
_MOVED_OUTPUT_KEYS = {
    "archetype": "render.shape", "series": "render.series", "reference": "render.target",
}
_PACKAGED = "agent_fleet.finance_agent."


class MeasureVerbError(DeclarationError):
    """A measure-verb row is invalid. Names the FILE."""


@dataclass(frozen=True)
class MeasureVerbRow:
    measure_id: str
    verb: str
    name: str
    description: str
    synonyms: tuple[str, ...]
    anti_synonyms: tuple[str, ...]
    params: tuple[str, ...]
    state: dict[str, str]           # function keyword -> vocabulary name
    module: str                     # as written in the row
    resolved_module: str            # as importable HERE
    function: str
    version: str
    authority: str
    clause: str
    citation: str
    transcription: str
    render: Any                     # a deep copy of the row's render block
    archetype: str                  # render.shape
    output_uri: str
    series: tuple[dict[str, Any], ...]      # render.series
    reference: Optional[dict[str, Any]]     # render.target
    undefined: Optional[dict[str, Any]]
    status: str
    cells: tuple[str, ...]
    granted_by: str
    reason: str
    module_sha256: str

    @property
    def series_key(self) -> str:
        return self.series[0]["key"]

    def resolve(self):
        return getattr(importlib.import_module(self.resolved_module), self.function)


def _resolve_module(name: str) -> str:
    """The importable spelling of `name`: itself, else the flat-image spelling."""
    try:
        if importlib.util.find_spec(name) is not None:
            return name
    except ModuleNotFoundError:
        pass
    if name.startswith(_PACKAGED):
        flat = name[len(_PACKAGED):]
        try:
            if importlib.util.find_spec(flat) is not None:
                return flat
        except ModuleNotFoundError:
            pass
    raise ValueError(f"cannot find module {name!r}")


def _impure_imports(source: str) -> list[str]:
    bad: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name.split(".")[0] not in PURE_IMPORTS]
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in PURE_IMPORTS:
                bad.append("." * node.level + (node.module or ""))
    return sorted(set(bad))


def _need(raw: dict, path: str) -> Any:
    cur: Any = raw
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
        if cur is None:
            raise ValueError(f"missing required key {path!r}")
    return cur


def _names(builtins: tuple[Iterable[str], Iterable[str]]) -> tuple[frozenset, frozenset]:
    return frozenset(builtins[0]), frozenset(builtins[1])


def _build(raw: dict, builtins: tuple[Iterable[str], Iterable[str]]) -> MeasureVerbRow:
    # Raises ValueError: `compose_rows` re-raises it as MeasureVerbError WITH THE FILE NAMED.
    fns, verbs = _names(builtins)
    moved = sorted(k for k in _MOVED_OUTPUT_KEYS if isinstance(raw.get("outputs"), dict)
                   and k in raw["outputs"])
    if moved:
        raise ValueError("; ".join(
            f"outputs.{k} has moved to {_MOVED_OUTPUT_KEYS[k]}: the row declares how it is drawn "
            f"under a top-level `render:` block (outputs keeps output_uri, unit and undefined)"
            for k in moved))
    unknown = sorted(set(raw) - _TOP_KEYS)
    if unknown:
        raise ValueError(
            f"row carries {unknown}, which no part of the engine reads; a measure row cannot "
            f"carry a formula, expression or query -- the computation lives in the named "
            f"module (ADR-0053 section 3)")
    for path in ("measure_id", "verb", "name", "inputs.params.program_id", "inputs.state",
                 "computation.module", "computation.function", "computation.version",
                 "computation.derived_from.authority", "computation.derived_from.clause",
                 "computation.derived_from.transcription",
                 "outputs.output_uri", "render.shape", "render.series",
                 "policy.status", "policy.cells", "policy.granted_by", "policy.reason"):
        _need(raw, path)
    mid, verb = raw["measure_id"], raw["verb"]
    if not _ID_RE.match(str(mid)):
        raise ValueError(f"measure_id {mid!r} does not match {_ID_RE.pattern}")
    if mid in fns:
        raise ValueError(f"measure_id {mid!r} is a built-in finance verb; a row cannot replace code")
    if verb in verbs:
        raise ValueError(f"verb {verb!r} is a built-in finance verb's name")

    inputs = raw["inputs"]
    extra = sorted(set(inputs) - {"params", "state"})
    if extra:
        raise ValueError(
            f"inputs carries {extra}; a row names quantities from the vocabulary and holds no "
            f"formula, expression or query (ADR-0053 section 3)")
    params = tuple(inputs["params"])
    unknown_params = sorted(set(params) - _PARAMS)
    if unknown_params:
        raise ValueError(f"inputs.params names {unknown_params}; this engine fills only {sorted(_PARAMS)}")
    state = dict(inputs["state"])
    bad_state = sorted(f"{k}: {v}" for k, v in state.items() if v not in STATE_VOCABULARY)
    if bad_state:
        raise ValueError(
            f"inputs.state names quantities outside the closed vocabulary: {bad_state}; "
            f"the vocabulary is {sorted(STATE_VOCABULARY)}")

    out, pol, comp = raw["outputs"], raw["policy"], raw["computation"]
    rnd = raw["render"]
    if not isinstance(rnd, dict):
        raise ValueError("render must be a mapping")
    if rnd["shape"] not in COMPUTED_SHAPES:
        raise ValueError(
            f"render.shape {rnd['shape']!r}; this engine computes only {sorted(COMPUTED_SHAPES)} "
            f"(one declared series per period)")
    if "://" in str(out["output_uri"]) or "#" in str(out["output_uri"]):
        raise ValueError(f"outputs.output_uri {out['output_uri']!r} is a local name, not a URI")
    series = tuple(dict(s) for s in rnd["series"])
    if len({s.get("unit") for s in series}) > 1:
        raise ValueError(
            "render.series mixes units; series on one card share a unit, and an index beside "
            "an amount is two charts drawn as one")
    if len(series) != 1:
        raise ValueError("render.series must hold exactly one series: the function returns one value per period")
    if pol["status"] not in _STATUSES:
        raise ValueError(f"policy.status {pol['status']!r} is not one of {sorted(_STATUSES)}")
    if "visibility" in pol:
        raise ValueError(
            "policy carries 'visibility'; a row cannot loosen program visibility -- every "
            "finance measure is can_view_program(program_id), deny by default")
    cells = tuple(pol["cells"])
    if not cells:
        raise ValueError("policy.cells is empty")
    undefined = out.get("undefined")
    if undefined is not None and not (isinstance(undefined, dict) and undefined.get("reason")):
        raise ValueError("outputs.undefined must be a mapping with a 'reason'")

    module = str(comp["module"])
    resolved = _resolve_module(module)
    spec = importlib.util.find_spec(resolved)
    origin = getattr(spec, "origin", None)
    if not origin or not Path(origin).is_file():
        raise ValueError(f"module {module!r} has no source file to check")
    data = Path(origin).read_bytes()
    impure = _impure_imports(data.decode("utf-8"))
    if impure:
        raise ValueError(
            f"module {module!r} imports {impure}; a measure module imports only "
            f"{sorted(PURE_IMPORTS)} (no I/O, ADR-0053 section 3)")
    mod = importlib.import_module(resolved)
    declared = getattr(mod, "VERSION", None)
    if declared is None:
        raise ValueError(f"module {module!r} declares no VERSION, so it has no manifest")
    if str(declared) != str(comp["version"]):
        raise ValueError(
            f"row says version {comp['version']!r}, module {module!r} declares {declared!r}; "
            f"the version travels beside every figure, so the two must agree")
    fn = getattr(mod, comp["function"], None)
    if fn is None:
        raise ValueError(f"module {module!r} has no function {comp['function']!r}")
    sig = inspect.signature(fn)
    kw_only = {n for n, p in sig.parameters.items() if p.kind is inspect.Parameter.KEYWORD_ONLY}
    if kw_only != set(state) or len(sig.parameters) != len(kw_only):
        raise ValueError(
            f"{comp['function']} takes keyword-only {sorted(sig.parameters)}, the row's "
            f"inputs.state names {sorted(state)}; they must be the same set")

    derived = comp["derived_from"]
    return MeasureVerbRow(
        measure_id=mid, verb=verb, name=str(raw["name"]),
        description=str(raw.get("description") or "").strip(),
        synonyms=tuple(raw.get("synonyms") or ()),
        anti_synonyms=tuple(raw.get("anti_synonyms") or ()),
        params=params, state=state, module=module, resolved_module=resolved,
        function=comp["function"], version=str(comp["version"]),
        authority=derived["authority"], clause=derived["clause"],
        citation=derived.get("citation", "unstated"), transcription=derived["transcription"],
        render=copy.deepcopy(rnd), archetype=str(rnd["shape"]),
        output_uri=str(out["output_uri"]), series=series,
        reference=dict(rnd["target"]) if rnd.get("target") else None,
        undefined=dict(undefined) if undefined else None,
        status=pol["status"], cells=cells, granted_by=str(pol["granted_by"]),
        reason=str(pol["reason"]), module_sha256=hashlib.sha256(data).hexdigest(),
    )


def load_measure_verbs(
    policy_dir: Path | str | None = None,
    overlay_dirs: list[Path] | None = None,
    *,
    builtins: tuple[Iterable[str], Iterable[str]] | None = None,
) -> list[MeasureVerbRow]:
    """Every declared measure verb, composed and validated, sorted by `measure_id`.

    NO ROWS IS A VALID ANSWER, unlike `load_method_rows`: the platform seeds none, and a
    deployment with no overlay declares none. `builtins` is `(fns, local verb names)` of the
    engine's own verbs; the engine passes its own, a caller that does not gets them from
    `main.VERBS`.
    """
    if builtins is None:
        try:
            from agent_fleet.finance_agent import main as _main
        except ImportError:  # pragma: no cover -- flat image: main always passes its own
            import main as _main
        builtins = (_measures.OUTPUT_URI, [v["verb"].split(":", 1)[-1] for v in _main.VERBS])
    d = Path(policy_dir) if policy_dir is not None else MEASURE_VERB_POLICY_DIR()
    ov = overlay_dirs if overlay_dirs is not None else MEASURE_VERB_OVERLAY_DIRS()
    return compose_rows(
        d, ov, key_field="measure_id", builder=lambda raw: _build(raw, builtins),
        label="measure verb row", error=MeasureVerbError,
    )


# ── THE EXECUTOR ─────────────────────────────────────────────────────────────────────────────

def run_declared(state, row: MeasureVerbRow, *, program_id: str, window=None) -> list[dict[str, Any]]:
    """One row per reported period. Pure over `FinanceState`; no I/O.

    Each vocabulary quantity is computed EXACTLY (Decimal, `_totals_exact`); the module is called
    once per period with the row's `state` mapping; `None` becomes a null value carrying the
    row's `undefined` reason. A period with nothing reported is skipped, as the built-in index
    series skips it: a period of no reports is not a period of zero performance.
    """
    program = _measures._require_program(state, program_id)
    ca_ids = {c.ca_id for c in state.accounts_of(program_id)}
    wp_ids = {w.wp_id for w in state.work_packages if w.ca_id in ca_ids}
    fn = row.resolve()
    key = row.series_key
    cum = [Decimal(0), Decimal(0), Decimal(0)]
    out: list[dict[str, Any]] = []
    for period in periods_in(window):
        bcws, bcwp, acwp = _measures._totals_exact(state, wp_ids, [period])
        if (bcws, bcwp, acwp) == (0, 0, 0):
            continue
        cum[0] += bcws
        cum[1] += bcwp
        cum[2] += acwp
        values = {
            "program.bac": Decimal(str(program.bac)),
            "period.bcws": bcws, "period.bcwp": bcwp, "period.acwp": acwp,
            "cumulative.bcws": cum[0], "cumulative.bcwp": cum[1], "cumulative.acwp": cum[2],
        }
        result = fn(**{kw: values[name] for kw, name in row.state.items()})
        item: dict[str, Any] = {
            "period": period,
            "scope_label": program.name,
            key: result,
            "inputs": {kw: str(values[name]) for kw, name in row.state.items()},
        }
        if result is None:
            if not row.undefined:
                raise ValueError(
                    f"{row.measure_id}: the function returned None for {period} and the row "
                    f"declares no outputs.undefined, so there is no reason to carry")
            item["undefined"] = row.undefined["reason"]
        out.append(item)
    return _measures._emit_money(out, money_fields=(), ratio_fields=(key,))


def declared_verdict(row: MeasureVerbRow, rows: list[dict[str, Any]]) -> Optional[str]:
    """A MECHANICAL restatement of the last period's figure against the row's reference, the same
    kind of line the built-in verbs' VERDICT entries are: it states where the figure stands, never
    whether that is acceptable. ABSENT (None) when there are no rows, as the built-ins are."""
    if not rows:
        return None
    last = rows[-1]
    label = row.series[0].get("label", row.name)
    value = last.get(row.series_key)
    if value is None:
        reason = last.get("undefined") or "undefined"
        return f"{label} undefined at {last['period']}: {reason}"
    if not row.reference:
        return f"{label} {value:.2f} at {last['period']}"
    ref = row.reference["value"]
    side = "above" if value > ref else "below" if value < ref else "at"
    return f"{label} {value:.2f}, {side} {ref} ({row.reference.get('label', 'reference')}) at {last['period']}"
