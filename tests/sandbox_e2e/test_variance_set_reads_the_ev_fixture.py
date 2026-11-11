"""LIVE TEST -- the variance set (VAC, TCPI) read through the finance resolver on the EV fixture.

WHAT IT PROVES ON THE RUNNING CLUSTER, through `POST /finance/measure/{fn}`, for each measure and
window of `variance_set_live.yaml`:
  CONTROL  the allowed subject (cell + program + asset grant) gets 200, `data_source` naming the
           asset, a banner that says what the figures are, and the seed's figures
  DENIED   a second subject with the SAME cell and program and NO asset grant gets 403
           `access_denied` naming the asset and that subject, and no figure

THE FIGURES ALONE PROVE NOTHING ABOUT THE SOURCE. The fixture was built from the seed, so an answer
from the seed carries the same numbers. What tells them apart: `data_source`, the denied leg (the
seed would have answered it), and the engine's own `asset read` log line.

SKIPPED UNTIL THE ROLL, AND A SKIP IS NOT A PASS. `missing_preconditions` reads each thing this
needs and the skip reason names what is still missing, so the test retires its own skip when the
last one is true. Run with `-rs` to read it. Once they all hold, any other outcome FAILS: a 503 is
the asset not being readable, and the denied subject refused at another gate is a failure, because
it would otherwise look like a seal.

The rail is read from this tree, not the live directory. A row that has not been synced shows up as
the denied subject's `program_not_visible`, or the allowed subject's 403.

NOT COVERED: the chat path. This relay forwards the caller's own bearer, so it does not need #213;
a chat-dispatched verb does.

Requires, all set by the operator and none committed:
    kubectl -n <ns> port-forward svc/iagent-cortex-bff 18090:8090       (or set BFF_URL)
    python -I scripts/mint_persona_token.py <persona> --out <dir>       (once per persona)
    FIN_VARIANCE_TOKEN_DIR=<dir>  FIN_VARIANCE_KUBECTL="kubectl -n <ns>"
Run: .venv/Scripts/python -m pytest tests/sandbox_e2e/test_variance_set_reads_the_ev_fixture.py -rs
Its own proof, with no cluster: tests/finance/test_the_variance_live_test_can_go_red.py
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.sandbox_e2e._seal_asset_read_denied_at_the_gate import _yaml, rail_preflight  # noqa: E402

DEFAULT_CONFIG = HERE / "variance_set_live.yaml"
DEFAULT_POLICY = REPO / "policy"
DEFAULT_BFF = "http://localhost:18090"
TOKEN_DIR_ENV = "FIN_VARIANCE_TOKEN_DIR"
KUBECTL_ENV = "FIN_VARIANCE_KUBECTL"
FLAG = "FIN_DATASET_URN"

#: Refusals raised BEFORE the asset is looked at. A denied subject stopped here proves nothing.
_EARLIER_GATES = {"program_not_visible", "measure_not_in_cell", "cell_not_entitled"}


def load_case(path: Path = DEFAULT_CONFIG) -> dict:
    return _yaml(str(path))


# ── what the test needs before it can say anything ─────────────────────────────

def read_pod_flag(kubectl: str, deployment: str) -> Optional[str]:
    """The flag as the running pod sees it, or None when the read failed. Unset prints nothing, and
    `printenv` exits 1 for it, so "" is an answer. stderr is never kept: it can name a host."""
    try:
        r = subprocess.run([*shlex.split(kubectl), "exec", f"deploy/{deployment}", "--", "printenv", FLAG],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout.strip()
    return out if out or r.returncode == 1 else None


def bff_reachable(url: str) -> bool:
    import httpx
    try:
        httpx.get(f"{url}/health", timeout=5.0)
    except httpx.TransportError:
        return False
    return True


def missing_preconditions(case: dict, env: Mapping[str, str], policy_dir: Path = DEFAULT_POLICY,
                          pod_flag: Optional[Callable[[str, str], Optional[str]]] = None,
                          reachable: Optional[Callable[[str], bool]] = None) -> list[str]:
    """Everything still missing, all of it and named. Empty means the legs may run."""
    missing: list[str] = []
    drift = rail_preflight(case, str(policy_dir))
    if drift:
        missing.append(f"the rail: {drift}")
    members = ((_yaml(str(Path(policy_dir) / "program_members.yaml")) or {}).get("programs") or {}) \
        .get(case["program_id"], {}).get("grant_to") or []
    for role in ("allowed_subject", "denied_subject"):
        if case[role] not in members:
            missing.append(f"the rail: {role} {case[role]} is not in program_members for the program, "
                           "so it stops at the program gate and never reaches the asset gate")

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
        missing.append(f"{KUBECTL_ENV} is unset (cannot read {FLAG} off the pod)")
    else:
        got = (pod_flag or read_pod_flag)(kubectl, case["deployment"])
        if got is None:
            missing.append(f"could not read {FLAG} off deploy/{case['deployment']}")
        elif got != case["asset"]:
            missing.append(f"{FLAG} on deploy/{case['deployment']} is "
                           f"{got or 'unset, so the seed answers'}, not the case's asset")

    bff = (env.get("BFF_URL") or DEFAULT_BFF).rstrip("/")
    if not (reachable or bff_reachable)(bff):
        missing.append(f"nothing answers at {bff} (the port-forward)")
    return missing


# ── the decisions, pure over one answer ───────────────────────────────────────

def expected_rows(case: dict, fn: str, window: Optional[list[str]]) -> list[dict]:
    """The seed's rows for the measure, as the wire would carry them. Computed here, not restated."""
    from agent_fleet.finance_agent import measure_verbs, measures, seed

    # The built-in ids, not none: the seed layer's source-only row names one (`fin_funding_status`).
    rows = measure_verbs.load_measure_verbs(overlay_dirs=[REPO / case["overlay_dir"]],
                                            builtins=(measures.OUTPUT_URI, ()))
    row = next(r for r in rows if r.measure_id == fn)
    got = measure_verbs.run_declared(seed.build_seed(), row, program_id=case["program_id"], window=window)
    return json.loads(json.dumps(got, default=str))


