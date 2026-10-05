"""The CASE half of ADR-0039: what opens at a trigger, and what opens when a definition ends.

`decision_table` evaluates one table against one set of facts. This module says WHICH table, and
WHICH facts, at the two moments ADR-0039 allows a choice -- and nothing else. It is pure: no
Restate, no I/O beyond reading the declared rows, so every rule here is sealable without a runtime.

## THREE DECLARATIONS, ALL DATA

* a TRIGGER row (``policy/triggers/`` + ``policy/overlays/*/triggers/``) names the selection table
  an event is decided by, the fact the case is keyed on, the facts that make two events one
  episode, and the facts a later table will need;
* a SELECTION table (an ordinary decision table) maps the event's facts to a definition;
* a CHAINING table declares ``after: <definition id>`` and maps that definition's terminal facts --
  the trigger, the ``outcome``, the chosen option's ``chosen.*`` attributes -- to the next
  definition or a declared terminal.

## `after:` IS DECLARED, NOT DERIVED FROM A NAME

The sample tables are called ``safety_acceptance_chaining`` and ``safety_concurrence_chaining``
and chain after ``safety_acceptance_direct`` and ``safety_concurrence``: no naming convention
recovers the first from its definition. A convention would also be a prefix registry, whose
misses pass through as "no table" -- which here ends a case. So the table says what it follows,
and two tables that say the same thing are refused.

## EVERY FAILURE IS A `CaseRoutingError`, AND THE RUNNER MAKES IT TERMINAL

A case that cannot be routed does not get better on retry, and has no safe default: "no row"
means nothing was chosen at the moment a decision was due.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from pydantic import Field

try:
    import decision_table as _dt  # type: ignore[no-redef]
    from workflow_definition import _Declared  # type: ignore[no-redef]
except ImportError:  # pragma: no cover -- import path differs by runtime
    from agent_fleet.restate_analyst import decision_table as _dt
    from agent_fleet.restate_analyst.workflow_definition import _Declared

#: A child instance's key is ``{case}~{n}``. A case key may not contain it, so no trigger can open
#: a case whose key is some other case's instance.
CHILD_SEP = "~"

#: Facts the runner writes at termination. A trigger fact of the same name would be overwritten
#: by -- or worse, mistaken for -- the definition's own outcome, so a collision is refused.
_RESERVED = ("outcome", "outcome_repeated", "chosen")

#: The scalar facts the runner itself MEASURES at termination (``chosen.*`` is the option's own).
#: A chaining table may match these, ``chosen.*``, or a fact some trigger requires -- nothing else
#: reaches it, and a table keyed on anything else refuses every case that ends there.
TERMINATION_FACTS = ("outcome", "outcome_repeated")


class CaseRoutingError(Exception):
    """A case could not be routed. ALWAYS terminal -- see the module docstring."""


class Trigger(_Declared):
    """One event a case can open on. Every fact field is a DOTTED path into the event."""

    trigger: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$")
    #: the decision table that selects the first definition
    selection: str = Field(..., min_length=1)
    #: the fact whose value IS the case key -- so a repeat of one event reaches the same case,
    #: and the dedupe is the key's, not a lookup's
    key: str = Field(..., min_length=1)
    #: facts that make two events ONE episode while a case for it is open
    episode: list[str] = Field(default_factory=list)
    #: facts a LATER table reads -- refused at intake, not after a human has already acted
    requires: list[str] = Field(default_factory=list)
    #: facts the event must CARRY, where any value is an answer: a null, a list, an empty mapping.
    #: ``requires`` refuses a null, and is right to for a fact a table matches on. Some facts' null
    #: IS the business state -- ``picture.nearest_spare`` is null when no site has stock -- and
    #: requiring them would refuse exactly the events the case exists for. Only an ABSENT key is
    #: refused here: the producer did not say. Lists live here too: a list is never a flat fact.
    carries: list[str] = Field(default_factory=list)
    #: the STUB VERB that pulls this event's newest picture from its source, read by a chaining
    #: row's ``refresh_input`` beside the revisions the source pushed. Absent: pushed only.
    pull: Optional[str] = Field(default=None, min_length=1)


# ── WHERE TRIGGERS LIVE ─────────────────────────────────────────────────────────────────────

def trigger_dirs() -> tuple[Path, list[Path]]:
    """``(seed, overlays)``, the same shape and env rule as ``decision_table.decision_dirs``."""
    env = os.environ.get("CASE_TRIGGER_DIR")
    if env:
        parts = [Path(p.strip()) for p in env.split(os.pathsep) if p.strip()]
        if parts:
            return parts[0], parts[1:]
    roots = _dt.candidate_decision_dirs(Path(__file__))
    root = next((r for r in roots if r.is_dir()), roots[0])
    return root / "triggers", sorted(p for p in (root / "overlays").glob("*/triggers") if p.is_dir())


def load_triggers() -> Dict[str, Trigger]:
    """Every composed trigger, by name, through the shared composer (ADR-0039 refuses a fourth).

    NO TWO OVERLAYS MAY DECLARE ONE TRIGGER. The composer lets a later overlay replace an earlier
    one, and between overlays "later" is name order -- a precedence nobody chose."""
    try:
        from iagent_mesh.declarations import compose_rows, read_rows
    except ImportError as exc:  # pragma: no cover -- the SDK is a hard dependency
        raise CaseRoutingError(f"iagent-mesh SDK is not importable: {exc}") from exc
    seed, overlays = trigger_dirs()
    seen: dict[str, Path] = {}
    try:
        for od in overlays:
            for key, (f, _raw) in read_rows(od, key_field="trigger").items():
                if key in seen:
                    raise CaseRoutingError(
                        f"trigger {key!r} is declared by two overlays ({seen[key]} and {f}); "
                        "name order is not a precedence anyone chose")
                seen[key] = f
        rows = compose_rows(seed, overlays, key_field="trigger",
                            builder=Trigger.model_validate, label="trigger")
    except CaseRoutingError:
        raise
    except Exception as exc:  # noqa: BLE001 -- re-raised terminal, with the paths named
        raise CaseRoutingError(
            f"could not compose triggers from {seed} + {[str(o) for o in overlays]}: {exc}") from exc
    return {r.trigger: r for r in rows}


def load_trigger(name: str) -> Trigger:
    triggers = load_triggers()
    if name not in triggers:
        raise CaseRoutingError(
            f"no trigger {name!r} is declared (have: {sorted(triggers)}). A case opens only on a "
            "declared trigger -- the route is never the caller's.")
    return triggers[name]


# ── FACTS ───────────────────────────────────────────────────────────────────────────────────

def flatten(obj: Any, prefix: str = "") -> Dict[str, Any]:
    """Every SCALAR leaf of a mapping, by dotted path. Lists are not facts: a table matches by
    equality, and a list equals nothing an author could write in a `when`."""
    out: Dict[str, Any] = {}
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, Mapping):
                out.update(flatten(v, path))
            elif v is None or isinstance(v, (str, int, float, bool)):
                out[path] = v
    return out


def _carried(facts: Mapping[str, Any], path: str) -> bool:
    node: Any = facts
    for seg in path.split("."):
        if not isinstance(node, Mapping) or seg not in node:
            return False
        node = node[seg]
    return True


def check_intake(trigger: Trigger, flat: Mapping[str, Any], case_key: str,
                 facts: Optional[Mapping[str, Any]] = None) -> None:
    """Refuse an event the case could not finish. Every check names the missing fact.

    ``facts`` is the event itself, unflattened: presence of a null, a list or a mapping cannot be
    read from ``flat``. A trigger that declares ``carries`` is refused without it -- a check that
    skipped would admit every event it exists to refuse."""
    if CHILD_SEP in case_key:
        raise CaseRoutingError(
            f"case key {case_key!r} contains {CHILD_SEP!r}, which is reserved for a case's own "
            "instances")
    clash = sorted(k for k in flat if k.split(".")[0] in _RESERVED)
    if clash:
        raise CaseRoutingError(
            f"trigger {trigger.trigger!r} event carries {clash}, which the runner writes at "
            "termination; a trigger fact may not stand in for an outcome")
    missing = [p for p in [trigger.key, *trigger.episode, *trigger.requires]
               if flat.get(p) in (None, "")]
    if missing:
        raise CaseRoutingError(
            f"trigger {trigger.trigger!r} event lacks {missing}. An absent fact is not a "
            f"wildcard -- the producer did not say (have: {sorted(flat)})")
    if trigger.carries:
        if facts is None:
            raise CaseRoutingError(
                f"trigger {trigger.trigger!r} declares `carries` {trigger.carries}, and intake was "
                "handed only the flattened event; presence cannot be read from it")
        absent = [p for p in trigger.carries if not _carried(facts, p)]
        if absent:
            raise CaseRoutingError(
                f"trigger {trigger.trigger!r} event does not carry {absent}. A null is an answer; "
                "an absent key is a producer that did not say")
    if str(flat[trigger.key]) != case_key:
        raise CaseRoutingError(
            f"case key {case_key!r} is not the event's {trigger.key} ({flat[trigger.key]!r}). The "
            "key IS the dedupe: a case keyed otherwise lets one event open two cases")


def episode_key(trigger: Trigger, flat: Mapping[str, Any]) -> Optional[str]:
    """The episode an event belongs to, or None when the trigger declares no episode."""
    if not trigger.episode:
        return None
    body = json.dumps([trigger.trigger, [flat[p] for p in trigger.episode]], sort_keys=True)
    return "ep-" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


def termination_facts(trigger_flat: Mapping[str, Any], envelope: Mapping[str, Any],
                      definition_id: str, transitions: Sequence[Mapping[str, Any]] = ()
                      ) -> Dict[str, Any]:
    """What a chaining table may read when `definition_id` ends: the trigger's facts, the
    definition's `outcome`, whether it has ended so before in this case, and the chosen option's
    attributes under ``chosen.``.

    ``outcome_repeated`` IS MEASURED HERE, NOT COUNTED IN A TABLE: a row matches by equality only
    (ADR-0039), so "the second refusal" needs a fact. It is a BOOL, not a count, so a table can be
    total over it -- the second refusal and every later one read the same. ``transitions`` is the
    case's record BEFORE this termination is appended."""
    facts = dict(trigger_flat)
    facts["outcome"] = envelope.get("outcome")
    facts["outcome_repeated"] = any(
        t.get("from") == definition_id and t.get("outcome") == facts["outcome"]
        for t in transitions)
    step = envelope.get("outcome_step_id")
    record = ((envelope.get("outputs") or {}).get(definition_id) or {}).get(step) or {}
    chosen = record.get("chosen") if isinstance(record, Mapping) else None
    if isinstance(chosen, Mapping):
        facts.update(flatten(chosen, "chosen"))
    return facts


