"""LIVE TEST -- the sandbox's refusal probes over dag-tools' planted-refusal assets.

WHAT IT PROVES ON THE RUNNING CLUSTER, through `POST /finance/measure/{fn}`:
  FIRST    the control program answers 200 from the row-level asset, so the URN the probes name is
           the one the catalog minted (the form is by analogy with ev_fixture and unverified until
           this passes). When it fails every leg after it fails as not run: each would fail the same way.
  CASES    every (planted case, probe) in the offline seal's EXPECTED answers as it does offline,
           either a 502 naming the reader's rule or a 200 from the probe's own asset
  DENIED   a subject with the control program and the cell and no asset grant gets 403
           `access_denied` naming the asset, and no figure

EXPECTED and its cells are imported from tests/finance/test_the_refusal_probes_refuse_as_derived.py,
so there is one table. Four planted cases are OWED a dataset-contract refusal (ruled 2026-11-10).
Each of their legs is a strict xfail asserting the refusal, never a pass: a 200 is the expected
failure, anything else but the refusal is a hard red, and the refusal itself XPASSes red until the
PR that declares it names its rule in the seal.

SKIPPED UNTIL THE ROLL, AND A SKIP IS NOT A PASS. `missing_preconditions` names everything still
missing, so the skip retires itself. Run with `-rsxX`. It needs: the rail (grants and membership)
in this tree, tokens for both personas, the probes' directory in the pod's overlay env, and the
port-forward. Materialising the three assets is not checked first: FIRST fails without it.

Requires, all set by the operator and none committed (the variance leg's, reused):
    kubectl -n <ns> port-forward svc/iagent-cortex-bff 18090:8090       (or set BFF_URL)
    python -I scripts/mint_persona_token.py <persona> --out <dir>       (once per persona)
    FIN_VARIANCE_TOKEN_DIR=<dir>  FIN_VARIANCE_KUBECTL="kubectl -n <ns>"
Run: .venv/Scripts/python -m pytest tests/sandbox_e2e/test_the_refusal_fixture_refuses_live.py -rsxX
Its own proof, with no cluster: tests/finance/test_the_refusal_live_test_can_go_red.py
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.sandbox_e2e._seal_asset_read_denied_at_the_gate import _yaml, rail_preflight  # noqa: E402
from tests.sandbox_e2e.test_variance_set_reads_the_ev_fixture import (  # noqa: E402
    _EARLIER_GATES, DEFAULT_BFF, KUBECTL_ENV, TOKEN_DIR_ENV, bff_reachable,
)

DEFAULT_CONFIG = HERE / "refusal_probes_live.yaml"
DEFAULT_POLICY = REPO / "policy"
#: A problem no xfail may absorb: the leg answered neither as today nor with the owed refusal.
HARD = "HARD "


def load_case(path: Path = DEFAULT_CONFIG) -> dict:
    return _yaml(str(path))


def seal():
    """The offline seal: EXPECTED, OWED, cells(), scope_of and SERIES are its, imported, never restated."""
    from tests.finance import test_the_refusal_probes_refuse_as_derived as s
    return s


def probe_urns(case: dict) -> dict[str, str]:
    from agent_fleet.finance_agent import measure_verbs
    rows = measure_verbs.load_measure_verbs(overlay_dirs=[REPO / case["overlay_dir"]], builtins=((), ()))
    return {r.measure_id: r.dataset_urn for r in rows}


# ── what the test needs before it can say anything ─────────────────────────────

def read_pod_env(kubectl: str, deployment: str, name: str) -> Optional[str]:
    """The variable as the running pod sees it, or None when the read failed. stderr is never kept."""
    try:
        r = subprocess.run([*shlex.split(kubectl), "exec", f"deploy/{deployment}", "--", "printenv", name],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout.strip()
    return out if out or r.returncode == 1 else None


def missing_preconditions(case: dict, env: Mapping[str, str], policy_dir: Path = DEFAULT_POLICY,
                          pod_env: Optional[Callable[[str, str, str], Optional[str]]] = None,
                          reachable: Optional[Callable[[str], bool]] = None) -> list[str]:
    """Everything still missing, all of it and named. Empty means the legs may run."""
    s = seal()
    missing: list[str] = []
    for urn in case["assets"]:
        drift = rail_preflight({**case, "asset": urn}, str(policy_dir))
        if drift:
            missing.append(f"the rail for {urn}: {drift}")
    members = (_yaml(str(Path(policy_dir) / "program_members.yaml")) or {}).get("programs") or {}
    for rule in s.EXPECTED:
        if case["allowed_subject"] not in (members.get(s.scope_of(rule)) or {}).get("grant_to", []):
            missing.append(f"the rail: allowed_subject is not a member of {s.scope_of(rule)}")
    if case["denied_subject"] not in (members.get(s.scope_of("none")) or {}).get("grant_to", []):
        missing.append(f"the rail: denied_subject is not a member of {s.scope_of('none')}, so it stops "
                       "at the program gate and never reaches the asset gate")

    token_dir = (env.get(TOKEN_DIR_ENV) or "").strip()
    if not token_dir:
        missing.append(f"{TOKEN_DIR_ENV} is unset (no tokens to call with)")
    else:
        for role in ("allowed_persona", "denied_persona"):
            p = Path(token_dir) / f"token-{case[role]}.txt"
            if not p.is_file() or not p.read_text(encoding="utf-8").strip():
                missing.append(f"no token for {role} {case[role]} in {TOKEN_DIR_ENV}")

    kubectl = (env.get(KUBECTL_ENV) or "").strip()
    if not kubectl:
        missing.append(f"{KUBECTL_ENV} is unset (cannot read {case['overlay_env']} off the pod)")
    else:
        got = (pod_env or read_pod_env)(kubectl, case["deployment"], case["overlay_env"])
        if got is None:
            missing.append(f"could not read {case['overlay_env']} off deploy/{case['deployment']}")
        elif case["overlay_in_pod"] not in got.split(":"):
            missing.append(f"{case['overlay_env']} on deploy/{case['deployment']} does not name "
                           f"{case['overlay_in_pod']} (the values change has not rolled)")

    bff = (env.get("BFF_URL") or DEFAULT_BFF).rstrip("/")
    if not (reachable or bff_reachable)(bff):
        missing.append(f"nothing answers at {bff} (the port-forward)")
    return missing


# ── the decisions, pure over one answer ───────────────────────────────────────

def _name(body: Any) -> str:
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        return str(detail.get("rule") or detail.get("error") or detail.get("status") or "")
    return ""


def answer_problems(status: int, body: Any, urn: str, reader_rule: Optional[str], banner: str) -> list[str]:
    """A 200 from the probe's own asset when `reader_rule` is None, a 502 naming exactly it when it is
    a rule, and for OWED a contract refusal naming any rule: a 200 there is the owed gap, anything
    else is HARD."""
    if reader_rule is seal().OWED:
        detail = body.get("detail") if isinstance(body, dict) else None
        if status == 502 and isinstance(detail, dict) and detail.get("error") == "asset_contract_violation" \
                and detail.get("rule"):
            return []
        if status == 200:
            return ["answered 200: the contract refusal is owed"]
        return [f"{HARD}expected 200 or the owed refusal, got {status} {_name(body)}".rstrip()]
    if reader_rule is not None:
        if status != 502 or _name(body) != reader_rule:
            return [f"expected 502 {reader_rule}, got {status} {_name(body)}".rstrip()]
        return []
    if status != 200:
        return [f"expected 200, got {status} {_name(body)}".rstrip()]
    out: list[str] = []
    if body.get("data_source") != {"kind": "asset", "urn": urn}:
        out.append(f"data_source is {body.get('data_source')!r}, not the probe's asset")
    if banner.lower() not in str(body.get("data_provenance") or "").lower():
        out.append(f"the provenance does not say {banner!r}")
    return out


def denied_problems(status: int, body: Any, urn: str, subject: str) -> list[str]:
    if status == 200:
        return ["BREACH: the denied subject was answered"]
    detail = body.get("detail") if isinstance(body, dict) else None
    detail = detail if isinstance(detail, dict) else {}
    if detail.get("error") in _EARLIER_GATES:
        return [f"refused before the asset gate ({detail['error']}): proves nothing about it"]
    if status != 403 or detail.get("status") != "access_denied":
        return [f"expected 403 access_denied, got {status} {_name(body)}".rstrip()]
    out: list[str] = []
    if detail.get("denied_assets") != [urn]:
        out.append("denied_assets does not name exactly the asset")
    if detail.get("subject") != subject:
        out.append("the refusal does not name the denied subject")
    if "rows" in body or "rows" in detail:
        out.append("BREACH: the refusal carries rows")
    return out


# ── the legs. `post(role, fn, params)` is the only way out ─────────────────────

def first_problems(case: dict, urns: dict[str, str], post: Callable[[str, str, dict], tuple[int, Any]]) -> list[str]:
    s = seal()
    status, body = post("allowed", s.SERIES, {"program_id": s.scope_of("none")})
    return [f"FIRST {s.SERIES} {s.scope_of('none')}: {p}; if the asset is materialised, suspect its "
            f"URN form ({urns[s.SERIES]}), which is unverified"
            for p in answer_problems(status, body, urns[s.SERIES], None, case["banner_must_say"])]


def not_run_after(first: list[str]) -> Optional[str]:
    """Why a leg after FIRST is not run, or None when FIRST passed."""
    return f"NOT RUN: FIRST failed ({'; '.join(first)})" if first else None


def case_problems(case: dict, urns: dict[str, str], post: Callable[[str, str, dict], tuple[int, Any]],
                  rule: str, fn: str, reader_rule: Optional[str]) -> list[str]:
    status, body = post("allowed", fn, {"program_id": seal().scope_of(rule)})
    return [f"{rule} via {fn}: {p}"
            for p in answer_problems(status, body, urns[fn], reader_rule, case["banner_must_say"])]


def denied_leg_problems(case: dict, urns: dict[str, str],
                        post: Callable[[str, str, dict], tuple[int, Any]]) -> list[str]:
    s = seal()
    status, body = post("denied", s.SERIES, {"program_id": s.scope_of("none")})
    return [f"DENIED: {p}" for p in denied_problems(status, body, urns[s.SERIES], case["denied_subject"])]


# ── the live tests ────────────────────────────────────────────────────────────

CASE = load_case()


@pytest.fixture(scope="module")
def live():
    missing = missing_preconditions(CASE, os.environ)
    if missing:
        pytest.skip("NOT RUN, NOT A PASS. Waiting on: " + "; ".join(missing))

    import httpx
    bff = (os.environ.get("BFF_URL") or DEFAULT_BFF).rstrip("/")
    token_dir = Path(os.environ[TOKEN_DIR_ENV])
    tokens = {role: (token_dir / f"token-{CASE[f'{role}_persona']}.txt").read_text(encoding="utf-8").strip()
              for role in ("allowed", "denied")}

    def post(role: str, fn: str, params: dict) -> tuple[int, Any]:
        r = httpx.post(f"{bff}/finance/measure/{fn}", json={"params": params}, timeout=60.0,
                       headers={"Authorization": f"Bearer {tokens[role]}"})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text

    return probe_urns(CASE), post


@pytest.fixture(scope="module")
def first(live):
    return first_problems(CASE, *live)


def test_first_the_control_answers_from_the_probes_asset(first):
    assert not first, "\n".join(first)


@pytest.mark.parametrize("rule,fn,reader_rule", seal().cells())
def test_each_planted_case_answers_live_as_offline(live, first, rule, fn, reader_rule):
    if not_run_after(first):
        pytest.fail(not_run_after(first))
    problems = case_problems(CASE, *live, rule, fn, reader_rule)
    hard = [p for p in problems if HARD in p]
    if hard:
        pytest.fail("\n".join(hard))
    assert not problems, "\n".join(problems)


def test_the_denied_caller_is_refused_at_the_asset_gate(live, first):
    if not_run_after(first):
        pytest.fail(not_run_after(first))
    problems = denied_leg_problems(CASE, *live)
    assert not problems, "\n".join(problems)
