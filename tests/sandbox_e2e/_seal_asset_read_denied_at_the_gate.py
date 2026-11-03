"""LIVE SEAL -- a principal who HOLDS the cell but lacks the asset grant is refused at the ASSET gate.

WHAT IT PROVES ON THE RUNNING CLUSTER, end to end, for one case of `asset_denial_seal.yaml`:
  CONTROL  the allowed subject (cell + asset grant) asks the question -> rows come back
  DENIED   a second subject who holds the SAME cell and has NO grant for the asset asks the SAME
           question -> an `access_denied` event naming the asset and that subject, no rows, and no
           data-plane ticket minted in the leg's window.

WHY THE DENIED SUBJECT HOLDS THE CELL. A principal who cannot hold the persona is refused at the
persona gate (403 cell_not_entitled) and proves nothing about the asset gate. So the denied
principal differs from the allowed one in exactly one fact, the per-asset grant, and the seal's
two preflights (the policy rail, then the live /me/entitlements) refuse to run on anything else.
Drift in either is exit 2, naming the fact.

EVERYTHING THE CASE NAMES IS CONFIG. No principal, asset, persona or domain appears in this file.

ROWS EVIDENCE (what "the read returned data" means here). The final payload of a successful read
is `{"components": [...]}`; a data read renders a CHART_WIDGET component whose `chart_data` is a
non-empty list of row objects (the presentation agent passes it through untouched, and falls back
to a KNOWLEDGE_DOCUMENT with no `chart_data` when there are none). Rows evidence is a component
with a non-empty `chart_data` (or `rows`) list, or a string that parses to one. Prose in
`markdown_content` that mentions a number is NOT rows.

WHAT THE GATEWAY LOG CAN SHOW (read from a saved log, 2026-11-03): no per-request allow/deny line.
There IS a `subject_gauge` line naming the header subject, and an httpx `POST .../internal/resolve`
line when a ticket is minted, with no subject in it. So reach = a line in the window naming the
denied subject; mint = the `internal/resolve` substring. Both matchers live in
`gateway_log_signals`, the one place to change when the gateway's log form changes.

Requires: a token per subject, minted by `scripts/mint_persona_token.py` into the scratchpad.
Run:  kubectl port-forward -n <ns> svc/iagent-cortex-bff 18090:8090
      python -I scripts/mint_persona_token.py <persona> --out <dir>      (once per subject)
      .venv/Scripts/python -X utf8 tests/sandbox_e2e/_seal_asset_read_denied_at_the_gate.py \\
          --allowed-token-file <dir>/token-<allowed>.txt --denied-token-file <dir>/token-<denied>.txt \\
          --gateway-log-cmd "kubectl -n <ns> logs deploy/iagent-cortex-bff --since={since}s"
Exit: 0 sealed - 1 breach (a ticket was minted, or rows reached the denied subject) -
      2 inconclusive (drift, a missing precondition, a refusal before the gate, anything unexpected).
      Exit 2 is NOT a pass.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from typing import Any, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEFAULT_CONFIG = os.path.join(HERE, "asset_denial_seal.yaml")
DEFAULT_POLICY = os.path.join(REPO, "policy")

# Error codes the persona/domain gate raises BEFORE any asset is looked at.
_CELL_REFUSALS = {"cell_not_entitled", "incomplete_override"}


class _Inconclusive(Exception):
    pass


# --------------------------------------------------------------------------- pure decision

def gateway_log_signals(lines: List[str], subject: str) -> Tuple[bool, bool]:
    """(reached, minted) for one leg's gateway log window. THE ONE PLACE the log form is read.

    reached: some line names the subject (case-insensitive). minted: some line is the httpx
    `internal/resolve` POST, which carries no subject.
    """
    subj = (subject or "").lower()
    reached = bool(subj) and any(subj in (ln or "").lower() for ln in lines or [])
    minted = any("internal/resolve" in (ln or "") for ln in lines or [])
    return reached, minted


def _components(final: Any) -> list:
    comps = final.get("components") if isinstance(final, dict) else None
    return [c for c in comps if isinstance(c, dict)] if isinstance(comps, list) else []


def _is_rows(value: Any) -> bool:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return False
    return isinstance(value, list) and len(value) > 0


def has_rows(final: Any) -> bool:
    """Rows evidence in a final payload: see the module docstring. Prose is never rows."""
    return any(_is_rows(c.get("chart_data")) or _is_rows(c.get("rows")) for c in _components(final))


def _access_denials(events: list) -> list:
    return [e.get("data") for e in events or []
            if isinstance(e, dict) and e.get("event") == "access_denied" and isinstance(e.get("data"), dict)]


def _refused_by_cell(events: list) -> bool:
    for e in events or []:
        d = e.get("data") if isinstance(e, dict) else None
        if isinstance(d, dict) and d.get("error") in _CELL_REFUSALS:
            return True
    return False


def control_failed(control: dict) -> bool:
    return (control.get("http_status") != 200 or bool(_access_denials(control.get("events") or []))
            or control.get("final") is None or not has_rows(control.get("final")))


def verdict(control: dict, denied: dict) -> Tuple[int, str]:
    """Decide the seal. Each leg: events, final, http_status, gateway_lines. The denied leg also
    carries `asset` (the URN) and `subject` (the denied subject's email)."""
    if control_failed(control):
        return 2, "control_failed"

    events = denied.get("events") or []
    if denied.get("http_status") != 200 or _refused_by_cell(events):
        return 2, "refused_before_the_gate"

    subject, asset = denied.get("subject") or "", denied.get("asset") or ""
    reached, minted = gateway_log_signals(denied.get("gateway_lines") or [], subject)
    if not reached:
        return 2, "gate_not_reached"

    denials = _access_denials(events)
    if minted and not denials:
        return 1, "ticket_minted"
    if has_rows(denied.get("final")):
        return 1, "rows_reached_denied_subject"

    for d in denials:
        if asset in (d.get("denied_assets") or []) and str(d.get("subject") or "").lower() == subject.lower():
            if minted:
                return 2, "resolve_in_window"
            return 0, "sealed"
    return 2, "undecided"


# --------------------------------------------------------------------------- preflights (pure)

def _yaml(path: str) -> Any:
    import yaml
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def rail_preflight(case: dict, policy_dir: str = DEFAULT_POLICY) -> Optional[str]:
    """None when the rail agrees with the case; else the drifted fact, named."""
    users = {u["id"]: u for u in (_yaml(os.path.join(policy_dir, "users.yaml")) or {}).get("users", [])}
    groups = (_yaml(os.path.join(policy_dir, "groups.yaml")) or {}).get("groups", {})
    grants = (_yaml(os.path.join(policy_dir, "asset_grants.yaml")) or {}).get("grants", [])
    asset, grp = case["asset"], case["persona_group"]

    def has_row(subject: str) -> bool:
        return any(g.get("subject") == subject and g.get("asset") == asset
                   and g.get("kind", "dataset") != "document" for g in grants)

    for role in ("allowed_subject", "denied_subject"):
        subj = case[role]
        if subj not in users:
            return f"{role} {subj} is not in policy/users.yaml"
        if grp not in (users[subj].get("groups") or []):
            return f"{role} {subj} is not in group {grp}"
    if not has_row(case["allowed_subject"]):
        return f"allowed_subject {case['allowed_subject']} has no asset_grants row for the asset"
    if has_row(case["denied_subject"]):
        return f"denied_subject {case['denied_subject']} HAS an asset_grants row for the asset"
    cells = {(g.get("persona"), g.get("domain")) for g in (groups.get(grp) or {}).get("grants", [])}
    for d in case["active_domains"]:
        if (case["active_persona"], d) not in cells:
            return f"group {grp} does not grant {case['active_persona']} on {d}"
    return None


def entitlement_drift(ent: Any, subject: str, persona: str, domains: List[str]) -> Optional[str]:
    """None when /me/entitlements says this principal is `subject` and holds persona x domains."""
    if not isinstance(ent, dict):
        return "/me/entitlements did not return an object"
    if str(ent.get("email") or "").lower() != subject.lower():
        return f"token resolves to a different email than {subject}"
    cells = {(c.get("persona"), c.get("domain")) for c in ent.get("cells") or [] if isinstance(c, dict)}
    for d in domains:
        if (persona, d) not in cells:
            return f"{subject} does not hold {persona} x {d} live"
    return None


# --------------------------------------------------------------------------- live legs

def _read_token(path: str, label: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            tok = fh.read().strip()
    except OSError as exc:
        raise _Inconclusive(f"{label} token file unreadable ({type(exc).__name__})")
    if not tok:
        raise _Inconclusive(f"{label} token file is empty")
    print(f"  {label} token: len={len(tok)} sha256[:8]={hashlib.sha256(tok.encode()).hexdigest()[:8]}")
    return tok


def _gateway_lines(cmd: Optional[str], since_s: int) -> List[str]:
    if not cmd:
        return []
    try:
        out = subprocess.run(cmd.replace("{since}", str(since_s)), shell=True, capture_output=True,
                             text=True, timeout=120)
    except Exception as exc:  # noqa: BLE001
        raise _Inconclusive(f"gateway log command failed ({type(exc).__name__})")
    if out.returncode != 0:
        raise _Inconclusive(f"gateway log command exited {out.returncode}")
    return out.stdout.splitlines()


async def _leg(mc, client, token: str, case: dict, label: str, log_cmd: Optional[str], timeout: float) -> dict:
    t0 = time.time()
    status, res = 200, {}
    try:
        res = await mc.orchestrate(
            client, token, case["question"], session_prefix=f"asset-seal-{label}",
            print_status=False, timeout_s=timeout,
            extra_body={"active_persona": case["active_persona"],
                        "active_domains": list(case["active_domains"])},
        )
    except RuntimeError as exc:
        m = re.search(r"orchestrate failed: (\d+)", str(exc))
        if not m:
            raise
        status = int(m.group(1))
    lines = _gateway_lines(log_cmd, int(time.time() - t0) + 30)
    return {"events": res.get("events") or [], "final": res.get("final"), "http_status": status,
            "gateway_lines": lines, "asset": case["asset"], "subject": case["denied_subject"]}


async def _live(case: dict, args) -> int:
    import httpx
    sys.path.insert(0, HERE)
    import mesh_client as mc

    allowed = _read_token(args.allowed_token_file, "allowed")
    denied = _read_token(args.denied_token_file, "denied")
    async with httpx.AsyncClient() as client:
        print("=== LEG 2: live entitlements ===")
        for label, tok, subj in (("allowed", allowed, case["allowed_subject"]),
                                 ("denied", denied, case["denied_subject"])):
            r = await client.get(f"{mc.BFF_URL}/me/entitlements",
                                 headers={"Authorization": f"Bearer {tok}"}, timeout=15.0)
            if r.status_code != 200:
                print(f"INCONCLUSIVE: /me/entitlements for {label} returned {r.status_code}")
                return 2
            drift = entitlement_drift(r.json(), subj, case["active_persona"], case["active_domains"])
            if drift:
                print(f"INCONCLUSIVE: {drift}")
                return 2
            print(f"  {label}: email={subj} holds the cell")
        print("=== LEG 3: control (allowed subject) ===")
        ctl = await _leg(mc, client, allowed, case, "ctl", args.gateway_log_cmd, args.timeout)
        if control_failed(ctl):
            print("INCONCLUSIVE: control_failed")
            return 2
        print("=== LEG 4: denied subject ===")
        den = await _leg(mc, client, denied, case, "den", args.gateway_log_cmd, args.timeout)
    code, reason = verdict(ctl, den)
    print(f"{'SEALED' if code == 0 else 'BREACH' if code == 1 else 'INCONCLUSIVE'}: {reason}")
    return code


def _load_case(path: str, name: Optional[str]) -> dict:
    rows = (_yaml(path) or {}).get("cases") or []
    if not rows:
        raise _Inconclusive("no cases in the config")
    if name is None:
        return rows[0]
    for r in rows:
        if r.get("name") == name:
            return r
    raise _Inconclusive(f"no case named {name}")


async def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--denied-token-file", required=True)
    ap.add_argument("--allowed-token-file", required=True)
    ap.add_argument("--case", default=None)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--policy-dir", default=DEFAULT_POLICY)
    ap.add_argument("--gateway-log-cmd", default=None)
    ap.add_argument("--timeout", type=float, default=900.0)
    args = ap.parse_args(argv)
    try:
        case = _load_case(args.config, args.case)
        print(f"=== LEG 1: policy rail, case {case.get('name')} ===")
        drift = rail_preflight(case, args.policy_dir)
        if drift:
            print(f"INCONCLUSIVE: rail drift: {drift}")
            return 2
        return await _live(case, args)
    except _Inconclusive as exc:
        print(f"INCONCLUSIVE: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 -- an unexpected failure is never a verdict
        print(f"INCONCLUSIVE: unexpected {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
