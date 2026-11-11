"""`mesh:whereIsThisPartUsed` - the SUSTAINMENT read "where is this part used" (ADR-0065 section 4).

WHAT IT ANSWERS. Given a part, walk `Part <- used in* <- EndItem -> program`, filtered by
applicability and by one declared configuration, and answer ONE ROW PER END ITEM AND PROGRAM:
the part's quantity per end item rolled up through every level, and the program that end item is
sustained under. The row is `ImpactRow` (ADR-0065 ruling 4).

WHAT IT READS. One repository dataset (policy/overlays/sample/product_structure/where_used.yaml,
or the file `WHERE_USED_DATASET` names): identities with their aliases, end items, part usages and
the per-asset sustained-under rows. READ-ONLY. The file read (`load_dataset`) is separate from the
shaping (`where_used`), so a test drives the shaping with no app and no file.

PROGRAM COMES FROM THE SUSTAINED-UNDER ROWS, NEVER THE BOM (ADR-0056 section 8). An end item with
no row is withheld: deny by default.

ABSENT IS NOT ZERO. `population` and `stock` have no source, so every row carries `None` for them
and `data_provenance.absent` says why. The table cell is `null` on the wire (a typed value, never
0, "" or a placeholder string), which is how cortex reads absence; the row text says "no source".
Every `None` inside `data_provenance.inputs` also gets an `absent` entry naming the input and
the reason, so a missing label is stated rather than left to be read as "checked".

CLASSIFICATION IS CARRIED, NOT COMPOSED. Each input's label rides inside `data_provenance.inputs`.
ADR-0064 is Proposed and `policy/classification/dimensions.yaml` ships empty ("No code reads this
file yet"), so no rule exists to combine labels and none is invented here: an unlabelled input
gives an unlabelled row.

ANSWERS, NEVER CONFLATED. Every refusal is the fleet's named envelope (`_refused`: `refused:
True`, `outcome: "refused"`, `reason`; `status: "refused"` stays for existing consumers):
  * `part_required`            - no part reached the verb.
  * `unknown_part`             - no identity or alias matches; ALSO the answer when every end item
                                 the part is in is withheld from this caller, byte for byte, so the
                                 read is not an existence oracle.
  * `ambiguous_part`           - the text matches two identities.
  * `unknown_configuration`    - the value is outside CONFIGURATIONS (the message lists them).
  * `configuration_not_available` - a visible end item the part is in lists no data for the asked
                                 configuration. Refused loudly, naming those end items: never an
                                 empty table and never a partial one.
  * `no_usage`                 - the part is known and used in no end item. A refusal, not an empty
                                 table: an empty table reads as "checked, none".
"""
from __future__ import annotations

import copy
import datetime as _dt
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict

try:  # engine image: flat layout (agent_fleet/ on sys.path as the root)
    from utils.slot_declarations import derive_slots
except ImportError:  # repo layout
    from agent_fleet.utils.slot_declarations import derive_slots  # type: ignore[no-redef]

VERB = "mesh:whereIsThisPartUsed"
DOMAIN = "SUSTAINMENT"
INPUT_URI = "http://internal/sustainment/product#Part"
OUTPUT_URI = "http://invincible-agent/mesh#WhereUsedSet"

#: RULED 2026-11-10: the verb is registered a second time on the notice graph's Component, so a
#: question grounded on a notice's part is offered it. Component is NOT put under `ps:Part` (that
#: over-claims); whether it sits under `ps:ManufacturerPart` is a separate ontology item.
COMPONENT_INPUT_URI = "http://internal/sustainment/pcn#Component"

#: (registration name, input class). One name per input: registering one verb twice under one
#: name deletes the first edge. Every other registration field is shared, so the verb keeps one
#: description across its subjects.
REGISTRATIONS = (
    ("engine_o_where_is_this_part_used", INPUT_URI),
    ("engine_o_where_is_this_part_used_component", COMPONENT_INPUT_URI),
)