def _same_figures(a: dict, b: dict) -> bool:
    """One row each. A source's float budget changes the audit strings and no figure, so `inputs`
    are compared as numbers and everything else exactly."""
    try:
        inputs = {k: Decimal(v) for k, v in a["inputs"].items()} == {k: Decimal(v) for k, v in b["inputs"].items()}
    except (KeyError, ArithmeticError, TypeError, AttributeError):
        return False
    return inputs and {k: v for k, v in a.items() if k != "inputs"} == {k: v for k, v in b.items() if k != "inputs"}


def control_problems(status: int, body: Any, case: dict, fn: str, want: list[dict]) -> list[str]:
    if status != 200:
        detail = body.get("detail") if isinstance(body, dict) else body
        name = detail.get("error") or detail.get("status") if isinstance(detail, dict) else None
        return [f"expected 200, got {status} {name or ''}".rstrip()]
    urn = case["asset"]
    out: list[str] = []
    if body.get("data_source") != {"kind": "asset", "urn": urn}:
        out.append(f"data_source is {body.get('data_source')!r}: this answer did not come from the asset")
    prov = str(body.get("data_provenance") or "")
    suffix = f"Source: {urn}"
    if not prov.endswith(suffix):
        out.append("data_provenance does not end with the asset's URN")
    if case["banner_must_say"].lower() not in prov[: -len(suffix)].lower():
        out.append(f"the banner does not say {case['banner_must_say']!r}")
    if (body.get("method") or {}).get("measure_id") != fn:
        out.append("method does not name the measure")
    rows = body.get("rows")
    if not want:
        out.append("the seed computes no rows for this case: the comparison would be empty")
    elif not isinstance(rows, list) or len(rows) != len(want):
        out.append(f"{len(rows) if isinstance(rows, list) else 'no'} rows, the seed has {len(want)}")
    elif not all(_same_figures(a, b) for a, b in zip(rows, want)):
        out.append("the figures differ from the seed's")
    return out


