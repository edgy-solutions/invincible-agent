"""Fire every walk-sheet question at the deployed fleet and print the result with a sha.

    uv run --frozen python scripts/walk_census.py
    uv run --frozen python scripts/walk_census.py --only cost-supplier-concentration-lot-4

Runs as the census's SECOND HALF after every roll. The first half says what is deployed; this
says what it can still answer.

── WHY THIS EXISTS ─────────────────────────────────────────────────────────────────────────────
Every regression in the week of 2026-09-15 was found by a person at a browser, a day late. The
lot 4 regression is the sharpest case: a CODE BISECT WAS CORRECTLY NEGATIVE — the engine was
byte-identical across the window — because the graph had gained twenty part numbers containing a
4 and a latent defect became live on DATA ARRIVAL. There was no commit to find. A suite cannot
see that, and no amount of unit testing would have; only asking the question of the running
fleet does.

── WHAT IT SENDS, AND THE THREE INSTRUMENT DEFECTS IT IS BUILT AGAINST ─────────────────────────
1. `active_persona` / `active_domains` ARE SENT. `tests/sandbox_e2e/mesh_client.py` does not send
   them and defaults to agent-user/DATA_ENGINEER, so an unentitled probe reads as a dead fleet.
   Four instrument defects on one walk this week traced to exactly this.
2. The per-row `user` gets its OWN token. bob's queue cannot be probed as agent-user.
3. A CONNECTION FAILURE IS REPORTED AS ONE, never as an empty payload. Port-forwards die across
   a roll, and a dead forward and a genuinely empty answer are indistinguishable at the call
   site unless the runner insists on telling them apart.

── AND WHAT A GREEN HERE DOES NOT MEAN ─────────────────────────────────────────────────────────
This reads the ARTIFACT, which is what the engine produced. It is not evidence that a card
renders — that still needs a human with the UI open, and the walk sheets say so. What it does
prove is the half that kept silently breaking: that the question still reaches the right verb
and comes back with a payload of the right shape.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from iagent_pure.walk_census import (  # noqa: E402
    FAIL, PASS, CensusRow, judge, load_rows, partition, reconcile,
)

CENSUS = _REPO / "docs" / "measurements" / "walk-census.yaml"
#: NO DEFAULT, DELIBERATELY — and the removal IS the fix, not a missing convenience.
#:
#: This read `http://localhost:18083/realms/invincible-agent` until 2026-09-23. 18083 is the
#: fleet's port-forward convention for keycloak (`tests/sandbox_e2e/mesh_client.py:5`, its README,
#: `tests/sandbox_e2e/test_engine_d_datahub_suite.py`), but on the box that runs this census the
#: port was squatted by a leftover stub from a DELETED scratchpad. Measured 2026-09-23, all three
#: legs: the realm path returns `{"component": "cortex-bff", "git_sha": "deadbeef…"}` — not a realm
#: document — and the token endpoint answers **500 to valid and invalid credentials alike**. So the
#: census reported *"keycloak refused a token"* about a request keycloak never saw.
#:
#: A dead forward fails loudly; a LIVE forward to the wrong process ANSWERS. That is why a default
#: port is the hazard here rather than the convenience: it decides silently which process gets to
#: adjudicate credentials.
#:
#: And the repair is deliberately NOT a different number. Four other sites already declare 18083;
#: inventing a rival default here would make this the fifth mirror of one value, and a default
#: invented locally becomes a contract the moment anything relies on it. Instead the operator must
#: SAY where keycloak is, and `_assert_is_keycloak` verifies the endpoint is keycloak before any
#: answer of its is believed. If the fleet wants a census port, it should be declared once,
#: fleet-wide, not a fifth time here.
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL")
BFF_URL = os.getenv("BFF_URL", "http://localhost:18090")
CLIENT_ID = os.getenv("KC_CLIENT_ID", "cortex-ui")

#: Per-user sandbox credential. The seeded realm gives each demo user its OWN password
#: (`alice`/`alice`, `bob`/`bob`) and only `agent-user` uses the literal `password` — a single
#: shared `KC_PASS` is why the census's first run 403'd every cost row as agent-user.
#:
#: NOT A SECRET, and said plainly rather than left to look like one: these are the demo values
#: the realm ConfigMap already carries in this repo, for a sandbox the architect keeps for
#: exactly this. A real deployment supplies `CENSUS_PASS_<USER>` and never reaches the default.
def _password(user: str) -> str:
    override = os.getenv(f"CENSUS_PASS_{user.upper().replace('-', '_')}")
    if override:
        return override
    return "password" if user == "agent-user" else user

#: PASS/FAIL come from the pure module so the runner and its seal cannot disagree
#: about what a verdict is called.
BLOCKED = "BLOCKED"


class Unreachable(RuntimeError):
    """The fleet could not be talked to. DISTINCT from a wrong answer, and the distinction is
    the point: a dead port-forward produces an empty result that reads exactly like a verb
    returning nothing."""


class NotKeycloak(Unreachable):
    """The endpoint ANSWERED, but not as keycloak — so nothing it said is about credentials.

    A THIRD state, and it needs to be its own: `Unreachable` covers a forward that is dead, and a
    refusal covers a credential keycloak rejected. Neither describes a live socket held by some
    other process, which is the case that actually occurred (a stub 500ing every credential) and
    the one the old message misreported as *"keycloak refused a token"*.
    """


def _keycloak_url() -> str:
    """The configured realm URL, or a failure that says what to do about it."""
    if not KEYCLOAK_URL:
        raise Unreachable(
            "KEYCLOAK_URL is not set, and this census no longer guesses a port — see the comment "
            "on KEYCLOAK_URL for why a guess is the defect and not the convenience.\n"
            "  kubectl -n sandbox port-forward svc/iagent-keycloak 18083:8080 &\n"
            "  KEYCLOAK_URL=http://localhost:18083/realms/invincible-agent \\\n"
            "    uv run --frozen python scripts/walk_census.py\n"
            "Check what holds the port before trusting it: the realm path must return a realm "
            "document carrying `realm` and `public_key`, not merely HTTP 200."
        )
    return KEYCLOAK_URL.rstrip("/")


#: The two fields a keycloak realm document always carries and a stub answering 200 will not.
_REALM_DOC_KEYS = ("realm", "public_key")


async def _assert_is_keycloak(client: httpx.AsyncClient) -> None:
    """Assert endpoint IDENTITY once, before any credential is judged by whatever is listening.

    Ordering is the whole point: without this, the first thing that reads the endpoint is a
    credential check, and a non-keycloak answer arrives already dressed as a verdict about the
    credential. Asked in this order, the same wrong process produces an unambiguous report.
    """
    url = _keycloak_url()
    try:
        r = await client.get(url, timeout=10.0)
    except httpx.HTTPError as exc:
        raise Unreachable(f"keycloak at {url} unreachable: {exc}") from exc
    try:
        doc = r.json()
    except ValueError:
        doc = None
    missing = (
        [k for k in _REALM_DOC_KEYS if not isinstance(doc, dict) or k not in doc]
        if r.status_code == 200
        else list(_REALM_DOC_KEYS)
    )
    if missing:
        raise NotKeycloak(
            f"{url} answered HTTP {r.status_code} but not as keycloak: a realm document is "
            f"missing {missing}. Body: {r.text[:200]!r}\n"
            "Something else holds this port. A stub on the census's old default answered exactly "
            "like this, and 500'd every credential, which the census used to report as a refusal."
        )


async def _token(client: httpx.AsyncClient, user: str) -> str:
    url = _keycloak_url()
    try:
        r = await client.post(
            f"{url}/protocol/openid-connect/token",
            data={"client_id": CLIENT_ID, "grant_type": "password",
                  "username": user, "password": _password(user)},
            timeout=15.0,
        )
    except httpx.HTTPError as exc:
        raise Unreachable(f"keycloak at {url} unreachable: {exc}") from exc
    if r.status_code == 200:
        return r.json()["access_token"]
    try:
        err = r.json().get("error")
    except ValueError:
        err = None
    # A REFUSAL IS A 4xx THAT NAMES ITS REASON. keycloak rejects a credential with 400/401 and an
    # OAuth `error` field (`invalid_grant`, `invalid_client`); anything else — a 5xx, HTML, an
    # empty body, a 4xx with no `error` — is the endpoint failing, and calling that a refusal
    # blames the credential for the endpoint's state.
    if r.status_code in (400, 401) and err:
        raise Unreachable(
            f"keycloak REFUSED a token for {user!r}: {r.status_code} {err} — the endpoint is "
            f"keycloak and it rejected this credential. Body: {r.text[:200]}"
        )
    raise NotKeycloak(
        f"the token endpoint at {url} answered HTTP {r.status_code} with no OAuth error field, "
        f"for user {user!r}. THIS IS NOT A REFUSAL and says nothing about the credential — it is "
        f"the endpoint failing or not being keycloak. Body: {r.text[:200]!r}"
    )


async def _fire(client: httpx.AsyncClient, token: str, row: CensusRow,
                timeout_s: float) -> dict[str, Any]:
    """POST /orchestrate as this row's cell and collect the stream."""
    body = {
        "message": row.question,
        "session_id": f"census-{row.id}-{uuid.uuid4().hex[:8]}",
        "active_persona": row.persona,
        "active_domains": list(row.domains),
        # ASKED AS THE BROWSER ASKS. Without this the fleet correctly refuses a live view
        # (`live_view_requires_registration`) and every archetype assertion scores a default
        # menu the walk sheet never describes.
        "frontend_id": row.frontend_id,
    }
    final: dict[str, Any] | None = None
    events: list[dict] = []
    try:
        async with client.stream(
            "POST", f"{BFF_URL}/orchestrate",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json",
                     "Accept": "text/event-stream"},
            json=body,
            timeout=httpx.Timeout(timeout_s, connect=10.0),
        ) as resp:
            if resp.status_code != 200:
                detail = (await resp.aread())[:400]
                # A 403 here is an ANSWER about entitlement, not an outage — surfaced as a
                # failure with its body rather than as an unreachable fleet.
                raise RuntimeError(f"orchestrate {resp.status_code}: {detail!r}")
            cur = None
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    cur = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    try:
                        payload = json.loads(line[len("data:"):].strip())
                    except Exception:
                        continue
                    events.append({"event": cur, "data": payload})
                    if cur in ("final_payload", "final_response", "complete", "result"):
                        final = payload
    except httpx.HTTPError as exc:
        raise Unreachable(f"cortex-bff at {BFF_URL} unreachable: {exc}") from exc
    return {"final": final, "events": events}


