"""The `recipient_readers` policy rail, and the ratchet that moves the code-held tables onto it.

Architect, 2026-10-27 ruling 4 (refined 2026-10-28): "gov writes the rail shape (a
recipient_readers family with grantors); fin and cost each move their own RECIPIENT_READERS onto
it." Who may download a recipient's disclosure package was a code table in two engines
(`finance_agent/export.py`, `cost_agent/seed.py`); this file seals the RAIL they move onto, not
the move itself (the owning lanes do that and shrink PENDING below as they go).

WHAT EACH GROUP DEFENDS
  loader      a malformed row is DROPPED and an error NAMES THE FIELD -- a broken overlay refuses
              whole, never partially applies (a silently dropped row is a reader nobody can find).
  derive      the Topaz object id is `<owner>:<scope>`; the same scope string under the two owners
              is two objects (CONTROL), so a reader of one engine is never a reader of the other.
  shipped     the committed policy/recipient_readers.yaml loads clean with exactly the three owners;
              its one plan row (ruled 2026-10-30) is alice on a scope an answer profile names.
  grantor     the family resolves in the composed grantor map, object-scoped, pointing at a rail
              file that exists -- so a refusal on this family can name who grants.
  join        the engine's question (object type, permission), the sync's constants and EVERY
              chart manifest copy agree. An invariant BETWEEN declarations is invisible to each
              declaration's own check.
  validate    a present malformed file is an error; an absent file is NOT (it is not in
              DATA_FILES; required-or-not is open with the architect).
  ratchet     no new module-level `RECIPIENT_READERS` table may appear in code, and a file that
              stops holding one must leave PENDING. The census is positive-controlled.
  render      the Job runs the leg AFTER program_member_sync, and an absent overlay file WARNs
              (fail-closed: nothing asserted, every check denies) instead of exiting 2.

Run:  uv run pytest tests/security/test_recipient_readers_rail.py -q
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_SYNC = _REPO / "policy" / "sync"
for _p in (str(_SYNC), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import recipient_reader_sync as rrs  # noqa: E402
from recipient_reader_sync import derive_desired, load_readers  # noqa: E402

_RAIL = _REPO / "policy" / "recipient_readers.yaml"
_CHART = "helm/invincible-agent"


def _row(**over):
    row = {"granted_by": "cnogradi", "reason": "demo", "grant_to": ["alice@example.com"]}
    row.update(over)
    return row


def _raw(owner="finance", scope="S1", row=None):
    return {"recipient_readers": {owner: {scope: _row() if row is None else row}}}


# -- loader ---------------------------------------------------------------------------------

def test_wellformed_row_loads():
    """The control for every refusal below: the same shape, nothing wrong, is accepted."""
    rows, errors = load_readers(_raw())
    assert errors == []
    assert [(r.owner, r.scope, r.grant_to) for r in rows] == [
        ("finance", "S1", ("alice@example.com",))]


@pytest.mark.parametrize("field,over", [
    ("granted_by", {"granted_by": ""}),
    ("granted_by", {"granted_by": "   "}),
    ("reason", {"reason": ""}),
    ("reason", {"reason": None}),
    ("grant_to", {"grant_to": []}),
    ("grant_to", {"grant_to": "alice@example.com"}),
    ("grant_to", {"grant_to": None}),
])
def test_a_row_missing_a_required_field_is_dropped_and_the_error_names_it(field, over):
    """An unexplained or targetless row is not a grant: dropped, and the error names the field."""
    rows, errors = load_readers(_raw(row=_row(**over)))
    assert rows == []
    assert len(errors) == 1 and field in errors[0], errors


def test_an_owner_outside_the_closed_set_is_dropped_and_named():
    rows, errors = load_readers(_raw(owner="safety"))
    assert rows == []
    assert len(errors) == 1 and "safety" in errors[0] and "owner" in errors[0], errors


def test_a_non_mapping_owner_block_is_dropped_and_named():
    rows, errors = load_readers({"recipient_readers": {"finance": ["S1"]}})
    assert rows == []
    assert len(errors) == 1 and "finance" in errors[0] and "owner block" in errors[0], errors


def test_a_non_mapping_row_is_dropped_and_named():
    rows, errors = load_readers(_raw(row="alice@example.com"))
    assert rows == []
    assert len(errors) == 1 and "S1" in errors[0] and "row" in errors[0], errors


def test_a_service_identity_grantee_is_refused():
    """ADR-0047 5.1: a disclosure to a `svc:` principal entitles every caller it serves."""
    rows, errors = load_readers(_raw(row=_row(grant_to=["alice@example.com", "svc:engine-x"])))
    assert rows == []
    assert len(errors) == 1 and "grant_to" in errors[0] and "svc:engine-x" in errors[0], errors


def test_empty_owners_are_explicit_and_load_clean():
    rows, errors = load_readers({"recipient_readers": {"finance": {}, "cost": {}}})
    assert (rows, errors) == ([], [])


# -- derive ---------------------------------------------------------------------------------

def test_derive_object_id_is_owner_colon_scope_one_relation_per_grantee():
    rows, errors = load_readers(_raw(owner="cost", scope="notional-customer-alpha",
                                     row=_row(grant_to=["alice@example.com", "bob@example.com"])))
    assert errors == []
    state = derive_desired(rows)
    rels = {(r.object_type, r.object_id, r.relation, r.subject_type, r.subject_id)
            for r in state.relations}
    assert rels == {
        ("recipient_scope", "cost:notional-customer-alpha", "reader", "user", "alice@example.com"),
        ("recipient_scope", "cost:notional-customer-alpha", "reader", "user", "bob@example.com"),
    }


def test_the_same_scope_under_both_owners_is_two_objects():
    """CONTROL for the owner prefix: a colliding scope string must NOT share readers. Drop the
    owner from the object id and this collapses to one object and goes red."""
    raw = {"recipient_readers": {"finance": {"X": _row()}, "cost": {"X": _row()}}}
    rows, errors = load_readers(raw)
    assert errors == []
    ids = {r.object_id for r in derive_desired(rows).relations}
    assert ids == {"finance:X", "cost:X"}


# -- the shipped file -----------------------------------------------------------------------

def test_shipped_rail_file_loads_clean_with_exactly_the_three_owners():
    """`plan` joined 2026-10-29 (architect's ruling) for fin's #148 plan recipient. A NEW owner
    needs a ruling, not an edit."""
    raw = yaml.safe_load(_RAIL.read_text(encoding="utf-8"))
    _rows, errors = load_readers(raw)
    assert errors == []
    assert set(raw["recipient_readers"]) == {"finance", "cost", "plan"} == set(rrs.OWNERS)


def test_the_shipped_plan_row_is_alice_on_the_notional_plan_office():
    """Ruled 2026-10-30: "#159 adds alice as a reader of plan:notional-plan-office". Exactly that
    one object and one reader -- a wider row is a reader nobody ruled."""
    raw = yaml.safe_load(_RAIL.read_text(encoding="utf-8"))
    rows, errors = load_readers(raw)
    assert errors == []
    plan = [(r.object_id, sorted(r.grant_to)) for r in rows if r.object_id.startswith("plan:")]
    assert plan == [("plan:notional-plan-office", ["alice@example.com"])], plan


def test_every_shipped_plan_scope_is_a_recipient_an_answer_profile_names():
    """Join: a plan reader row on a scope no answer-export profile names entitles a download that
    never exists, and the real recipient stays refused. Read from #148's profiles by FORM
    (policy/exports/answers/*.yaml `recipients`); skips until they are on this tree."""
    answers = _REPO / "policy" / "exports" / "answers"
    named = set()
    for f in sorted(answers.glob("*.yaml")) if answers.is_dir() else []:
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        if isinstance(doc, dict) and not doc.get("deleted"):
            named |= set(doc.get("recipients") or [])
    if not named:
        pytest.skip("no answer-export profile names a recipient on this tree (fin's #148 has not landed)")
    raw = yaml.safe_load(_RAIL.read_text(encoding="utf-8"))
    scopes = set((raw["recipient_readers"].get("plan") or {}))
    assert scopes and scopes <= named, (scopes, named)


def test_a_plan_row_loads_and_derives_a_plan_object():
    rows, errors = load_readers(_raw(owner="plan", scope="notional-plan-office"))
    assert errors == [] and [r.object_id for r in rows] == ["plan:notional-plan-office"]
    ids = {r.object_id for r in derive_desired(rows).relations}
    assert ids == {"plan:notional-plan-office"}


def test_the_plan_owner_is_the_one_every_consumer_asks_for():
    """Join: the owner string fin's consumers pass (#148: engine-cost and the BFF each declare
    `_PLAN_OWNER`) is a member of the closed set. Found by FORM, so a third consumer is held too.
    Skips until a consumer is on this tree; then a renamed constant on either side reds."""
    form = re.compile(r'^_PLAN_OWNER\s*=\s*"([^"]*)"', re.M)
    found = {}
    for top in ("agent_fleet", "src"):
        for f in (_REPO / top).rglob("*.py"):
            if ".venv" in f.parts or "__pycache__" in f.parts:
                continue
            for m in form.finditer(f.read_text(encoding="utf-8", errors="replace")):
                found[f.relative_to(_REPO).as_posix()] = m.group(1)
    if not found:
        pytest.skip("no consumer declares _PLAN_OWNER on this tree (fin's #148 has not landed)")
    assert {k: v for k, v in found.items() if v not in rrs.OWNERS} == {}, found


# -- grantor --------------------------------------------------------------------------------

def test_grantor_family_is_object_scoped_and_points_at_the_rail(monkeypatch):
    from src.iagent.authz import refusal as ref
    monkeypatch.setattr(ref, "_GRANTORS_CACHE", None)
    monkeypatch.delenv("GRANTOR_OVERLAY_DIRS", raising=False)
    g = ref.grantors().get("recipient_readers")
    assert g is not None, "no policy/grantors/recipient_readers.yaml in the composed map"
    assert g.object_scoped is True
    assert g.rail_file == "policy/recipient_readers.yaml"
    assert (_REPO / g.rail_file).is_file()
    with pytest.raises(ValueError):
        ref.refusal("recipient_readers:anything", "reader on finance:S1")
    monkeypatch.setattr(ref, "_GRANTORS_CACHE", None)  # do not leak this map to other tests


# -- the join: engine question == sync constants == every manifest copy ---------------------

def _manifest_copies() -> list[tuple[str, dict]]:
    """Every chart template that carries a Topaz manifest (found by declaring the `program`
    type), parsed. The configmap is a block scalar under a Helm template, so the manifest text
    is cut at the `manifest.yaml: |` key and de-indented before parsing."""
    out = []
    for f in sorted((_REPO / _CHART / "templates").glob("*.yaml")):
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            m = re.match(r"^(\s*)manifest\.yaml:\s*\|", line)
            if not m:
                continue
            ind = len(m.group(1))
            body = []
            for nxt in lines[i + 1:]:
                if nxt.strip() and len(nxt) - len(nxt.lstrip(" ")) <= ind:
                    break
                body.append(nxt[ind + 2:] if nxt.strip() else "")
            doc = yaml.safe_load("\n".join(body))
            out.append((f.name, doc))
    return out


def test_engine_check_and_every_manifest_copy_agree_with_the_sync():
    from agent_fleet.utils.recipient_readers import check_payload
    p = check_payload("finance", "S1", "alice@example.com")
    assert p["object_type"] == rrs.OBJECT_TYPE
    assert p["relation"] == rrs.PERMISSION
    assert p["object_id"] == "finance:S1" and p["subject_type"] == "user"
    copies = _manifest_copies()
    assert copies, "found no manifest copy in the chart -- the parse below would pass vacuously"
    for name, doc in copies:
        types = doc["types"]
        t = types.get(rrs.OBJECT_TYPE)
        assert t is not None, f"{name}: manifest does not declare {rrs.OBJECT_TYPE}"
        assert t["permissions"][rrs.PERMISSION] == rrs.RELATION, name
        assert t["relations"][rrs.RELATION] == "user", f"{name}: users only, no group#member"


# -- validate_policy ------------------------------------------------------------------------

def _policy_copy(tmp_path: Path) -> Path:
    import validate_policy as vp
    d = tmp_path / "policy"
    d.mkdir()
    for name in (*vp.DATA_FILES, "personas.yaml", "domains.yaml"):
        shutil.copy(_REPO / "policy" / name, d / name)
    return d


def test_validate_policy_absent_rail_file_is_not_an_error(tmp_path):
    import validate_policy as vp
    d = _policy_copy(tmp_path)
    assert not (d / "recipient_readers.yaml").exists()
    assert "recipient_readers.yaml" not in vp.DATA_FILES
    assert vp.validate(d, d) == []


def test_validate_policy_present_malformed_rail_file_is_an_error(tmp_path):
    import validate_policy as vp
    d = _policy_copy(tmp_path)
    (d / "recipient_readers.yaml").write_text(yaml.safe_dump(
        {"recipient_readers": {"finance": {"S1": {"granted_by": "", "reason": "r",
                                                  "grant_to": ["alice@example.com"]}}}}))
    errs = vp.validate(d, d)
    assert any("recipient_readers.yaml" in e and "granted_by" in e for e in errs), errs


def test_validate_policy_present_wellformed_rail_file_with_unknown_user_is_an_error(tmp_path):
    """The unknown-user helper reaches the new file; the control is the known user passing."""
    import validate_policy as vp
    d = _policy_copy(tmp_path)
    known = yaml.safe_load((d / "users.yaml").read_text(encoding="utf-8"))["users"][0]["id"]
    ok = {"recipient_readers": {"cost": {"S1": _row(grant_to=[known])}}}
    (d / "recipient_readers.yaml").write_text(yaml.safe_dump(ok))
    assert vp.validate(d, d) == []
    ok["recipient_readers"]["cost"]["S1"]["grant_to"] = ["nobody-at-all@example.com"]
    (d / "recipient_readers.yaml").write_text(yaml.safe_dump(ok))
    assert any("recipient_readers.yaml" in e for e in vp.validate(d, d))


# -- RATCHET: no code-held RECIPIENT_READERS table beyond the pending two -------------------

PENDING = {
    "agent_fleet/finance_agent/export.py",
    "agent_fleet/cost_agent/seed.py",
}
_NAME = "RECIPIENT_READERS"


def holds_table(source: str) -> bool:
    """True if the source has a MODULE-LEVEL assignment (Assign or AnnAssign) to RECIPIENT_READERS.
    Nested assignments (inside a def/class/if body) are not module-level and are ignored."""
    for node in ast.parse(source).body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if any(isinstance(t, ast.Name) and t.id == _NAME for t in targets):
            return True
    return False


def _census() -> set[str]:
    found: set[str] = set()
    for top in ("agent_fleet", "src"):
        for dirpath, dirnames, filenames in os.walk(_REPO / top):
            dirnames[:] = [d for d in dirnames if d not in (".venv", "__pycache__")
                           and not d.startswith(".venv")]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                p = Path(dirpath) / fn
                # No skip on an unreadable or unparseable file: a census that passes over a file
                # cannot say the file holds no table. Either error fails the arm, naming the file.
                rel = p.relative_to(_REPO).as_posix()
                try:
                    src = p.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as e:  # a decode error names no file
                    raise AssertionError(f"census cannot read {rel}: {e}") from e
                if _NAME not in src:  # cheap prefilter; the AST decides
                    continue
                try:
                    held = holds_table(src)
                except SyntaxError as e:  # ast.parse names no file
                    raise AssertionError(f"census cannot parse {rel}: {e}") from e
                if held:
                    found.add(rel)
    return found


def test_census_finds_a_planted_table_and_ignores_a_nested_one():
    """CONTROL: the detector can fire (plain and annotated assignment) and does not fire on a
    non-module-level name, so a green below is not a blind detector."""
    assert holds_table("RECIPIENT_READERS = {'a': ['x']}\n")
    assert holds_table("RECIPIENT_READERS: dict[str, list[str]] = {}\n")
    assert not holds_table("def f():\n    RECIPIENT_READERS = {}\n    return RECIPIENT_READERS\n")
    assert not holds_table("class C:\n    RECIPIENT_READERS = {}\n")
    assert not holds_table("x = RECIPIENT_READERS\n")


def test_no_new_code_held_recipient_readers_table():
    new = _census() - PENDING
    assert not new, (
        f"a code-held RECIPIENT_READERS table appeared in {sorted(new)} -- move it onto "
        f"policy/recipient_readers.yaml"
    )


def test_pending_lists_only_files_that_still_hold_a_table():
    gone = PENDING - _census()
    assert not gone, (
        f"{sorted(gone)} no longer hold a RECIPIENT_READERS table -- remove it from PENDING "
        f"(the ratchet only tightens)"
    )


# -- the Job render -------------------------------------------------------------------------

needs_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def _render(*extra: str) -> str:
    r = subprocess.run(["helm", "template", "t", _CHART, *extra],
                       capture_output=True, text=True, cwd=str(_REPO), timeout=300)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    assert r.stdout.strip(), "helm rendered nothing and reported success"
    return r.stdout


def _sandbox_args() -> list[str]:
    src = (_REPO / "scripts" / "upgrade-sandbox.sh").read_text(encoding="utf-8")
    m = re.search(r"VALUES=\((.*?)\)", src, re.S)
    assert m, "upgrade-sandbox.sh's VALUES array is not in the recognised shape"
    args: list[str] = []
    for p in re.findall(r'"\$\{CHART\}/([^"]+)"', m.group(1)):
        f = _REPO / _CHART / p
        if f.exists():
            args += ["-f", str(f)]
    return args


def _job(out: str) -> str:
    i = out.index("name: t-task-grant-sync")
    j = out.find("\n---", i)
    return out[i:j if j != -1 else None]


@needs_helm
def test_job_runs_recipient_reader_sync_after_program_member_sync():
    job = _job(_render(*_sandbox_args()))
    assert "recipient_reader_sync.py" in job
    assert job.index("program_member_sync.py") < job.index("recipient_reader_sync.py")


@needs_helm
def test_overlay_mode_absent_recipient_readers_warns_and_does_not_exit_2():
    job = _job(_render(
        *_sandbox_args(),
        "--set", "topazSeed.policySource.type=configMap",
        "--set", "topazSeed.policySource.configMap.name=iagent-policy-overlay"))
    assert 'export RECIPIENT_READERS_FILE="$POLICY_DIR/recipient_readers.yaml"' in job
    warn = [ln for ln in job.splitlines() if "WARN:" in ln and "recipient_readers.yaml" in ln]
    assert warn, "no WARN line for an absent recipient_readers.yaml"
    assert not any("FATAL" in ln and "recipient_readers" in ln for ln in job.splitlines())
    i = job.index("recipient_readers.yaml\" ]; then")
    assert "exit 2" not in job[i:job.index("POLICY_DIR=/work/policy", i)]
    # the other two stay FATAL (the control: the absent branch differs in exactly this)
    assert "FATAL: policy overlay is missing program_members.yaml" in job