def denied_problems(status: int, body: Any, case: dict, want: list[dict]) -> list[str]:
    if status == 200:
        return ["BREACH: the denied subject was answered"]
    detail = body.get("detail") if isinstance(body, dict) else None
    detail = detail if isinstance(detail, dict) else {}
    if detail.get("error") in _EARLIER_GATES:
        return [f"refused before the asset gate ({detail['error']}): proves nothing about it"]
    if status != 403 or detail.get("status") != "access_denied":
        return [f"expected 403 access_denied, got {status} {detail.get('error') or detail.get('status') or ''}".rstrip()]
    out: list[str] = []
    if detail.get("denied_assets") != [case["asset"]]:
        out.append("denied_assets does not name exactly the asset")
    if detail.get("subject") != case["denied_subject"]:
        out.append("the refusal does not name the denied subject")
    text = json.dumps(body)
    if any(v in text for r in want for v in r["inputs"].values() if len(v) >= 6):
        out.append("BREACH: the refusal carries a figure")
    return out


def read_evidence_problem(log_lines: list[str], urn: str) -> Optional[str]:
    """None when the engine logged a read of the asset that returned rows. THE ONE PLACE this log
    line's form is read (`asset_inputs.read_rows`)."""
    for line in log_lines:
        if "asset read " in line and line.rstrip().endswith(f"urn={urn}") and " rows=0 " not in line:
            return None
    return "the engine logged no `asset read` of the asset with rows in it"


def run_legs(case: dict, post: Callable[[str, str, dict], tuple[int, Any]]) -> list[str]:
    """Every measure and window, both subjects. `post(role, fn, params)` is the only way out."""
    problems: list[str] = []
    for fn in case["measures"]:
        for window in case["windows"]:
            params = {"program_id": case["program_id"], **({} if window is None else {"window": window})}
            want = expected_rows(case, fn, window)
            label = f"{fn} window={window}"
            status, body = post("allowed", fn, params)
            problems += [f"{label} CONTROL: {p}" for p in control_problems(status, body, case, fn, want)]
            status, body = post("denied", fn, params)
            problems += [f"{label} DENIED: {p}" for p in denied_problems(status, body, case, want)]
    return problems


# ── the live test ─────────────────────────────────────────────────────────────

def test_the_variance_set_reads_the_fixture_and_the_asset_gate_refuses():
    case = load_case()
    missing = missing_preconditions(case, os.environ)
    if missing:
        pytest.skip("NOT RUN, NOT A PASS. Waiting on: " + "; ".join(missing))

    import httpx
    bff = (os.environ.get("BFF_URL") or DEFAULT_BFF).rstrip("/")
    token_dir = Path(os.environ[TOKEN_DIR_ENV])
    tokens = {role: (token_dir / f"token-{case[f'{role}_persona']}.txt").read_text(encoding="utf-8").strip()
              for role in ("allowed", "denied")}

    def post(role: str, fn: str, params: dict) -> tuple[int, Any]:
        r = httpx.post(f"{bff}/finance/measure/{fn}", json={"params": params}, timeout=60.0,
                       headers={"Authorization": f"Bearer {tokens[role]}"})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text

    started = time.time()
    problems = run_legs(case, post)
    since = int(time.time() - started) + 30
    logs = subprocess.run([*shlex.split(os.environ[KUBECTL_ENV]), "logs", f"deploy/{case['deployment']}",
                           f"--since={since}s"], capture_output=True, text=True, timeout=60)
    evidence = read_evidence_problem(logs.stdout.splitlines(), case["asset"])
    assert not problems and evidence is None, "\n".join([*problems, *([evidence] if evidence else [])])
