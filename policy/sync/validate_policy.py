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
    (see known_export_profiles), no profile name is in BOTH kinds, and every review-export
    profile (policy/exports) has a `can_export:<P>` row (deny-by-default: no row, nobody exports)
  - recipient_readers.yaml        → recipient_reader_sync.load_readers (WHEN PRESENT; not in
    DATA_FILES -- see the note there)
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
import os
import sys
from pathlib import Path

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


def known_export_profiles(
    sources: list[tuple[Path, str]] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """The export profiles a `can_export:<P>` capability key may name: {name: kind}, and notes.

    kind is "review_export" (lane/01's ingest-review profiles, policy/exports) or "fin_cdrl"
    (fin's CDRL profiles). `sources` is an ordered [(dir, kind)] for tests; None composes:
      - review_export: <root>/policy/exports (lane/01 adds its overlay env var here once it
        defines one; the directory does not exist yet, which is read as absent, not an error);
      - fin_cdrl: the seed (FIN_EXPORT_PROFILE_POLICY_DIR if set, else
        <root>/policy/fin_export_profiles), each dir in FIN_EXPORT_PROFILE_OVERLAY_DIRS, then the
        sandbox's overlay (policy/overlays/sample/fin_export_profiles).
    Within a kind fin's semantics apply (agent_fleet/finance_agent/export_profiles.py): dirs are
    applied in order, a later same-`name` row replaces an earlier one, `deleted: true` removes the
    name. Only `name` and `deleted` are read (this gate runs where the engines are not
    importable); unparseable files are ignored, as known_content_kinds does. A name present in
    both final sets is a COLLISION: a note starting `COLLISION:` which validate() turns into an
    error. Each source's note reads `<dir> (<n> profile(s))` or `<dir> (absent)`."""
    root = Path(__file__).resolve().parents[2]
    if sources is None:
        sources = [(root / "policy" / "exports", "review_export")]
        sources.append((Path(os.getenv("FIN_EXPORT_PROFILE_POLICY_DIR")
                             or root / "policy" / "fin_export_profiles"), "fin_cdrl"))
        raw = (os.getenv("FIN_EXPORT_PROFILE_OVERLAY_DIRS") or "").strip()
        sources += [(Path(p.strip()), "fin_cdrl") for p in raw.split(os.pathsep) if p.strip()]
        sources.append((root / "policy" / "overlays" / "sample" / "fin_export_profiles", "fin_cdrl"))
    by_kind: dict[str, set[str]] = {}
    notes: list[str] = []
    for d, kind in sources:
        names = by_kind.setdefault(kind, set())
        if not d.is_dir():
            notes.append(f"{d.as_posix()} (absent)")
            continue
        found = 0
        for f in sorted(d.glob("*.yaml")):
            try:
                doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                continue
            n = doc.get("name") if isinstance(doc, dict) else None
            if not (isinstance(n, str) and n.strip()):
                continue
            n = n.strip()
            if doc.get("deleted") is True:
                names.discard(n)
            else:
                names.add(n)
                found += 1
        notes.append(f"{d.as_posix()} ({found} profile(s))")
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
    # "alert-processors by default" is met by COMPLETENESS here: every review-export profile must
    # have a row. A fin CDRL row is allowed but NOT required (pending the architect's ruling: a CDRL
    # is a program-office deliverable, an AP default looks wrong for it).
    _profiles, _pnotes = known_export_profiles()
    for _n in _pnotes:
        if _n.startswith("COLLISION:"):
            errors.append(f"capability_grants.yaml: export profile {_n}")
    _pnotes = [n for n in _pnotes if not n.startswith("COLLISION:")]
    _export_keys = {c.key[len("can_export:"):] for c in caps if c.key.startswith("can_export:")}
    for _p in sorted(_export_keys - set(_profiles)):
        errors.append(
            f"capability_grants.yaml: 'can_export:{_p}' names {_p!r}, which is NOT a known export "
            f"profile -- a misspelt key gates nothing and the real profile stays unexportable. "
            f"Known profiles ({len(_profiles)}) were composed from the `name` field of: "
            + "; ".join(_pnotes))
    for _p, _k in sorted(_profiles.items()):
        if _k == "review_export" and _p not in _export_keys:
            errors.append(
                f"capability_grants.yaml: review-export profile {_p!r} has no 'can_export:{_p}' "
                f"row, so NOBODY could export it (deny-by-default). Add one; the default is "
                f"`grant_to_groups: [alert-processors]`")

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