# ── THE TWO CHOICES ─────────────────────────────────────────────────────────────────────────

def select(trigger: Trigger, flat: Mapping[str, Any]) -> Dict[str, Any]:
    """The definition this event opens. A terminal here is refused: a trigger that opens nothing
    must be a visible refusal, not a case that closed before it began."""
    try:
        d = _dt.decide(_dt.load_table(trigger.selection), flat)
    except _dt.DecisionError as exc:
        raise CaseRoutingError(f"trigger {trigger.trigger!r}: {exc}") from exc
    if d.terminal:
        raise CaseRoutingError(
            f"{trigger.selection} routes this event to the terminal {d.then!r}; a selection opens "
            "a definition, it cannot close a case that never opened")
    return {"then": d.then, "terminal": False, "row": d.row, "table": trigger.selection}


def chaining_index(tables: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Dict[str, Dict]:
    """``{definition id: the table that chains after it}``. Two tables for one definition are
    refused -- which of them a case followed would depend on dict order."""
    tables = _dt.load_tables() if tables is None else tables
    out: Dict[str, Dict] = {}
    for name, t in sorted(tables.items()):
        after = t.get("after")
        if not after:
            continue
        if after in out:
            raise CaseRoutingError(
                f"{out[after].get('decision')} and {name} both declare `after: {after}`")
        out[str(after)] = dict(t)
    return out


def chain(definition_id: str, facts: Mapping[str, Any],
          index: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """What opens when `definition_id` ends. A definition with no chaining table is refused: a
    case may end only at a terminal some table DECLARES, never at "nothing said what follows"."""
    index = chaining_index() if index is None else index
    table = index.get(definition_id)
    if table is None:
        raise CaseRoutingError(
            f"no decision table declares `after: {definition_id}`, so nothing says what follows "
            "it. A case may end only at a terminal a table declares")
    try:
        d = _dt.decide(table, facts)
    except _dt.DecisionError as exc:
        raise CaseRoutingError(f"after {definition_id}: {exc}") from exc
    return {"then": d.then, "terminal": d.terminal, "row": d.row, "table": table.get("decision"),
            "refresh_input": d.refresh_input}


# ── INPUT REVISIONS ─────────────────────────────────────────────────────────────────────────

def check_revision(trigger: Trigger, facts: Any, case_key: str,
                   episode: Optional[str]) -> Dict[str, Any]:
    """The flattened facts of a NEWER picture of the event a case opened on, or a refusal.

    A revision is the same event again -- the same key -- so it passes the same intake as the
    original, and it must stay in the case's episode: a picture that moved the fault to another
    asset is another case's event, not this case's newer one."""
    if not isinstance(facts, dict):
        raise CaseRoutingError(f"a revision carries the event's facts; got {type(facts).__name__}")
    flat = flatten(facts)
    check_intake(trigger, flat, case_key, facts=facts)
    moved = episode_key(trigger, flat)
    if moved != episode:
        raise CaseRoutingError(
            f"a revision of case {case_key!r} is in episode {moved!r}, and the case holds "
            f"{episode!r}; another fault or asset is another case's event")
    return flat


def received_at(revision: Any) -> datetime:
    """A revision's ``received_at`` as an aware instant, or a refusal: ordering is by it, and a
    naive time cannot be ordered against an aware one without inventing a zone."""
    at = revision.get("received_at") if isinstance(revision, dict) else None
    try:
        when = datetime.fromisoformat(at) if isinstance(at, str) else None
    except ValueError:
        when = None
    if when is None or when.tzinfo is None:
        raise CaseRoutingError(
            f"an input revision carries a `received_at` with its zone; got {at!r}")
    return when


def _same_revision(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return all(a.get(k) == b.get(k) for k in ("rev", "received_at", "facts"))


def _order(revision: Any) -> tuple:
    """Where a revision sorts: ``(received_at, pulled, rev)``. Refuses one without an integer
    ``rev``, the event's ``facts`` and an orderable ``received_at``."""
    rev = revision.get("rev") if isinstance(revision, dict) else None
    if not isinstance(rev, int) or isinstance(rev, bool) or not isinstance(revision.get("facts"), dict):
        raise CaseRoutingError(
            f"an input revision carries an integer `rev` and the event's `facts`; got {revision!r}")
    return (received_at(revision), revision.get("provenance") == "pulled", rev)


def newest_revision(current: Dict[str, Any], candidates: list) -> Optional[Dict[str, Any]]:
    """The candidate that sorts newest, if it sorts after ``current`` (the revision the case is
    on, ``rev``/``received_at``/``provenance``/``facts``); else None.

    ORDERED BY ``received_at``, ruled 2026-10-03: pushed and pulled pictures are revisions of the
    same artifact, so this is an ordering rule, not a merge -- the winner replaces the input whole.
    ON A TIE THE PULLED ONE WINS, because it was asked for. THEN ``rev``, ruled the same day: two
    revisions received in one clock tick still have an order, because ``keep_revision`` counts
    ``rev`` on arrival, so the later push is read. ``rev`` comes AFTER the pulled flag: a pulled
    revision's ``rev`` is its own source's count, not comparable with a pushed one, and putting it
    first would let a push beat a pull at the same instant.

    THE SAME REVISION REACHED TWICE IS NOT A TIE (ruled 2026-10-03). The shipped pull stub returns
    the kept revision itself, so it ties every push; letting "pulled" win that would record every
    pushed picture as pulled. A candidate identical (``rev``, ``received_at``, ``facts``) to
    another keeps the pushed provenance, and one identical to ``current`` is not newer."""
    floor = _order(current)
    best, best_key = None, None
    for c in candidates:
        if c is None:
            continue
        key = _order(c)
        if key <= floor or _same_revision(current, c):
            continue
        if best is not None and _same_revision(best, c):
            if best.get("provenance") == "pulled":   # whichever order they came in
                best, best_key = c, key
            continue
        if best is None or key > best_key:
            best, best_key = c, key
    return best
