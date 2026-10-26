"""Every policy refusal names its policy, the binding the caller lacks, and who can grant it.

DIRECTIVE (architect via Chris, 2026-10-24, to lane/gov): "a missing binding today surfaces as red
text nobody can act on. Draft the rule that every policy refusal names (a) the policy id, (b) the
binding or role missing, (c) who can grant it -- and the test that enforces it across the refusal
paths." The rule is `src/iagent/authz/refusal.py`'s docstring and the proposal
`docs/proposals/a-policy-refusal-names-its-policy-the-missing-binding-and-who-can-grant-it.md`.

THIS FILE IS A RATCHET over a DERIVED population. `census()` walks every tracked `.py` under
`src/` and `agent_fleet/` (tests excluded) and finds each refusal site by its FORM:

  STATUS    any call carrying `status_code` 401 or 403 (keyword, or HTTPException/TerminalError's
            first positional; `status.HTTP_40x_*` included) -- HTTPException, TerminalError,
            StepFailAndRelease, JSONResponse alike, because the form is the status, not the class
  INBAND    `_refusal("unentitled", ...)` (ADR-0049 Ruling 4's in-band shape) and any dict, not
            already a counted call's body, whose `status`/`outcome`/`error`/`reason` is a refusal word
  HELPER    a call to `policy_refusal(...)`, which is compliant by construction

Each site is keyed `path::function::fingerprint` (fingerprint = the `error` code, else the
message's leading literal, else the expression's name), so a key survives a line move and three
different refusals in one function stay three keys. Every key is in exactly one bucket:

  COMPLIANT   built by `policy_refusal`, or a body carrying `refusal` = {policy_id, missing_binding, ...}
  NOT_POLICY  no binding could lift it: AUTHN (no identity), STRUCTURAL (a route pinned to one
              service, separation of duties, protocol state), each with its reason
  PENDING     a policy refusal that does not yet comply -- the debt, listed EXACTLY

UNDECIDED FAILS (a new refusal site must be classified or built compliant), and A LISTED SITE THAT
IS GONE OR NOW COMPLIANT FAILS (the list is exact, so it shrinks as sites are fixed and never
carries a dead row). The detector is positive-controlled on synthetic source holding every form.

WHAT THIS FILE DOES NOT CHECK. That a COMPLIANT site's `policy_id` names the right binding (that is
each instance's own seal, beginning with finance's); that a relayed engine refusal reaches the
caller with `grantable_by` filled (each relay's seal, via `relay_refusal`); refusals in other repos.
"""
from __future__ import annotations

import ast
import re
import subprocess
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ROOTS = ("src", "agent_fleet")

_WORD = re.compile(r"(?i)not_entitled|unentitled|not_authorized|forbidden")
_STATUS_ATTR = {"HTTP_401_UNAUTHORIZED": 401, "HTTP_403_FORBIDDEN": 403}
_POSITIONAL_STATUS = ("HTTPException", "TerminalError")
HELPER = "policy_refusal"


# --------------------------------------------------------------------------------------
# The detector
# --------------------------------------------------------------------------------------