#: ADR-0065 ruling 2's vocabulary and default. It moves to the ontology slice (board item C) when
#: C lands; until then this is the one place the fleet spells it.
CONFIGURATIONS = ("as_designed", "as_built", "as_maintained")
DEFAULT_CONFIGURATION = "as_designed"

#: The shipped dataset, repo-relative. Also the `locator` an answer names for it.
SHIPPED_LOCATOR = "policy/overlays/sample/product_structure/where_used.yaml"
DATASET_ENV = "WHERE_USED_DATASET"

#: The text the answer's row lines read when a value has no source. Never 0 or "".
NO_SOURCE = "no source"


class ImpactRow(BaseModel):
    """ADR-0065 ruling 4's row. LOCAL until the SDK's `ImpactRow` is reshaped to it (ca's), then
    re-exported from the SDK the way `workflow_definition.py` re-exports the DSL."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    end_item: str
    program: str
    component: str
    qty_per: float | int
    population: int | None = None
    stock: int | None = None
    configuration: str
    as_of: str | None
    data_provenance: dict


# ── the dataset ─────────────────────────────────────────────────────────────────────────────────

class DatasetRefused(ValueError):
    """The dataset is malformed. Named, so the route can answer 503 with the loader's message
    instead of serving a quantity rolled up through a broken structure."""


@dataclass(frozen=True)
class Dataset:
    inputs: Dict[str, Dict[str, Any]]
    #: identity -> {"label": str, "aliases": [alias dict, ...]}
    identities: Dict[str, Dict[str, Any]]
    #: end item identity -> configurations it has data for
    end_items: Dict[str, Tuple[str, ...]]
    usages: Tuple[Dict[str, Any], ...]
    #: end item identity -> program
    sustained_under: Dict[str, str]
    locator: str = SHIPPED_LOCATOR
    extra: Dict[str, Any] = field(default_factory=dict)


def _policy_roots(module_path: Path) -> List[Path]:
    """Repo layout (`<repo>/agent_fleet/ontology_service/x.py` -> `<repo>/policy`), then the
    flattened image (`/app/ontology_service/x.py` or `/app/x.py` -> `/app/policy`)."""
    here = module_path.resolve()
    out: List[Path] = []
    for depth in (2, 1, 0):
        if len(here.parents) > depth:
            out.append(here.parents[depth] / "policy")
    return out


def shipped_dataset_path() -> Path:
    """`WHERE_USED_DATASET` if set, else the shipped fixture beside the first policy root that
    has it. Falls back to the first candidate so the loader's refusal names a real path."""
    env = (os.environ.get(DATASET_ENV) or "").strip()
    if env:
        return Path(env)
    rel = Path(SHIPPED_LOCATOR).relative_to("policy")
    roots = _policy_roots(Path(__file__))
    for root in roots:
        if (root / rel).is_file():
            return root / rel
    return roots[0] / rel


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _check_acyclic(usages: List[Dict[str, Any]]) -> None:
    children: Dict[str, List[str]] = {}
    for u in usages:
        children.setdefault(u["parent"], []).append(u["child"])
    state: Dict[str, int] = {}  # 1 = on the walk, 2 = done

    def visit(node: str) -> None:
        state[node] = 1
        for nxt in children.get(node, ()):
            if state.get(nxt) == 1:
                raise DatasetRefused(f"the product structure has a cycle through {nxt!r}")
            if nxt not in state:
                visit(nxt)
        state[node] = 2

    for root in list(children):
        if root not in state:
            visit(root)


