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
* a built-in's `measure_id` or verb name, EXCEPT in a source-only row (below);
* a module that does I/O: its source is parsed and every import must be in `PURE_IMPORTS`;
* a module whose `VERSION` is not the row's, or whose keyword-only parameters are not exactly the
  row's `inputs.state` keys (a function wired to a quantity the row does not name is a figure
  computed from something nobody declared);
* any `policy.visibility` key. A row cannot loosen program visibility: the route runs the program
  check (`_require_visible`) BEFORE the executor, for every declared verb, and nothing in a row
  reaches it.

── WHERE A MEASURE READS UNDER THE FLAG: `source` ──────────────────────────────────────────
Ruled 2026-11-09: the source is declared per row, not per flag. With `FIN_DATASET_URN` set a
measure computes over the asset (`source: asset`, the default when a row says nothing); a row
declaring `source: seed` keeps answering from the notional seed, and must say why (`reason`) and
who ratified that (`ratified_by`). A row naming a BUILT-IN may exist only to say this: its keys are
exactly `_SOURCE_KEYS`, it loads as a `SourceRow`, and anything else on it is refused. A
dataset-kind row reads its own asset and carries no `source`. The seed layer ships
`fin_funding_status: seed` (the contract carries no funding lines yet); an overlay row of the same
id replaces it whole, so a deployment whose asset gains them re-sources it with one row.

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
    "inputs", "computation", "outputs", "render", "policy", "menu",
    "source", "reason", "ratified_by",
})
#: `source` values. Under `FIN_DATASET_URN`, `asset` is the default and `seed` the declared exception.
SOURCE_ASSET, SOURCE_SEED = "asset", "seed"
_SOURCES = frozenset({SOURCE_ASSET, SOURCE_SEED})
#: Every key a row naming a BUILT-IN may carry: it says where the built-in reads, and nothing else.
_SOURCE_KEYS = frozenset({"measure_id", "source", "reason", "ratified_by"})
#: The render shapes this engine's runner fills: one declared series per period. A MECHANISM list,
#: not a vocabulary: the archetype vocabulary is `capability_admission.KNOWN_ARCHETYPES`, which the
#: flattened image cannot import, so a test ties this set to it (this set must be a subset).
COMPUTED_SHAPES = frozenset({"MULTI_SERIES", "FLOW_DECOMPOSITION"})
#: The two kinds of row, told apart by `inputs.dataset`, and the one shape each kind draws as.
KIND_STATE, KIND_DATASET = "state", "dataset"
_SHAPE_OF_KIND = {KIND_STATE: "MULTI_SERIES", KIND_DATASET: "FLOW_DECOMPOSITION"}
_DATASET_PARAMS = frozenset({"program_id"})   # no period axis: `window` is refused for this kind
_URN_PREFIX = "urn:li:dataset:"               # `asset_inputs.URN_PREFIX`; the flat image cannot import it
_DATASET_FN_KEYWORDS = frozenset({"root", "paths", "other_threshold"})
#: Old layout key -> the key that replaced it. Refused, never silently accepted.
_MOVED_OUTPUT_KEYS = {
    "archetype": "render.shape", "series": "render.series", "reference": "render.target",
}
#: The ONE output class every declared measure registers as (the ruling of 2026-11-02). A row
#: names no class: the measure is told apart by its id on the wire (`measure`, `method.measure_id`),
#: so a deployment adds a measure and no ontology.
DECLARED_OUTPUT_CLASS = "DeclaredMeasureSeries"
#: The keys of the optional `menu:` block: where the row's card sits on the menu (the ruling of
#: 2026-11-07: "the measure's overlay row declares its menu placement, the BFF serves it, cortex
#: reads it"). The BFF serves this field set and no other. `subject` and `archetype` restate what
#: the row already implies, so each is checked against it rather than trusted.
_MENU_KEYS = frozenset({"subject", "archetype", "persona_fit", "domain_fit"})
_PACKAGED = "agent_fleet.finance_agent."


def archetype_class(shape: str) -> str:
    """The mesh class a render shape draws as: `FLOW_DECOMPOSITION` -> `mesh:FlowDecomposition`."""
    return "mesh:" + "".join(w.capitalize() for w in shape.split("_"))


