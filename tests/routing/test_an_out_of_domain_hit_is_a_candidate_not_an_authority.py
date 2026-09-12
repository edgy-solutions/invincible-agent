"""Domain scoping for instance-provider hits — cases 2 and 3, sealed.

IN-PROCESS BY CONSTRUCTION. Everything here stubs the resolver fan-out, so it measures the
SCOPING RULE rather than a cluster. That is deliberate and it is the lesson from the suite this
file lives in: `tests/routing/` exits 124 when the cluster is unreachable, saturated, or mid-roll,
because parts of it call the deployed classifier (`classify_latency_s = 10.41` measured by
invincible-agent-81). **A rule that can only be checked against a live cluster cannot gate the
roll that changes the cluster.**

THE ARC, in three cases, because only the first was a bug:

1. **A BARE DIGIT WAS AN IDENTIFIER.** `banana 4` resolved at exactly the floor because the
   instance id sat in the token set. A scorer defect, fixed in `finance_agent` and sealed in
   `test_a_bare_digit_is_not_an_identifier.py`.

2. **AN OUT-OF-DOMAIN HIT WAS AN AUTHORITY.** After (1), 81 enumerated all 33 cost instances
   against all 28 finance instances and found word-based collisions with no digit anywhere::

       'Notional Program Meridian'  -> cost 'Notional Production Program Vermilion'  0.533
       'Program Support'            -> cost 'Notional Production Program Vermilion'  0.500

   **Neither scorer is wrong.** Each is confident about its own vocabulary and `program` is
   genuinely a word in both. Nothing inside one engine's scoring can resolve it, and tightening
   either engine's overlap tier would make that engine worse at its own job. The only thing
   separating the readings is **which domain the question was asked in**, so the fix is here.

3. **TWO IN-DOMAIN CLAIMANTS IS AN ASK.** Scoping cannot help when both claimants are legitimately
   in the asked domain. Choosing by score then chooses by an accident of each engine's tokeniser.
   The engine abstains and hands back the competing readings; rendering the choice is cortex's.

THE THIRD STATE, which is the line that is easy to lose: **a provider declaring NO domains stays
UNSCOPED.** Absence of a declaration is not evidence of a boundary, and demoting it would be the
router inventing a boundary nobody asserted. It is logged by name at discovery instead, so the
list can be driven to zero and the next undeclared provider is a review question.

Run: uv run --frozen pytest tests/routing/test_an_out_of_domain_hit_is_a_candidate_not_an_authority.py -v
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_OS = _REPO / "agent_fleet" / "ontology_service"
if str(_OS) not in sys.path:
    sys.path.insert(0, str(_OS))

# Unique alias — see the note in `test_a_bare_digit_is_not_an_identifier.py`. Two engines
# both ship `main.py`, and `import main` makes the winner depend on collection order.
# `rdflib` is an ontology_service dependency and is NOT in the root venv by design (the
# dependency seal scopes to the root pyproject; engines declare their own), so the skip
# names the command that supplies it rather than saying "not importable".
_spec = importlib.util.spec_from_file_location(
    "ontology_service_main_under_test", str(_OS / "main.py"))
if _spec is None or _spec.loader is None:  # pragma: no cover
    pytest.skip("ontology_service/main.py not found", allow_module_level=True)
main = importlib.util.module_from_spec(_spec)
sys.modules["ontology_service_main_under_test"] = main
try:
    _spec.loader.exec_module(main)
except Exception as _exc:  # noqa: BLE001
    pytest.skip(
        f"ontology_service not importable here ({type(_exc).__name__}: {_exc}). "
        f"Run: uv run --frozen --with rdflib pytest {Path(__file__).name}",
        allow_module_level=True,
    )


class _Cand:
    """Shaped like `InstanceCandidate` — the four fields the scoping rule reads."""
    def __init__(self, instance_id, class_uri, label, score, provider):
        self.instance_id, self.class_uri = instance_id, class_uri
        self.label, self.score, self.provider = label, score, provider


class _Outcome:
    def __init__(self, provider, candidates):
        self.provider, self.candidates = provider, candidates
        self.status, self.endpoint_url, self.elapsed_s = "ok", "http://stub", 0.01


_FIN = "http://invincible-agent/fin#Program"
_COST = "http://invincible-agent/cost#ProductionProgram"


def _run(monkeypatch, *, resolvers, outcomes, asked, identifier="Notional Program Meridian"):
    """Drive `_resolve_instance` with a stubbed fan-out."""
    monkeypatch.setattr(main, "_discover_instance_resolvers", lambda *a, **k: resolvers)

    async def _fake_call(resolver, term, query):
        for o in outcomes:
            if o.provider == resolver["provider"]:
                return o
        return _Outcome(resolver["provider"], [])

    monkeypatch.setattr(main, "_call_resolver", _fake_call)
    return asyncio.run(main._resolve_instance(identifier, "q", asked))


# ---------------------------------------------------------------------------------------
# CASE 2 — the cross-domain hit
# ---------------------------------------------------------------------------------------

def test_AN_OUT_OF_DOMAIN_PROVIDER_IS_DEMOTED_not_authoritative(monkeypatch):
    """THE SEAL for case 2. A COST hit must not preempt a PROGRAM_FINANCE question."""
    resolvers = [{"provider": "engine-cost", "endpoint_url": "http://c",
                  "timeout_s": None, "domains": ["COST_ANALYST"]}]
    outcomes = [_Outcome("engine-cost", [
        _Cand("vermilion", _COST, "Notional Production Program Vermilion", 0.533, "engine-cost")])]
    subject, prov = _run(monkeypatch, resolvers=resolvers, outcomes=outcomes,
                         asked=["PROGRAM_FINANCE"])
    assert subject is None, (
        f"a cost provider preempted a PROGRAM_FINANCE question with {subject!r} — the "
        f"out-of-domain hit is acting as an authority again"
    )
    demoted = prov.get("instance_out_of_domain_demoted") or []
    assert any(d["provider"] == "engine-cost" for d in demoted), (
        "the demotion is not recorded, so 'nobody knew this name' is indistinguishable from "
        "'somebody knew it, in another domain' — which is the log line that sent four correct "
        "abstentions to a human as 'the cards are not routing'"
    )


def test_the_SAME_domain_provider_still_resolves(monkeypatch):
    """THE POSITIVE CONTROL for case 2, and the seal is vacuous without it.

    If scoping demoted everything, the assertion above would pass while measuring nothing.
    """
    resolvers = [{"provider": "engine-fin", "endpoint_url": "http://f",
                  "timeout_s": None, "domains": ["PROGRAM_FINANCE"]}]
    outcomes = [_Outcome("engine-fin", [
        _Cand("meridian", _FIN, "Notional Program Meridian", 1.0, "engine-fin")])]
    subject, prov = _run(monkeypatch, resolvers=resolvers, outcomes=outcomes,
                         asked=["PROGRAM_FINANCE"])
    assert subject is not None, (
        f"CONTROL FAILED: an IN-domain provider at score 1.0 resolved to nothing "
        f"({prov.get('instance_match')!r}). Scoping is refusing everything, so the demotion "
        f"asserted above proves nothing."
    )


# ---------------------------------------------------------------------------------------
# CASE 3 — two in-domain claimants
# ---------------------------------------------------------------------------------------

def test_TWO_IN_DOMAIN_CLAIMANTS_ABSTAIN_AS_AN_ASK(monkeypatch):
    """THE SEAL for case 3. Both are in the asked domain; neither is wrong; do not pick."""
    resolvers = [
        {"provider": "engine-fin", "endpoint_url": "http://f", "timeout_s": None,
         "domains": ["PROGRAM_FINANCE"]},
        {"provider": "engine-cost", "endpoint_url": "http://c", "timeout_s": None,
         "domains": ["PROGRAM_FINANCE"]},
    ]
    outcomes = [
        _Outcome("engine-fin", [_Cand("meridian", _FIN, "Notional Program Meridian", 0.9, "engine-fin")]),
        _Outcome("engine-cost", [_Cand("vermilion", _COST, "Notional Production Program Vermilion", 0.533, "engine-cost")]),
    ]
    subject, prov = _run(monkeypatch, resolvers=resolvers, outcomes=outcomes,
                         asked=["PROGRAM_FINANCE"])
    assert subject is None, f"picked {subject!r} instead of asking — by score, i.e. by tokeniser accident"
    assert prov.get("instance_match") == "ambiguous_in_domain", \
        f"abstained as {prov.get('instance_match')!r} rather than naming the ambiguity"
    opts = prov.get("instance_ambiguous_options") or []
    assert len(opts) >= 2, (
        f"the ask carries {len(opts)} option(s). A refusal that withholds the competing "
        f"readings is a dead end wearing a refusal's clothes — the caller cannot form the "
        f"question 'the finance program or the cost program?'"
    )
    providers = {o[0] for o in opts}
    assert {"engine-fin", "engine-cost"} <= providers, f"options name only {providers}"


def test_ONE_in_domain_claimant_is_not_an_ask(monkeypatch):
    """THE CONTROL for case 3. A single claimant must still resolve — ambiguity is two."""
    resolvers = [{"provider": "engine-fin", "endpoint_url": "http://f",
                  "timeout_s": None, "domains": ["PROGRAM_FINANCE"]}]
    outcomes = [_Outcome("engine-fin", [
        _Cand("meridian", _FIN, "Notional Program Meridian", 0.9, "engine-fin")])]
    subject, prov = _run(monkeypatch, resolvers=resolvers, outcomes=outcomes,
                         asked=["PROGRAM_FINANCE"])
    assert prov.get("instance_match") != "ambiguous_in_domain", (
        "CONTROL FAILED: a single claimant was reported ambiguous, so the ask fires on "
        "anything and the seal above cannot tell a real collision from normal operation"
    )


# ---------------------------------------------------------------------------------------
# THE THIRD STATE — undeclared is not empty
# ---------------------------------------------------------------------------------------

def test_a_provider_declaring_NO_domains_stays_UNSCOPED(monkeypatch):
    """`None` is not `[]`. Demoting an undeclared provider invents a boundary nobody asserted."""
    resolvers = [{"provider": "engine-legacy", "endpoint_url": "http://l",
                  "timeout_s": None, "domains": []}]
    outcomes = [_Outcome("engine-legacy", [
        _Cand("x", _FIN, "Notional Program Meridian", 1.0, "engine-legacy")])]
    subject, prov = _run(monkeypatch, resolvers=resolvers, outcomes=outcomes,
                         asked=["PROGRAM_FINANCE"])
    assert not (prov.get("instance_out_of_domain_demoted") or []), (
        "a provider with NO declared domains was demoted. Absence of a declaration is not "
        "evidence of a boundary — it is a third state, and it is logged by name at discovery "
        "rather than guessed at here."
    )
    assert subject is not None, "the unscoped provider's answer was dropped"


def test_the_unscoped_provider_is_LOGGED_BY_NAME_at_discovery(capsys, monkeypatch):
    """The lint that lets the unscoped list be driven to zero."""
    rows = [{"endpoint_url": "http://l", "provider": "engine-legacy", "timeout_s": None,
             "domains": []},
            {"endpoint_url": "http://f", "provider": "engine-fin", "timeout_s": None,
             "domains": ["PROGRAM_FINANCE"]}]

    class _Sess:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def run(self, *a, **k): return type("R", (), {"data": lambda _s: rows})()

    monkeypatch.setattr(main, "_NEO4J_DRIVER", type("D", (), {"session": lambda _s: _Sess()})())
    monkeypatch.setattr(main, "_INSTANCE_RESOLVERS_CACHE", None)
    main._discover_instance_resolvers(refresh=True)
    out = capsys.readouterr().out
    assert "UNSCOPED" in out and "engine-legacy" in out, (
        f"discovery did not name the unscoped provider; a list nobody can see cannot be "
        f"driven to zero. got: {out!r}"
    )
    # Assert on the UNSCOPED LINE, not on everything following the word. The first cut split
    # the whole capture at "UNSCOPED" and swept up the general "Discovered N providers: ..."
    # listing that comes after it — which names every provider, declared ones included. The
    # assertion was on a neighbour of the claim rather than on the claim.
    unscoped_line = next(line for line in out.splitlines() if "UNSCOPED" in line)
    assert "engine-fin" not in unscoped_line, \
        f"a declared provider was reported as unscoped: {unscoped_line!r}"