def build_dataset(raw: Dict[str, Any], *, locator: str = SHIPPED_LOCATOR) -> Dataset:
    """Validate a parsed dataset and freeze it. Every refusal names the offending row."""
    raw = raw or {}
    identities: Dict[str, Dict[str, Any]] = {}
    seen_alias: Dict[Tuple[str, str], str] = {}
    for row in raw.get("identities") or []:
        ident = row.get("identity")
        if not ident or ident in identities:
            raise DatasetRefused(f"identity {ident!r} is missing or listed twice")
        aliases = list(row.get("aliases") or [])
        for a in aliases:
            key = (str(a.get("scheme") or ""), str(a.get("value") or ""))
            if key in seen_alias and seen_alias[key] != ident:
                raise DatasetRefused(
                    f"alias {key[0]}:{key[1]} is on two identities "
                    f"({seen_alias[key]!r} and {ident!r}); an alias is never a second node")
            seen_alias[key] = ident
        identities[ident] = {"label": row.get("label") or ident, "aliases": aliases}

    end_items: Dict[str, Tuple[str, ...]] = {}
    for row in raw.get("end_items") or []:
        ident = row.get("identity")
        if ident not in identities:
            raise DatasetRefused(f"end item {ident!r} names no identity")
        confs = tuple(row.get("configurations") or ())
        bad = [c for c in confs if c not in CONFIGURATIONS]
        if bad:
            raise DatasetRefused(
                f"end item {ident!r} lists configuration {bad[0]!r}, outside {list(CONFIGURATIONS)}")
        end_items[ident] = confs

    usages: List[Dict[str, Any]] = []
    for row in raw.get("usages") or []:
        for side in ("parent", "child"):
            if row.get(side) not in identities:
                raise DatasetRefused(f"usage {side} {row.get(side)!r} names no identity")
        if not _positive_number(row.get("quantity")):
            raise DatasetRefused(
                f"usage {row['parent']!r} -> {row['child']!r} has quantity {row.get('quantity')!r}; "
                "a quantity is a positive number")
        conf = row.get("configuration") or DEFAULT_CONFIGURATION
        if conf not in CONFIGURATIONS:
            raise DatasetRefused(
                f"usage {row['parent']!r} -> {row['child']!r} has configuration {conf!r}, "
                f"outside {list(CONFIGURATIONS)}")
        usages.append({**row, "configuration": conf})
    _check_acyclic(usages)

    sustained: Dict[str, str] = {}
    for row in raw.get("sustained_under") or []:
        if row.get("end_item") not in identities:
            raise DatasetRefused(f"sustained-under row names unknown identity {row.get('end_item')!r}")
        sustained[row["end_item"]] = str(row.get("program") or "")

    return Dataset(
        inputs=copy.deepcopy(raw.get("inputs") or {}),
        identities=identities,
        end_items=end_items,
        usages=tuple(usages),
        sustained_under=sustained,
        locator=locator,
    )


def load_dataset(path: Optional[Path | str] = None) -> Dataset:
    """Read and validate the dataset file. Raises `DatasetRefused` if it is unreadable or malformed."""
    import yaml  # noqa: PLC0415

    p = Path(path) if path else shipped_dataset_path()
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise DatasetRefused(f"the where-used dataset is unreadable ({p.name}): {exc}") from exc
    if not isinstance(raw, dict):
        raise DatasetRefused(f"the where-used dataset ({p.name}) is not a mapping")
    locator = SHIPPED_LOCATOR if not os.environ.get(DATASET_ENV) and not path else p.name
    return build_dataset(raw, locator=locator)


# ── the slot declaration ────────────────────────────────────────────────────────────────────────

def _declared_arguments(configuration: Literal[CONFIGURATIONS] = DEFAULT_CONFIGURATION) -> None:  # type: ignore[valid-type]
    """Signature only: `derive_slots` reads the vocabulary and the default out of it, so the
    declaration and CONFIGURATIONS cannot disagree. The part is not a slot: the resolver binds it."""


def slots() -> List[dict]:
    return derive_slots(_declared_arguments)


# ── resolution ──────────────────────────────────────────────────────────────────────────────────

def part_of(params: Optional[Dict[str, Any]], resolved_instance_id: str = "") -> str:
    """The part the verb answers about: the `part` slot if filled, else the resolved instance."""
    slot = (params or {}).get("part")
    if isinstance(slot, str) and slot.strip():
        return slot.strip()
    return (resolved_instance_id or "").strip()


def _alias_live(alias: Dict[str, Any], today: str) -> bool:
    valid_to = alias.get("valid_to")
    return not valid_to or str(valid_to) >= today


