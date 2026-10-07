"""Declared-query verbs — a mesh read whose question is DATA, served by engine-o by name.

A verb declared here is a set of SPARQL SELECTs, the run-context values that parameterise them, and
the shape the answer takes. The declaration is the whole of the verb: the runner renders its
parameters, engine-o executes its selects in the declared domain's graphs, and the runner renders
its ``returns`` from the shaped rows. NO PYTHON NAMES THE DOMAIN IT READS -- a maintenance walk and
any other read differ only in their YAML.

THE QUERY NEVER CROSSES THE WIRE. A caller names the verb and passes parameter values; engine-o
loads the declaration from its own baked policy tree. A route that executed caller-supplied SPARQL
would let any holder of a service token read any graph, and the domain scoping would be the
caller's to leave out.

WHAT THE LOADER REFUSES, and why each is a refusal rather than a convention:
  * anything but ``[PREFIX…] SELECT [DISTINCT] ?v… WHERE { … } [modifiers]`` -- engine-o's scope
    wrap (``execute_sparql``) injects the graph scope after the first ``WHERE {`` and closes it at
    the LAST ``}``, so a second group, a sub-select or a brace after the body would put the scope
    around the wrong text;
  * ``GRAPH``, ``SERVICE``, ``FROM`` -- each names its own dataset, and a GRAPH clause is exactly
    what makes engine-o SKIP its scope;
  * ``SELECT *`` and projected expressions -- an unbound variable must still be a key, present and
    None, so the projection has to be the declaration's;
  * a list (``many``/``values``) with no ``ORDER BY`` -- its order would be the store's;
  * a parameter no select reads, and a select named ``params``.

A PARAMETER VALUE THAT SPELLS A GRAPH CLAUSE IS REFUSED AT BUILD. engine-o decides whether to scope
by searching the WHOLE query text for ``GRAPH <`` / ``GRAPH ?``, literals included, so a value
carrying one would unscope the read it rides in. The loader cannot see values; the builder can.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

__all__ = [
    "DeclaredQueryError", "Select", "QueryVerb", "candidate_policy_roots", "policy_root",
    "verb_dirs", "load_query_verbs", "sparql_literal", "build_selects", "shape_rows",
    "shape_selects",
]

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_SHAPE = re.compile(
    r"^\s*(?P<prefixes>(?:PREFIX\s+[A-Za-z0-9_-]*:\s*<[^<>\s]*>\s*)*)"
    r"SELECT\s+(?P<distinct>(?:DISTINCT|REDUCED)\s+)?(?P<vars>(?:\?" + _IDENT + r"\s+)+)"
    r"WHERE\s*\{(?P<body>.*)\}(?P<tail>[^{}]*)$",
    re.IGNORECASE | re.DOTALL,
)
_FORBIDDEN = re.compile(r"\b(GRAPH|SERVICE|FROM)\b", re.IGNORECASE)
# engine-o's own rule (ontology_service/main.py, execute_sparql): a GRAPH clause is the keyword
# followed by an IRI or a variable. A VALUE that matches it would make engine-o skip its scope.
_SCOPE_SKIP = re.compile(r"\bGRAPH\s*[<?$]", re.IGNORECASE)


class DeclaredQueryError(ValueError):
    """A declaration, a parameter or an answer the verb cannot stand behind."""


class Select(BaseModel):
    """One SELECT and the shape its rows take.

    ``one`` -- None for no row, the row for one, REFUSED for more (picking would be the store's order).
    ``many`` -- every row, each with every projected variable (None where unbound).
    ``values`` -- the single projected variable's value from every row, none of them unbound."""

    model_config = ConfigDict(extra="forbid")

    sparql: str = Field(..., min_length=1)
    cardinality: Literal["one", "many", "values"]
    integers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _shape(self) -> "Select":
        m = _SHAPE.match(self.sparql)
        if not m:
            raise ValueError(
                "a declared select is `[PREFIX…] SELECT [DISTINCT] ?v… WHERE { … } [modifiers]` "
                "with no brace after its body -- engine-o scopes the first WHERE group and closes "
                "the scope at the last brace")
        bad = sorted({w.upper() for w in _FORBIDDEN.findall(m.group("body") + m.group("tail"))})
        if bad:
            raise ValueError(f"{bad} name a dataset of their own; a declared select reads only the "
                             "declared domain's graphs")
        if re.search(r"\bSELECT\b", m.group("body"), re.IGNORECASE):
            raise ValueError("a sub-select would put engine-o's scope around the wrong group")
        proj = self.projected
        if len(set(proj)) != len(proj):
            raise ValueError(f"projected twice: {proj}")
        stray = sorted(set(self.integers) - set(proj))
        if stray:
            raise ValueError(f"integers {stray} are not projected ({proj})")
        if self.cardinality == "values" and len(proj) != 1:
            raise ValueError(f"`values` takes exactly one projected variable, not {proj}")
        if self.cardinality != "one" and not re.search(r"\bORDER\s+BY\b", m.group("tail"),
                                                       re.IGNORECASE):
            raise ValueError(f"a `{self.cardinality}` select has no ORDER BY, so its order "
                             "would be the store's")
        return self

    @property
    def projected(self) -> list[str]:
        m = _SHAPE.match(self.sparql)
        return [v[1:] for v in m.group("vars").split()] if m else []


class QueryVerb(BaseModel):
    """A declared-query verb (see the module docstring). Honoured only from the registry."""

    model_config = ConfigDict(extra="forbid")

    verb: str = Field(..., min_length=1)
    #: The single decider's object: ``can_invoke(caller, capability)`` before engine-o is asked.
    capability: str = Field(..., min_length=1)
    #: Whose graphs the selects read: ``http://internal/{domain}`` and ``…{domain}_INSTANCES``.
    domain: str = Field(..., pattern=r"^[A-Za-z0-9_]+$")
    #: Parameter name -> a run-context template. Rendered by the runner, bound by engine-o.
    params: dict[str, str] = Field(default_factory=dict)
    selects: dict[str, Select] = Field(..., min_length=1)
    returns: Any

    @field_validator("params")
    @classmethod
    def _param_names(cls, v: dict[str, str]) -> dict[str, str]:
        bad = sorted(k for k in v if not re.fullmatch(_IDENT, k))
        if bad:
            raise ValueError(f"parameter names {bad} are not SPARQL variable names")
        return v

    @model_validator(mode="after")
    def _wiring(self) -> "QueryVerb":
        bad = sorted(k for k in self.selects if not re.fullmatch(_IDENT, k) or k == "params")
        if bad:
            raise ValueError(f"select names {bad}: an identifier, and never `params` (the "
                             "returns template reads `params` and every select by name)")
        unread = sorted(p for p in self.params
                        if not any(re.search(r"\?" + p + r"\b", s.sparql)
                                   for s in self.selects.values()))
        if unread:
            raise ValueError(f"parameters {unread} are read by no select")
        for name, s in self.selects.items():
            clash = sorted(set(s.projected) & set(self.params))
            if clash:
                raise ValueError(f"select {name!r} projects its own parameter(s) {clash}")
        return self


def candidate_policy_roots(module_path: Path) -> list[Path]:
    """Repo layout (``agent_fleet/utils/…`` -> ``<repo>/policy``), then the flattened image
    (``/app/utils/…`` -> ``/app/policy``). The same two layouts as
    ``workflow_definition.candidate_definition_dirs``, one directory shallower."""
    here = module_path.resolve()
    out: list[Path] = []
    if len(here.parents) >= 3:
        out.append(here.parents[2] / "policy")
    out.append(here.parents[1] / "policy")
    return out


def policy_root() -> Path:
    """The policy tree the runner's registry reads: the parent of ``WORKFLOW_DEFINITIONS_DIR``'s
    first entry when set (``workflow_definition.verb_dirs`` takes the same parent), else the first
    existing candidate."""
    env = os.environ.get("WORKFLOW_DEFINITIONS_DIR")
    if env:
        first = next((p.strip() for p in env.split(os.pathsep) if p.strip()), "")
        if first:
            return Path(first).parent
    cands = candidate_policy_roots(Path(__file__))
    return next((c for c in cands if c.is_dir()), cands[0])


def verb_dirs(root: Path) -> list[Path]:
    """``<root>/verbs`` then every ``<root>/overlays/*/verbs`` in name order."""
    return [root / "verbs", *sorted(p for p in (root / "overlays").glob("*/verbs") if p.is_dir())]


def load_query_verbs(dirs: Iterable[Path]) -> dict[str, QueryVerb]:
    """Every declared-query verb, keyed by verb. A file that says ``stub`` is the stub registry's
    and is skipped here; any other file must be a valid QueryVerb. One verb declared twice is
    refused -- name order would otherwise choose which question a run asks."""
    out: dict[str, QueryVerb] = {}
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.yaml")):
            try:
                doc = yaml.safe_load(p.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                raise DeclaredQueryError(f"{p}: unreadable verb: {exc}") from exc
            if isinstance(doc, dict) and "stub" in doc:
                continue
            try:
                v = QueryVerb.model_validate(doc)
            except ValidationError as exc:
                raise DeclaredQueryError(f"{p}: invalid declared-query verb:\n{exc}") from exc
            if v.verb in out:
                raise DeclaredQueryError(f"{p}: declared-query verb {v.verb!r} is declared twice")
            out[v.verb] = v
    return out


def sparql_literal(value: str) -> str:
    """A SPARQL string literal (short form): backslash, quote and the line breaks escaped."""
    esc = (value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
           .replace("\r", "\\r").replace("\t", "\\t"))
    return f'"{esc}"'


def build_selects(verb: QueryVerb, params: dict) -> dict[str, str]:
    """Each select with its parameters bound as an inline ``VALUES`` row at the top of its group.

    The values must be exactly the declared parameters, each a non-blank string that does not
    spell a GRAPH clause (module docstring)."""
    params = dict(params or {})
    missing = sorted(set(verb.params) - set(params))
    extra = sorted(set(params) - set(verb.params))
    if missing or extra:
        raise DeclaredQueryError(f"verb {verb.verb!r} takes parameters {sorted(verb.params)}; "
                                 f"missing {missing}, undeclared {extra}")
    for k, v in params.items():
        if not isinstance(v, str) or not v.strip():
            raise DeclaredQueryError(f"parameter {k!r} of {verb.verb!r} is {v!r}: a declared "
                                     "query binds non-blank strings only")
        if _SCOPE_SKIP.search(v):
            raise DeclaredQueryError(f"parameter {k!r} of {verb.verb!r} spells a GRAPH clause, "
                                     "which would make engine-o skip the domain scope")
    out: dict[str, str] = {}
    for name, s in verb.selects.items():
        m = _SHAPE.match(s.sparql)
        used = [p for p in verb.params if re.search(r"\?" + p + r"\b", m.group("body"))]
        values = ""
        if used:
            values = (f" VALUES ({' '.join('?' + p for p in used)}) "
                      f"{{ ({' '.join(sparql_literal(params[p]) for p in used)}) }}")
        out[name] = (f"{m.group('prefixes')}SELECT {m.group('distinct') or ''}"
                     f"{' '.join('?' + v for v in s.projected)} WHERE {{{values}"
                     f"{m.group('body')}}}{m.group('tail')}")
    return out


def shape_rows(name: str, select: Select, rows: list[dict]) -> Any:
    """The select's rows in its declared shape. Every projected variable is a key; an unbound one
    is None; an ``integers`` value that is not an integer is refused rather than passed on."""
    shaped: list[dict] = []
    for row in rows or []:
        r: dict[str, Optional[object]] = {}
        for var in select.projected:
            val = row.get(var)
            if val is not None and var in select.integers:
                try:
                    val = int(str(val))
                except ValueError:
                    raise DeclaredQueryError(
                        f"select {name!r}: ?{var} is {val!r}, declared an integer") from None
            r[var] = val
        shaped.append(r)
    if select.cardinality == "many":
        return shaped
    if select.cardinality == "values":
        var = select.projected[0]
        if any(r[var] is None for r in shaped):
            raise DeclaredQueryError(f"select {name!r}: ?{var} is unbound in a row of a `values` "
                                     "select")
        return [r[var] for r in shaped]
    if len(shaped) > 1:
        raise DeclaredQueryError(
            f"select {name!r} is declared `one` and matched {len(shaped)} rows; choosing one "
            "would be the store's order")
    return shaped[0] if shaped else None


def shape_selects(verb: QueryVerb, rows_by_select: dict[str, list[dict]]) -> dict[str, Any]:
    return {name: shape_rows(name, s, rows_by_select.get(name) or [])
            for name, s in verb.selects.items()}