def _fname(call: ast.Call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def _code(v) -> int | None:
    if isinstance(v, ast.Constant) and v.value in (401, 403):
        return v.value
    if isinstance(v, ast.Attribute) and v.attr in _STATUS_ATTR:
        return _STATUS_ATTR[v.attr]
    return None


def _status(call: ast.Call) -> int | None:
    for kw in call.keywords:
        if kw.arg == "status_code":
            return _code(kw.value)
    if _fname(call) in _POSITIONAL_STATUS and call.args:
        return _code(call.args[0])
    return None


def _dict_get(d: ast.Dict, key: str):
    for k, v in zip(d.keys, d.values):
        if isinstance(k, ast.Constant) and k.value == key:
            return v
    return None


def _frag(node) -> str:
    """The fingerprint of a refusal's message or body."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        s = node.value
    elif isinstance(node, ast.JoinedStr):
        # The TEMPLATE, placeholders as {} -- "caller {} is excluded ..." and "caller {} is not
        # authorized ..." are different refusals, and their leading literal alone is "caller ".
        s = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    elif isinstance(node, ast.BinOp):
        return _frag(node.left)
    elif isinstance(node, ast.Dict):
        # The code, then the message: one code can carry two refusals of different kinds
        # (`not_entitled` is a delegate's structural refusal AND a missing task grant).
        code = next((v.value for v in (_dict_get(node, k) for k in
                                       ("error", "status", "outcome", "reason"))
                     if isinstance(v, ast.Constant) and isinstance(v.value, str)), "<dict>")
        msg = _dict_get(node, "message")
        return code if msg is None else f"{code} | {_frag(msg)[:32].strip()}"
    elif isinstance(node, (ast.Name, ast.Attribute, ast.Call)):
        return f"<{ast.unparse(node.func if isinstance(node, ast.Call) else node)}>"
    else:
        return "<?>"
    return " ".join(s.split())[:48].strip()


def _body(call: ast.Call):
    """The refusal's body: `detail=`/`content=`, else the first non-status positional."""
    for kw in call.keywords:
        if kw.arg in ("detail", "content"):
            return kw.value
    args = [a for a in call.args if _code(a) is None]
    return args[0] if args else None


def _carries_refusal(body) -> bool:
    """A hand-built compliant body: a dict whose `refusal` is a dict naming policy_id and missing_binding."""
    if not isinstance(body, ast.Dict):
        return False
    r = _dict_get(body, "refusal")
    return isinstance(r, ast.Dict) and all(
        isinstance(_dict_get(r, f), ast.AST) for f in ("policy_id", "missing_binding"))


def find_sites(src: str, path: str) -> list[tuple[str, str]]:
    """[(key, bucket)] for one file; bucket is 'compliant' or 'refusal' (to be partitioned)."""
    tree = ast.parse(src, path)
    owned: set[int] = set()
    out: list[tuple[str, str]] = []

    # `body = {...}; raise HTTPException(403, detail=body)` is ONE site: resolve a Name body to
    # the dict assigned to it in the same function, and do not count that dict again.
    resolved: dict[int, ast.Dict] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        assigned = {t.id: n.value for n in ast.walk(fn) if isinstance(n, ast.Assign)
                    and isinstance(n.value, ast.Dict) for t in n.targets if isinstance(t, ast.Name)}
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and _status(n):
                b = _body(n)
                if isinstance(b, ast.Name) and b.id in assigned:
                    resolved[id(n)] = assigned[b.id]
                    owned.update(id(d) for d in ast.walk(assigned[b.id]) if isinstance(d, ast.Dict))

    def walk(node, stack):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            stack = stack + [node.name]
        where = f"{path}::{'.'.join(stack) or '<module>'}::"
        if isinstance(node, ast.Call):
            name = _fname(node)
            if name == HELPER:
                err = node.args[0] if node.args else None
                out.append((where + _frag(err), "compliant"))
                owned.update(id(d) for d in ast.walk(node) if isinstance(d, ast.Dict))
            elif _status(node):
                body = resolved.get(id(node), _body(node))
                out.append((where + _frag(body),
                            "compliant" if _carries_refusal(body) else "refusal"))
                owned.update(id(d) for d in ast.walk(node) if isinstance(d, ast.Dict))
            elif name == "_refusal" and node.args and isinstance(node.args[0], ast.Constant) \
                    and node.args[0].value == "unentitled":
                carries = any(kw.arg == "refusal" for kw in node.keywords)
                fp = _frag(node.args[1]) if len(node.args) > 1 else "<?>"
                out.append((where + "unentitled:" + fp, "compliant" if carries else "refusal"))
                owned.update(id(d) for d in ast.walk(node) if isinstance(d, ast.Dict))
        elif isinstance(node, ast.Dict) and id(node) not in owned:
            for key in ("status", "outcome", "error", "reason"):
                v = _dict_get(node, key)
                if isinstance(v, ast.Constant) and isinstance(v.value, str) and _WORD.search(v.value):
                    out.append((where + v.value, "compliant" if _carries_refusal(node) else "refusal"))
                    owned.add(id(node))
                    break
        for child in ast.iter_child_nodes(node):
            walk(child, stack)

    walk(tree, [])
    return out


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--", *ROOTS], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.split("\n")
    keep = []
    for p in out:
        if not p.endswith(".py"):
            continue
        parts = p.split("/")
        if "tests" in parts[:-1] or parts[-1].startswith(("test_", "conftest")) \
                or "baml_client" in parts:
            continue
        keep.append(p)
    return keep


_CACHE: dict = {}


def census() -> tuple[Counter, Counter]:
    """(compliant, refusal) -- each a Counter of keys over the tracked tree."""
    if "c" not in _CACHE:
        compliant, refusal = Counter(), Counter()
        for p in _tracked_files():
            src = (ROOT / p).read_text(encoding="utf-8", errors="replace")
            for key, bucket in find_sites(src, p):
                (compliant if bucket == "compliant" else refusal)[key] += 1
        _CACHE["c"] = (compliant, refusal)
    return _CACHE["c"]


# --------------------------------------------------------------------------------------
# The partition (measured on master 7a45a3cb, 2026-10-24: 69 sites, 69 keys, 0 compliant)
# --------------------------------------------------------------------------------------

GW = "src/iagent/gateway.py"
RA = "agent_fleet/restate_analyst/main.py"
SPO = "agent_fleet/restate_analyst/spo_step_executor.py"
GRW = "agent_fleet/restate_analyst/grouped_review_workflow.py"
FIN = "agent_fleet/finance_agent/main.py"
COST = "agent_fleet/cost_agent/main.py"

AUTHN = "no identity on the request: nothing to grant until the caller is known"
PINNED = "the route is pinned to one service identity; no grant adds a caller"
SECTION_5_1 = "ADR-0047 §5.1: a delegate reads what it seeded; no grant widens it"
DUTIES = "separation of duties declared by the definition; no grant lifts it"
STATE = "workflow protocol state, not a caller's binding"
NO_AUDIENCE = "integrity: no journalled audience to check against; fails closed"

#: No binding could lift these, so they keep their bodies. Value = why.
NOT_POLICY: dict[str, str] = {
    "src/iagent/auth.py::get_current_user::Authentication failed: {}": AUTHN,
    "src/iagent/auth.py::get_current_user::Invalid token payload: {}": AUTHN,
    "src/iagent/auth.py::get_current_user::Token has expired": AUTHN,
    "src/iagent/auth.py::get_current_user::Token validation failed: {}": AUTHN,
    f"{GW}::_answers_scope_id::no usable caller identity on this request": AUTHN,
    f"{GW}::_entitled_artifact_rec::no caller identity on this request": AUTHN,
    f"{GW}::answer_case_signal::no_actor | a case signal needs an authentic": AUTHN,
    f"{FIN}::mesh_ticketed_read::a governed finance read requires the caller's id": AUTHN,
    "agent_fleet/graph_host/main.py::run_graph::{} runs as the INITIATOR and this request carrie": AUTHN,
    f"{GRW}::submit_decision::submit_decision requires `acted_by` (the caller'": AUTHN,
    f"{RA}::_authorize_resolution::approve requires `acted_by` (the caller's authz_": AUTHN,
    f"{RA}::approve_task::identity_required | approving a task requires a veri": AUTHN,
    f"{SPO}::execute_direct_call::direct_call {{}}: no acting identity for capabilit": AUTHN,
    f"{GW}::ingest_title_leaf_route::not_doc_tools | POST /ingest/{{ingest_id}}/title_l": PINNED,
    f"{GW}::list_ingest_retries::not_doc_tools | GET /ingest/retries is callable": PINNED,
    f"{GW}::put_processable_kinds::not_doc_tools | PUT /ingest/processable-kinds is": PINNED,
    f"{GW}::update_ingest_stage::not_doc_tools | POST /ingest/{{ingest_id}}/stage i": PINNED,
    f"{GW}::stamp_seeded_by_route::not_case_runner | POST /internal/cases/{{case_id}}/s": PINNED,
    f"{GW}::write_action_record_route::not_case_runner | POST /internal/cases/{{case_id}}/a": PINNED,
    f"{GW}::write_case_summary_route::not_case_runner | POST /internal/cases/{{case_id}}/s": PINNED,
    f"{GW}::write_origin_route::not_case_runner | POST /internal/origin/write is c": PINNED,
    f"{GW}::redeem_caller_identity::not_the_redeemer | The identity vault is redeemable": PINNED,
    f"{GW}::ingest_retry_route::retry_is_pin_driven | a retry is driven only by an ext":
        "a retry is driven by an extractor pin change, never by a person",
    f"{GW}::get_case::delegate_reads_artifacts_only | a delegate reads the artifacts i": SECTION_5_1,
    f"{GW}::get_case_action._not_your_case::not_your_case | a delegate reads the action reco": SECTION_5_1,
    f"{GW}::_ingest_review_access::not_entitled | a service reads only the drops i": SECTION_5_1,
    f"{RA}::_authorize_resolution::caller {{}} is excluded from deciding promise {{}} b": DUTIES,
    f"{RA}::_authorize_resolution::caller {{}}, acting via on behalf of {{}} (R-089), i": DUTIES,
    f"{RA}::_authorize_resolution::no audience journalled for promise {{}} — refusing": NO_AUDIENCE,
    f"{GRW}::submit_decision::no audience journalled for this grouped review —": NO_AUDIENCE,
    "agent_fleet/restate_analyst/workflow_runner.py::_run_instance::case {} opened no instance {} -- an instance run": STATE,
    "agent_fleet/restate_analyst/workflow_runner.py::signal::no signal {} is awaited on {}": STATE,
    f"{FIN}::package_export::<str>":
        "an unknown recipient scope: the scopes are the seed's programs, not grants",
    f"{FIN}::package_export::panel {{}} ({{}}) is scoped to program {{}}, not {{}} —":
        "a recipient discloses only its own program; no grant widens it",
}

RELAY = "relay"

#: The debt: a policy refusal that does not yet name all three. Value = the policy family the
#: fix is expected to name (its grantor row must already exist), or RELAY for a site that
#: re-raises an upstream's 401/403 and must carry the upstream's `refusal` through instead.
PENDING: dict[str, str] = {
    f"{GW}::file_triage_task::not_entitled_to_file_triage | {{}} lacks can_invoke({{}}); grant i": "capability_grants",
    "agent_fleet/ontology_service/main.py::_require_capability::caller {} is not authorized (can_invoke) for {}": "capability_grants",
    f"{RA}::_run_definition._gate::caller {{}} is not authorized (can_invoke) for cap": "capability_grants",
    f"{SPO}::execute_declared_query::caller {{}} is not authorized (can_invoke) for cap": "capability_grants",
    f"{SPO}::execute_direct_call::caller {{}} is not authorized (can_invoke) for cap": "capability_grants",
    "agent_fleet/restate_analyst/review_starter.py::start_review::NOT_ENTITLED_TO_INITIATE": "capability_grants",
    f"{GW}::act_on_human_task::not_authorized_to_act": "task_grants",
    f"{GW}::_ingest_review_access::not_entitled | only the dropper or a holder of": "task_grants",
    f"{GRW}::submit_decision::caller {{}} is not authorized (can_act) for audien": "task_grants",
    f"{RA}::_authorize_resolution::caller {{}} is not authorized (can_act) for audien": "task_grants",
    f"{GW}::_require_plan_write::not_entitled_to_change_the_plan | Changing plan state requires the": "groups",
    f"{GW}::canvas_seed::cell_cannot_see_verbs | seeded 0 of {{}} panels; every ask": "groups",
    f"{GW}::orchestrate::cell_not_entitled | user {{}} is not entitled to perso": "groups",
    f"{GW}::federated_image::not entitled for this domain": "groups",
    "agent_fleet/ontology_service/main.py::notice_parts_route::not_entitled": "groups",
    f"{SPO}::verify_spo_step::verb {{}} is NOT eligible for subject {{}} under dom": "groups",
    f"{GW}::_admit_on_behalf_of::not_a_delegate": "config",
    f"{GW}::_admit_on_behalf_of::principal_not_declared_for_delegate": "config",
    f"{GW}::export_package_artifact::caller {{}} is not entitled to the package for {{}}.": "code",
    f"{GW}::_export_package_from_template::not_a_recipient_you_may_export_to": "code",
    f"{GW}::export_package::not_a_recipient_you_may_export_to": "code",
    f"{COST}::artifact::caller {{}} is not entitled to the package for {{}}.": "code",
    f"{COST}::measure::unentitled:<canvas.ENTITLEMENT_REFUSAL>": "code",
    f"{COST}::measure::unentitled:<str>": "code",
    f"{FIN}::get_artifact::not entitled to {{}}'s package": "code",
    f"{GW}::start_review::<out>": RELAY,
    f"{GW}::act_on_human_task::not_authorized_to_act | <_restate_refusal_message>": RELAY,
    f"{GW}::answer_case_signal::not_authorized_to_act | <msg>": RELAY,
    f"{RA}::approve_task::not_authorized_to_act | <_restate_error_message>": RELAY,
    f"{RA}::_execute_service_task::access denied ({{}}) on service task {{}} -> {{}}; fai": RELAY,
    f"{RA}::_register_human_task::access denied ({{}}) registering HumanTask {{}} (aud": RELAY,
    "agent_fleet/restate_analyst/dispatch_driver.py::_mint_dispatch_task::access denied ({}) registering pcn dispatch task": RELAY,
    f"{SPO}::dispatch_spo_step::access denied ({{}}) dispatching {{}} to {{}} — the PE": RELAY,
    f"{SPO}::execute_declared_query::access denied ({{}}) on declared query {{}} -> {{}}; f": RELAY,
    f"{SPO}::execute_direct_call::access denied ({{}}) on direct_call {{}} -> {{}}; fail": RELAY,
}


# --------------------------------------------------------------------------------------
# The ratchet
# --------------------------------------------------------------------------------------

def test_every_refusal_site_is_compliant_or_classified():
    _, refusal = census()
    undecided = sorted(set(refusal) - set(NOT_POLICY) - set(PENDING))
    assert undecided == [], (
        "a refusal site nobody has classified. If a missing binding causes it, build it with "
        "`src.iagent.authz.refusal.policy_refusal` (in an engine: a body carrying "
        "`refusal: {policy_id, missing_binding}`); if no binding could lift it, add it to NOT_POLICY with "
        f"the reason: {undecided}")


def test_the_lists_name_only_live_noncompliant_sites():
    _, refusal = census()
    assert not set(NOT_POLICY) & set(PENDING)
    stale = sorted((set(NOT_POLICY) | set(PENDING)) - set(refusal))
    assert stale == [], (
        "listed, but no longer a non-compliant refusal site -- fixed (delete its PENDING row) "
        f"or moved (re-derive its key): {stale}")
    doubled = {k: refusal[k] for k in (*NOT_POLICY, *PENDING) if refusal[k] != 1}
    assert doubled == {}, f"one key now names several sites; re-fingerprint them: {doubled}"


def test_the_canonical_refusal_is_in_the_population():
    """policy/README's own example of a correct deny nobody could act on (2026-08-10)."""
    _, refusal = census()
    assert "agent_fleet/restate_analyst/review_starter.py::start_review::NOT_ENTITLED_TO_INITIATE" \
        in refusal


# --------------------------------------------------------------------------------------
# Positive control on the detector
# --------------------------------------------------------------------------------------

_EVERY_FORM = '''
from fastapi import HTTPException, status
def a():
    raise HTTPException(status_code=403, detail={"error": "e_kw"})
def b():
    raise HTTPException(403, "positional")
def c():
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="attr")
def d(x):
    raise TerminalError(f"caller {x} is not allowed", status_code=403)
def e(x):
    raise StepFailAndRelease(f"caller {x} lacks it", status_code=403)
def f():
    return JSONResponse(status_code=403, content={"error": "e_json", "message": "m"})
def g():
    return _refusal("unentitled", "inband message")
def h():
    return {"status": "NOT_ENTITLED_TO_X", "id": 1}
def h2():
    return {"status": "refused", "reason": "not_entitled", "message": "m"}
def i():
    body = {"error": "e_named"}
    raise HTTPException(status_code=403, detail=body)
def j():
    raise policy_refusal("e_helper", policy_id="capability_grants:mesh:x", missing_binding="can_invoke(mesh:x)")
def k():
    raise HTTPException(status_code=403, detail={"error": "e_hand", "refusal": {"policy_id": "groups", "missing_binding": "m"}})
def l():
    return _refusal("unentitled", "m", refusal={"policy_id": "code", "missing_binding": "m"})
def not_a_refusal():
    raise HTTPException(status_code=404, detail={"error": "not_found"})
'''


def test_the_detector_finds_every_form_once():
    got = sorted(find_sites(_EVERY_FORM, "x.py"))
    assert got == sorted([
        ("x.py::a::e_kw", "refusal"),
        ("x.py::b::positional", "refusal"),
        ("x.py::c::attr", "refusal"),
        ("x.py::d::caller {} is not allowed", "refusal"),
        ("x.py::e::caller {} lacks it", "refusal"),
        ("x.py::f::e_json | m", "refusal"),
        ("x.py::g::unentitled:inband message", "refusal"),
        ("x.py::h::NOT_ENTITLED_TO_X", "refusal"),
        ("x.py::h2::not_entitled", "refusal"),
        ("x.py::i::e_named", "refusal"),
        ("x.py::j::e_helper", "compliant"),
        ("x.py::k::e_hand", "compliant"),
        ("x.py::l::unentitled:m", "compliant"),
    ]), got


# --------------------------------------------------------------------------------------
# The helper and the grantor map
# --------------------------------------------------------------------------------------

@pytest.fixture
def R(monkeypatch):
    from src.iagent.authz import refusal as mod
    monkeypatch.setattr(mod, "_GRANTORS_CACHE", None)
    monkeypatch.delenv("GRANTOR_OVERLAY_DIRS", raising=False)
    yield mod
    mod._GRANTORS_CACHE = None


def test_the_fields_are_the_sdk_refusal_envelope(R):
    """`iagent_mesh.refusal.Refusal` (SDK 0.9.11, 26b1238): this repo pins 0.9.10, so the body is
    a dict. On the bump, validate it with `Refusal.model_validate` here and delete this restatement."""
    assert R.FIELDS == ("policy_id", "missing_binding", "grantable_by", "candidates")


def test_a_policy_refusal_names_policy_missing_and_the_seeded_grantor(R):
    exc = R.policy_refusal("not_entitled_to_initiate",
                           policy_id="capability_grants:mesh:startReview",
                           missing_binding="can_invoke(mesh:startReview)")
    assert exc.status_code == 403
    r = exc.detail["refusal"]
    assert tuple(r) == R.FIELDS
    assert r["policy_id"] == "capability_grants:mesh:startReview"
    assert r["missing_binding"] == "can_invoke(mesh:startReview)"
    seed = R.grantors()["capability_grants"]
    assert r["grantable_by"] == f"{seed.who}; {seed.how}"
    assert "policy/capability_grants.yaml" in r["grantable_by"]
    assert r["candidates"] == []


def test_an_overlay_row_replaces_the_seed_grantor(R, tmp_path, monkeypatch):
    (tmp_path / "capability_grants.yaml").write_text(
        "family: capability_grants\nwho: the platform security board\nhow: file a ticket\n",
        encoding="utf-8")
    monkeypatch.setenv("GRANTOR_OVERLAY_DIRS", str(tmp_path))
    r = R.refusal("capability_grants:mesh:startReview", "can_invoke(mesh:startReview)")
    assert r["grantable_by"] == "the platform security board; file a ticket"
    assert R.grantors()["task_grants"].who.startswith("the approvers of")  # the rest is seed


def test_an_object_scoped_family_is_named_without_its_key(R):
    scoped = sorted(f for f, g in R.grantors().items() if g.object_scoped)
    assert scoped == ["asset_grants", "ontology_compartments", "program_members"]
    for fam in scoped:
        assert R.refusal(fam, "member_of(program)")["policy_id"] == fam
        with pytest.raises(ValueError, match="object-scoped"):
            R.refusal(f"{fam}:SOME_KEY", "member_of(program)")


def test_a_family_the_map_lacks_still_refuses_and_says_so(R):
    exc = R.policy_refusal("x", policy_id="no_such_family:k", missing_binding="m")
    assert exc.status_code == 403
    assert exc.detail["refusal"]["grantable_by"].startswith(
        "not declared in this deployment's grantor map")


def test_a_relay_fills_the_grantor_and_narrows_an_object_key(R):
    up = {"status": "NOT_ENTITLED_TO_INITIATE",
          "refusal": {"policy_id": "capability_grants:mesh:startReview",
                      "missing_binding": "can_invoke(mesh:startReview)",
                      "grantable_by": "an engine may not speak for the deployment"}}
    out = R.relay_refusal(up)
    assert out["status"] == "NOT_ENTITLED_TO_INITIATE"
    assert out["refusal"] == R.refusal("capability_grants:mesh:startReview",
                                       "can_invoke(mesh:startReview)")
    leaky = {"refusal": {"policy_id": "program_members:SECRET_PROGRAM",
                     "missing_binding": "member_of(program)"}}
    narrowed = R.relay_refusal(leaky)
    assert narrowed["refusal"]["policy_id"] == "program_members"
    assert "SECRET_PROGRAM" not in repr(narrowed)
    assert R.relay_refusal({"error": "x"}) == {"error": "x"}
    assert R.relay_refusal("text") == "text"


def test_every_grant_bearing_policy_file_has_a_grantor_row(R):
    """DERIVED: every `policy/*.yaml` whose rows carry `granted_by` grants something; groups and
    users are membership files that grant cells. Each needs a row, or its refusals cannot comply."""
    granting = {p.stem for p in (ROOT / "policy").glob("*.yaml")
                if re.search(r"^\s*granted_by:", p.read_text(encoding="utf-8"), re.M)}
    assert {"capability_grants", "task_grants"} <= granting  # control: the derivation reads
    missing = (granting | {"groups", "users"}) - set(R.grantors())
    assert missing == set(), missing


def test_every_seed_row_names_its_own_rail_file(R):
    for fam, g in R.grantors().items():
        if g.rail_file is None:
            assert fam in ("config", "code"), fam
        else:
            assert g.rail_file == f"policy/{fam}.yaml", (fam, g.rail_file)
            assert (ROOT / g.rail_file).is_file(), (fam, g.rail_file)


def test_every_pending_family_has_a_grantor_row(R):
    """A fix must be able to comply: the family it will name already resolves to a grantor."""
    families = {v for v in PENDING.values() if v != RELAY}
    assert families - set(R.grantors()) == set()


def _named_families(src: str) -> list[str]:
    """Every literal `policy_id=` family a compliant site names (helper kwarg or hand-built body)."""
    out = []
    for n in ast.walk(ast.parse(src)):
        v = None
        if isinstance(n, ast.Call) and _fname(n) == HELPER:
            v = next((kw.value for kw in n.keywords if kw.arg == "policy_id"), None)
        elif isinstance(n, ast.Call) and isinstance(
                r := next((kw.value for kw in n.keywords if kw.arg == "refusal"), None), ast.Dict):
            v = _dict_get(r, "policy_id")  # the in-band form: _refusal(..., refusal={...})
        elif isinstance(n, ast.Dict) and isinstance(r := _dict_get(n, "refusal"), ast.Dict):
            v = _dict_get(r, "policy_id")
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            out.append(v.value.partition(":")[0])
        elif isinstance(v, ast.JoinedStr) and v.values and isinstance(v.values[0], ast.Constant):
            out.append(v.values[0].value.partition(":")[0])
    return out


def test_every_family_a_compliant_site_names_resolves(R):
    assert sorted(_named_families(_EVERY_FORM)) == ["capability_grants", "code", "groups"]  # control
    named = {(p, fam) for p in _tracked_files()
             for fam in _named_families((ROOT / p).read_text(encoding="utf-8", errors="replace"))}
    unknown = sorted((p, f) for p, f in named if f not in R.grantors())
    assert unknown == [], unknown
