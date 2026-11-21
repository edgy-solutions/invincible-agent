"""What a follow-on task must record before it can be completed (architect ruling 2026-11-19).

    "a follow-on task cannot complete without what it exists to settle ... At review these are
    optional, and a blank is written as the ruled blank text, never left empty."

THIS MODULE KNOWS THE MECHANISM AND NONE OF THE CASES (config names the case, ruled 10-30).
A discriminator key in the task's payload, a declared list of fields per discriminator value, a
field's type, the verbs that require the fields, and the blank text: all of it is read from the
`task_completion/` declaration family. No kind, disposition, field name or blank text is in this
file.

WHERE THE DECLARATION LIVES. A sibling family beside `task_kinds/`, never inside it: the SDK's
`TaskKind` row is `extra="forbid"`, so the key cannot ride in a task-kind row, and changing the SDK
is a cross-repo release. The family is composed by the SDK's own generic composer
(`iagent_mesh.declarations.compose_rows`, ADR-0036: overlay rows replace or delete by key):

  * seed:    `policy/task_completion/` (structural species only; domain rows never enter it);
  * overlay: for each entry of `TASK_KIND_OVERLAY_DIRS` (the variable `human_tasks._declared_kinds`
             already reads, split on `os.pathsep`), the directory `<entry's parent>/task_completion`
             when it is a directory. A missing sibling declares no completion fields. There is no
             new environment variable and no chart change: the overlay's task_kinds directory
             already names the overlay's root.

AN UNREADABLE DECLARATION IS READ AT LOAD AND REFUSES ONLY WHAT IT MUST (architect ruling
2026-11-21: "At start: the BFF checks the declarations when it loads them, and reports not ready
if they can't be read. That makes a broken deployment visible before anyone acts. At act time: if
they become unreadable later, refuse only decisions that complete a task and could require
fields. A rejection goes through.").
  * AT START the BFF lifespan calls `declarations_unreadable_reason()` and logs an error; it never
    raises, so boot does not depend on it. `GET /ready` (the readiness probe only; `/health` stays
    the liveness probe, so a config fault never restart-loops the pod) answers 503
    `completion_declarations: <exception class name>` while the family does not compose, and 200
    once it does, without a restart (nothing unreadable is cached).
  * AT ACT TIME, when the family does not compose, `get_declarations` raises
    `CompletionDeclarationUnreadable`. The act route then asks `fields_could_be_required(kind,
    decision)`: a TOLERANT scan of the same files (no model validation) that is True when the
    decision is named in a `required_on` of any row of that kind (deleted or not: conservative),
    and True for every decision when a row cannot be attributed (unparseable file, not a mapping,
    no usable `kind`, a `required_on` that is not a list of non-empty strings, or a live row
    whose `required_on` is absent or empty). True refuses with 409
    `completion_declaration_unreadable`; False lets the act proceed with no fields required.
A malformed row is caught before deploy by `policy/sync/validate_policy.py`, which composes this
family with `compose_completion` directly.

`TASK_KIND_OVERLAY_DIRS` UNSET IS NOT UNREADABLE: it composes the SEED ALONE, after a loud warning.
That is `human_tasks._declared_kinds`'s reading of the same variable: seeded species answer from
their own rows, and a domain species the seed does not carry is refused at the kind gate before
it reaches this module. So no domain task completes unchecked through an unset variable.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from iagent_mesh.declarations import DeclarationError, compose_rows
from pydantic import BaseModel, ConfigDict, model_validator

logger = logging.getLogger(__name__)

OVERLAY_DIRS_ENV = "TASK_KIND_OVERLAY_DIRS"  # the same variable as human_tasks._OVERLAY_DIRS_ENV
FAMILY_DIR = "task_completion"
SEED_DIR = Path(__file__).resolve().parents[2] / "policy" / FAMILY_DIR

FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
TEXT_MAX = 120

#: The generic types. A declaration names one of these; the code never names a field.
TYPES = ("text", "positive_integer", "date")

_DIGITS = re.compile(r"^[0-9]+$")
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class CompletionDeclarationError(DeclarationError):
    """A task_completion row is invalid. Names the file (the base class's contract)."""


class CompletionField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    label: str
    type: str


class CompletionDeclaration(BaseModel):
    """One kind's completion contract. The validators are the §1 checks; the subset-of-`accepts`
    check needs the task-kind row and so lives in the policy validator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    by: str
    required_on: tuple[str, ...]
    blank: str
    fields: dict[str, tuple[CompletionField, ...]]

    @model_validator(mode="after")
    def _is_well_formed(self) -> "CompletionDeclaration":
        k = self.kind
        if not isinstance(self.by, str) or not self.by.strip():
            raise ValueError(f"kind {k!r}: key 'by' must be a non-empty string")
        if not isinstance(self.blank, str) or not self.blank.strip():
            raise ValueError(f"kind {k!r}: key 'blank' must be a non-empty string")
        if not self.required_on or any(not isinstance(v, str) or not v for v in self.required_on):
            raise ValueError(f"kind {k!r}: key 'required_on' must name at least one verb")
        for value, flds in self.fields.items():
            seen: set[str] = set()
            for f in flds:
                if not FIELD_NAME.match(f.name):
                    raise ValueError(f"kind {k!r}: key 'fields.{value}' has a field name "
                                     f"{f.name!r} outside {FIELD_NAME.pattern}")
                if not f.label.strip():
                    raise ValueError(f"kind {k!r}: key 'fields.{value}.{f.name}.label' is empty")
                if f.type not in TYPES:
                    raise ValueError(f"kind {k!r}: key 'fields.{value}.{f.name}.type' is "
                                     f"{f.type!r}, not a known type")
                if f.name in seen:
                    raise ValueError(f"kind {k!r}: key 'fields.{value}' declares {f.name!r} "
                                     f"more than once")
                seen.add(f.name)
        return self


def _build(raw: dict) -> CompletionDeclaration:
    return CompletionDeclaration(**raw)


def compose_completion(seed_dir: Path | str, overlay_dirs=()) -> dict[str, CompletionDeclaration]:
    """PURE (filesystem only). kind -> declaration, composed by the SDK's generic composer."""
    rows = compose_rows(seed_dir, overlay_dirs, key_field="kind", builder=_build,
                        label="task completion declaration", error=CompletionDeclarationError)
    return {r.kind: r for r in rows}


def overlay_dirs_from_env(environ: Optional[Mapping[str, str]] = None) -> Optional[list[Path]]:
    """The completion overlays derived from `TASK_KIND_OVERLAY_DIRS`; None when it is unset."""
    raw = ((environ if environ is not None else os.environ).get(OVERLAY_DIRS_ENV) or "").strip()
    if not raw:
        return None
    out = []
    for entry in (s.strip() for s in raw.split(os.pathsep)):
        if not entry:
            continue
        sibling = Path(entry).parent / FAMILY_DIR
        if sibling.is_dir():
            out.append(sibling)
    return out


_CACHE: Optional[dict[str, CompletionDeclaration]] = None
_UNREADABLE = object()


def reset_cache() -> None:
    """For tests: forget what was composed."""
    global _CACHE
    _CACHE = None


class CompletionDeclarationUnreadable(RuntimeError):
    """The completion declarations did not compose. Completion is refused until they do."""


def get_declarations() -> dict[str, CompletionDeclaration]:
    """The composed declarations, cached. Raises `CompletionDeclarationUnreadable` (after a loud
    error log, and without caching) when they do not compose."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    overlays = overlay_dirs_from_env()
    if overlays is None:
        logger.warning(
            "%s is unset, so task completion declarations are the SEED HALF ONLY: a domain "
            "species is refused at the kind gate. Set it to the deployment's overlay task_kinds "
            "directory.", OVERLAY_DIRS_ENV)
        overlays = []
    try:
        _CACHE = compose_completion(SEED_DIR, overlays)
    except Exception as exc:  # noqa: BLE001 -- every failure to compose is the same refusal
        logger.error(
            "could not compose task completion declarations from %s + %s (%s: %s): NO task "
            "can be completed until this is fixed.",
            SEED_DIR, overlays, type(exc).__name__, exc)
        raise CompletionDeclarationUnreadable(f"{type(exc).__name__}: {exc}") from exc
    return _CACHE


def declarations_unreadable_reason() -> Optional[str]:
    """None when the declarations read; otherwise the CLASS NAME of the underlying cause and
    nothing else (no path, no message: the readiness route serves it unauthenticated)."""
    try:
        get_declarations()
    except CompletionDeclarationUnreadable as exc:
        cause = exc.__cause__
        return type(cause).__name__ if cause is not None else type(exc).__name__
    return None


def files_compose_error() -> Optional[str]:
    """None when the files on disk compose NOW; otherwise `<class>: <message>` of the failure.

    Uncached, and it neither reads nor fills the cache: `get_declarations` caches a clean read for
    the life of the process, so once it has read, a later break on disk changes nothing this
    process uses and nothing it reports. This is the only way to see such a break before a
    restart. Silent itself (the caller decides what to log), and quiet about an unset overlay
    variable, which `get_declarations` already warns about once."""
    try:
        compose_completion(SEED_DIR, overlay_dirs_from_env() or [])
    except Exception as exc:  # noqa: BLE001 -- every failure to compose is the same break
        return f"{type(exc).__name__}: {exc}"
    return None


def _verbs_attributable(verbs: object, *, tombstone: bool) -> bool:
    """Can this row's `required_on` be read as the verbs it names?

    A live row needs a non-empty list of non-empty strings: the strict model refuses an absent,
    misspelled (so absent), empty or `['']` value, so a live row without one is a row whose
    verbs were MEANT and cannot be read; reading it as naming no verb would let a decision it
    names complete with no fields. A tombstone (`deleted: true`) may omit the key. A list
    holding an empty or non-string entry is unreadable on any row."""
    if verbs is None:
        return tombstone
    if not isinstance(verbs, list) or not all(isinstance(v, str) and v for v in verbs):
        return False
    return bool(verbs) or tombstone


def fields_could_be_required(kind: str, decision: str) -> bool:
    """For use ONLY when the strict compose failed: could `decision` on `kind` require fields?

    A tolerant scan of the directories `get_declarations` composes (the seed, then each overlay),
    with the composer's own file glob and no model validation. True when `decision` is in the
    union of the `required_on` lists of every row of `kind` (any layer, deleted or not:
    conservative); True for every decision when a row cannot be attributed, because a row whose
    verbs cannot be read could name this one. False otherwise."""
    import yaml
    overlays = overlay_dirs_from_env() or []
    for directory in [SEED_DIR, *overlays]:
        try:
            files = sorted(Path(directory).glob("*.yaml"))
        except OSError:
            files = []
        for f in files:
            try:
                raw = yaml.safe_load(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 -- a file that cannot be read is unattributable
                raw = _UNREADABLE
            row_kind = raw.get("kind") if isinstance(raw, dict) else None
            verbs = raw.get("required_on") if isinstance(raw, dict) else None
            tombstone = isinstance(raw, dict) and raw.get("deleted") is True
            if (not isinstance(raw, dict) or not isinstance(row_kind, str) or not row_kind
                    or not _verbs_attributable(verbs, tombstone=tombstone)):
                logger.warning("task completion row %s cannot be attributed to a kind: every "
                               "decision is treated as one that may need fields", f.name)
                return True
            if row_kind == kind and decision in (verbs or []):
                return True
    return False


def declaration_for_kind(kind: str) -> Optional[CompletionDeclaration]:
    """The kind's declaration, or None when it declares none. Raises
    `CompletionDeclarationUnreadable` when the family does not compose."""
    return get_declarations().get(kind)


def as_wire(decl: CompletionDeclaration) -> dict:
    """The shape a client reads (types as strings)."""
    return {
        "by": decl.by,
        "required_on": list(decl.required_on),
        "blank": decl.blank,
        "fields": {v: [{"name": f.name, "label": f.label, "type": f.type} for f in flds]
                   for v, flds in decl.fields.items()},
    }


def _payload_dict(payload: Any) -> dict:
    if isinstance(payload, (str, bytes)):
        import json
        try:
            payload = json.loads(payload)
        except ValueError:
            return {}
    return payload if isinstance(payload, dict) else {}


def declared_for_payload(decl: CompletionDeclaration, payload: Any) -> tuple[CompletionField, ...]:
    """The field list the payload's discriminator value selects; empty when it selects none."""
    value = _payload_dict(payload).get(decl.by)
    return decl.fields.get(value, ()) if isinstance(value, str) else ()


def _clean(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return v.strip()
    return v


def _is_the_blank(decl: CompletionDeclaration, value: Any) -> bool:
    """Whether a CLEANED value is the declaration's blank text, in any capitalisation: the blank
    typed in another case still says nothing was settled, so it never stands in for a value."""
    return isinstance(value, str) and value.casefold() == decl.blank.strip().casefold()


def value_ok(type_: str, value: Any) -> bool:
    """Whether a CLEANED value satisfies a generic type."""
    if type_ == "text":
        return isinstance(value, str) and bool(value) and len(value) <= TEXT_MAX \
            and "\n" not in value and "\r" not in value
    if type_ == "positive_integer":
        return isinstance(value, str) and bool(_DIGITS.match(value)) and int(value) >= 1
    if type_ == "date":
        if not (isinstance(value, str) and _ISO_DATE.match(value)):
            return False
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True
    return False


def written_at_register(decl: CompletionDeclaration, payload: Optional[dict]) -> Optional[dict]:
    """The payload as registered: `fields` holds EVERY declared name, a blank written as the
    declaration's blank text, undeclared supplied names dropped. Returns the payload unchanged
    (the same object) when the discriminator selects no declared fields."""
    declared = declared_for_payload(decl, payload)
    if not declared:
        return payload
    base = _payload_dict(payload)
    supplied = base.get("fields")
    supplied = supplied if isinstance(supplied, dict) else {}
    out = {}
    for f in declared:
        v = _clean(supplied.get(f.name))
        out[f.name] = v if isinstance(v, str) and v and not _is_the_blank(decl, v) else decl.blank
    return {**base, "fields": out}


def finals_at_act(decl: CompletionDeclaration, payload: Any, supplied: Optional[dict]
                  ) -> tuple[dict, list[str], list[str]]:
    """(finals, missing, invalid) for completing a task. final = the act's value when supplied
    non-blank, else the value recorded at review. A value that is absent, blank, or the blank
    text is MISSING; a present one that fails its type is INVALID."""
    declared = declared_for_payload(decl, payload)
    base = _payload_dict(payload).get("fields")
    base = base if isinstance(base, dict) else {}
    sup = supplied if isinstance(supplied, dict) else {}
    finals: dict = {}
    missing: list[str] = []
    invalid: list[str] = []
    for f in declared:
        v = _clean(sup.get(f.name))
        if v is None or v == "":
            v = _clean(base.get(f.name))
        if v is None or v == "" or _is_the_blank(decl, v):
            missing.append(f.name)
            continue
        if not value_ok(f.type, v):
            invalid.append(f.name)
            continue
        finals[f.name] = v
    return finals, missing, invalid
