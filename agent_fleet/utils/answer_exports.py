"""An ANSWER-EXPORT PROFILE as an overlay row (`policy/exports/answers/<name>.yaml`).

A profile declares one deliverable that has one row per answer: which verbs' answers it takes
(`kinds`), which recipient scopes receive it (`recipients`), and which field of an answer lands
in which column (`columns`). The BFF decides WHICH answers a recipient takes by `kinds`; engine-cost
renders and writes the file by `render`. Neither computes anything: every cell is a value an
answer already carried.

It lives in `utils` because both the BFF and engine-cost import it (engine images flatten
`agent_fleet/utils` to `/app/utils`; the BFF keeps the package path -- the import dance below).

── THE VOCABULARY IS THE REVIEW EXPORT'S ───────────────────────────────────────────────────
A row opens with `column_map_version`, `name`, `label`, `format`, `granularity` -- the keys of
lane/01's review export (`src/iagent/export_profiles.py`, `policy/exports/*.yaml`) -- and its
columns are `{output, source: {field}}`. Here `granularity` is `answer` (one row per answer).
The two loaders are kept apart by the SUBDIRECTORY (this one reads `policy/exports/answers/`,
lane/01's glob is not recursive) until the export-profile header type lands in the SDK
(iagent-mesh v0.9.12); one loader then reads both. It cannot import lane/01's module: engine
images flatten `agent_fleet/utils` and carry no `src/iagent`.

── WHAT A ROW MAY NOT SAY, AND WHERE IT IS REFUSED ──────────────────────────────────────────
Every refusal is at LOAD, names the FILE and the key, and ALL of them are listed in one error
(a profile set that loaded half is a deliverable that exists for some deployments only):

* a key outside the closed set; `format` other than csv|json; `granularity` other than `answer`;
  `column_map_version` other than lane/01's; `name` that is not `^[a-z][a-z0-9-]{0,63}$` or is
  not the file's stem;
* `kinds` missing, empty, duplicated, or an entry that is not `mesh:<Verb>`;
* `recipients` missing or empty; a recipient scope in more than one profile (naming both);
* `columns` missing or empty, a `source.field` outside `ANSWER_FIELDS`, an `output` blank or
  repeated, and the review export's column keys this granularity does not render.
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

from iagent_mesh.declarations import DeclarationError, compose_rows, read_rows

_SEED_ENV = "EXPORT_PROFILE_POLICY_DIR"
_OVERLAY_ENV = "EXPORT_PROFILE_OVERLAY_DIRS"


def _default_seed_dir() -> Path:
    """`<repo>/policy/exports/answers`, found by walking up rather than counting levels: in the flattened
    engine image this file is `/app/utils/answer_exports.py` and a fixed `parents[2]` is wrong
    there (the way `finance_agent/export_profiles.py` finds its own seed)."""
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / "policy" / "exports" / "answers"
        if candidate.is_dir():
            return candidate
    return Path("/app/policy/exports/answers")


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

#: lane/01's `export_profiles.COLUMN_MAP_VERSION` (7f's contract_version). Not imported: engine
#: images carry no `src/iagent`. Sealed equal to it in
#: tests/test_a_portfolio_board_exports_to_a_plan_recipient.py.
COLUMN_MAP_VERSION = 1

#: The header `granularity` vocabulary, CLOSED to what this loader renders. lane/01's loader owns
#: `notice_part` and `notice`.
GRANULARITIES = ("answer",)

#: lane/01's profile-name rule (`export_profiles._NAME_RE`), adopted. Sealed equal in the test.
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
#: Column keys / source keys of the review export that this granularity does not render.
_REVIEW_ONLY_COL_KEYS = ("format", "on_unresolvable", "landing", "transforms")
_REVIEW_ONLY_SRC_KEYS = ("row_field", "absent_row")

_VERB = re.compile(r"^mesh:[A-Za-z][A-Za-z0-9]*$")
_TOP_KEYS = frozenset({"column_map_version", "name", "label", "format", "granularity", "kinds",
                       "recipients", "columns"})
_COLUMN_KEYS = frozenset({"output", "source"})
_SOURCE_KEYS = frozenset({"field"})


class AnswerExportError(DeclarationError):
    """An answer-export profile is invalid. Names the FILE and the key."""


@dataclass(frozen=True)
class Column:
    field: str      # source.field
    output: str     # the column header and key


@dataclass(frozen=True)
class AnswerExportProfile:
    name: str
    format: str
    granularity: str
    label: str
    kinds: tuple[str, ...]
    recipients: tuple[str, ...]
    columns: tuple[Column, ...]
    source: str = ""            # the file the winning row came from

    def header(self) -> dict[str, str]:
        return {"name": self.name, "format": self.format, "granularity": self.granularity,
                "label": self.label}


def _build(raw: Mapping[str, Any], source: str) -> AnswerExportProfile:
    """Raises ValueError listing every problem of THIS row, each naming its key."""
    problems: list[str] = []
    extra = sorted(set(raw) - _TOP_KEYS)
    if extra:
        problems.append(f"unknown key(s) {extra}; the keys are {sorted(_TOP_KEYS)}")
    for key in ("column_map_version", "name", "format", "granularity", "label", "kinds",
                "recipients", "columns"):
        if raw.get(key) in (None, "", [], {}):
            problems.append(f"missing required key {key!r}")
    ver = raw.get("column_map_version")
    if ver not in (None, "") and (ver != COLUMN_MAP_VERSION or isinstance(ver, bool)):
        problems.append(f"column_map_version {ver!r}; it must be {COLUMN_MAP_VERSION}")
    nm = raw.get("name")
    if nm not in (None, "") and (not isinstance(nm, str) or not _NAME_RE.match(nm)):
        problems.append(f"name {nm!r} does not match {_NAME_RE.pattern}")
    fmt, gran = raw.get("format"), raw.get("granularity")
    if fmt not in (None, "") and fmt not in MEDIA_TYPES:
        problems.append(f"format {fmt!r}; the formats are {sorted(MEDIA_TYPES)}")
    if gran not in (None, "") and gran not in GRANULARITIES:
        problems.append(f"granularity {gran!r}; this loader's granularities are "
                        f"{list(GRANULARITIES)} (lane/01's loader owns notice_part and notice)")

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
    seen_out: set[str] = set()
    for col in cols or []:
        if not isinstance(col, dict):
            problems.append(f"columns entry {col!r} is not {{output, source: {{field}}}}")
            continue
        review_only = sorted(set(col) & set(_REVIEW_ONLY_COL_KEYS))
        if review_only:
            problems.append(f"columns entry carries {review_only}; the answer granularity takes "
                            "source.field only")
        bad = sorted(set(col) - _COLUMN_KEYS - set(_REVIEW_ONLY_COL_KEYS))
        if bad:
            problems.append(f"columns entry carries {bad}; the keys are {sorted(_COLUMN_KEYS)}")
        out, src = col.get("output"), col.get("source")
        fld = None
        if not isinstance(src, dict):
            problems.append(f"columns entry {out!r} has no source mapping with a 'field'")
        else:
            review_src = sorted(set(src) & set(_REVIEW_ONLY_SRC_KEYS))
            if review_src:
                problems.append(f"columns entry {out!r} source carries {review_src}; the answer "
                                "granularity takes source.field only")
            bad_src = sorted(set(src) - _SOURCE_KEYS - set(_REVIEW_ONLY_SRC_KEYS))
            if bad_src:
                problems.append(f"columns entry {out!r} source carries {bad_src}; the keys are "
                                f"{sorted(_SOURCE_KEYS)}")
            fld = src.get("field")
            if fld not in ANSWER_FIELDS:
                problems.append(f"columns source.field {fld!r} is outside the answer fields "
                                f"{list(ANSWER_FIELDS)}")
        if not isinstance(out, str) or not out.strip():
            problems.append(f"columns entry for field {fld!r} has no non-blank 'output'")
        elif out in seen_out:
            problems.append(f"columns 'output' {out!r} is used twice")
        else:
            seen_out.add(out)
        if fld in ANSWER_FIELDS and isinstance(out, str) and out.strip():
            columns.append(Column(fld, out))
    if problems:
        raise ValueError("; ".join(problems))
    return AnswerExportProfile(
        name=str(raw["name"]), format=str(fmt), granularity=str(gran), label=str(raw["label"]),
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

    # lane/01's rule, adopted: a row's `name` is its file's stem. The composer's builder is not
    # told the file, so each directory's files are read once here (a tombstone has no stem rule).
    for directory in [d, *ov]:
        for key, (f, raw) in read_rows(directory, key_field="name",
                                       error=AnswerExportError).items():
            if not raw.get("deleted") and key != f.stem:
                errors.append(f"{f.name}: name {key!r} is not the file stem {f.stem!r}")

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

    DETERMINISTIC: the same rows give the same bytes. csv is a header row from `output`, CRLF, no BOM,
    `None` written empty. json is `{"profile": name, "rows": [...]}` with keys in column order,
    `None` omitted, indent 2, non-ASCII kept, and a trailing newline.
    """
    if profile.format == "csv":
        buf = io.StringIO(newline="")
        w = csv.writer(buf, lineterminator="\r\n")
        w.writerow([c.output for c in profile.columns])
        for row in rows:
            w.writerow(["" if row.get(c.field) is None else row.get(c.field)
                        for c in profile.columns])
        return buf.getvalue().encode("utf-8")
    if profile.format == "json":
        body = {"profile": profile.name, "rows": [
            {c.output: row.get(c.field) for c in profile.columns if row.get(c.field) is not None}
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
