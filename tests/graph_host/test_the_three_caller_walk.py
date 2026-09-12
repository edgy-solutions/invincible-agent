"""5.3 — three callers, three outcomes, and the graph must tell them apart.

ADR-0049 Ruling 1: an inner call carries the INITIATOR's identity, so a caller entitled to less
sees less. Ruling 2: what a graph does with an inner refusal is DECLARED PER ROW. Together they
mean one graph has three distinct honest answers, and this file is where they are distinguished:

    entitled to all three          a brief with three findings and NO holes
    entitled minus fin_burn_rate   a brief with that finding NAMED ABSENT — the declared
                                   `named-hole` disposition, visible to the READER
    entitled to none               every finding a hole, and the brief SAYS it answered nothing

── WHY THIS FILE IS FIXTURE-DRIVEN AND A SECOND FILE IS NOT ────────────────────────────────
The three Topaz persona cells are a human write and do not exist yet. A harness that waited for
them would deliver nothing today and, worse, would tempt a skip that reads as a pass.

So the split is deliberate and the halves prove different things:

  THIS FILE   the GRAPH's behaviour given each entitlement outcome. A stub engine-fin returns
              200 / 403 / 403-for-all, and the graph must produce finding / named hole / all
              holes. No cluster, no model, no cells — provable now, and it is the half that
              would otherwise be assumed.
  THE LIVE    that a REAL caller's entitlement produces those outcomes. That needs the cells
  WALK        and is gated on them, in `test_the_three_caller_walk_live.py`, skipping with a
              reason that names the missing cells rather than reading as green.

**A stub proving the graph branches correctly is not evidence that Topaz scopes the caller.**
Stated here because the two are routinely conflated, and this file can only ever support the
first.

── WHAT THIS CANNOT DISTINGUISH ────────────────────────────────────────────────────────────
**A hole tells you a finding is unavailable. Only its REASON says why, and only the live walk
can attribute the reason to a real entitlement.** The graph separates an entitlement refusal
(401/403 -> "the caller is not entitled to X") from any other failure (">= 400 -> X returned
N"), and the partially-entitled test asserts the first — but a 403 from engine-fin because the
CALLER is unentitled and a 403 because engine-fin is MISCONFIGURED are the same status code, so
the graph cannot tell them apart and is right not to guess.

That distinction was not asserted in the first draft of this file, and a MUTATION FOUND IT:
deleting the 401/403 branch entirely left every test green, because execution fell through to
the generic `>= 400` branch which also returns a hole. The branch existed, the seal covered the
file, and the branch was not load-bearing. A surviving mutation on healthy code means the test
cannot tell yet — here it was the test's REACH, not its assertion.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import TCPServer

import pytest

_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def engine_fin_stub():
    """A stand-in engine-fin whose verdict per verb the test chooses.

    Records what it was CALLED WITH, because "the graph produced a hole" is only half the
    claim — the other half is that it forwarded the initiator's credential rather than
    inventing one, and a stub that does not capture headers cannot see the difference.
    """
    verdicts: dict[str, int] = {}
    seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            fn = self.path.rsplit("/", 1)[-1]
            n = int(self.headers.get("Content-Length", 0))
            seen.append({
                "fn": fn,
                "authorization": self.headers.get("authorization"),
                "originator_email": self.headers.get("x-originator-email"),
                "body": json.loads(self.rfile.read(n) or b"{}"),
            })
            code = verdicts.get(fn, 200)
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            body = ({"headline": f"{fn} ok", "artifact_id": f"art-{fn}"} if code == 200
                    else {"detail": "not entitled"})
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *a):
            pass

    srv = TCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}", verdicts, seen
    finally:
        srv.shutdown()


def _run_brief(stub_url: str, identity: dict) -> dict:
    """Invoke the real graph against the stub, as the host would."""
    import importlib
    import os
    import sys

    sys.path.insert(0, str(_ROOT))
    os.environ["ENGINE_FIN_URL"] = stub_url
    from agent_fleet.graph_host.graphs import fin_program_brief as g

    importlib.reload(g)
    compiled = g.build().compile()
    return compiled.invoke({"program_id": "PGM-001", "identity": identity})


_IDENT = {"authorization": "Bearer caller-token", "x-originator-email": "alice@example.com"}


def test_the_stub_is_actually_reached(engine_fin_stub):
    """POSITIVE CONTROL, first, and REWRITTEN because the first version controlled nothing.

    It called `pytest.importorskip("langgraph")` and passed — which asserts a package is
    installed, not that the graph reaches the stub. If the graph never called engine-fin at all
    (wrong env var, a swallowed exception, a renamed endpoint) every outcome below would be
    produced by a graph talking to nothing, and THREE HOLES WOULD LOOK LIKE A CORRECT
    UNENTITLED RESULT. That is the failure this control exists for, and the original could not
    see it.
    """
    url, _verdicts, seen = engine_fin_stub
    _run_brief(url, _IDENT)
    assert [c["fn"] for c in seen] == [fn for fn, _ in __import__(
        "agent_fleet.graph_host.graphs.fin_program_brief", fromlist=["_VIEWS"]
    )._SOURCES], "the graph did not call the stub for each declared source, in order"


def test_ENTITLED_gets_three_findings_and_no_holes(engine_fin_stub):
    url, verdicts, seen = engine_fin_stub
    out = _run_brief(url, _IDENT)

    assert len(seen) == 3, f"the graph called {len(seen)} inner verbs, not 3 — {[s['fn'] for s in seen]}"
    assert len(out.get("findings") or []) == 3, f"expected three findings: {out}"
    assert not out.get("holes"), f"an entitled caller got holes: {out.get('holes')}"

    # THE IDENTITY HALF. Without this the test passes for a graph that called engine-fin under
    # the HOST's own credential, which is the laundering ADR-0029 Decision 5 forbids and is
    # invisible in the output.
    for call in seen:
        assert call["authorization"] == _IDENT["authorization"], (
            f"{call['fn']} was called with {call['authorization']!r}, not the initiator's token"
        )
        assert call["originator_email"] == _IDENT["x-originator-email"]

    assert "PGM-001" in out.get("summary", ""), "the brief does not name the program it is about"


def test_PARTIALLY_ENTITLED_gets_the_missing_finding_NAMED(engine_fin_stub):
    url, verdicts, seen = engine_fin_stub
    verdicts["fin_burn_rate"] = 403

    out = _run_brief(url, _IDENT)

    assert len(out.get("findings") or []) == 2, f"expected two findings: {out}"
    holes = out.get("holes") or []
    assert len(holes) == 1 and holes[0]["source"] == "fin_burn_rate", f"wrong hole: {holes}"

    # THE REASON, NOT JUST THE HOLE — added after a SURVIVING MUTATION. Deleting the
    # `401/403` branch entirely left this test green, because execution falls through to the
    # generic `>= 400` branch which ALSO returns a hole. So "a hole appeared" could not
    # distinguish an ENTITLEMENT REFUSAL from engine-fin being broken, and the branch that
    # exists to make that distinction was not load-bearing under the seal. A hole is evidence
    # the finding is unavailable; only its reason is evidence about WHY, and a caller told
    # "returned 403" when the truth is "you are not entitled" is sent to debug the wrong thing.
    assert "not entitled" in holes[0]["reason"], (
        f"the hole does not say the CALLER was refused — it reads as a generic failure, which "
        f"is a different diagnosis for the reader: {holes[0]['reason']!r}"
    )

    # THE HOLE MUST BE IN THE BRIEF, not only in the state. A brief built from two of three
    # sources and presented as a brief is a silently-narrowed answer; naming it is what makes
    # the narrowing visible to whoever reads it rather than known only to the log.
    summary = out.get("summary", "")
    assert "NOT AVAILABLE" in summary, f"the hole is not in the rendered brief:\n{summary}"
    assert "burn" in summary.lower(), f"the brief does not say WHICH finding is missing:\n{summary}"

    # AND THE GRAPH STILL RAN THE OTHER TWO — a refusal on one inner verb must not abort a
    # `named-hole` graph, which is the whole difference from cost_lot_costing_review's `fail`.
    assert len(seen) == 3, "a refused inner verb stopped the graph; this row declares named-hole"


def test_UNENTITLED_gets_all_holes_AND_the_brief_says_it_answered_NOTHING(engine_fin_stub):
    """The third caller, and the assertion is about HONESTY rather than refusal.

    This row declares `named-hole`, so an unentitled caller does not get a 403 from the graph —
    they get a brief in which every finding is absent. That is only acceptable if the brief
    SAYS SO: three holes rendered as a brief, with nothing marking it empty, is the
    silently-narrowed answer at its worst, because the narrowing is total.
    """
    url, verdicts, seen = engine_fin_stub
    for fn in ("fin_variance_analysis", "fin_burn_rate", "fin_funding_status"):
        verdicts[fn] = 403

    out = _run_brief(url, _IDENT)

    assert not out.get("findings"), f"an unentitled caller got findings: {out.get('findings')}"
    assert len(out.get("holes") or []) == 3, f"expected three holes: {out.get('holes')}"
    summary = out.get("summary", "")
    assert "no finding was retrievable" in summary, (
        "a brief with NOTHING in it must say so. Three holes rendered as a brief, with nothing "
        f"marking it empty, is a narrowed answer presented as a whole one:\n{summary}"
    )


def test_NO_IDENTITY_is_a_hole_and_the_host_credential_is_never_used(engine_fin_stub):
    """The fourth case, and it is the one that would be a security defect rather than a gap.

    A node that found no initiator identity and proceeded would run a governed finance read as
    the HOST — seeing everything the host is entitled to and handing it to a caller entitled to
    less. The graph must record a hole and NOT CALL engine-fin AT ALL.
    """
    url, verdicts, seen = engine_fin_stub
    out = _run_brief(url, {})

    assert len(out.get("holes") or []) == 3, f"expected three holes: {out.get('holes')}"
    assert seen == [], (
        f"the graph called engine-fin with NO initiator identity ({len(seen)} calls) — that is "
        f"a governed read performed as the host, which is laundering rather than a gap"
    )
    assert any("identity" in h["reason"] for h in out["holes"]), (
        f"the holes do not say the identity was missing: {out['holes']}"
    )
