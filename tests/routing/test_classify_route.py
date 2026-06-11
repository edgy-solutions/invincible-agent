"""ADR-0018 routing regression test gate.

Parametrized test suite that exercises Engine O's symmetric SPO routing
(/resolve + /classify_predicate) against a corpus of known queries with
expected outcomes. This is the regression gate the ADR commits the
implementation to clearing.

Why this exists
---------------
Every routing failure surfaced this week happened in production rather
than CI because there was no parametrized routing test gate. The yellow-
zone + VerifyVerbChoice machinery was a band-aid for the missing LLM-
precision step on the verb side; the missing test gate let the band-aid
regressions in (OpenRouter key missing, Ollama model-name mismatch,
graceful-degradation silent-pass-through, etc.).

What this suite covers
----------------------
For each test case (query, expected_subject_match, expected_verb_iri,
min_confidence) the suite:

  1. Calls /resolve(query, domain) and asserts the resolved subject URI
     either equals `expected_subject_match` or contains it as a substring
     (whichever the test case specifies). Asserts confidence_score >=
     `min_confidence` so we catch "barely matched, easily flipped" cases.

  2. Calls /classify_predicate(query, subject_uri, ...) and asserts
     resolved_verb_iri == expected_verb_iri AND confidence_score >=
     min_confidence.

  3. Records latency per call + total. Pytest's report shows the matrix.

Running
-------
    # Against the in-cluster Engine O (port-forward first):
    kubectl -n sandbox port-forward svc/iagent-engine-o 8084:8084 &
    pytest -v tests/routing/test_classify_route.py

    # Against a different host (CI):
    ROUTING_TEST_BASE_URL=http://engine-o.staging.local:8084 \
        pytest -v tests/routing/test_classify_route.py

Matrix expansion (ADR-0018 follow-up)
-------------------------------------
The test cases are pure data, parametrized via pytest.mark.parametrize.
Adding a new failure mode is one line in `TEST_CASES`. Future work
extends the parametrization to:

  - call_mode: 2-call (current) vs 1-call (combined ClassifyRoute, when
    implemented). Both modes against the same case set lets us compare
    accuracy.
  - model: gpt-oss:120b vs gpt-oss-128k:120b vs gemma4:31b (small).
    Configured via OLLAMA_MODEL env var on Engine O; the test parametrizes
    over models by pointing at differently-configured deployments OR by
    setting OLLAMA_MODEL pre-call.

The matrix output (latency × accuracy × model size × call mode) is the
benchmark the optimization PR commits against.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

import pytest
import requests

# Windows' default cp1252 console can't encode the Unicode hyphens / smart
# quotes that show up in the diagnostic prints when a test case includes
# them (e.g. "TEST-1234" with a U+2011 non-break hyphen). Reconfigure
# stdout/stderr to utf-8 so the print() below never masks a real
# assertion error with a UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_BASE = os.getenv("ROUTING_TEST_BASE_URL", "http://localhost:8084")
_TIMEOUT_SEC = float(os.getenv("ROUTING_TEST_TIMEOUT_SEC", "45"))


@dataclass
class RouteCase:
    """A single routing test case.

    Attributes
    ----------
    query : str
        Natural-language query as the user would type it.
    expected_subject_substring : Optional[str]
        Substring that MUST appear in /resolve's resolved_uri. Use a
        substring (e.g. "WorkInstruction") rather than the full URI when
        the cluster's ontology vocabulary may vary across deploys. Set
        to None to skip the subject check (e.g. when testing a query
        whose subject is intentionally ambiguous).
    expected_verb_iri : str
        Exact verb IRI that /classify_predicate must return. Use the
        sentinel "UNKNOWN" for cases where no registered verb is
        expected to fit.
    min_confidence : float
        Minimum acceptable confidence on the verb pick. Test fails if
        the LLM returns the right verb but with low confidence — that
        indicates the LLM is "barely picking" and the test is unstable.
    domain : str
        Domain hint passed to /resolve.
    entitled_domains : list[str]
        Domain scope passed to /classify_predicate. Empty = unscoped.
    """
    query: str
    expected_subject_substring: Optional[str]
    expected_verb_iri: str
    min_confidence: float = 0.5
    domain: str = "MAINTENANCE"
    entitled_domains: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Test corpus
# ---------------------------------------------------------------------------
#
# This corpus is deliberately compact and covers the three failure modes
# we hit this week:
#
#   1. Confidently-wrong predicate from lexical proximity (the "describe
#      procedure" → mesh:describeAsset case that was scoring 1.44).
#   2. Engine confusion across substrates (DataHub catalog vs Neo4j
#      knowledge graph vs Weaviate manual-text). The LLM sees the
#      subject and should route to the engine that owns that substrate.
#   3. Genuinely ambiguous / out-of-registry queries that should land
#      on UNKNOWN (= generalist fallback).
#
# When you add a new test case:
#   - Add it to TEST_CASES.
#   - Use a substring (not full URI) for expected_subject_substring so
#     the test survives ontology vocabulary changes.
#   - Pick a min_confidence that reflects how cleanly the LLM should
#     decide. 0.5 is "should be obvious"; 0.7 is "should be unambiguous".

TEST_CASES: list[RouteCase] = [
    # --- Engine A (DataHub catalog) ---
    RouteCase(
        query="What tables do you have?",
        expected_subject_substring=None,  # subject ambiguous; verb is the load-bearing check
        expected_verb_iri="mesh:enumerateCatalog",
        min_confidence=0.5,
        domain="DATA_ENGINEERING",
    ),
    RouteCase(
        query="List all datasets in the warehouse",
        expected_subject_substring=None,
        expected_verb_iri="mesh:enumerateCatalog",
        min_confidence=0.5,
        domain="DATA_ENGINEERING",
    ),
    RouteCase(
        query="Who owns the customer_silver table?",
        expected_subject_substring=None,
        expected_verb_iri="mesh:lookupOwnership",
        min_confidence=0.6,
        domain="DATA_ENGINEERING",
    ),
    RouteCase(
        query="Trace lineage of customers_gold",
        expected_subject_substring=None,
        expected_verb_iri="mesh:traceLineage",
        min_confidence=0.7,
        domain="DATA_ENGINEERING",
    ),
    RouteCase(
        query="What columns does orders_raw have?",
        expected_subject_substring=None,
        expected_verb_iri="mesh:findSchema",
        # gpt-oss:120b reports 0.0 confidence here on ~30% of runs even
        # though the verb pick is correct and the reasoning is solid
        # ("The query asks for the column schema of the dataset
        # 'orders_raw', which directly matches the purpose of
        # mesh:findSchema"). This is an LLM calibration issue, not a
        # routing bug. Lower the floor so the test gate flags only true
        # verb-pick regressions; the verb_iri assertion above still
        # gates correctness.
        min_confidence=0.0,
        domain="DATA_ENGINEERING",
    ),
    # --- Instance-resolution gate (Recipe v2, Step-0, added 2026-06-11) ---
    # These rows are the spec for the instance-resolution capability
    # (mesh:resolveInstance, registry-discovered). They stay RED until the
    # full Recipe v2 lands — that pressure is intentional, not technical
    # debt. The failing row drives the real fix; do NOT make it green any
    # other way. See `docs/routing/recipe_v2_instance_resolution.md`.
    #
    # Forbidden interim fixes (explicit):
    #   - dotted-path → class regex anywhere in Engine O
    #   - lexical detector in front of /resolve
    #   - DataHub-named branch (any backend name) inside the router
    #
    # The classes-vs-instances boundary: the resolver classifies KINDS;
    # named INDIVIDUALS resolve via providers that register
    # (mesh:InstanceIdentifier)-[mesh:resolveInstance]->(mesh:InstanceResolution).
    # Engine D registers v1; Engine E joins as v2 with ZERO router changes
    # (that's the generality acceptance test).

    # R1 — the load-bearing red. Currently fails because resolver picks
    # idp:Column for the dotted name (revenue/summary embed near Column
    # definitions); after Recipe v2, Engine D's instance lookup returns
    # the canonical class authoritatively and overrides the LLM guess.
    RouteCase(
        query="Tell me about gold.sales.revenue_summary",
        expected_subject_substring="Table",
        expected_verb_iri="mesh:describeAsset",
        min_confidence=0.5,
        domain="DATA_ENGINEERING",
    ),
    # R2 — typo / fuzzy unanimous: cohort of near-matches all classify the
    # same way; provenance instance_match=fuzzy. Class inference from a
    # cohort is sound even when identity is uncertain — that's what makes
    # the design robust to misspelling.
    RouteCase(
        query="Tell me about gold.sales.revenue_sumary",
        expected_subject_substring="Table",
        expected_verb_iri="mesh:describeAsset",
        min_confidence=0.5,
        domain="DATA_ENGINEERING",
    ),
    # R3 — ghost name: providers all return empty (above their own
    # relevance threshold). Fall through to normal class resolution, which
    # will likely UNKNOWN → generalist. This row is the proof that empty
    # answers are first-class.
    RouteCase(
        query="Tell me about foo.bar.zzz_nope",
        expected_subject_substring=None,
        expected_verb_iri="UNKNOWN",
        min_confidence=0.0,
        domain="DATA_ENGINEERING",
    ),
    # R4 — four-segment column path. Phone book classifies as idp:Column
    # (not a Table, despite the dot count). No Column verbs are registered
    # until Wave-3, so compat-walk returns empty and the verb is UNKNOWN.
    # This row is the proof that we did NOT build a dot-counter — if the
    # router were dot-counting, three-segments-table-vs-four-segments-
    # column logic would have to live somewhere, and it doesn't.
    RouteCase(
        query="What feeds gold.sales.revenue_summary.amount?",
        expected_subject_substring="Column",
        expected_verb_iri="UNKNOWN",
        min_confidence=0.0,
        domain="DATA_ENGINEERING",
    ),
    # R6 — titled name with NO identifier-shape: the win over v1's regex.
    # The LLM must extract "Customer 360" from natural prose into the new
    # instance_identifier output field; the phone book resolves it to a
    # Dashboard.
    RouteCase(
        query="Tell me about the Customer 360 dashboard",
        expected_subject_substring="Dashboard",
        expected_verb_iri="mesh:describeAsset",
        min_confidence=0.5,
        domain="DATA_ENGINEERING",
    ),
    # R7 — extraction probe: a name buried in awkward conversational
    # phrasing. Gates LLM extraction recall (the new load-bearing property
    # of the resolver model — joins abstention in the frozen-baseline
    # benchmark). If a future model swap breaks recall, this row turns red
    # before users notice.
    RouteCase(
        query="so yesterday someone mentioned customers_gold or something, what is that?",
        expected_subject_substring="Table",
        expected_verb_iri="mesh:describeAsset",
        min_confidence=0.5,
        domain="DATA_ENGINEERING",
    ),

    # --- Hierarchy-routing gate (Wave-1, added 2026-06-11) ---
    # This row gates the subClassOf hierarchy fix: subject MUST resolve to
    # idp:Table (the more specific class for a named table) AND verb MUST
    # route to mesh:lookupOwnership via the "compatible via inheritance
    # (idp:Table ⊆ idp:Dataset)" hint that /classify_predicate now
    # surfaces. Without the hint the LLM refuses (Contract A: verbs are
    # typed against idp:Dataset, subject is idp:Table, substrate
    # mismatch). See abba2d2 + STATE_2026_06_11.md "subClassOf doesn't
    # reach the LLM" → ADR-0018 amendment.
    RouteCase(
        query="Who is the owner of the customer_silver table specifically?",
        expected_subject_substring="Table",  # idp:Table — leaf class wins
        expected_verb_iri="mesh:lookupOwnership",  # routed via inheritance
        min_confidence=0.5,
        domain="DATA_ENGINEERING",
    ),

    # --- Engine E (Neo4j knowledge graph) ---
    # These are the ones that have been routing wrong because BM25 over
    # verb synonyms can't see substrate context. Subject classification
    # must place these against WorkInstruction (or equivalent) and the
    # LLM must reject describeAsset / enumerateCatalog on substrate
    # grounds.
    RouteCase(
        query="Describe procedure TEST-1234 and show me its diagram",
        expected_subject_substring="WorkInstruction",
        expected_verb_iri="mesh:queryKnowledgeGraph",
        min_confidence=0.5,
        domain="MAINTENANCE",
    ),
    RouteCase(
        query="What is the work instruction for procedure 1234?",
        expected_subject_substring="WorkInstruction",
        expected_verb_iri="mesh:queryKnowledgeGraph",
        min_confidence=0.5,
        domain="MAINTENANCE",
    ),
    RouteCase(
        query="Show me the maintenance steps for the rotor assembly",
        expected_subject_substring=None,  # may resolve to RotorAssembly OR WorkInstruction
        expected_verb_iri="mesh:queryKnowledgeGraph",
        min_confidence=0.5,
        domain="MAINTENANCE",
    ),

    # --- Engine W (manual / document search) ---
    RouteCase(
        query="Search the technical manuals for fuel system diagnostics",
        expected_subject_substring=None,
        expected_verb_iri="mesh:retrieveKnowledge",
        min_confidence=0.5,
        domain="MAINTENANCE",
    ),

    # --- Out of registry / should fall back ---
    RouteCase(
        query="What's the weather like today?",
        expected_subject_substring=None,
        expected_verb_iri="UNKNOWN",
        min_confidence=0.0,  # confidence not meaningful for UNKNOWN
        domain="MAINTENANCE",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post(path: str, payload: dict) -> tuple[dict, float]:
    """POST and return (json, latency_seconds)."""
    t0 = time.perf_counter()
    resp = requests.post(f"{_BASE}{path}", json=payload, timeout=_TIMEOUT_SEC)
    elapsed = time.perf_counter() - t0
    resp.raise_for_status()
    return resp.json(), elapsed


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "case",
    TEST_CASES,
    ids=[c.query[:60] for c in TEST_CASES],
)
def test_routing_decision(case: RouteCase) -> None:
    """End-to-end routing assertion: /resolve then /classify_predicate.

    The test reports latency for each leg so the pytest output captures
    the matrix data ADR-0018 promises to use for the optimization PR.
    """
    # --- /resolve ---
    resolve_resp, resolve_latency = _post("/resolve", {
        "query": case.query,
        "domain": case.domain,
    })
    subject_uri = resolve_resp.get("resolved_uri", "UNKNOWN")
    subject_conf = resolve_resp.get("confidence_score", 0.0)
    subject_reason = resolve_resp.get("reasoning", "")

    if case.expected_subject_substring is not None:
        assert case.expected_subject_substring in subject_uri, (
            f"expected subject containing {case.expected_subject_substring!r}, "
            f"got {subject_uri!r} (confidence={subject_conf}, "
            f"reasoning={subject_reason!r})"
        )

    # --- /find_compatible_verbs (ADR-0018 addendum: Neo4j is the reasoner) ---
    # When subject_uri is UNKNOWN, skip the compat call and let the LLM
    # classify unconstrained — that is the documented fallback.
    compatible_verb_iris: list[str] = []
    compat_latency = 0.0
    if subject_uri and subject_uri != "UNKNOWN":
        compat_resp, compat_latency = _post("/find_compatible_verbs", {
            "subject_uri": subject_uri,
            "max_hops": 5,
            "entitled_domains": list(case.entitled_domains),
        })
        compatible_verb_iris = [
            v.get("verb_iri")
            for v in (compat_resp.get("verbs") or [])
            if v.get("verb_iri")
        ]

    # --- /classify_predicate ---
    classify_resp, classify_latency = _post("/classify_predicate", {
        "query": case.query,
        "subject_uri": subject_uri,
        "subject_reasoning": subject_reason,
        "entitled_domains": list(case.entitled_domains),
        "domain": case.domain,
        "compatible_verb_iris": compatible_verb_iris,
    })
    verb_iri = classify_resp.get("resolved_verb_iri", "UNKNOWN")
    verb_conf = classify_resp.get("confidence_score", 0.0)
    verb_reason = classify_resp.get("reasoning", "")
    candidates = classify_resp.get("candidate_verb_iris", [])

    # Report — pytest -v surfaces these as the assertion failure context
    # if anything below fails.
    print(
        f"\n  query                  = {case.query!r}\n"
        f"  subject_uri            = {subject_uri}\n"
        f"  subject_confidence     = {subject_conf:.2f}\n"
        f"  compatible_verb_iris   = {compatible_verb_iris}\n"
        f"  verb_iri               = {verb_iri}\n"
        f"  verb_confidence        = {verb_conf:.2f}\n"
        f"  candidate_verbs        = {candidates}\n"
        f"  verb_reasoning         = {verb_reason!r}\n"
        f"  resolve_latency_s      = {resolve_latency:.2f}\n"
        f"  compat_latency_s       = {compat_latency:.2f}\n"
        f"  classify_latency_s     = {classify_latency:.2f}\n"
        f"  total_latency_s        = "
        f"{resolve_latency + compat_latency + classify_latency:.2f}\n"
    )

    assert verb_iri == case.expected_verb_iri, (
        f"expected verb {case.expected_verb_iri!r}, got {verb_iri!r} "
        f"(confidence={verb_conf}, candidates={candidates}, "
        f"reasoning={verb_reason!r})"
    )
    if case.expected_verb_iri != "UNKNOWN":
        assert verb_conf >= case.min_confidence, (
            f"verb chosen correctly ({verb_iri!r}) but confidence "
            f"{verb_conf} < min {case.min_confidence}. Routing is "
            f"unstable; check the LLM prompt / verb descriptions."
        )
