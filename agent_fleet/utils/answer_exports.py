"""An ANSWER-EXPORT PROFILE as an overlay row (`policy/exports/<name>.yaml`).

A profile declares one deliverable that has one row per answer: which verbs' answers it takes
(`kinds`), which recipient scopes receive it (`recipients`), and which field of an answer lands
in which column (`columns`). The BFF decides WHICH answers a recipient takes by `kinds`; engine-cost
renders and writes the file by `render`. Neither computes anything: every cell is a value an
answer already carried.

It lives in `utils` because both the BFF and engine-cost import it (engine images flatten
`agent_fleet/utils` to `/app/utils`; the BFF keeps the package path -- the import dance below).

── THE HEADER IS SHARED ─────────────────────────────────────────────────────────────────────
A row opens with `name`, `format`, `scope`, `label`: the same four keys fin's CDRL profiles open
with and the shape cortex asked lane/01 for (`[{name, format, scope, label}]`). Here `scope` is
`answer` (one row per answer).

── WHAT A ROW MAY NOT SAY, AND WHERE IT IS REFUSED ──────────────────────────────────────────
Every refusal is at LOAD, names the FILE and the key, and ALL of them are listed in one error
(a profile set that loaded half is a deliverable that exists for some deployments only):

* a key outside the closed set; `format` other than csv|json; `scope` other than `answer`;
* `kinds` missing, empty, duplicated, or an entry that is not `mesh:<Verb>`;
* `recipients` missing or empty; a recipient scope in more than one profile (naming both);
* `columns` missing or empty, a `field` outside `ANSWER_FIELDS`, an `as` missing or repeated.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from iagent_mesh.declarations import DeclarationError, compose_rows

_SEED_ENV = "EXPORT_PROFILE_POLICY_DIR"
_OVERLAY_ENV = "EXPORT_PROFILE_OVERLAY_DIRS"


def _default_seed_dir() -> Path:
    """`<repo>/policy/exports`, found by walking up rather than counting levels: in the flattened
    engine image this file is `/app/utils/answer_exports.py` and a fixed `parents[2]` is wrong
    there (the way `finance_agent/export_profiles.py` finds its own seed)."""
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / "policy" / "exports"
        if candidate.is_dir():
            return candidate
    return Path("/app/policy/exports")


EXPORT_PROFILE_POLICY_DIR_DEFAULT = _default_seed_dir()


def EXPORT_PROFILE_POLICY_DIR() -> Path:  # noqa: N802 -- named like the constants it parallels
    """The seed directory, read from the environment at CALL time."""
    return Path(os.getenv(_SEED_ENV) or str(EXPORT_PROFILE_POLICY_DIR_DEFAULT))


def EXPORT_PROFILE_OVERLAY_DIRS() -> list[Path]:  # noqa: N802
    return [Path(p) for p in os.getenv(_OVERLAY_ENV, "").split(os.pathsep) if p]


#: The fields of an answer a column may take. CLOSED: a name outside it is a load refusal.
#:   answer_id   the answer artifact's id
#:   question    the question the answer was produced for (`question_text`)
#:   summary     the answer's one-line summary
#:   verb        the verb IRI the answer was routed to (`mesh:...`)
#:   subject     the intent's subject URI, or empty when the intent named none
#:   program     the program the answer belongs to (`origin_program`)
#:   status      the answer artifact's status
#:   valid_as_of the date the answer is valid as of, ISO 8601
ANSWER_FIELDS = ("answer_id", "question", "summary", "verb", "subject", "program", "status",
                 "valid_as_of")

#: The `format` vocabulary and the media type each is served as.
MEDIA_TYPES = {"csv": "text/csv; charset=utf-8", "json": "application/json"}

#: The header `scope` vocabulary, CLOSED to what this loader renders. lane/01's ingest-review
#: export shares this header and widens it to `row` / `notice` when it adds its kind.
SCOPES = frozenset({"answer"})

_VERB = re.compile(r"^mesh:[A-Za-z][A-Za-z0-9]*$")
_TOP_KEYS = frozenset({"name", "format", "scope", "label", "kinds", "recipients", "columns"})
_COLUMN_KEYS = frozenset({"field", "as"})


class AnswerExportError(DeclarationError):
    """An answer-export profile is invalid. Names the FILE and the key."""


@dataclass(frozen=True)
class Column:
    field: str
    as_: str


@dataclass(frozen=True)
class AnswerExportProfile:
    name: str
    format: str
    scope: str
    label: str
    kinds: tuple[str, ...]
    recipients: tuple[str, ...]
    columns: tuple[Column, ...]
    source: str = ""            # the file the winning row came from

    def header(self) -> dict[str, str]:
        return {"name": self.name, "format": self.format, "scope": self.scope, "label": self.label}


def _build(raw: Mapping[str, Any], source: str) -> AnswerExportProfile:
    """Raises ValueError listing every problem of THIS row, each naming its key."""
    problems: list[str] = []
    extra = sorted(set(raw) - _TOP_KEYS)
    if extra:
        problems.append(f"unknown key(s) {extra}; the keys are {sorted(_TOP_KEYS)}")
    for key in ("name", "format", "scope", "label", "kinds", "recipients", "columns"):
        if raw.get(key) in (None, "", [], {}):
            problems.append(f"missing required key {key!r}")
    fmt, scope = raw.get("format"), raw.get("scope")
    if fmt not in (None, "") and fmt not in MEDIA_TYPES:
        problems.append(f"format {fmt!r}; the formats are {sorted(MEDIA_TYPES)}")
    if scope not in (None, "") and scope not in SCOPES:
        problems.append(f"scope {scope!r}; the scopes are {sorted(SCOPES)}")

    kinds = raw.get("kinds")
    if kinds not in (None, [], "") and not isinstance(kinds, list):
        problems.append("kinds is not a list; kinds are listed explicitly, there is no 'all'")
        kinds = None
    for k in kinds or []:
        if not isinstance(k, str) or not _VERB.match(k):
            problems.append(f"kinds entry {k!r} is not a verb IRI like 'mesh:planSchedule'; "
                            "kinds are listed explicitly, no wildcard or 'all'")
    if kinds and len(set(map(str, kinds))) != len(kinds):
        dup = sorted({str(k) for k in kinds if [str(x) for x in kinds].count(str(k)) > 1})
        problems.append(f"kinds repeats {dup}")

    recipients = raw.get("recipients")
    if recipients not in (None, [], "") and not isinstance(recipients, list):
        problems.append("recipients is not a list")
        recipients = None
    for r in recipients or []:
        if not isinstance(r, str) or not r.strip():
            problems.append(f"recipients entry {r!r} is not a recipient scope")

    columns: list[Column] = []
    cols = raw.get("columns")
    if cols not in (None, [], "") and not isinstance(cols, list):
        problems.append("columns is not a list")
        cols = None
    seen_as: set[str] = set()
    for col in cols or []:
        if not isinstance(col, dict):
            problems.append(f"columns entry {col!r} is not {{field, as}}")
            continue
        bad = sorted(set(col) - _COLUMN_KEYS)
        if bad:
            problems.append(f"columns entry carries {bad}; the keys are {sorted(_COLUMN_KEYS)}")
        fld, as_ = col.get("field"), col.get("as")
        if fld not in ANSWER_FIELDS:
            problems.append(f"columns field {fld!r} is outside the answer fields {list(ANSWER_FIELDS)}")
        if not isinstance(as_, str) or not as_:
            problems.append(f"columns entry for field {fld!r} has no 'as'")
        elif as_ in seen_as:
            problems.append(f"columns 'as' {as_!r} is used twice")
        else:
            seen_as.add(as_)
        if fld in ANSWER_FIELDS and isinstance(as_, str) and as_:
            columns.append(Column(fld, as_))
    if problems:
        raise ValueError("; ".join(problems))
    return AnswerExportProfile(
        name=str(raw["name"]), format=str(fmt), scope=str(scope), label=str(raw["label"]),
        kinds=tuple(kinds), recipients=tuple(recipients), columns=tuple(columns), source=source,
    )


def load_answer_export_profiles(
    policy_dir: Path | str | None = None,
    overlay_dirs: Iterable[Path | str] | None = None,
) -> dict[str, AnswerExportProfile]:
    """Every answer-export profile, composed (ADR-0036) and validated, by `name`.

    ONE ERROR LISTS EVERY REFUSAL (each row's problems, then a recipient scope claimed by two
    profiles). NO ROWS IS A VALID ANSWER: an absent directory composes to none.
    """
    d = Path(policy_dir) if policy_dir is not None else EXPORT_PROFILE_POLICY_DIR()
    ov = list(overlay_dirs) if overlay_dirs is not None else EXPORT_PROFILE_OVERLAY_DIRS()
    errors: list[str] = []

    def _builder(raw: dict) -> Optional[AnswerExportProfile]:
        name = raw.get("name")
        try:
            return _build(raw, str(name))
        except ValueError as exc:
            errors.append(f"export profile {name!r}: {exc}")
            return None

    rows = compose_rows(d, ov, key_field="name", builder=_builder,
                        label="answer export profile", error=AnswerExportError)
    built = [r for r in rows if r is not None]

    owner: dict[str, str] = {}
    for p in built:
        for scope in p.recipients:
            if scope in owner:
                errors.append(
                    f"recipient {scope!r} is named by both {owner[scope]!r} and {p.name!r}; a "
                    f"recipient receives exactly one profile")
            else:
                owner[scope] = p.name
    if errors:
        raise AnswerExportError("answer export profiles refused:\n  " + "\n  ".join(errors))
    return {p.name: p for p in built}


def profile_for_recipient(
    profiles: Mapping[str, AnswerExportProfile], scope: str,
) -> Optional[AnswerExportProfile]:
    """The profile that names `scope` as a recipient, or None."""
    for name in sorted(profiles):
        if scope in profiles[name].recipients:
            return profiles[name]
    return None


def render(profile: AnswerExportProfile, rows: list[dict]) -> bytes:
    """The file's bytes. `rows` are dicts keyed by `ANSWER_FIELDS`, in the order to write.

    DETERMINISTIC: the same rows give the same bytes. csv is a header row from `as`, CRLF, no BOM,
    `None` written empty. json is `{"profile": name, "rows": [...]}` with keys in column order,
    `None` omitted, indent 2, non-ASCII kept, and a trailing newline.
    """
    if profile.format == "csv":
        buf = io.StringIO(newline="")
        w = csv.writer(buf, lineterminator="\r\n")
        w.writerow([c.as_ for c in profile.columns])
        for row in rows:
            w.writerow(["" if row.get(c.field) is None else row.get(c.field)
                        for c in profile.columns])
        return buf.getvalue().encode("utf-8")
    if profile.format == "json":
        body = {"profile": profile.name, "rows": [
            {c.as_: row.get(c.field) for c in profile.columns if row.get(c.field) is not None}
            for row in rows]}
        return (json.dumps(body, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    raise ValueError(f"format {profile.format!r} is not renderable")  # unreachable past load


# ── THE FILE'S NAME, AND THE NAME BACK TO ITS RECIPIENT ───────────────────────────────────────
#: `export_id` and a recipient scope are composed into a filename, so both are held to this.
SAFE_PART = re.compile(r"^[A-Za-z0-9_.-]+$")
_PREFIX = "ia-answers-"


def artifact_filename(profile: AnswerExportProfile, scope: str, export_id: str) -> str:
    """`ia-answers-<profile>-<scope>-<export_id>.<format>`. Raises ValueError on an unsafe part."""
    for label, part in (("profile", profile.name), ("recipient_scope", scope),
                        ("export_id", export_id)):
        if not isinstance(part, str) or not SAFE_PART.match(part) or part in (".", ".."):
            raise ValueError(f"{label} {part!r} is not [A-Za-z0-9_.-]+")
    return f"{_PREFIX}{profile.name}-{scope}-{export_id}.{profile.format}"


def match_artifact(
    profiles: Mapping[str, AnswerExportProfile], filename: str,
) -> Optional[tuple[AnswerExportProfile, str]]:
    """The (profile, recipient scope) a filename belongs to, or None.

    A CLOSED MATCH against the loaded profiles: for every profile x recipient, the filename must
    start with `ia-answers-<profile>-<scope>-` and end `.<format>` around a safe export id. NEVER
    a split on `-`, because scopes contain `-`. A name two different scopes both claim is claimed
    by none (an ambiguous name is never served on a guess). Mirrors fin's `_cdrl_artifact_program`.
    """
    if not isinstance(filename, str) or not filename.startswith(_PREFIX):
        return None
    hits: set[tuple[str, str]] = set()
    for name in sorted(profiles):
        p = profiles[name]
        for scope in p.recipients:
            head, tail = f"{_PREFIX}{p.name}-{scope}-", f".{p.format}"
            if (filename.startswith(head) and filename.endswith(tail)
                    and len(filename) > len(head) + len(tail)
                    and SAFE_PART.match(filename[len(head):-len(tail)])):
                hits.add((p.name, scope))
    if len(hits) != 1:
        return None
    pname, scope = next(iter(hits))
    return profiles[pname], scope