async def _run(rows: list[CensusRow], timeout_s: float) -> list[dict]:
    out = []
    async with httpx.AsyncClient() as client:
        # IDENTITY FIRST, ONCE, AND FATAL. Not per-row: a wrong endpoint is a property of the run,
        # and letting it fail row-by-row would print N credential verdicts about one bad forward —
        # a uniform column that reads as a broken fleet. Raised, not appended, so no census output
        # is produced at all; a census that cannot authenticate has measured nothing.
        await _assert_is_keycloak(client)
        tokens: dict[str, str] = {}
        for row in rows:
            try:
                if row.user not in tokens:
                    tokens[row.user] = await _token(client, row.user)
                result = await _fire(client, tokens[row.user], row, timeout_s)
            except Unreachable as exc:
                out.append({"row": row, "state": FAIL, "why": [f"UNREACHABLE: {exc}"]})
                continue
            except Exception as exc:  # noqa: BLE001
                out.append({"row": row, "state": FAIL, "why": [f"{type(exc).__name__}: {exc}"]})
                continue
            state, why = judge(row, result)
            out.append({"row": row, "state": state, "why": why})
    return out


def _sha() -> str:
    """The REPO sha — what the rows and their expectations were read from."""
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(_REPO),
                              capture_output=True, text=True, timeout=30).stdout.strip() or "?"
    except Exception:
        return "?"