def resolve_part(dataset: Dataset, text: str, *, today: Optional[str] = None) -> List[str]:
    """Every identity the text names: exactly, or by one alias value (`scheme:value` or bare
    `value`). An alias whose `valid_to` is past is not matched."""
    today = today or _dt.date.today().isoformat()
    hits: List[str] = []
    for ident, row in dataset.identities.items():
        if ident == text:
            hits.append(ident)
            continue
        for a in row["aliases"]:
            if not _alias_live(a, today):
                continue
            value = str(a.get("value") or "")
            if text == value or text == f"{a.get('scheme')}:{value}":
                hits.append(ident)
                break
    return hits


# ── the walk ────────────────────────────────────────────────────────────────────────────────────

def _qty_per(dataset: Dataset, end_item: str, part: str, configurations: Tuple[str, ...]) -> float | int:
    """Sum over every path from `end_item` down to `part` of the product of the quantities, using
    only usages in `configurations` whose applicability is absent or names this end item.
    0 means unreachable."""
    by_parent: Dict[str, List[Dict[str, Any]]] = {}
    for u in dataset.usages:
        if u["configuration"] not in configurations:
            continue
        applic = u.get("applicability")
        if applic and end_item not in applic:
            continue
        by_parent.setdefault(u["parent"], []).append(u)
    memo: Dict[str, float | int] = {}

    def paths(node: str) -> float | int:
        if node == part:
            return 1
        if node not in memo:
            memo[node] = sum(u["quantity"] * paths(u["child"]) for u in by_parent.get(node, ()))
        return memo[node]

    return paths(end_item) if end_item != part else 0


# ── the answer ──────────────────────────────────────────────────────────────────────────────────

def _refused(reason: str, message: str, **extra: Any) -> Dict[str, Any]:
    """The named refusal envelope every refusal here speaks."""
    return {
        "status": "refused",
        "refused": True,
        "outcome": "refused",
        "reason": reason,
        "verb": VERB,
        "message": message,
        **extra,
    }


def _unknown_part() -> Dict[str, Any]:
    # No part text in the message: this envelope is also the all-withheld answer, and the two
    # must be byte-equal.
    return _refused("unknown_part", "No part with that identity or alias is known.")


#: Table columns, keyed by the `ImpactRow` field each reads. `from` names that field.
_COLUMNS = (
    ("end_item", "End item"),
    ("program", "Program"),
    ("qty_per", "Qty per"),
    ("population", "Population"),
    ("stock", "Stock"),
    ("configuration", "Configuration"),
    ("as_of", "As of"),
)
IBP_COLUMNS = [{"key": k, "label": label, "from": f"ImpactRow.{k}"} for k, label in _COLUMNS]
IBP_ROW_IDENTITY = {"key": "instance"}


def _provenance(dataset: Dataset) -> Tuple[Dict[str, Any], Optional[str]]:
    """The row's `data_provenance` and its `as_of` (the earliest input's)."""
    inputs: List[Dict[str, Any]] = []
    absent: Dict[str, str] = {"population": "no source", "stock": "no source"}
    for name, meta in dataset.inputs.items():
        inputs.append({
            "name": name,
            "dataset_urn": meta.get("dataset_urn"),
            "locator": dataset.locator,
            "as_of": meta.get("as_of"),
            "ticket_id": None,
            "classification": meta.get("classification"),
            "notional": bool(meta.get("notional")),
        })
        if meta.get("dataset_urn") is None:
            absent[f"{name}.dataset_urn"] = "repository fixture: no catalogue entry"
        absent[f"{name}.ticket_id"] = "no broker read"
        if meta.get("classification") is None:
            absent[f"{name}.classification"] = "unlabelled"
        if meta.get("as_of") is None:
            absent[f"{name}.as_of"] = "the input states no as_of"
    stamps = [i["as_of"] for i in inputs]
    as_of = None if (not stamps or any(s is None for s in stamps)) else min(str(s) for s in stamps)
    if as_of is None:
        absent["as_of"] = "an input states no as_of"
    return {"inputs": inputs, "absent": absent}, as_of


