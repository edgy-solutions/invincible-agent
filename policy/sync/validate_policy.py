#!/usr/bin/env python3
"""Network-free validation of ALL EIGHT git-asserted policy files.

WHY THIS EXISTS. The seven syncs each validate their own file — but only
at apply time, one sync at a time. topaz_sync failing stops the seed
chain, yet a malformed task_grants.yaml would only surface AFTER four
other syncs had already applied. This tool front-loads every pure
(no-network) validation so a broken overlay is refused BEFORE any write
— in the seed job as a fail-fast gate, and in a private policy repo's
PR CI where no cluster is reachable at all.

WHAT IT CHECKS (all of it reusing the syncs' own loaders — one
definition of "valid", never a parallel re-implementation):
  - personas/domains/groups/users → topaz_sync's PolicyBundle
    (Pydantic + cross-reference validation)
  - asset_grants.yaml             → grant_sync.load_grants
  - task_grants.yaml              → task_grant_sync.load_audiences
  - ontology_compartments.yaml    → ontology_compartment_sync.load_compartments
  - capability_grants.yaml        → capability_grant_sync.load_capabilities
  - program_members.yaml          → program_member_sync.load_programs
  - capability_grants.yaml        → also: a `grant_to_groups` group exists and has members, and
    a `can_drop:<K>` key names a KNOWN content kind (see known_content_kinds)
  - capability_grants.yaml        → also: a `can_export:<P>` key names a KNOWN export profile
    (see known_export_profiles), no profile name is in two kinds, and every known profile -- of
    each kind policy/export_profile_sources.yaml declares -- has a `can_export:<P>` row
    (deny-by-default: no row, nobody exports)
  - capability_grants.yaml        → also: a `can_call:<T>` key names a tag of the served MCP document
    (see known_call_tags); no row is required per tag (deny-by-default: no row, nobody calls)
  - capability_grants.yaml        → also: a `can_review:<S>` key names a registered review subject
    (see known_review_subjects); no row is required per subject (no row, nobody reviews)
  - capability_grants.yaml        → also: a `can_configure:<S>` key names a registered configure
    subject (see known_configure_subjects); no row is required per subject (no row, nobody configures)
  - recipient_readers.yaml        → recipient_reader_sync.load_readers (WHEN PRESENT; not in
    DATA_FILES -- see the note there)
  - repository_paths.yaml         → repository_paths_errors (WHEN PRESENT; not in
    DATA_FILES -- see the note there)
  - gateway_delegates.yaml        → gateway_delegates_errors (WHEN PRESENT; not in
    DATA_FILES -- see the note there)
  - classification/levels.yaml    → classification_levels_errors (WHEN PRESENT; not in
    DATA_FILES -- see the note there): an id is a bare name, unique; a row says why and who ratified
  - level_readers.yaml            → level_readers_errors (WHEN PRESENT; not in DATA_FILES -- see
    the note there): a level is registered, one row per level, a group exists and has members
  - option_deciders.yaml          → option_deciders_errors (WHEN PRESENT; not in DATA_FILES -- see
    the note there): a workflow and option have one row, a group exists and has members
  - domain_consumption.yaml       → domain_consumption_required_fields (this file;
    no sync of its own — can_consume is evaluated in-process)
  - every DATA file must EXIST — explicit-empty (`grants: []`) is a
    valid assertion; an absent file is not. In overlay deployments a
    missing file must never fall back to the image's sandbox copy.

WHAT IT CANNOT CHECK (stays with the live syncs): dangling-asset grants
(needs the directory's dataset objects — grant_sync's deny-on-dangling)
and every readback. This gate is necessary, not sufficient.

ENUMS SPLIT (`--enums-from` / `--overlay-enums`). personas.yaml /
domains.yaml come from the product image by default, but a deployment
may ASSERT ownership of either (mirrors the chart's
`topazSeed.policySource.overlayEnums`): domains.yaml is a deployment's
classification vocabulary (labels must match its data tagging at
ingest); personas.yaml is fully assertable since chart 0.3.12 — the
catalog rego walks the directory (domain.can_view) instead of
enumerating a hardcoded persona list, so ADDING personas via overlay
works too. An enum file present in --policy-dir but NOT asserted is an
ERROR — an ignored-but-authoritative-looking file is the two-truths
trap.

    # inside the product image (work policy repo mounted at /overlay):
    python policy/sync/validate_policy.py \\
        --policy-dir /overlay --enums-from /app/policy \\
        --overlay-enums domains.yaml

Exit: 0 valid · 2 any error (all errors listed, none silently dropped).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml
from pydantic import ValidationError

from topaz_sync import PolicyBundle, expand_platform_domains
from grant_sync import load_grants
from task_grant_sync import load_audiences
from ontology_compartment_sync import load_compartments
from capability_grant_sync import load_capabilities
from program_member_sync import load_programs
from recipient_reader_sync import load_readers

# The eight DATA files a deployment asserts (enums excluded — product-owned).
# domain_consumption.yaml added 2026-10-02 (origin-entitlement ruling): it has no
# Topaz sync of its own (can_consume is evaluated in-process, src/iagent/origin.py) —
# validated here anyway because an unexplained or out-of-vocabulary row is exactly
# the author-bug class this gate exists to catch before review.
DATA_FILES = (
    "users.yaml",
    "groups.yaml",
    "asset_grants.yaml",
    "task_grants.yaml",
    "ontology_compartments.yaml",
    "capability_grants.yaml",
    "domain_consumption.yaml",
    "program_members.yaml",
)

# recipient_readers.yaml is DELIBERATELY NOT in DATA_FILES: that tuple means "every deployment must
# assert this file", and adding it would fail the seed of every existing deployment whose policy
# repository lacks it. It is validated WHEN PRESENT (see validate()). Whether it becomes
# required -- and so whether an absent file is an error here and FATAL in the sync Job -- is an
# OPEN question with the architect.
#
# repository_paths.yaml (ADR-0062 section 5) is likewise NOT in DATA_FILES: only engine-r reads it,
# and a deployment's policy repository may not run engine-r. Validated WHEN PRESENT.
#
# gateway_delegates.yaml is likewise NOT in DATA_FILES: a deployment with no delegate has nothing to
# assert, and an absent file means the same as an empty one, no service names a person. Validated
# WHEN PRESENT.
#
# classification/levels.yaml and level_readers.yaml (ADR-0064 item B, Proposed, #266) are likewise NOT
# in DATA_FILES: no code reads either yet (dag-tools step 5), an absent registry registers no level
# and an absent rail grants no level. Validated WHEN PRESENT.
#
# option_deciders.yaml (the `can_decide:<workflow_id>.<option>` rail, ADR-0065 (provisional, not yet
# written)) is likewise NOT in DATA_FILES: no code reads it yet (a workflow definition's decide step will
# carry the options, ADR-0065 ruling 3), and an absent rail grants no option. Validated WHEN PRESENT.


def known_content_kinds() -> tuple[set[str], list[str]]:
    """The content kinds a `can_drop:<K>` capability key may name, and what they were composed from.

    Read straight from the `kind:` field of every `*.yaml` row in the SEED directory
    (policy/content_kinds), each directory in CONTENT_KIND_OVERLAY_DIRS (the deployment's, as
    src/iagent/content_kinds.py reads it), and the chart's default overlay
    (policy/overlays/openddil-lab/content_kinds), because this gate runs where src/iagent and
    the SDK are not importable (a private policy repo's CI). Returns (kinds, sources) where each
    source reads `<dir> (<n> kind(s))` or `<dir> (absent)`, so a refusal can say what it knew."""
    root = Path(__file__).resolve().parents[2]
    dirs = [root / "policy" / "content_kinds"]
    raw = (os.getenv("CONTENT_KIND_OVERLAY_DIRS") or "").strip()
    dirs += [Path(p.strip()) for p in raw.split(os.pathsep) if p.strip()]
    dirs.append(root / "policy" / "overlays" / "openddil-lab" / "content_kinds")
    kinds: set[str] = set()
    sources: list[str] = []
    for d in dirs:
        if not d.is_dir():
            sources.append(f"{d.as_posix()} (absent)")
            continue
        found = 0
        for f in sorted(d.glob("*.yaml")):
            try:
                doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            k = doc.get("kind") if isinstance(doc, dict) else None
            if isinstance(k, str) and k.strip():
                kinds.add(k.strip())
                found += 1
        sources.append(f"{d.as_posix()} ({found} kind(s))")
    return kinds, sources


def known_call_tags() -> tuple[set[str], list[str]]:
    """The tags a `can_call:<T>` capability key may name: the union of `tags` over every operation
    of docs/api/mcp.openapi.json (the committed projection of the served MCP document), and a note
    `<path> (<n> tag(s))` or `<path> (absent)`."""
    root = Path(__file__).resolve().parents[2]
    f = root / "docs" / "api" / "mcp.openapi.json"
    if not f.is_file():
        return set(), [f"{f.as_posix()} (absent)"]
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), [f"{f.as_posix()} (absent)"]
    tags: set[str] = set()
    for item in (doc.get("paths") or {}).values():
        for op in (item or {}).values():
            if isinstance(op, dict):
                tags.update(t for t in (op.get("tags") or []) if isinstance(t, str))
    return tags, [f"{f.as_posix()} ({len(tags)} tag(s))"]


def _registered_subjects(name: str, path: Path | None) -> tuple[set[str], list[str]]:
    """The `name` of every row under the key `<stem>` of policy/`<stem>.yaml` (a registry of the
    product, read from beside this script and never from a deployment's policy dir), and a note
    `<path> (<n> subject(s))` or `<path> (absent)`. An absent or unreadable registry is an empty
    set, which refuses every key that must name a subject in it."""
    f = path or Path(__file__).resolve().parents[2] / "policy" / name
    if not f.is_file():
        return set(), [f"{f.as_posix()} (absent)"]
    try:
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return set(), [f"{f.as_posix()} (absent)"]
    rows = doc.get(Path(name).stem) if isinstance(doc, dict) else None
    subjects = {r["name"].strip() for r in (rows if isinstance(rows, list) else [])
                if isinstance(r, dict) and isinstance(r.get("name"), str) and r["name"].strip()}
    return subjects, [f"{f.as_posix()} ({len(subjects)} subject(s))"]


def known_review_subjects(path: Path | None = None) -> tuple[set[str], list[str]]:
    """The subjects a `can_review:<S>` capability key may name: policy/review_subjects.yaml."""
    return _registered_subjects("review_subjects.yaml", path)


def known_configure_subjects(path: Path | None = None) -> tuple[set[str], list[str]]:
    """The subjects a `can_configure:<S>` capability key may name: policy/configure_subjects.yaml."""
    return _registered_subjects("configure_subjects.yaml", path)


#: Where each export kind's profiles are composed from: one row per kind (architect 2026-10-30, via
#: Chris: "one function; source rows live in a policy file both the validator and engines share").
#: No grantee is named in code either (standing rule, 2026-10-30): each ruled grantee is a ROW in
#: policy/capability_grants.yaml, and the completeness refusal derives its advice from the rows that
#: already decide profiles of the same kind.
EXPORT_PROFILE_SOURCES = "export_profile_sources.yaml"


def known_export_profiles(
    rows: list | None = None,
) -> tuple[dict[str, str], list[str]]:
    """The export profiles a `can_export:<P>` capability key may name: {name: kind}, and notes.

    Each kind is a row of policy/export_profile_sources.yaml (`rows` stands in for the file, for
    tests), composed by iagent_mesh.compose_export_profiles: the seed (`seed_env` if set, else
    `seed_default` under the repository root), then each dir in `overlay_env` (os.pathsep-separated,
    empty entries dropped, as the engines split it), then the row's `offline_overlays`. A later
    same-`name` row replaces an earlier one, and `deleted: true` removes the name. The SDK REFUSES
    what this gate's old copy skipped: an empty or nameless file, two files of one name in one
    directory, and a tombstone for a name nothing before it ships.

    This gate imports the SDK. Both places it runs carry it: the seed CronJob and a policy repo's
    CI run it from the cortex-bff image (templates/topaz-seed-cronjob.yaml, policy/README.md),
    whose `python` is that image's venv (.github/docker/Dockerfile.agent puts /app/.venv/bin first
    on PATH).

    One note per kind: `<kind>: <dir>, <dir> (absent), ... -> <n> profile(s)`. A note starting
    `REFUSED:` (a source row, or a profile file the SDK refused) or `COLLISION:` (a name in two
    kinds' final sets) is turned into an error by validate()."""
    from iagent_mesh import ExportProfileError, ExportProfileSource, compose_export_profiles

    root = Path(__file__).resolve().parents[2]
    if rows is None:
        f = root / "policy" / EXPORT_PROFILE_SOURCES
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            return {}, [f"REFUSED: {f.as_posix()} is unreadable ({type(exc).__name__})"]
        rows = doc.get("sources") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            return {}, [f"REFUSED: {f.as_posix()} has no `sources:` list"]
    by_kind: dict[str, set[str]] = {}
    notes: list[str] = []
    for i, row in enumerate(rows):
        if not (isinstance(row, dict) and isinstance(row.get("seed_default"), str)):
            notes.append(f"REFUSED: {EXPORT_PROFILE_SOURCES} row {i} is not a source row: {row!r}")
            continue
        overlay_env = row.get("overlay_env")
        try:
            # The SDK's overlay_env is a str. A kind whose loader reads no overlay variable says
            # null, and the SDK never reads it here: overlay_dirs is always passed.
            src = ExportProfileSource.model_validate(
                {**row, "seed_default": (root / row["seed_default"]).as_posix(),
                 "overlay_env": overlay_env or ""})
        except ValidationError as exc:
            notes.append(f"REFUSED: {EXPORT_PROFILE_SOURCES} row {i}: "
                         + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()))
            continue
        if src.kind in by_kind:
            notes.append(f"REFUSED: {EXPORT_PROFILE_SOURCES} declares kind {src.kind!r} twice")
            continue
        dirs: list[str] = []
        seen: set[Path] = set()
        listed = [p for p in os.getenv(overlay_env, "").split(os.pathsep) if p] if overlay_env else []
        for d in listed + [(root / d).as_posix() for d in row.get("offline_overlays") or []]:
            if Path(d).resolve() not in seen:  # a dir both set and offline is composed once
                seen.add(Path(d).resolve())
                dirs.append(d)
        try:
            composed = compose_export_profiles(src, overlay_dirs=dirs)
        # read_rows calls .get on each file's document, so a file that is not a mapping raises
        # AttributeError, and an unparseable one raises yaml's own error.
        except (ExportProfileError, yaml.YAMLError, OSError, AttributeError) as exc:
            by_kind[src.kind] = set()
            notes.append(f"REFUSED: {src.kind}: {type(exc).__name__}: {exc}")
            continue
        by_kind[src.kind] = set(composed)
        read = [os.getenv(src.seed_env, src.seed_default), *dirs]  # the seed as the SDK reads it
        notes.append(f"{src.kind}: "
                     + ", ".join(Path(d).as_posix() + ("" if Path(d).is_dir() else " (absent)") for d in read)
                     + f" -> {len(composed)} profile(s)")
    profiles: dict[str, str] = {}
    for kind, names in by_kind.items():
        for n in sorted(names):
            if n in profiles:
                notes.append(f"COLLISION: {n!r} is a {profiles[n]} profile and a {kind} profile")
            profiles[n] = kind
    return profiles, notes


def _read_yaml(path: Path, errors: list[str]) -> dict:
    """Parse one YAML file to a top-level mapping; any failure is an
    ERROR (collected, not raised) so the caller reports everything at
    once instead of dying on the first bad file."""
    if not path.is_file():
        errors.append(f"{path.name}: MISSING — every data file must exist "
                      f"(explicit-empty is fine; absent is not)")
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        errors.append(f"{path.name}: YAML parse error — {e}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"{path.name}: top-level YAML must be a mapping")
        return {}
    return data


#: Service principals are seeded as users so they are LEGIBLE and grantable through the
#: rails; this prefix is what marks one as not-a-human-recipient.
SERVICE_SUBJECT_PREFIX = "svc:"


def service_identity_recipients(file_label: str, pairs) -> list[str]:
    """DISCLOSURE TO A SERVICE IS THE CONFUSED DEPUTY. Refuses `svc:*` as a grantee.

    THE GAP THIS CLOSES, named by `invincible-agent-81` against the grant rail: `svc:` subjects
    ARE seeded users, so `unknown_user_subjects` resolves them happily and a grant reading
    `grant_to: svc:cortex-bff` passes validation, syncs, and reads back green.

    **The rule existed and lived in a COMMENT.** `policy/users.yaml` says it plainly beside
    `svc:data-analyst`:

        the service credential says WHICH SERVICE is calling, not WHOSE data may be read.
        DA serves every caller, so a read grant on svc:data-analyst would entitle EVERY
        caller to whatever it can reach - the confused deputy the per-caller conjunction
        exists to prevent.

    An engine-local rule the rail silently accepts is droppable by the next person who edits
    the rail without reading the engine. Making it a validator makes it a property of the FILE,
    which is the whole difference between a convention and a constraint.

    SCOPE IS DISCLOSURE-RECIPIENT GRANTS - who may SEE something. `capability_grants.yaml` is
    deliberately NOT passed through this: an INVOKE is an EFFECT rather than a read, as that
    file's own header states, and a service principal invoking a capability is not the confused
    deputy. If a capability grant ever conveys disclosure, that exemption must be revisited
    rather than inherited.

    PURE - no filesystem. ``pairs`` = ``[(context, grantee), ...]``.
    """
    out: list[str] = []
    for context, grantee in pairs:
        if str(grantee).strip().startswith(SERVICE_SUBJECT_PREFIX):
            out.append(
                f"{file_label}: {context} grants disclosure to {grantee!r}, a SERVICE identity. "
                f"A service credential says which service is calling, not whose data may be "
                f"read - the service serves every caller, so this entitles all of them "
                f"(confused deputy). Grant to the acting human, or formalise the delegation as "
                f"a design decision rather than settling it with a grant here."
            )
    return out


def unknown_user_subjects(file_label: str, pairs, known_users: set[str]) -> list[str]:
    """AUTHOR-BUG GATE (validators catch author bugs; readbacks catch sync bugs —
    neither substitutes for the other). EVERY grant sync (asset/task/ontology/
    capability) writes ``user`` subjects UNCONDITIONALLY, so a grantee that isn't a
    KNOWN user seeds a phantom ``user:<name>`` object — a grant that PASSES readback
    (the relation exists) while granting nothing to any real principal (silent-wrong-
    grant, the grant-side of broken-closed). This refuses it LOUD at validation, the
    same posture as the overlay-enum guards. Group grants are a DEFERRED design
    decision (they split "who has access" across git + group membership, which drifts
    without a grant-file change — a real weakening of the git-blame audit story that
    needs its own ruling; plus ``user | group#member`` in the manifest + sync support).
    Until then, USERS ONLY family-wide.

    PURE — no filesystem. ``pairs`` = ``[(context, grantee), ...]``. Returns one
    ``<file_label>: ...`` error per grantee not in ``known_users`` (empty when all
    resolve)."""
    out: list[str] = []
    for context, grantee in pairs:
        if grantee not in known_users:
            out.append(
                f"{file_label}: grant subject {grantee!r} (for {context!r}) is NOT a "
                f"known user (not in users.yaml) — group grants are not supported (the "
                f"sync writes `user` subjects; a group name seeds a phantom "
                f"user:{grantee} that passes readback while granting nothing to the "
                f"group's members). Add the user to users.yaml or fix the entry."
            )
    return out


def unusable_group_audiences(audiences, groups: dict, users: list, *,
                             file_label: str = "task_grants.yaml", noun: str = "audience",
                             nobody: str = "the task would route to NOBODY") -> list[str]:
    """`grant_to_groups` gate. A group not in groups.yaml, or with zero members in users.yaml,
    routes the task to NOBODY (the phantom-user failure by another door). PURE. The keyword
    arguments only relabel the message for another file that carries `key` + `grant_to_groups`
    rows (capability_grants.yaml); the defaults are task_grants.yaml's wording, unchanged."""
    members: dict[str, int] = {}
    for u in users:
        if isinstance(u, dict):
            for g in u.get("groups") or []:
                members[g] = members.get(g, 0) + 1
    out: list[str] = []
    for a in audiences:
        for g in a.grant_to_groups:
            if g not in (groups or {}):
                out.append(f"{file_label}: {noun} {a.key!r} grants group {g!r}, which is "
                           f"NOT a group in groups.yaml")
            elif not members.get(g):
                out.append(f"{file_label}: {noun} {a.key!r} grants group {g!r}, which has "
                           f"ZERO members in users.yaml - {nobody}")
    return out


def domain_consumption_required_fields(raw: dict, known_domains: set[str]) -> list[str]:
    """PROVE-THE-NEGATIVE on domain_consumption.yaml, same posture as
    load_capabilities/load_programs: every consumer-domain row must name
    `granted_by`, `reason`, and a non-empty `allowed_origins` — the identity-row
    discipline the file's own header requires (NO IMPLICIT IDENTITY: a domain
    consuming its own origin needs an explicit row, so a row silently losing its
    fields is a domain silently losing its own read-back, not a no-op).

    ALSO refuses any consumer key or `allowed_origins` entry that names a domain
    not in `known_domains` (domains.yaml, platform domains included) — a row
    naming a domain policy doesn't recognize is the "registration is not
    entitlement" shape domains.yaml itself warns about: it reads as granted and
    authorizes nothing, because the domain cannot appear in anyone's entitled
    cells either.

    PURE — no filesystem. `raw` is the already-parsed domain_consumption.yaml dict.
    """
    out: list[str] = []
    table = (raw or {}).get("domain_consumption") or {}
    if not isinstance(table, dict):
        return [f"domain_consumption.yaml: top-level `domain_consumption` must be a mapping"]
    for consumer, entry in table.items():
        entry = entry or {}
        granted_by = str((entry or {}).get("granted_by") or "").strip()
        reason = (entry or {}).get("reason")
        allowed = [str(o).strip() for o in ((entry or {}).get("allowed_origins") or [])
                   if str(o).strip()]
        missing = [k for k, v in (("granted_by", granted_by), ("reason", reason),
                                  ("allowed_origins", allowed)) if not v]
        if missing:
            out.append(f"domain_consumption.yaml: {consumer!r} MALFORMED: missing "
                        f"{', '.join(missing)}")
            continue
        if consumer not in known_domains:
            out.append(f"domain_consumption.yaml: consumer domain {consumer!r} is not in "
                        f"domains.yaml")
        for origin_domain in allowed:
            if origin_domain not in known_domains:
                out.append(f"domain_consumption.yaml: {consumer!r} allows origin domain "
                            f"{origin_domain!r}, which is not in domains.yaml")
    return out


#: A FORK of iagent_mesh ReviewShapeRow's required fields, restated because this gate runs
#: without the SDK. tests/test_review_shapes_are_one_registry.py holds it equal to the model.
REVIEW_SHAPE_REQUIRED = ("review_shape",)
#: The model's all-or-nothing rule, restated the same way: a coverage row sets all three, a card-only
#: row none. A `rules: []` is set: the shape exists and no rule is declared for it yet.
REVIEW_SHAPE_COVERAGE = ("item_kind", "rules_version", "rules")


def _read_review_shapes(d: Path) -> tuple[dict[str, Path], list[str]]:
    """{review_shape: file} for every VALID `*.yaml` row in `d`, and the errors for the rest.
    This gate runs where the SDK is not importable, so the row's shape (iagent_mesh
    ReviewShapeRow: review_shape, and for a coverage row item_kind and rules_version, strings;
    params a mapping; rules a list of {id: str, params: mapping}; item_kind, rules_version and rules
    all or nothing) is checked here, and the file stem must equal the row's
    `review_shape` (src/iagent/review_shapes.py applies the same rule)."""
    shapes: dict[str, Path] = {}
    errors: list[str] = []
    if not d.is_dir():
        return shapes, errors
    for f in sorted(d.glob("*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"{f.as_posix()}: unreadable ({type(exc).__name__})")
            continue
        if not isinstance(doc, dict):
            errors.append(f"{f.as_posix()}: a review-shape row is a mapping")
            continue
        problems: list[str] = []
        set_fields = [k for k in REVIEW_SHAPE_COVERAGE if doc.get(k) is not None]
        strings = (*REVIEW_SHAPE_REQUIRED, *[k for k in set_fields if k != "rules"])
        bad = [k for k in strings if not (isinstance(doc.get(k), str) and doc[k].strip())]
        if bad:
            problems.append(f"{', '.join(bad)} must be a non-empty string")
        if not isinstance(doc.get("params", {}), dict):
            problems.append("params must be a mapping")
        rules = doc.get("rules")
        if rules is not None and (not isinstance(rules, list) or not all(
                isinstance(r, dict) and isinstance(r.get("id"), str)
                and isinstance(r.get("params", {}), dict) for r in rules)):
            problems.append("rules must be a list of {id: str, params: mapping}")
        if set_fields and len(set_fields) != len(REVIEW_SHAPE_COVERAGE):
            problems.append(f"{', '.join(REVIEW_SHAPE_COVERAGE)} are all or nothing: this row sets "
                            f"{', '.join(set_fields)}")
        if problems:
            errors += [f"{f.as_posix()}: {m}" for m in problems]
            continue
        if doc["review_shape"] != f.stem:
            errors.append(f"{f.as_posix()}: file stem {f.stem!r} must equal review_shape "
                          f"{doc['review_shape']!r}")
            continue
        shapes[doc["review_shape"]] = f
    return shapes, errors


def review_shape_errors(policy_dir: Path, enums_dir: Path) -> tuple[list[str], int]:
    """(errors, n_shapes). Every `review_shapes/*.yaml` (the seed, and each
    `overlays/*/review_shapes`) must validate, and every content-kind row that sets `review_shape`
    (the seed's and each overlay's) must name a row in the registry composed FOR THAT OVERLAY:
    the seed plus that overlay's own review_shapes. The seed is `<policy_dir>/review_shapes`, else
    the product's (`<enums_dir>/review_shapes`) for an overlay repo validating its own tree."""
    errors: list[str] = []
    seed_dir = policy_dir / "review_shapes"
    if not seed_dir.is_dir():
        seed_dir = enums_dir / "review_shapes"
    seed, errs = _read_review_shapes(seed_dir)
    errors += errs
    total = len(seed)
    layers: list[tuple[Path, dict[str, Path]]] = [(policy_dir / "content_kinds", seed)]
    overlays = policy_dir / "overlays"
    for o in sorted(overlays.iterdir()) if overlays.is_dir() else []:
        shapes, errs = _read_review_shapes(o / "review_shapes")
        errors += errs
        total += len(shapes)
        layers.append((o / "content_kinds", {**seed, **shapes}))
    for kinds_dir, registry in layers:
        for f in sorted(kinds_dir.glob("*.yaml")) if kinds_dir.is_dir() else []:
            try:
                doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            shape = doc.get("review_shape") if isinstance(doc, dict) else None
            if shape is not None and shape not in registry:
                errors.append(
                    f"{f.as_posix()}: review_shape {shape!r} names no row in the review-shape "
                    f"registry (known: {', '.join(sorted(registry)) or 'none'})")
    return errors, total


#: Mirrors `agent_fleet.repository_agent.repo_core.GOVERNED_ROOTS` (ADR-0062 section 1). Restated, not
#: imported: pygit2 is not in every image this gate runs in. tests/security/test_repository_paths_rail.py
#: asserts the two are equal.
GOVERNED_ROOTS = ("policy/", "docs/adr/", "tests/fixtures/", "sessions/")

_RP_ROW_FIELDS = ("review", "approvers", "granted_by", "reason", "unowned_review", "unmatched_review")

#: A `review` ending `:<DOMAIN>` is a per-row audience (section 5: `access_grant:<DOMAIN>`, "taken
#: from each row the diff changes"). engine-r resolves it per changed row; validate_policy checks
#: every audience it could resolve to, and the `unmatched_review` a row with no such audience falls
#: back to.
_RP_DOMAIN = "<DOMAIN>"


def repository_paths_errors(raw: dict, audiences, groups: dict, users: list) -> list[str]:
    """ADR-0062 section 5: validate policy/repository_paths.yaml. PURE.

    `raw` is the parsed file, `audiences` the records `load_audiences` returned, `groups` the
    groups.yaml mapping, `users` the users.yaml list. Each error reads
    `repository_paths.yaml: <repo>: <paths|tags>: <key>: ...`. Unknown keys are refused by name
    at every level, so a typo (`approver:`) cannot pass silently."""
    pre = "repository_paths.yaml"
    out: list[str] = []
    if not isinstance(raw, dict) or set(raw) != {"repository_paths"}:
        extra = sorted(map(str, set(raw) - {"repository_paths"})) if isinstance(raw, dict) else []
        return [f"{pre}: top level must be a mapping with exactly one key, `repository_paths`"
                + (f" (unknown key(s): {', '.join(extra)})" if extra else "")]
    repos = raw["repository_paths"]
    if not isinstance(repos, dict):
        return [f"{pre}: `repository_paths` must map repository id -> mapping"]

    by_key = {a.key: a for a in audiences}
    members: dict[str, set[str]] = {}
    for u in users or []:
        if isinstance(u, dict) and u.get("id"):
            for g in u.get("groups") or []:
                members.setdefault(g, set()).add(str(u["id"]).strip())

    def distinct_users(a) -> set[str]:
        s = set(a.grant_to)
        for g in a.grant_to_groups:
            s |= members.get(g, set())
        return s

    def row_errors(where: str, row, *, is_tag: bool, key: str) -> list[str]:
        e: list[str] = []
        if not isinstance(row, dict):
            return [f"{where}: row must be a mapping"]
        for k in row:
            if k not in _RP_ROW_FIELDS:
                e.append(f"{where}: unknown key {k!r} (allowed: {', '.join(_RP_ROW_FIELDS)})")
        for f in ("granted_by", "reason"):
            v = row.get(f)
            if not isinstance(v, str) or not v.strip():
                e.append(f"{where}: `{f}` is required and must be a non-empty string")
        ap = row.get("approvers")
        if "approvers" not in row:
            e.append(f"{where}: `approvers` is required")
        elif isinstance(ap, bool) or not isinstance(ap, int) or ap < 1:
            e.append(f"{where}: `approvers` must be an int >= 1 (got {ap!r})")
        review = row.get("review")
        named: list[tuple[str, str]] = []
        if not isinstance(review, str) or not review.strip():
            e.append(f"{where}: `review` is required and must be a non-empty string")
        elif review == "owning_lane":
            if is_tag or not key.startswith("sessions/"):
                e.append(f"{where}: `review: owning_lane` is legal only on a `sessions/` path row, "
                         f"never on a tag or another path")
            ur = row.get("unowned_review")
            if not isinstance(ur, str) or not ur.strip():
                e.append(f"{where}: an `owning_lane` row requires `unowned_review` (an audience key)")
            elif ur not in by_key:
                e.append(f"{where}: `unowned_review` {ur!r} is not an audience in task_grants.yaml")
            else:
                named.append(("unowned_review", ur))
        elif review.endswith(":" + _RP_DOMAIN):
            prefix = review[: -len(_RP_DOMAIN)]
            matched = sorted(k for k in by_key if k.startswith(prefix))
            if not matched:
                e.append(f"{where}: `review` {review!r} resolves to no audience in task_grants.yaml "
                         f"(none starts {prefix!r})")
            named.extend(("review", k) for k in matched)
            mr = row.get("unmatched_review")
            if not isinstance(mr, str) or not mr.strip():
                e.append(f"{where}: a `{_RP_DOMAIN}` row requires `unmatched_review` (an audience key) "
                         f"for a changed row whose domain has no audience")
            elif mr not in by_key:
                e.append(f"{where}: `unmatched_review` {mr!r} is not an audience in task_grants.yaml")
            else:
                named.append(("unmatched_review", mr))
            if "unowned_review" in row:
                e.append(f"{where}: `unowned_review` is allowed only on an `owning_lane` row")
        else:
            if review not in by_key:
                e.append(f"{where}: `review` {review!r} is not an audience in task_grants.yaml")
            else:
                named.append(("review", review))
            if "unowned_review" in row:
                e.append(f"{where}: `unowned_review` is allowed only on an `owning_lane` row")
        if "unmatched_review" in row and not (isinstance(review, str)
                                              and review.endswith(":" + _RP_DOMAIN)):
            e.append(f"{where}: `unmatched_review` is allowed only on a `{_RP_DOMAIN}` row")
        if isinstance(ap, int) and not isinstance(ap, bool):
            for field_, aud in named:
                n = len(distinct_users(by_key[aud]))
                if n < ap:
                    e.append(f"{where}: audience {aud!r} ({field_}) has {n} distinct user(s) but the "
                             f"row requires {ap} approver(s) -- the row could never be satisfied")
        return e

    for repo, body in repos.items():
        rp = f"{pre}: {repo}"
        if not isinstance(repo, str) or not isinstance(body, dict):
            out.append(f"{rp}: repository id must be a str mapping to a mapping")
            continue
        for k in body:
            if k not in ("paths", "tags"):
                out.append(f"{rp}: unknown key {k!r} (a repository carries only `paths` and `tags`)")
        paths = body.get("paths")
        if not isinstance(paths, dict):
            out.append(f"{rp}: `paths` is required and must be a mapping")
            paths = {}
        for key, row in paths.items():
            where = f"{rp}: paths: {key}"
            if not isinstance(key, str):
                out.append(f"{where}: path key must be a str")
                continue
            if not key.startswith(GOVERNED_ROOTS):
                out.append(f"{where}: outside the governed roots {GOVERNED_ROOTS} -- the rail cannot "
                           f"widen check 6")
            if ".." in key.split("/"):
                out.append(f"{where}: a `..` segment is not allowed")
            if key.startswith("/"):
                out.append(f"{where}: a leading `/` is not allowed")
            if "*" in key:
                out.append(f"{where}: `*` is not allowed in a path key (patterns are for tags only)")
            out.extend(row_errors(where, row, is_tag=False, key=key))
        tags = body.get("tags", {})
        if not isinstance(tags, dict):
            out.append(f"{rp}: `tags` must be a mapping")
            tags = {}
        for key, row in tags.items():
            where = f"{rp}: tags: {key}"
            if not isinstance(key, str) or not key.strip():
                out.append(f"{where}: tag pattern must be a non-empty str")
                continue
            out.extend(row_errors(where, row, is_tag=True, key=key))
    return out


#: The central gateway's route ids a delegate row may name. The gateway owns them, and dag-tools
#: publishes them as data (architect 11-04): `central_gateway/gateway_routes.json`, read through
#: `dag_tools.central_gateway.routes`. A route is delegatable when its row says
#: `delegate_rows_may_name: true`; nothing here restates one. The gateway's other routes are internal
#: doors with their own caller lists, and they never consult this table. A misspelt route fails
#: here, not as a delegate who never matches.

#: The BFF's route ids a `door: bff` row may name (architect 11-04). The BFF owns them
#: (`src/iagent/gateway.py`); tests/security/test_gateway_delegates_rail.py goes red when
#: `gateway._REGISTER_DELEGATE_ROUTE` is not in this list. gateway_routes.json carries only the
#: central gateway's routes, so it does not retire this copy (01M6KF8279KZ843KG5MMM0R3YH).
BFF_DELEGATE_ROUTES = ("human_tasks.register",)


def _gd_doors() -> dict[str, tuple[str, ...]]:
    """A row's door is `row.get("door", "gateway")`; each door has its own route list."""
    from dag_tools.central_gateway.routes import delegatable_route_ids
    return {"gateway": tuple(delegatable_route_ids()), "bff": BFF_DELEGATE_ROUTES}

_GD_ROW_FIELDS = ("service", "door", "routes", "granted_by", "reason", "ratified_by")
#: A run with no person behind it (architect 11-04). It acts as itself, so it is never a delegate.
_PIPELINE_PREFIX = "pipeline:"


def gateway_delegates_errors(raw: dict, users: list) -> list[str]:
    """Validate policy/gateway_delegates.yaml. PURE.

    `raw` is the parsed file, `users` the users.yaml list. Each error reads
    `gateway_delegates.yaml: <service>: ...`. A delegate names a person on a route, so a row's
    `service` must be a seeded service identity (a person holds their own token) and each route a
    known one (a wildcard is an unknown route). Every row says why (`reason`) and which seat
    ratified it (`ratified_by`, e.g. `owner`: a seat, never an identity). Unknown keys are refused
    by name, so a typo (`route:`) cannot pass silently.

    A row's `door` is `gateway` (the default) or `bff`; its routes are checked against THAT door's
    list, and an unknown door is one error with no route errors. A service is unique per
    `(service, door)`: it may hold one gateway row and one bff row."""
    pre = "gateway_delegates.yaml"
    if not isinstance(raw, dict) or set(raw) != {"gateway_delegates"}:
        extra = sorted(map(str, set(raw) - {"gateway_delegates"})) if isinstance(raw, dict) else []
        return [f"{pre}: top level must be a mapping with exactly one key, `gateway_delegates`"
                + (f" (unknown key(s): {', '.join(extra)})" if extra else "")]
    rows = raw["gateway_delegates"]
    if not isinstance(rows, list):
        return [f"{pre}: `gateway_delegates` must be a list of rows (an empty list names no delegate)"]

    seeded = {str(u["id"]).strip() for u in users or [] if isinstance(u, dict) and u.get("id")}
    doors = _gd_doors()
    out: list[str] = []
    seen: set[tuple[str, str]] = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            out.append(f"{pre}: row {i}: must be a mapping")
            continue
        service = row.get("service")
        where = f"{pre}: {service if isinstance(service, str) and service.strip() else f'row {i}'}"
        for k in row:
            if k not in _GD_ROW_FIELDS:
                out.append(f"{where}: unknown key {k!r} (allowed: {', '.join(_GD_ROW_FIELDS)})")

        door = row.get("door", "gateway")
        door_key = door if isinstance(door, str) else repr(door)
        door_known = isinstance(door, str) and door in doors
        if not door_known:
            out.append(f"{where}: unknown door {door!r} (known: {', '.join(doors)})")

        if not isinstance(service, str) or not service.strip():
            out.append(f"{where}: `service` must be a non-empty string")
        else:
            if service.startswith(_PIPELINE_PREFIX):
                out.append(f"{where}: a `{_PIPELINE_PREFIX}<name>` run acts for no person and is "
                           "never a delegate row")
            elif not service.startswith(SERVICE_SUBJECT_PREFIX):
                out.append(f"{where}: `service` must be a `{SERVICE_SUBJECT_PREFIX}` identity; "
                           "a person holds their own token and is no delegate")
            elif service not in seeded:
                out.append(f"{where}: `service` is not a seeded identity in users.yaml")
            if (service, door_key) in seen:
                out.append(f"{where}: more than one row names this service on door {door_key}")
            seen.add((service, door_key))

        routes = row.get("routes")
        if not isinstance(routes, list) or not routes:
            out.append(f"{where}: `routes` must be a non-empty list")
        elif not door_known:
            pass  # one error for the door, not one per route
        else:
            known = doors[door]
            for j, r in enumerate(routes):
                if r not in known:
                    out.append(f"{where}: unknown route {r!r} for door {door} (known: {', '.join(known)})")
                elif r in routes[:j]:
                    out.append(f"{where}: route {r!r} is listed more than once")

        for k in ("granted_by", "reason", "ratified_by"):
            v = row.get(k)
            if not isinstance(v, str) or not v.strip():
                out.append(f"{where}: `{k}` must be a non-empty string")
            elif k == "ratified_by" and v.strip() in seeded:
                out.append(f"{where}: `ratified_by` names a seat (e.g. `owner`), not an identity "
                           "in users.yaml")
    return out


#: The row fields of policy/classification/levels.yaml and policy/level_readers.yaml (ADR-0064 item B,
#: Proposed, #266). Neither file is read by code yet; dag-tools step 5 serves a dataset's level.
_CL_ROW_FIELDS = ("id", "reason", "ratified_by")
_LR_ROW_FIELDS = ("level", "grant_to_groups", "granted_by", "reason", "ratified_by")


def classification_levels_errors(raw: dict, users: list) -> tuple[list[str], list[str] | None]:
    """Validate policy/classification/levels.yaml. PURE.

    Returns `(errors, levels)`. `levels` is the ORDERED list of valid ids, in file order (list
    position IS the order: least restrictive first), or None when the file is refused at the top
    level. Each error reads `classification/levels.yaml: <id or row i>: ...`. An id is the
    `<level>` of `cleared_for:<level>`, so it has no whitespace and no `:`; it is unique. Every row
    says why (`reason`) and which seat ratified it (`ratified_by`: a seat, never an identity).
    Unknown keys are refused by name. A row with a bad id contributes no level."""
    pre = "classification/levels.yaml"
    if not isinstance(raw, dict) or set(raw) != {"classification_levels"}:
        extra = sorted(map(str, set(raw) - {"classification_levels"})) if isinstance(raw, dict) else []
        return ([f"{pre}: top level must be a mapping with exactly one key, `classification_levels`"
                 + (f" (unknown key(s): {', '.join(extra)})" if extra else "")], None)
    rows = raw["classification_levels"]
    if not isinstance(rows, list):
        return ([f"{pre}: `classification_levels` must be a list of rows "
                 "(an empty list registers no level)"], None)

    seeded = {str(u["id"]).strip() for u in users or [] if isinstance(u, dict) and u.get("id")}
    out: list[str] = []
    levels: list[str] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            out.append(f"{pre}: row {i}: must be a mapping")
            continue
        lid = row.get("id")
        where = f"{pre}: {lid if isinstance(lid, str) and lid.strip() else f'row {i}'}"
        for k in row:
            if k not in _CL_ROW_FIELDS:
                out.append(f"{where}: unknown key {k!r} (allowed: {', '.join(_CL_ROW_FIELDS)})")
        if not isinstance(lid, str) or not lid.strip():
            out.append(f"{where}: `id` must be a non-empty string")
        elif any(ch.isspace() for ch in lid) or ":" in lid:
            out.append(f"{where}: `id` must have no whitespace and no `:` (it is the `<level>` "
                       "of `cleared_for:<level>`)")
        elif lid in levels:
            out.append(f"{where}: more than one row has this id")
        else:
            levels.append(lid)
        for k in ("reason", "ratified_by"):
            v = row.get(k)
            if not isinstance(v, str) or not v.strip():
                out.append(f"{where}: `{k}` must be a non-empty string")
            elif k == "ratified_by" and v.strip() in seeded:
                out.append(f"{where}: `ratified_by` names a seat (e.g. `owner`), not an identity "
                           "in users.yaml")
    return out, levels


def level_readers_errors(raw: dict, levels: list[str] | None, groups: dict, users: list) -> list[str]:
    """Validate policy/level_readers.yaml. PURE.

    `levels` is the registry's ordered ids: `[]` when the registry file is absent, None when the
    registry was refused (then no level-membership or completeness check runs: the registry's own
    error already stands, and one refused registry must not become one "unknown level" per row).
    Each error reads `level_readers.yaml: <level or row i>: ...`. One row per registered level;
    `grant_to_groups` names groups that exist and have members, and may be empty (nobody reads the
    level). A user is never named: `grant_to:` is an unknown key. Every row says why (`reason`) and
    which seat ratified it (`ratified_by`: a seat, never an identity).

    A grant is a ceiling (a group named at a level is cleared for every less restrictive one), so a
    group named at two or more registered levels is refused at each LESS restrictive row: removing it
    from a lower row would otherwise look like a revocation and change nothing. Order is the
    registry's, never the rail's row order. Runs only when `levels` is not None."""
    pre = "level_readers.yaml"
    if not isinstance(raw, dict) or set(raw) != {"level_readers"}:
        extra = sorted(map(str, set(raw) - {"level_readers"})) if isinstance(raw, dict) else []
        return [f"{pre}: top level must be a mapping with exactly one key, `level_readers`"
                + (f" (unknown key(s): {', '.join(extra)})" if extra else "")]
    rows = raw["level_readers"]
    if not isinstance(rows, list):
        return [f"{pre}: `level_readers` must be a list of rows (an empty list grants no level)"]

    seeded = {str(u["id"]).strip() for u in users or [] if isinstance(u, dict) and u.get("id")}
    out: list[str] = []
    seen: set[str] = set()
    named: dict[str, dict[str, list[str]]] = {}
    dup_levels: set[str] = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            out.append(f"{pre}: row {i}: must be a mapping")
            continue
        level = row.get("level")
        where = f"{pre}: {level if isinstance(level, str) and level.strip() else f'row {i}'}"
        for k in row:
            if k not in _LR_ROW_FIELDS:
                out.append(f"{where}: unknown key {k!r} (allowed: {', '.join(_LR_ROW_FIELDS)})")

        if not isinstance(level, str) or not level.strip():
            out.append(f"{where}: `level` must be a non-empty string")
        else:
            if levels is not None and level not in levels:
                out.append(f"{where}: {level!r} is not a level in classification/levels.yaml")
            if level in seen:
                out.append(f"{where}: more than one row names this level")
                dup_levels.add(level)
            seen.add(level)

        gtg = row.get("grant_to_groups")
        if not isinstance(gtg, list):
            out.append(f"{where}: `grant_to_groups` must be a list (`[]` says nobody reads the level)")
        else:
            names: list[str] = []
            for g in gtg:
                if not isinstance(g, str) or not g.strip():
                    out.append(f"{where}: `grant_to_groups` entries must be non-empty strings")
                elif g in names:
                    out.append(f"{where}: group {g!r} is listed more than once")
                else:
                    names.append(g)
            if isinstance(level, str) and level.strip():
                named.setdefault(level, {}).setdefault("groups", []).extend(names)
            out.extend(unusable_group_audiences(
                [SimpleNamespace(key=level if isinstance(level, str) else f"row {i}",
                                 grant_to_groups=names)],
                groups, users, file_label=pre, noun="level",
                nobody="the grant would clear NOBODY"))

        for k in ("granted_by", "reason", "ratified_by"):
            v = row.get(k)
            if not isinstance(v, str) or not v.strip():
                out.append(f"{where}: `{k}` must be a non-empty string")
            elif k == "ratified_by" and v.strip() in seeded:
                out.append(f"{where}: `ratified_by` names a seat (e.g. `owner`), not an identity "
                           "in users.yaml")

    if levels is not None:
        at: dict[str, list[str]] = {}
        for lv in levels:
            if lv in dup_levels:
                continue
            for g in dict.fromkeys(named.get(lv, {}).get("groups", [])):
                at.setdefault(g, []).append(lv)
        for lv in levels:
            for g in dict.fromkeys(named.get(lv, {}).get("groups", [])) if lv not in dup_levels else ():
                held = at[g]
                if len(held) > 1 and lv != held[-1]:
                    out.append(f"{pre}: {lv}: group {g!r} is also listed at {held[-1]!r}, which already "
                               f"clears it for {lv!r} (a grant is a ceiling: list a group once, at its "
                               f"highest level)")
        for lv in levels:
            if lv not in seen:
                out.append(f"{pre}: level {lv!r} has no row (one row per level; "
                           "`grant_to_groups: []` with a reason says nobody reads it)")
    return out

#: The row fields of policy/option_deciders.yaml (ADR-0065 (provisional, not yet written)). One row per
#: workflow and option, keyed `<workflow_id>.<option>`. Nothing reads the file yet; the options will come
#: from the workflow definition's decide step (ruling 3).
_OD_ROW_FIELDS = ("workflow", "option", "grant_to_groups", "granted_by", "reason", "ratified_by")


def option_deciders_errors(raw: dict, groups: dict, users: list) -> list[str]:
    """Validate policy/option_deciders.yaml. PURE.

    Each error reads `option_deciders.yaml: <workflow>.<option> (or row i): ...`. A row is keyed
    `<workflow_id>.<option>`, the two parts of `can_decide:<workflow_id>.<option>`: each has no whitespace,
    no `:` and no `.`, so the key splits one way; a key has one row. `grant_to_groups` names
    groups that exist and have members, and may be empty (nobody chooses the option). A user is never
    named: `grant_to:` is an unknown key. Every row says why (`reason`) and which seat ratified it
    (`ratified_by`: a seat, never an identity). Option membership (each `<option>` is one of its workflow's
    decide-step options) and one row per offered option are checked once a workflow definition carries
    the options (ADR-0065, ruling 3)."""
    pre = "option_deciders.yaml"
    if not isinstance(raw, dict) or set(raw) != {"option_deciders"}:
        extra = sorted(map(str, set(raw) - {"option_deciders"})) if isinstance(raw, dict) else []
        return [f"{pre}: top level must be a mapping with exactly one key, `option_deciders`"
                + (f" (unknown key(s): {', '.join(extra)})" if extra else "")]
    rows = raw["option_deciders"]
    if not isinstance(rows, list):
        return [f"{pre}: `option_deciders` must be a list of rows (an empty list grants no option)"]

    seeded = {str(u["id"]).strip() for u in users or [] if isinstance(u, dict) and u.get("id")}
    out: list[str] = []
    seen: set[str] = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            out.append(f"{pre}: row {i}: must be a mapping")
            continue
        workflow = row.get("workflow")
        option = row.get("option")
        parts = all(isinstance(v, str) and v.strip() for v in (workflow, option))
        key = f"{workflow}.{option}" if parts else f"row {i}"
        where = f"{pre}: {key}"
        for k in row:
            if k not in _OD_ROW_FIELDS:
                out.append(f"{where}: unknown key {k!r} (allowed: {', '.join(_OD_ROW_FIELDS)})")

        part_ok = True
        for field, v in (("workflow", workflow), ("option", option)):
            if not isinstance(v, str) or not v.strip():
                out.append(f"{where}: `{field}` must be a non-empty string")
                part_ok = False
            elif any(ch.isspace() for ch in v) or ":" in v or "." in v:
                out.append(f"{where}: `{field}` must have no whitespace, no `:` and no `.` (it is a part "
                           "of `<workflow_id>.<option>` in `can_decide:<workflow_id>.<option>`)")
                part_ok = False
        if part_ok:
            if key in seen:
                out.append(f"{where}: more than one row names this workflow and option")
            seen.add(key)

        gtg = row.get("grant_to_groups")
        if not isinstance(gtg, list):
            out.append(f"{where}: `grant_to_groups` must be a list (`[]` says nobody may choose the option)")
        else:
            names: list[str] = []
            for g in gtg:
                if not isinstance(g, str) or not g.strip():
                    out.append(f"{where}: `grant_to_groups` entries must be non-empty strings")
                elif g in names:
                    out.append(f"{where}: group {g!r} is listed more than once")
                else:
                    names.append(g)
            out.extend(unusable_group_audiences(
                [SimpleNamespace(key=key, grant_to_groups=names)],
                groups, users, file_label=pre, noun="option",
                nobody="the grant would let NOBODY choose"))

        for k in ("granted_by", "reason", "ratified_by"):
            v = row.get(k)
            if not isinstance(v, str) or not v.strip():
                out.append(f"{where}: `{k}` must be a non-empty string")
            elif k == "ratified_by" and v.strip() in seeded:
                out.append(f"{where}: `ratified_by` names a seat (e.g. `owner`), not an identity "
                           "in users.yaml")
    return out


def validate(
    policy_dir: Path,
    enums_dir: Path,
    overlay_enums: list[str] | None = None,
) -> list[str]:
    """PURE (filesystem-only): validate all eight data files against the
    enums. `overlay_enums` names the enum files the OVERLAY asserts
    (read from policy_dir instead of enums_dir). Returns the full error
    list — empty means valid."""
    errors: list[str] = []
    overlay_enums = overlay_enums or []

    def _enum_source(name: str) -> Path:
        return policy_dir if name in overlay_enums else enums_dir

    # Two-truths guard (only meaningful when the dirs differ): an enum
    # file sitting in the overlay WITHOUT being asserted would look
    # authoritative while being ignored — refuse it.
    if policy_dir != enums_dir:
        for name in ("personas.yaml", "domains.yaml"):
            if name not in overlay_enums and (policy_dir / name).is_file():
                errors.append(
                    f"{name}: present in the overlay but NOT asserted via "
                    f"--overlay-enums — an ignored-but-authoritative-looking "
                    f"enum is the two-truths trap; assert it or delete it"
                )

    personas = _read_yaml(_enum_source("personas.yaml") / "personas.yaml", errors).get("personas", [])
    _domains_doc = _read_yaml(_enum_source("domains.yaml") / "domains.yaml", errors)
    domains = list(_domains_doc.get("domains", []))
    _platform = list(_domains_doc.get("platform_domains", []))

    users_raw = _read_yaml(policy_dir / "users.yaml", errors)
    groups_raw = _read_yaml(policy_dir / "groups.yaml", errors)
    grants_raw = _read_yaml(policy_dir / "asset_grants.yaml", errors)
    tasks_raw = _read_yaml(policy_dir / "task_grants.yaml", errors)
    comps_raw = _read_yaml(policy_dir / "ontology_compartments.yaml", errors)
    caps_raw = _read_yaml(policy_dir / "capability_grants.yaml", errors)
    dc_raw = _read_yaml(policy_dir / "domain_consumption.yaml", errors)
    progs_raw = _read_yaml(policy_dir / "program_members.yaml", errors)

    # Entitlement matrix — the PolicyBundle cross-validation is the
    # same one topaz_sync runs before any write.
    try:
        # THE SAME EXPANSION topaz_sync APPLIES, from the same function. Reading `domains` alone
        # here validated a DIFFERENT bundle than the sync writes: the validator said 10 domains
        # while the sync applied 12. A validator that checks a bundle nobody deploys is the
        # mirror class in its most expensive form — it passes, and the thing it passed is not
        # the thing that ships.
        _groups = groups_raw.get("groups", {})
        domains = expand_platform_domains(domains, _platform, _groups)
        bundle = PolicyBundle(
            personas=personas,
            domains=domains,
            groups=_groups,
            users=users_raw.get("users", []),
        )
        print(f"  users.yaml/groups.yaml: personas={len(bundle.personas)} "
              f"domains={len(bundle.domains)} groups={len(bundle.groups)} "
              f"users={len(bundle.users)}")
    except (ValidationError, ValueError) as e:
        errors.append(f"users.yaml/groups.yaml: {e}")

    grants, grant_errors = load_grants(grants_raw)
    errors.extend(f"asset_grants.yaml: {e}" for e in grant_errors)
    print(f"  asset_grants.yaml: {len(grants)} grant(s)")

    audiences, audience_errors = load_audiences(tasks_raw)
    errors.extend(f"task_grants.yaml: {e}" for e in audience_errors)
    print(f"  task_grants.yaml: {len(audiences)} audience(s)")

    comps, comp_errors, default_visibility = load_compartments(comps_raw)
    errors.extend(f"ontology_compartments.yaml: {e}" for e in comp_errors)
    print(f"  ontology_compartments.yaml: {len(comps)} compartment(s), "
          f"default_visibility={default_visibility}")

    caps, cap_errors = load_capabilities(caps_raw)
    errors.extend(f"capability_grants.yaml: {e}" for e in cap_errors)
    print(f"  capability_grants.yaml: {len(caps)} capability(ies)")

    # ORIGIN ENTITLEMENT (architect ruling, 2026-10-02): domain_consumption.yaml's rows
    # and program_members.yaml's grants, validated against the SAME expanded domain set
    # the entitlement matrix above checks against — a domain named here that domains.yaml
    # does not know is the same mirror-class error as an unknown persona/domain cell.
    dc_known_domains = set(domains)
    errors.extend(domain_consumption_required_fields(dc_raw, dc_known_domains))
    n_dc_rows = len((dc_raw or {}).get("domain_consumption") or {})
    print(f"  domain_consumption.yaml: {n_dc_rows} row(s)")

    programs, program_errors = load_programs(progs_raw)
    errors.extend(f"program_members.yaml: {e}" for e in program_errors)
    print(f"  program_members.yaml: {len(programs)} program(s)")

    # `cleared_for:<level>` is the level rail's key (ADR-0064 item B), never a capability row; `can_read`
    # stays what it is, so no `can_read:` key is refused here.
    for c in caps:
        if c.key.startswith("cleared_for:"):
            errors.append(
                f"capability_grants.yaml: capability {c.key!r}: a level's clearances are rows of "
                f"policy/level_readers.yaml, not a capability row")

    # `can_decide:<workflow_id>.<option>` is the option rail's key (ADR-0065, provisional), never a
    # capability row.
    for c in caps:
        if c.key.startswith("can_decide:"):
            errors.append(
                f"capability_grants.yaml: capability {c.key!r}: an option's deciders are rows of "
                f"policy/option_deciders.yaml, not a capability row")

    # `can_drop:<K>` (2026-10-28 ruling): the key gates drops of content kind K by the capability
    # OBJECT's existence, so a misspelt kind (`can_drop:pnc`) would gate a kind nobody drops and
    # leave `pcn` open, silently. REFUSE it, naming what the known set was composed from.
    _kinds, _sources = known_content_kinds()
    for c in caps:
        if c.key.startswith("can_drop:") and c.key[len("can_drop:"):] not in _kinds:
            errors.append(
                f"capability_grants.yaml: {c.key!r} names {c.key[len('can_drop:'):]!r}, which is "
                f"NOT a known content kind -- a misspelt key gates nothing and leaves the real "
                f"kind open. Known kinds ({len(_kinds)}) were composed from the `kind:` field "
                f"of: " + "; ".join(_sources))

    # `can_export:<P>` (DENY-BY-DEFAULT, unlike can_drop): the door asks can_invoke on
    # `can_export:<P>` and False refuses, so a profile with no row is exportable by NOBODY. There is
    # no generated default (the sync Job's image cannot reliably see every profile overlay), so the
    # defaults are met by COMPLETENESS here: every known profile, of every kind, must have a row
    # (CDRL ruled 2026-10-29, answer-export ruled 2026-10-30). The refusal's advice is DERIVED from
    # the rows that decide other profiles of the same kind -- never a group held in code.
    _profiles, _pnotes = known_export_profiles()
    for _n in _pnotes:
        if _n.startswith("COLLISION:"):
            errors.append(f"capability_grants.yaml: export profile {_n}")
        elif _n.startswith("REFUSED:"):
            errors.append(f"export profiles: {_n}")
    # A refused kind composed no names, so its rows would all read as misspelt: say the refusal once.
    _refused = any(n.startswith("REFUSED:") for n in _pnotes)
    _pnotes = [n for n in _pnotes if not n.startswith(("COLLISION:", "REFUSED:"))]
    _export_keys = {c.key[len("can_export:"):] for c in caps if c.key.startswith("can_export:")}
    for _p in sorted(set() if _refused else _export_keys - set(_profiles)):
        errors.append(
            f"capability_grants.yaml: 'can_export:{_p}' names {_p!r}, which is NOT a known export "
            f"profile -- a misspelt key gates nothing and the real profile stays unexportable. "
            f"Known profiles ({len(_profiles)}) were composed from the `name` field of: "
            + "; ".join(_pnotes))
    _kind_groups: dict[str, set[str]] = {}
    for c in caps:
        _cp = c.key[len("can_export:"):] if c.key.startswith("can_export:") else None
        if _cp in _profiles:
            _kind_groups.setdefault(_profiles[_cp], set()).update(c.grant_to_groups)
    for _p, _k in sorted(_profiles.items()):
        if _p not in _export_keys:
            _g = sorted(_kind_groups.get(_k, ()))
            errors.append(
                f"capability_grants.yaml: {_k} profile {_p!r} has no 'can_export:{_p}' row, so "
                f"NOBODY could export it (deny-by-default). Add one; "
                + (f"the other {_k} rows grant `grant_to_groups: [{', '.join(_g)}]`" if _g else
                   f"no other {_k} profile has a row to follow, so the row names its own group "
                   f"(ask the architect)"))

    # `can_call:<T>` (2026-10-30 ruling, deny-by-default): the door asks can_invoke on `can_call:<T>`
    # for every tag of the route; a misspelt key gates nothing. No row is required per tag.
    _ctags, _cnotes = known_call_tags()
    for c in caps:
        if c.key.startswith("can_call:") and c.key[len("can_call:"):] not in _ctags:
            errors.append(
                f"capability_grants.yaml: {c.key!r} names {c.key[len('can_call:'):]!r}, which is "
                f"NOT a tag of the served MCP document -- a misspelt key gates nothing and the "
                f"real tag stays uncallable through a door. Known tags ({len(_ctags)}): "
                + ", ".join(sorted(_ctags)) + "; composed from " + "; ".join(_cnotes))

    # `can_review:<S>` (2026-11-02 ruling, deny-by-default) and `can_configure:<S>` (ruled the same
    # way): the surface asks can_invoke on the key; a misspelt key gates nothing. No row is required
    # per subject.
    for _prefix, _known, _noun, _able in (
            ("can_review:", known_review_subjects, "review", "reviewable"),
            ("can_configure:", known_configure_subjects, "configure", "configurable")):
        _subjects, _notes = _known()
        for c in caps:
            if c.key.startswith(_prefix) and c.key[len(_prefix):] not in _subjects:
                errors.append(
                    f"capability_grants.yaml: {c.key!r} names {c.key[len(_prefix):]!r}, which is "
                    f"NOT a registered {_noun} subject -- a misspelt key gates nothing and the real "
                    f"subject stays {_able} by nobody. Known subjects ({len(_subjects)}): "
                    + ", ".join(sorted(_subjects)) + "; composed from " + "; ".join(_notes))

    # recipient_readers.yaml: validated WHEN PRESENT only (not in DATA_FILES -- see the note
    # there; required-or-not is open with the architect). Absent = no reader asserted = every
    # recipient check denies, which is fail-closed, so absence is not an error here.
    readers: list = []
    _readers_path = policy_dir / "recipient_readers.yaml"
    if _readers_path.is_file():
        readers_raw = _read_yaml(_readers_path, errors)
        readers, reader_errors = load_readers(readers_raw)
        errors.extend(f"recipient_readers.yaml: {e}" for e in reader_errors)
        print(f"  recipient_readers.yaml: {len(readers)} recipient scope(s)")

    # repository_paths.yaml (ADR-0062 section 5): validated WHEN PRESENT only (not in DATA_FILES --
    # see the note there). Only engine-r reads it, and a deployment may not run engine-r.
    _rp_path = policy_dir / "repository_paths.yaml"
    if _rp_path.is_file():
        rp_raw = _read_yaml(_rp_path, errors)
        errors.extend(repository_paths_errors(
            rp_raw, audiences, groups_raw.get("groups") or {}, users_raw.get("users") or []))
        _repos = rp_raw.get("repository_paths") or {}
        _repos = _repos if isinstance(_repos, dict) else {}
        _n_rows = sum(len(b.get(k) or {}) for b in _repos.values() if isinstance(b, dict)
                      for k in ("paths", "tags") if isinstance(b.get(k), dict))
        _m = len(_repos)
        print(f"  repository_paths.yaml: {_n_rows} row(s) across {_m} "
              f"{'repository' if _m == 1 else 'repositories'}")

    # gateway_delegates.yaml: validated WHEN PRESENT only (not in DATA_FILES -- see the note there).
    _gd_path = policy_dir / "gateway_delegates.yaml"
    if _gd_path.is_file():
        gd_raw = _read_yaml(_gd_path, errors)
        errors.extend(gateway_delegates_errors(gd_raw, users_raw.get("users") or []))
        _gd_rows = gd_raw.get("gateway_delegates")
        print(f"  gateway_delegates.yaml: {len(_gd_rows) if isinstance(_gd_rows, list) else 0} row(s)")

    # classification/levels.yaml + level_readers.yaml (ADR-0064 item B, Proposed, #266): validated
    # WHEN PRESENT only (not in DATA_FILES -- see the note there). The rail is checked against the
    # registry; an absent registry registers no level, and a registered level with the rail absent
    # reports its missing row.
    _users_list = users_raw.get("users") or []
    _groups_map = groups_raw.get("groups") or {}
    _cl_levels: list[str] | None = []
    _cl_path = policy_dir / "classification" / "levels.yaml"
    if _cl_path.is_file():
        cl_raw = _read_yaml(_cl_path, errors)
        _cl_errors, _cl_levels = classification_levels_errors(cl_raw, _users_list)
        errors.extend(_cl_errors)
        _cl_rows = cl_raw.get("classification_levels")
        print(f"  classification/levels.yaml: {len(_cl_rows) if isinstance(_cl_rows, list) else 0} level(s)")
    _lr_path = policy_dir / "level_readers.yaml"
    if _lr_path.is_file():
        lr_raw = _read_yaml(_lr_path, errors)
        errors.extend(level_readers_errors(lr_raw, _cl_levels, _groups_map, _users_list))
        _lr_rows = lr_raw.get("level_readers")
        print(f"  level_readers.yaml: {len(_lr_rows) if isinstance(_lr_rows, list) else 0} row(s)")
    elif _cl_levels:
        errors.extend(level_readers_errors({"level_readers": []}, _cl_levels, _groups_map, _users_list))
    # option_deciders.yaml (ADR-0065, provisional): WHEN PRESENT only; no code reads workflow definitions yet.
    _od_path = policy_dir / "option_deciders.yaml"
    if _od_path.is_file():
        od_raw = _read_yaml(_od_path, errors)
        errors.extend(option_deciders_errors(od_raw, _groups_map, _users_list))
        _od_rows = od_raw.get("option_deciders")
        print(f"  option_deciders.yaml: {len(_od_rows) if isinstance(_od_rows, list) else 0} row(s)")

    # ADMISSION POSTURE (ADR-0034). Validated through the SAME parser the runtime loads with, so
    # there is ONE definition of a well-formed table and this gate cannot drift from the loader.
    # Added when the table acquired a production reader (phase 1.3) — before that it was a git
    # artifact nothing consumed, and a validator for it would have guarded nothing.
    #
    # OPTIONAL BY DESIGN: a deployment with no trust table expresses no admission policy and
    # supervises everything, which is the born-default, not an error.
    trust_path = policy_dir / "trust_table.yaml"
    if trust_path.exists():
        trust_raw = _read_yaml(trust_path, errors)
        try:
            import sys as _sys
            _root = Path(__file__).resolve().parents[2]
            if str(_root) not in _sys.path:
                _sys.path.insert(0, str(_root))
            from agent_fleet.utils.trust_table import parse_trust_table  # noqa: PLC0415
            parse_trust_table(trust_raw, ref="validate")
            fmts = trust_raw.get("formats") or {}
            n_promoted = sum(1 for e in fmts.values()
                             if isinstance(e, dict) and e.get("rung") not in (None, "supervised"))
            print(f"  trust_table.yaml: {len(fmts)} format(s), {n_promoted} above supervised")
        except Exception as exc:  # noqa: BLE001 — a malformed table REFUSES, never warns
            errors.append(f"trust_table.yaml: {exc}")

    # VENDOR ALIASES (ADR-0034 phase 1.3 normalization). Validated through the SAME parser the
    # producer loads with, so the gate cannot drift from the emitter. A malformed overlay must
    # REFUSE rather than be skipped: silently ignoring it would canonicalise some artifacts and not
    # others, producing the very vendor split it exists to prevent — intermittently, which is worse
    # than consistently.
    #
    # Optional by design: a deployment with no witnessed splits declares no aliases.
    alias_path = policy_dir / "vendor_aliases.yaml"
    if alias_path.exists():
        alias_raw = _read_yaml(alias_path, errors)
        try:
            import sys as _sys
            _root = Path(__file__).resolve().parents[2]
            if str(_root) not in _sys.path:
                _sys.path.insert(0, str(_root))
            from agent_fleet.utils.format_fingerprint import parse_vendor_aliases  # noqa: PLC0415
            aliases = parse_vendor_aliases(alias_raw)
            print(f"  vendor_aliases.yaml: {len(aliases)} alias(es)")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"vendor_aliases.yaml: {exc}")

    # AUTHOR-BUG GATE, family-wide. ALL FOUR grant syncs write `user` subjects
    # UNCONDITIONALLY, so a grantee that isn't a known user seeds a phantom
    # `user:<name>` that PASSES readback while granting nothing (silent-wrong-grant).
    # On task_grants this is the sharpest: an approval task routed to NOBODY while the
    # file says it's covered — a workflow suspends awaiting an approver who cannot
    # exist. Refuse it LOUD here. Group grants are a DEFERRED design decision (needs a
    # membership-drift audit ruling + manifest `user | group#member` + sync support);
    # until then, USERS ONLY across the family.
    known_users = {
        str(u.get("id", "")).strip()
        for u in users_raw.get("users", []) if isinstance(u, dict)
    }
    known_users.discard("")
    if known_users:  # skip if users.yaml didn't parse (that's already an error above)
        errors.extend(unknown_user_subjects("asset_grants.yaml",
            [(g.asset, g.subject) for g in grants], known_users))
        errors.extend(unknown_user_subjects("task_grants.yaml",
            [(a.key, gt) for a in audiences for gt in a.grant_to], known_users))
        errors.extend(unknown_user_subjects("ontology_compartments.yaml",
            [(comp.name, gt) for comp in comps for gt in comp.grant_to], known_users))
        errors.extend(unknown_user_subjects("capability_grants.yaml",
            [(c.key, gt) for c in caps for gt in c.grant_to], known_users))
        errors.extend(unknown_user_subjects("program_members.yaml",
            [(p.key, gt) for p in programs for gt in p.grant_to], known_users))
        errors.extend(unknown_user_subjects("recipient_readers.yaml",
            [(r.object_id, gt) for r in readers for gt in r.grant_to], known_users))

    # grant_to_groups: the group must exist and have members (2026-10-10 ruling).
    errors.extend(unusable_group_audiences(
        audiences, groups_raw.get("groups") or {}, users_raw.get("users") or []))
    errors.extend(unusable_group_audiences(
        caps, groups_raw.get("groups") or {}, users_raw.get("users") or [],
        file_label="capability_grants.yaml", noun="capability",
        nobody="nobody could invoke the capability"))

    # review_shape: one vocabulary, one registry (ruled 2026-10-30). A row must validate, and a
    # content kind's `review_shape` must name a row, or the card it asks for is not one we render.
    _shape_errors, _n_shapes = review_shape_errors(policy_dir, enums_dir)
    errors.extend(_shape_errors)
    print(f"  review_shapes: {_n_shapes} shape(s)")

    # ── NO SERVICE IDENTITY AS A DISCLOSURE RECIPIENT ───────────────────────────────────────
    #
    # Runs OUTSIDE the `known_users` guard on purpose: a `svc:` grantee is refused whether or
    # not users.yaml parsed. The other check asks "does this principal exist"; this one asks
    # "may this KIND of principal receive disclosure", and the answer does not depend on the
    # roster being readable.
    errors.extend(service_identity_recipients("asset_grants.yaml",
        [(g.asset, g.subject) for g in grants]))
    errors.extend(service_identity_recipients("task_grants.yaml",
        [(a.key, gt) for a in audiences for gt in a.grant_to]))
    errors.extend(service_identity_recipients("ontology_compartments.yaml",
        [(comp.name, gt) for comp in comps for gt in comp.grant_to]))
    # ADR-0047 §5.1: program membership is DISCLOSURE (origin-entitlement ruling,
    # 2026-10-02) — a `svc:` principal must never be a program member.
    errors.extend(service_identity_recipients("program_members.yaml",
        [(p.key, gt) for p in programs for gt in p.grant_to]))
    # ADR-0047 §5.1: a recipient's disclosure package is DISCLOSURE too (the loader refuses a
    # `svc:` grantee itself; this is the shared check, kept so the two cannot drift).
    errors.extend(service_identity_recipients("recipient_readers.yaml",
        [(r.object_id, gt) for r in readers for gt in r.grant_to]))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate all eight policy data files (no network).",
    )
    parser.add_argument(
        "--policy-dir",
        default="policy",
        help="Directory holding the six DATA files (default: %(default)s).",
    )
    parser.add_argument(
        "--enums-from",
        default=None,
        help=(
            "Directory holding personas.yaml/domains.yaml (default: same "
            "as --policy-dir). Overlay repos validate their data files "
            "against the PRODUCT's enums: --enums-from /app/policy."
        ),
    )
    parser.add_argument(
        "--overlay-enums",
        action="append",
        default=[],
        choices=["personas.yaml", "domains.yaml"],
        metavar="FILE",
        help=(
            "Enum file the OVERLAY asserts (repeatable) — read from "
            "--policy-dir instead of --enums-from. Mirrors the chart's "
            "topazSeed.policySource.overlayEnums. Both enums are fully "
            "assertable (personas since chart 0.3.12 — the catalog rego "
            "walks the directory, no hardcoded list)."
        ),
    )
    args = parser.parse_args()

    policy_dir = Path(args.policy_dir).resolve()
    enums_dir = Path(args.enums_from).resolve() if args.enums_from else policy_dir
    print(f"===== Validate policy data from {policy_dir} "
          f"(enums from {enums_dir}"
          f"{'; overlay-asserted: ' + ', '.join(args.overlay_enums) if args.overlay_enums else ''}) =====")

    errors = validate(policy_dir, enums_dir, args.overlay_enums)
    if errors:
        print(f"REFUSED — {len(errors)} error(s); nothing should be applied:",
              file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 2

    print("===== VALIDATION OK =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