def _deployed_sha() -> str:
    """The sha of the fleet that ANSWERED — which is the one a regression belongs to.

    THE REPO SHA IS THE WRONG STAMP AND WOULD HAVE BEEN QUIETLY WRONG. A census line exists to
    say "lot 4 broke at <sha>"; `git rev-parse HEAD` names the tree the RUNNER was read from,
    and those two diverge constantly — tonight by three commits, because a fix was committed
    while the cluster still served the image built before it. A row attributed to the local HEAD
    would blame a commit the fleet has never run.

    Derived from the running deployments rather than from the helm values, because what answered
    is what is running. A mixed fleet is reported as mixed instead of being collapsed to one
    value: "which sha answered" has no single answer mid-rollout, and saying so is the honest
    form. Unavailable -> `?`, never the repo sha as a stand-in.
    """
    try:
        r = subprocess.run(
            ["kubectl", "--context", "edge", "get", "deploy", "-n", "sandbox", "-o",
             "jsonpath={range .items[*]}{.spec.template.spec.containers[0].image}{'\\n'}{end}"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "MSYS_NO_PATHCONV": "1"},
        )
        tags = {
            ln.rsplit(":", 1)[-1] for ln in r.stdout.splitlines()
            if ln.strip() and len(ln.rsplit(":", 1)[-1]) == 40
        }
        if not tags:
            return "?"
        if len(tags) > 1:
            return "MIXED(" + ",".join(sorted(t[:7] for t in tags)) + ")"
        return next(iter(tags))[:7]
    except Exception:
        return "?"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=[], help="row id (repeatable)")
    ap.add_argument("--timeout", type=float, default=900.0)
    args = ap.parse_args()

    rows = load_rows(CENSUS)
    rec = reconcile(rows, _REPO)
    sha = _sha()
    deployed = _deployed_sha()

    # BOTH, and labelled. `repo` is where the questions and expectations came from;
    # `fleet` is what answered them. Printing one number called "sha" invited the
    # reader to attribute a failure to whichever of the two they assumed it was.
    print(f"WALK CENSUS  repo={sha}  fleet={deployed}  rows={len(rows)}")
    if not rec.ok:
        # THE DERIVATION IS BROKEN, so the run is not authoritative and says so before it runs
        # anything. A census whose questions have drifted from the sheets is asking text nobody
        # asks, and green on it would be worse than red.
        print(f"  !! DERIVATION BROKEN — {len(rec.problems)} problem(s); results below are NOT "
              f"authoritative")
        for kind, who, detail in rec.problems:
            print(f"     {kind}: {who}: {detail}")

    runnable, blocked = partition(rows)
    if args.only:
        runnable = [r for r in runnable if r.id in args.only]
        blocked = [r for r in blocked if r.id in args.only]

    results = asyncio.run(_run(runnable, args.timeout)) if runnable else []

    # BLOCKED ROWS ARE PRINTED, AS STATE. They are not skipped and not hidden: a standing gap
    # that nobody sees becomes a standing gap nobody fixes.
    for row in blocked:
        results.append({"row": row, "state": BLOCKED, "why": [row.blocked]})

    width = max((len(r["row"].id) for r in results), default=10)
    for r in results:
        print(f"  {r['state']:<7} {r['row'].id:<{width}}  {r['row'].persona}")
        for w in r["why"]:
            print(f"          {w}")

    n_pass = sum(1 for r in results if r["state"] == PASS)
    n_fail = sum(1 for r in results if r["state"] == FAIL)
    n_blk = sum(1 for r in results if r["state"] == BLOCKED)
    print(f"\n  {n_pass} pass, {n_fail} fail, {n_blk} blocked   "
          f"repo={sha}  fleet={deployed}")
    # A BLOCKED ROW IS A NON-ZERO EXIT. It is a question the fleet is not being asked, which is
    # exactly the state that goes unnoticed if it exits 0.
    return 0 if (n_fail == 0 and n_blk == 0 and rec.ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