def _menu(raw: Any, shape: str, cells: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("menu must be a mapping")
    if set(raw) != _MENU_KEYS:
        raise ValueError(f"menu carries {sorted(raw)}; it holds exactly {sorted(_MENU_KEYS)}")
    subject = "fin:" + DECLARED_OUTPUT_CLASS
    if raw["subject"] != subject:
        raise ValueError(
            f"menu.subject {raw['subject']!r} is not {subject!r}, the class every declared "
            f"measure registers as; the menu places what the row produces")
    if raw["archetype"] != archetype_class(shape):
        raise ValueError(
            f"menu.archetype {raw['archetype']!r} is not {archetype_class(shape)!r}, the class "
            f"of render.shape {shape!r}; the menu places the card the row draws")
    fit = {}
    for key in ("persona_fit", "domain_fit"):
        vals = raw[key]
        if not (isinstance(vals, list) and vals and all(isinstance(v, str) and v for v in vals)):
            raise ValueError(f"menu.{key} must be a non-empty list of names")
        fit[key] = list(vals)
    outside = sorted(set(fit["domain_fit"]) - set(cells))
    if outside:
        raise ValueError(
            f"menu.domain_fit names {outside}, outside policy.cells {list(cells)}; a caller in "
            f"that domain is refused the measure, so the menu would rank a card it cannot open")
    return {"subject": subject, "archetype": raw["archetype"], **fit}


class MeasureVerbError(DeclarationError):
    """A measure-verb row is invalid. Names the FILE."""


@dataclass(frozen=True)
class SourceRow:
    """A row naming a BUILT-IN measure, saying only where it reads under `FIN_DATASET_URN`."""
    measure_id: str
    source: str
    source_reason: str = ""
    ratified_by: str = ""


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
    series: tuple[dict[str, Any], ...]      # render.series
    reference: Optional[dict[str, Any]]     # render.target
    undefined: Optional[dict[str, Any]]
    status: str
    cells: tuple[str, ...]
    granted_by: str
    reason: str
    module_sha256: str
    # The dataset kind (`inputs.dataset`); a state row carries the defaults.
    kind: str = KIND_STATE
    dataset_urn: str = ""
    banner: str = ""
    levels: tuple[str, ...] = ()
    value_columns: tuple[str, ...] = ()   # one column, or the two of a `minus`
    value_op: str = "column"              # "column" (the one column) or "minus" (first less second)
    per_path: str = "sum"                 # "sum" (rows add) or "once" (a path's amount counted once)
    other_threshold: Optional[Decimal] = None
    menu: Optional[dict[str, Any]] = None     # the `menu:` block, checked; None when undeclared
    # Where a state row reads under `FIN_DATASET_URN`; `source_reason`/`ratified_by` only for seed.
    source: str = SOURCE_ASSET
    source_reason: str = ""
    ratified_by: str = ""

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


def _check_dataset(inputs: dict) -> dict:
    """The validated `inputs.dataset` / `inputs.other_threshold` of a dataset row. ValueError."""
    ds = inputs["dataset"]
    if not isinstance(ds, dict):
        raise ValueError("inputs.dataset must be a mapping")
    unknown = sorted(set(ds) - {"urn", "banner", "levels", "value", "per_path"})
    if unknown:
        raise ValueError(f"inputs.dataset carries {unknown}; it holds urn, banner, levels, value and per_path only")
    urn = ds.get("urn")
    if not isinstance(urn, str) or not urn.startswith(_URN_PREFIX) or len(urn) == len(_URN_PREFIX):
        raise ValueError(f"inputs.dataset.urn must be a '{_URN_PREFIX}...' URN")
    banner = ds.get("banner")
    if not isinstance(banner, str) or not banner.strip():
        raise ValueError(
            "inputs.dataset.banner is required: it is what stops a synthetic asset reading as real")
    levels = ds.get("levels")
    if (not isinstance(levels, list) or len(levels) < 2
            or not all(isinstance(c, str) and c.strip() for c in levels)
            or len(set(levels)) != len(levels)):
        raise ValueError("inputs.dataset.levels must be a list of at least two distinct, non-empty column names")
    value = ds.get("value")
    if isinstance(value, str) and value.strip():
        op, columns = "column", (value,)
    elif isinstance(value, dict):
        pair = value.get("minus")
        if (set(value) != {"minus"} or not isinstance(pair, list) or len(pair) != 2
                or not all(isinstance(c, str) and c.strip() for c in pair) or pair[0] == pair[1]):
            raise ValueError(
                "inputs.dataset.value must be a column name or exactly {minus: [a, b]} "
                "with two distinct column names")
        op, columns = "minus", tuple(pair)
    else:
        raise ValueError(
            "inputs.dataset.value must be a column name or exactly {minus: [a, b]}")
    for c in columns:
        if c in levels:
            raise ValueError(f"inputs.dataset.value column {c!r} is also one of the levels")
    per_path = ds.get("per_path", "sum")
    if per_path not in ("sum", "once"):
        raise ValueError("inputs.dataset.per_path must be 'sum' or 'once'")
    raw_t = inputs.get("other_threshold")
    if raw_t is None:
        raise ValueError("missing required key 'inputs.other_threshold'")
    try:
        threshold = Decimal(raw_t) if isinstance(raw_t, str) else None
        if threshold is None or not (0 <= threshold < 1):
            raise ArithmeticError
    except ArithmeticError:  # InvalidOperation is one
        raise ValueError(
            f"inputs.other_threshold {raw_t!r} must be a Decimal string with 0 <= t < 1") from None
    return {"urn": urn, "banner": banner.strip(), "levels": tuple(levels), "value_columns": columns,
            "value_op": op, "per_path": per_path, "other_threshold": threshold}


def _source(raw: dict) -> tuple[str, str, str]:
    """`(source, reason, ratified_by)` of a row; `seed` must say why and who ratified it."""
    source = raw.get("source", SOURCE_ASSET)
    if source not in _SOURCES:
        raise ValueError(f"source {source!r} is not one of {sorted(_SOURCES)}")
    if source == SOURCE_SEED:
        for key in ("reason", "ratified_by"):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise ValueError(f"source: seed needs `{key}`: a row that keeps a measure on the "
                                 f"notional seed under the flag says why and who ratified that")
        return source, raw["reason"].strip(), raw["ratified_by"].strip()
    stray = sorted(k for k in ("reason", "ratified_by") if k in raw)
    if stray:
        raise ValueError(f"row carries {stray} with source {source!r}; they say why a measure "
                         f"reads the seed, and only a `source: seed` row does")
    return source, "", ""


def _build(raw: dict, builtins: tuple[Iterable[str], Iterable[str]]) -> MeasureVerbRow | SourceRow:
    # Raises ValueError: `compose_rows` re-raises it as MeasureVerbError WITH THE FILE NAMED.
    fns, verbs = _names(builtins)
    if raw.get("measure_id") in fns:
        extra = sorted(set(raw) - _SOURCE_KEYS)
        if extra:
            raise ValueError(
                f"measure_id {raw['measure_id']!r} is a built-in finance verb; a row naming it may "
                f"carry only {sorted(_SOURCE_KEYS)} (where it reads), never {extra}: a row cannot "
                f"replace code")
        _need(raw, "source")
        return SourceRow(raw["measure_id"], *_source(raw))
    moved = sorted(k for k in _MOVED_OUTPUT_KEYS if isinstance(raw.get("outputs"), dict)
                   and k in raw["outputs"])
    if moved:
        raise ValueError("; ".join(
            f"outputs.{k} has moved to {_MOVED_OUTPUT_KEYS[k]}: the row declares how it is drawn "
            f"under a top-level `render:` block (outputs keeps only `undefined`)"
            for k in moved))
    if isinstance(raw.get("outputs"), dict) and "output_uri" in raw["outputs"]:
        raise ValueError(
            f"outputs.output_uri {raw['outputs']['output_uri']!r} is refused: every declared "
            f"measure registers as fin:{DECLARED_OUTPUT_CLASS}, told apart by its measure id, so a "
            f"row names no class and adds no ontology; the row keeps only `outputs.undefined`")
    unknown = sorted(set(raw) - _TOP_KEYS)
    if unknown:
        raise ValueError(
            f"row carries {unknown}, which no part of the engine reads; a measure row cannot "
            f"carry a formula, expression or query -- the computation lives in the named "
            f"module (ADR-0053 section 3)")
    kind = (KIND_DATASET if isinstance(raw.get("inputs"), dict) and "dataset" in raw["inputs"]
            else KIND_STATE)
    for path in ("measure_id", "verb", "name", "inputs.params.program_id",
                 "inputs.dataset" if kind == KIND_DATASET else "inputs.state",
                 "computation.module", "computation.function", "computation.version",
                 "computation.derived_from.authority", "computation.derived_from.clause",
                 "computation.derived_from.transcription",
                 "render.shape", *(("render.series",) if kind == KIND_STATE else ()),
                 "policy.status", "policy.cells", "policy.granted_by", "policy.reason"):
        _need(raw, path)
    mid, verb = raw["measure_id"], raw["verb"]
    if not _ID_RE.match(str(mid)):
        raise ValueError(f"measure_id {mid!r} does not match {_ID_RE.pattern}")
    if verb in verbs:
        raise ValueError(f"verb {verb!r} is a built-in finance verb's name")

    inputs = raw["inputs"]
    if kind == KIND_DATASET:
        if "state" in inputs:
            raise ValueError(
                "inputs carries both `dataset` and `state`; a row is one kind or the other: "
                "`state` names engine quantities per period, `dataset` names columns of an asset")
        extra = sorted(set(inputs) - {"params", "dataset", "other_threshold"})
    else:
        extra = sorted(set(inputs) - {"params", "state"})
    if extra:
        raise ValueError(
            f"inputs carries {extra}; a row names quantities from the vocabulary and holds no "
            f"formula, expression or query (ADR-0053 section 3)")
    params = tuple(inputs["params"])
    allowed_params = _DATASET_PARAMS if kind == KIND_DATASET else _PARAMS
    unknown_params = sorted(set(params) - allowed_params)
    if unknown_params:
        raise ValueError(f"inputs.params names {unknown_params}; this engine fills only {sorted(allowed_params)}"
                         + (" for a dataset row (it has no period axis)" if kind == KIND_DATASET else ""))
    dataset: dict = {}
    if kind == KIND_DATASET:
        dataset = _check_dataset(inputs)
        state: dict = {}
    else:
        state = dict(inputs["state"])
        bad_state = sorted(f"{k}: {v}" for k, v in state.items() if v not in STATE_VOCABULARY)
        if bad_state:
            raise ValueError(
                f"inputs.state names quantities outside the closed vocabulary: {bad_state}; "
                f"the vocabulary is {sorted(STATE_VOCABULARY)}")

    out, pol, comp = raw.get("outputs") or {}, raw["policy"], raw["computation"]
    if not isinstance(out, dict):
        raise ValueError("outputs must be a mapping")
    rnd = raw["render"]
    if not isinstance(rnd, dict):
        raise ValueError("render must be a mapping")
    if kind == KIND_DATASET and "other_label" in rnd:
        raise ValueError(
            "render.other_label is declared by the row; the engine serves render.other_label from "
            "the module's OTHER_LABEL, so a row does not declare it")
    if rnd["shape"] not in COMPUTED_SHAPES:
        raise ValueError(
            f"render.shape {rnd['shape']!r}; this engine computes only {sorted(COMPUTED_SHAPES)} "
            f"(one declared series per period)")
    if rnd["shape"] != _SHAPE_OF_KIND[kind]:
        raise ValueError(
            f"render.shape {rnd['shape']!r} does not match a {kind} row, which draws as "
            f"{_SHAPE_OF_KIND[kind]!r}")
    if kind == KIND_STATE:
        series = tuple(dict(s) for s in rnd["series"])
        if len({s.get("unit") for s in series}) > 1:
            raise ValueError(
                "render.series mixes units; series on one card share a unit, and an index beside "
                "an amount is two charts drawn as one")
        if len(series) != 1:
            raise ValueError("render.series must hold exactly one series: the function returns one value per period")
    else:
        series = ()
    if pol["status"] not in _STATUSES:
        raise ValueError(f"policy.status {pol['status']!r} is not one of {sorted(_STATUSES)}")
    if "visibility" in pol:
        raise ValueError(
            "policy carries 'visibility'; a row cannot loosen program visibility -- every "
            "finance measure is can_view_program(program_id), deny by default")
    cells = tuple(pol["cells"])
    if not cells:
        raise ValueError("policy.cells is empty")
    menu = _menu(raw["menu"], str(rnd["shape"]), cells) if "menu" in raw else None
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
    if kind == KIND_DATASET:
        if kw_only != _DATASET_FN_KEYWORDS or len(sig.parameters) != len(kw_only):
            raise ValueError(
                f"{comp['function']} takes keyword-only {sorted(sig.parameters)}; a dataset row's "
                f"function takes exactly {sorted(_DATASET_FN_KEYWORDS)}")
        other = getattr(mod, "OTHER_LABEL", None)
        if not isinstance(other, str) or not other:
            raise ValueError(
                f"module {module!r} must define OTHER_LABEL as a non-empty str: it is the label the "
                f"engine serves as render.other_label for the collapse's sink")
    elif kw_only != set(state) or len(sig.parameters) != len(kw_only):
        raise ValueError(
            f"{comp['function']} takes keyword-only {sorted(sig.parameters)}, the row's "
            f"inputs.state names {sorted(state)}; they must be the same set")

    if kind == KIND_DATASET and "source" in raw:
        raise ValueError("a dataset row reads its own `inputs.dataset.urn` and carries no `source`; "
                         "`source` says where a state row reads under FIN_DATASET_URN")
    source, source_reason, ratified_by = _source(raw)
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
        series=series,
        reference=dict(rnd["target"]) if rnd.get("target") else None,
        undefined=dict(undefined) if undefined else None,
        status=pol["status"], cells=cells, granted_by=str(pol["granted_by"]),
        reason=str(pol["reason"]), module_sha256=hashlib.sha256(data).hexdigest(),
        kind=kind, dataset_urn=dataset.get("urn", ""), banner=dataset.get("banner", ""),
        levels=dataset.get("levels", ()), value_columns=dataset.get("value_columns", ()),
        value_op=dataset.get("value_op", "column"), per_path=dataset.get("per_path", "sum"),
        other_threshold=dataset.get("other_threshold"), menu=menu,
        source=source, source_reason=source_reason, ratified_by=ratified_by,
    )