def _cell(value: Any) -> str:
    return NO_SOURCE if value is None else str(value)


def where_used(dataset: Dataset, part: str, configuration: Optional[str] = None, *,
               caller_id: str, can_view_program: Callable[[str, str], bool]) -> Dict[str, Any]:
    """The pure shaping: one answer envelope or one named refusal."""
    configuration = configuration or DEFAULT_CONFIGURATION
    part = (part or "").strip()
    if not part:
        return _refused("part_required", "No part reached this read; name the part to look up.")
    if configuration not in CONFIGURATIONS:
        return _refused(
            "unknown_configuration",
            f"Configuration {configuration!r} is not one of: {', '.join(CONFIGURATIONS)}.")
    hits = resolve_part(dataset, part)
    if not hits:
        return _unknown_part()
    if len(hits) > 1:
        return _refused("ambiguous_part", "That text names more than one part; give its identity.")
    ident = hits[0]
    label = dataset.identities[ident]["label"]

    reach_in = tuple({DEFAULT_CONFIGURATION, configuration})
    reachable = [e for e in dataset.end_items if _qty_per(dataset, e, ident, reach_in) > 0]
    if not reachable:
        return _refused("no_usage", f"{label} is known and is used in no end item.")

    verdicts: Dict[str, bool] = {}
    visible: List[str] = []
    for e in reachable:
        program = dataset.sustained_under.get(e)
        if not program:
            continue
        if program not in verdicts:
            verdicts[program] = bool(can_view_program(program, caller_id))
        if verdicts[program]:
            visible.append(e)
    if not visible:
        return _unknown_part()

    lacking = [e for e in visible if configuration not in dataset.end_items[e]]
    if lacking:
        names = ", ".join(sorted(dataset.identities[e]["label"] for e in lacking))
        return _refused(
            "configuration_not_available",
            f"No {configuration} data is held for end item(s): {names}. "
            f"Ask for {DEFAULT_CONFIGURATION}, or wait for that configuration's data.",
            configuration=configuration)

    provenance, as_of = _provenance(dataset)
    rows: List[ImpactRow] = []
    for e in visible:
        qty = _qty_per(dataset, e, ident, (configuration,))
        if qty > 0:
            rows.append(ImpactRow(
                end_item=e, program=dataset.sustained_under[e], component=ident, qty_per=qty,
                configuration=configuration, as_of=as_of,
                data_provenance=copy.deepcopy(provenance)))
    if not rows:
        return _refused("no_usage", f"{label} is known and is used in no end item for {configuration}.")
    rows.sort(key=lambda r: (dataset.identities[r.end_item]["label"], r.program))

    lines = [
        f"{dataset.identities[r.end_item]['label']} ({r.program}): {r.qty_per} per end item, "
        f"population {_cell(r.population)}, stock {_cell(r.stock)} [{r.configuration}]"
        for r in rows
    ]
    message = "\n".join(lines)
    notional = any(i["notional"] for i in provenance["inputs"])
    suffix = f"{configuration}, synthetic fixture" if notional else configuration
    columns = [dict(c) for c in IBP_COLUMNS]
    group_by = next(c["key"] for c in columns if c["from"] == "ImpactRow.program")
    table = [
        {
            "instance": r.end_item,
            "end_item": dataset.identities[r.end_item]["label"],
            "program": r.program,
            "qty_per": r.qty_per,
            "population": r.population,
            "stock": r.stock,
            "configuration": r.configuration,
            "as_of": r.as_of,
        }
        for r in rows
    ]
    return {
        "status": "ok",
        "verb": VERB,
        "output_uri": OUTPUT_URI,
        "component": ident,
        "configuration": configuration,
        "count": len(rows),
        "where_used": [r.model_dump() for r in rows],
        "message": message,
        "data": message,
        "title": f"Where {label} is used ({suffix})",
        "target": {"domain": DOMAIN, "class": "ps:Part"},
        "columns": columns,
        "row_identity": dict(IBP_ROW_IDENTITY),
        "group_by": group_by,
        "rows": table,
    }