def load_measure_verbs(
    policy_dir: Path | str | None = None,
    overlay_dirs: list[Path] | None = None,
    *,
    builtins: tuple[Iterable[str], Iterable[str]] | None = None,
) -> list[MeasureVerbRow]:
    """Every declared measure verb, composed and validated, sorted by `measure_id`.

    NO ROWS IS A VALID ANSWER, unlike `load_method_rows`: the platform seeds no measure (its one
    seed row is a built-in's `SourceRow`, which `load_measure_sources` returns), and a deployment
    with no overlay declares none. `builtins` is `(fns, local verb names)` of the
    engine's own verbs; the engine passes its own, a caller that does not gets them from
    `main.VERBS`.
    """
    return [r for r in _compose(policy_dir, overlay_dirs, builtins) if isinstance(r, MeasureVerbRow)]


def load_measure_sources(
    policy_dir: Path | str | None = None,
    overlay_dirs: list[Path] | None = None,
    *,
    builtins: tuple[Iterable[str], Iterable[str]] | None = None,
) -> list[SourceRow]:
    """The source-only rows naming built-ins, from the same composition as `load_measure_verbs`."""
    return [r for r in _compose(policy_dir, overlay_dirs, builtins) if isinstance(r, SourceRow)]


def _compose(policy_dir, overlay_dirs, builtins) -> list[MeasureVerbRow | SourceRow]:
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


# ── THE DATASET KIND ─────────────────────────────────────────────────────────────────────────

def run_dataset(paths, row: MeasureVerbRow, *, program_id: str) -> list[dict[str, Any]]:
    """The edge table of one program's rows. Pure over `paths`; no I/O.

    `paths` is what `asset_inputs.read_dataset_rows` returns: a list of `(level values below the
    root, Decimal amount)`, the amount already computed from the row's value spec and reduced per
    its `per_path`. The module is called once; each edge's `value` is emitted as `_emit_money`
    emits money (a cent-quantized float beside `value_exact`).
    """
    edges = row.resolve()(root=program_id, paths=list(paths), other_threshold=row.other_threshold)
    return _measures._emit_money(edges, money_fields=("value",))


def dataset_verdict(row: MeasureVerbRow, rows: list[dict[str, Any]]) -> Optional[str]:
    """A MECHANICAL restatement of the edge table: the root's net signed value (read off the root
    edge), how many edges below the root, over how many levels, and how many sinks the collapse
    made. It states where the figure stands, never whether that is acceptable. ABSENT (None) when
    there are no edges."""
    if not rows:
        return None
    sign = {"positive": 1, "negative": -1, "zero": 0}
    (root,) = [e for e in rows if e["source"] is None]
    net = Decimal(root["value_exact"]) * sign[root["sign"]]
    below = [e for e in rows if e["source"] is not None]
    zeros = sum(1 for e in below if e["sign"] == "zero")
    sinks = sum(1 for e in below if e.get("node_kind") == "other")
    label = row.render.get("value_label", row.name)
    return (f"{label}: net {net:.2f} across {len(below)} edges over {len(row.levels) - 1} levels, "
            f"{sinks} 'All other' sink(s) from the collapse, "
            f"{zeros} edge(s) at zero")
