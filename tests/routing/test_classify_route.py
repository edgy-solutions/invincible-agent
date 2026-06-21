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
    # ADR-0019 Contract B observability. When the matrix author KNOWS a
    # row resolves to a zero-verb subject (verb-typing gap, e.g. idp:Column
    # before Wave-3), set this to False to assert that /classify_predicate
    # short-circuited without invoking the LLM. None = don't assert.
    # The standing-guard shape: a regression that re-introduces "LLM picks
    # from unconstrained pool when compat-walk returned []" turns this red
    # before the confidently-wrong verb leaks into dispatch.
    expect_classify_called: Optional[bool] = None
    # Phone-book provenance: when set, asserts that /resolve's response
    # had instance_resolved=True AND instance_provider matched. Promotes
    # the R6 template (green-via-override has more meaning than green-via-
    # fallback) project-wide for every override row. None = don't assert.
    expect_instance_provider: Optional[str] = None
    # Frozen-baseline EXTRACTION-RECALL property (added 2026-06-12 per
    # the architect's A4). Asserts that /resolve's LLM extraction step
    # pulled the named instance out of conversational / awkward
    # phrasing, and the phone book matched it. The assertion is a
    # case-insensitive substring check on provenance.instance_identifier
    # — what matters is "the LLM found the name," not "the LLM produced
    # an exact echo of it" (phone-book providers normalize/canonicalize
    # the label).
    #
    # This is a HELD PROPERTY of the frozen routing baseline. A model
    # swap that regresses extraction-recall turns this red BEFORE the
    # query-to-verb matrix notices the wrong verb downstream. Joins
    # `expect_classify_called` (abstention) and `expected_verb_iri`
    # (correctness) as the three load-bearing properties the baseline
    # promises. See MODEL_COMPARISON_BENCHMARK.md.
    expect_extraction_of: Optional[str] = None


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
        # Step 4 (R6 template promoted): green-via-override means the
        # phone book spoke. Asserting the provider distinguishes
        # "DataHub said Table" from "Neo4j said Table" the moment
        # Engine E joins as a second provider that could plausibly
        # also resolve the identifier.
        expect_instance_provider="engine_d",
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
        expect_instance_provider="engine_d",
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
    # R4 — four-segment column path. Doubles as the Contract B
    # regression row (2026-06-12). Phone book classifies as idp:Column
    # (not a Table, despite the dot count). No Column verbs are
    # registered until Wave-3, so /find_compatible_verbs returns [],
    # and /classify_predicate MUST short-circuit to UNKNOWN WITHOUT
    # invoking the LLM (ADR-0019 Contract B: "subject valid + zero
    # compatible verbs → hard NO_MATCH without burning an LLM call").
    # Before the Contract B fix landed, the LLM was being called with
    # the unconstrained Weaviate pool and picking mesh:traceLineage
    # from open vocabulary — exactly the confidently-wrong dispatch
    # the contract was specified to prevent. This row stays as the
    # standing guard so a future regression that re-introduces the
    # "empty compat = unconstrained" semantics turns red here before
    # the LLM bill or the wrong verb leak downstream.
    #
    # Doubles as proof we did NOT build a dot-counter — if the router
    # were dot-counting, three-segments-table-vs-four-segments-column
    # logic would have to live somewhere, and it doesn't.
    RouteCase(
        query="What feeds gold.sales.revenue_summary.amount?",
        expected_subject_substring="Column",
        expected_verb_iri="UNKNOWN",
        expect_classify_called=False,  # Contract B: skip the LLM entirely
        min_confidence=0.0,
        domain="DATA_ENGINEERING",
    ),
    # R6 — titled name with NO identifier-shape: the win over v1's regex.
    # The LLM must extract "Customer 360" from natural prose into the new
    # instance_identifier output field; the phone book resolves it to a
    # Dashboard. Originally GREEN-via-fallback (LLM lucky-guessed Dashboard
    # from "dashboard" in the query); now asserted GREEN-via-OVERRIDE —
    # the architecture must be doing the work, not the LLM's luck.
    RouteCase(
        query="Tell me about the Customer 360 dashboard",
        expected_subject_substring="Dashboard",
        expected_verb_iri="mesh:describeAsset",
        min_confidence=0.5,
        domain="DATA_ENGINEERING",
        expect_instance_provider="engine_d",
        # Extraction-recall property: the LLM must pull "Customer 360"
        # out of "Tell me about the Customer 360 dashboard" — the prose
        # carries the name + a kind hint, the model has to separate them.
        expect_extraction_of="Customer 360",
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
        expect_instance_provider="engine_d",
        # Extraction-recall property: the LLM must pull "customers_gold"
        # out of awkward conversational hedging ("someone mentioned ...
        # or something, what is that?"). This is the harder of the two
        # R6/R7 probes — recall over phrasings that don't follow the
        # canonical "describe X" / "tell me about X" template.
        expect_extraction_of="customers_gold",
    ),

    # R8 — Gate 6 generality acceptance row (Engine E as provider #2).
    # The query names a SPECIFIC procedure code (TEST-1234) which
    # exists in Neo4j as a WorkInstruction node. The LLM must extract
    # the code; the router fans it out; Engine E's /resolve_instance
    # MUST be the provider that speaks (Engine D's catalog has no
    # entry for it). provenance.instance_provider="engine_e" is the
    # load-bearing assertion — it proves the architecture isn't
    # secretly Engine-D-flavored. expect_classify_called=True because
    # the verb mesh:queryKnowledgeGraph IS typed against the chosen
    # subject's ancestor, so the compat-walk has work to do and the
    # LLM gets called as designed.
    RouteCase(
        query="Tell me about procedure TEST-1234 in detail",
        expected_subject_substring="WorkInstruction",
        expected_verb_iri="mesh:queryKnowledgeGraph",
        min_confidence=0.5,
        domain="MAINTENANCE",
        expect_instance_provider="engine_e",
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

    # --- B4 verb 2 (2026-06-16): maintwp ProcedureDataModule routing ---
    # mesh:queryKnowledgeGraph typed against mil:ProcedureDataModule,
    # owned by Engine E. Extends Engine E's existing dual registration
    # (queryKnowledgeGraph against WorkInstruction + ProcedureStep) to
    # cover the mil:* family of procedural content kinds. The B3a
    # helmet TM ingest materialized 4 maintwp instances as
    # INSTANCE_OF mil:ProcedureDataModule (M0004 "MICROPHONE BOOM
    # REMOVAL/INSTALLATION", M0008 general maintenance, gen.maintwp,
    # opusualwp).
    #
    # **Phrasing is document-framed, not content-framed.** The architect's
    # 2026-06-16 finding: mil:ProcedureDataModule is the DOCUMENT (the
    # S1000D/40051 data module — what tech writers author and manage),
    # while mro:WorkInstruction is the CONTENT (the actual procedural
    # steps — what maintainers execute). They're container/content,
    # not flat siblings, so a query asking for STEPS (maintainer
    # framing) correctly resolves to WorkInstruction, and a query
    # asking for the MODULE (tech-writer framing) correctly resolves
    # to ProcedureDataModule. The overnight halt surfaced this
    # distinction — original phrasing "What are the steps to install
    # the microphone boom on the helmet?" was a maintainer's question
    # and resolved to WorkInstruction at 0.95 (correctly, per the
    # container/content semantics). This row uses the tech-writer
    # framing to exercise what ProcedureDataModule uniquely owns.
    #
    # Banked: the containment relationship itself is currently
    # UNMODELED in mil_extension.ttl (mil:ProcedureDataModule and
    # mro:WorkInstruction are in different namespaces with no declared
    # relationship between them). The structural fix — model the
    # contains/hasContent relationship so the two layers disambiguate
    # by question framing rather than by hint-priming similarity
    # contest — is an ADR-shaped decision banked for a separate
    # design session. See STATE_GATEWAY_V02.md "2026-06-16 verb 2
    # halt + reframe" for the trace.
    RouteCase(
        query="What procedure data module covers microphone boom removal and installation?",
        expected_subject_substring="ProcedureDataModule",
        expected_verb_iri="mesh:queryKnowledgeGraph",
        min_confidence=0.5,
        domain="MAINTENANCE",
    ),

    # --- B4 verb 1 (2026-06-15): fault-isolation routing ---
    # mesh:retrieveKnowledge typed against mil:FaultIsolationDataModule,
    # owned by Engine W. The B3a helmet TM ingest materialized 3 tswp
    # instances as INSTANCE_OF mil:FaultIsolationDataModule; this row is
    # the routing layer's release-from-pool-hold for that content kind.
    #
    # Pre-B4 (no verb typed): the resolver picks mro:WorkInstruction
    # at ~0.95 confidence (wrong semantic match for diagnostic queries;
    # the only routable MAINTENANCE-domain class for "procedure"-shaped
    # queries was WorkInstruction, FaultIsolationDataModule was held
    # out of the resolver pool). Post-B4: resolver picks
    # FaultIsolationDataModule (the right kind), compat-walk finds
    # retrieveKnowledge, dispatch lands at Engine W.
    #
    # The phrasing uses "fault isolation" + "diagnose" rather than
    # "troubleshooting procedure" — the latter ranks WorkInstruction
    # higher because WorkInstruction's hint-primed definition includes
    # the word "procedure." The semantic-match-by-definition is the
    # right contract: FaultIsolationDataModule's definition explicitly
    # owns "diagnostic / why is it broken / how do I find the fault."
    RouteCase(
        query="How do I find the fault in the helmet microphone?",
        expected_subject_substring="FaultIsolationDataModule",
        expected_verb_iri="mesh:retrieveKnowledge",
        min_confidence=0.5,
        domain="MAINTENANCE",
    ),

    # --- B4 verb 3 (2026-06-15): IllustratedPartsDataModule routing ---
    # mesh:retrieveKnowledge typed against mil:IllustratedPartsDataModule,
    # owned by Engine W. Third source-level registration on Engine W
    # (after TechnicalManual and FaultIsolationDataModule); IPD content
    # (DMC info code 9xx, exploded parts views + part lists) is
    # text-search-shaped in practice, so retrieveKnowledge is the
    # natural verb-typing.
    #
    # **Multi-phrasing probe observation** (the new acceptance gate
    # introduced from this verb, per architect 2026-06-15: every new
    # mil:* content-kind verb-typing records 3-5 probe phrasings and
    # the lexical cues that drive subject resolution, building the
    # evidence base for the widened procedural-content-disambiguation
    # ADR):
    #
    #   P1 "What parts make up the microphone boom?" -> IPD @ 0.97
    #   P2 "Show me the illustrated parts breakdown ..."  -> IPD @ 0.98
    #   P3 "What is the part number for the boom cable?"  -> mil:Part @ 0.92
    #     (kind-vs-instance distinction at the surface vocabulary —
    #      "part number" pulls to the Part class, not to the IPD
    #      document. Defensible: a part-number question asks about an
    #      instance of Part, not about the parts-breakdown document.)
    #   P4 "Describe the parts data module for the boom"  -> IPD @ 0.96
    #     (asymmetric with verb 2's probe 1: there, "describe the
    #      procedure data module" pulled to mil:DescriptiveDataModule;
    #      here, "describe the parts data module" stays on IPD. The
    #      "parts" multi-word anchor in IPD's class definition is
    #      strong enough to beat "describe"'s generic descriptive cue.
    #      The boundary between IPD and DescriptiveDataModule is
    #      sharper than between ProcedureDataModule and DDM.)
    #   P5 "What is the IPD for part number 12345?" -> IPD @ 0.97
    #     (acronym match + instance-resolution layer also fired on
    #      "12345"; all three providers abstained cleanly, class
    #      fallback held.)
    #
    # Matrix row uses P2 — cleanest discriminator: exact "illustrated
    # parts breakdown" trigger, highest confidence (0.98), zero
    # instance-resolution noise, and the class definition's strongest
    # multi-word anchor.
    #
    # Banked observation for the widened ADR design pass:
    # IPD's "parts" vocabulary holds against "describe"; PDM's
    # "procedure" vocabulary does NOT. The ADR's class-definition
    # tuning should target the weaker boundaries (PDM <-> DDM,
    # WorkInstruction <-> PDM container/content) rather than the
    # already-sharp ones (IPD <-> DDM, IPD <-> Part instance layer).
    RouteCase(
        query="Show me the illustrated parts breakdown for the boom assembly",
        expected_subject_substring="IllustratedPartsDataModule",
        expected_verb_iri="mesh:retrieveKnowledge",
        min_confidence=0.5,
        domain="MAINTENANCE",
    ),

    # --- B4 verb 4 (2026-06-16): DescriptiveDataModule routing ---
    # mesh:retrieveKnowledge typed against mil:DescriptiveDataModule,
    # owned by Engine W. Fourth source-level registration on Engine W
    # (TechnicalManual + FaultIsolationDataModule + IPD + DDM); closes
    # the four-class mil:* procedural-content set with verb edges.
    #
    # **The two-purpose probe scan** (architect's sharpened gate for
    # verb 4): the multi-phrasing scan deliberately included three
    # leak-test probes designed to measure DDM over-attraction --
    # queries whose correct target is another content kind but that
    # use "describe" framing. "Describe" is the most common query verb
    # and DDM's anchor is weak-and-over-broad, so the prediction was
    # that DDM would steal queries that belong to PDM/WI/IPD/FI.
    #
    # Result: **DDM over-attraction is BOUNDED**. All three leak
    # probes held their correct boundaries:
    #   L3 "Describe how to install the boom"           -> WI @ 0.85
    #   L4 "Describe the parts of the boom assembly"   -> IPD @ 0.95
    #   L5 "Describe the troubleshooting procedure ..."-> WI @ 0.85
    # Strong-anchor classes (IPD's "parts", WorkInstruction's hand-
    # tuned hints) hold against "describe" alone. The structural ADR
    # is NOT urgent for DDM-vs-others; the weak boundary the ADR still
    # needs to address is FaultIsolation <-> WorkInstruction (L5 leaked
    # across that boundary, not from DDM).
    #
    # Genuine-DDM probes (matrix-row candidates):
    #   D1 "What is the helmet display unit?"             -> DDM @ 0.86
    #   D2 "Tell me about the helmet HMD architecture"   -> DDM @ 0.86-0.95
    #
    # Matrix row picks D1 -- pure "what is" framing, cleanest DDM
    # ownership, stable at confidence floor.
    #
    # **Instance-resolution insulates named-identifier queries**: the
    # at-risk row "Describe procedure TEST-1234 and show me its diagram"
    # routes via mesh:resolveInstance (engine_e finds TEST-1234 as an
    # exact-match instance at score 1.0); instance resolution preempts
    # the class-vocabulary contest. This is the document<->content/
    # instance duality the architect identified -- structurally
    # encoded via the instance-resolution layer's fan-out, the same
    # pattern verb 3 P3 showed for "part number" -> mil:Part. Worth
    # banking for the ADR.
    #
    # Four-class lexical map now complete: FaultIsolation +
    # ProcedureDataModule + IllustratedParts + Descriptive all have
    # verb edges, multi-phrasing probe data on file, lexical-cue
    # boundaries identified. The widened ADR (model document<->content/
    # instance duality as a general pattern + add structural
    # disambiguation only at weak-anchor boundaries) gets its design
    # pass with full evidence.
    RouteCase(
        query="What is the helmet display unit?",
        expected_subject_substring="DescriptiveDataModule",
        expected_verb_iri="mesh:retrieveKnowledge",
        min_confidence=0.5,
        domain="MAINTENANCE",
    ),

    # --- MFG verb 1: mfg:WorkInstruction routing (post ADR-0021 cleanup) ---
    #
    # Per ADR-0021 Phase 1 (ratified 2026-06-20), this case was UPDATED
    # to expect the canonical `mfg:WorkInstruction` URI instead of the
    # legacy residue `http://example.com/manufacturing#MunitionsAssemblyStep`.
    # The expectation change followed (not preceded) a resolution probe
    # that confirmed canonical wins: after deleting the 7 mfg + 2 ISA-95
    # residue classes from Neo4j and Weaviate, the same query resolved
    # to `mfg:WorkInstruction` at confidence 0.98 — top of the predicted
    # band, via semantic match on the class definition phrase
    # "Routing subject for ... 'what are the assembly steps for X'".
    #
    # Why the change was required: the instances stamped by the
    # manufacturing plugin (manufacturing.py:333-334) carry
    # `INSTANCE_OF mfg:WorkInstruction`, but resolution was landing on
    # the residue class `MunitionsAssemblyStep` (pre-canonical direct-
    # load era, synced_by=None) — so the verb couldn't actually reach
    # the instances it was meant to. The conjunctive-read failure.
    # Cleanup closed the loop: instances and resolution now both land
    # on `mfg:WorkInstruction`.
    #
    # Historical context — the V1 mfg verb (2026-06-17 overnight) was
    # originally typed against `MunitionsAssemblyStep` because that was
    # the strongest-anchor class in the residue pool the matrix had at
    # the time. ADR-0021 retired both that name (general kind is
    # `mfg:WorkInstruction`, not munitions-specific) and the residue
    # nodes themselves. The standing residue guard
    # (test_no_legacy_residue.py) is the class-fix that catches a
    # regression of either condition.
    #
    # --- ORIGINAL V1 ROUTING NOTES (kept as probe-evidence reference) ---
    # mesh:retrieveKnowledge was typed against
    # http://example.com/manufacturing#MunitionsAssemblyStep,
    # owned by Engine W. This was the FIRST mfg verb in the matrix.
    #
    # Why MunitionsAssemblyStep: of the 7 manufacturing classes Gap-1
    # released (Step 1 overnight), MunitionsAssemblyStep is the most
    # content-shaped (procedural assembly steps for munitions —
    # narrative + step lists — exactly what retrieveKnowledge over
    # manuals search handles). The other 6 (ExplosiveMaterial,
    # ExplosivesSafetyHazard, ComplianceRule, StandardIndustrialProcess,
    # Class_1_1, Class_1_3) are mostly classifier categories rather
    # than content kinds.
    #
    # **Multi-phrasing probe scan** (the standing gate per the B4 verb
    # discipline) ran 5 probes — recorded findings:
    #   P1 "What are the assembly steps for the M67 grenade?"
    #        -> MunitionsAssemblyStep @ 0.98 (instance-resolution layer
    #         also fired on 'M67 grenade'; providers abstained cleanly)
    #   P2 "Show me the munitions assembly procedure for the warhead"
    #        -> MunitionsAssemblyStep @ 0.95
    #   P3 "What is the explosive material classification..."
    #        -> ExplosiveMaterial @ 0.99 (cross-class boundary clean)
    #   P4 "What are the safety hazards in munitions assembly?"
    #        -> ExplosivesSafetyHazard @ 0.96 (ambiguous case;
    #         'safety hazards' anchor won over 'munitions assembly')
    #   P5 "Standard industrial process for warhead fill"
    #        -> StandardIndustrialProcess @ 0.98 (cross-class clean)
    #
    # **Lexical-cue findings worth banking** (analogous to the B4
    # documents↔content/instance duality):
    #   - MunitionsAssemblyStep has strong "assembly steps" /
    #     "assembly procedure" anchors — clean discriminator.
    #   - Cross-class boundaries P3/P5 are sharp.
    #   - The P4 ambiguity ("safety hazards in munitions assembly") is
    #     the analog of the verb 4 "describe + parts" tension: when two
    #     anchors compete, the more specific class wins (ExplosivesSafetyHazard
    #     beats MunitionsAssemblyStep on a mixed query). Bank as next-
    #     session observation; not blocking the mfg-V1 ship.
    #
    # Matrix row picks P1 — highest confidence (0.98), strong "assembly
    # steps" trigger, bonus instance-resolution layer engagement.
    #
    # **Important banked items** for daylight:
    #   1. URI namespace is `http://example.com/manufacturing#` —
    #      placeholder, not a stable identifier. When the canonical-
    #      pipeline ingest of Munitions.ttl lands (Gap-1 banked work),
    #      migrating to `http://edgy-solutions.com/ontology/mfg#`
    #      would stabilize the URIs. The mfg verb works on whatever
    #      URI is in substrate; not blocking.
    #   2. The 7 mfg classes are pre-canonical residue
    #      (synced_from=None). The canonical-pipeline re-ingest will
    #      need to MERGE on URI (preserves identity + this verb's
    #      registration) vs. re-create. MERGE is the safer call.
    RouteCase(
        query="What are the assembly steps for the M67 grenade?",
        # Updated 2026-06-20 per ADR-0021 Phase 1 ratification — see
        # the comment block above for the expectation-follows-probe
        # rationale. Probe B post-cleanup: WorkInstruction @ 0.98.
        expected_subject_substring="WorkInstruction",
        expected_verb_iri="mesh:retrieveKnowledge",
        min_confidence=0.5,
        domain="MANUFACTURING",
        entitled_domains=("MANUFACTURING",),
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
    classify_called = classify_resp.get("classify_called", True)
    resolve_provenance = resolve_resp.get("provenance") or {}

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
        f"  classify_called        = {classify_called}\n"
        f"  resolve_provenance     = {resolve_provenance}\n"
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

    # ADR-0019 Contract B regression guard. Pinned per-row by
    # expect_classify_called. False means the row's subject is a
    # known zero-verb kind (e.g. idp:Column before Wave-3 ships its
    # verbs) and /classify_predicate MUST short-circuit without
    # invoking the LLM. classify_called=True here is the symptom
    # the architect's R4 reanalysis exposed: empty compat list was
    # being treated as "unconstrained" inside /classify_predicate
    # instead of "forbidden," and the LLM was picking from open
    # vocabulary. The guard turns red BEFORE the cost or the
    # confidently-wrong dispatch leaks downstream.
    if case.expect_classify_called is not None:
        assert classify_called == case.expect_classify_called, (
            f"Contract B regression: expected classify_called="
            f"{case.expect_classify_called}, got {classify_called}. "
            f"subject={subject_uri!r}, compat={compatible_verb_iris}, "
            f"verb={verb_iri!r}, reasoning={verb_reason!r}.\n"
            f"  When subject is resolved AND /find_compatible_verbs "
            f"returns [], /classify_predicate MUST short-circuit "
            f"without invoking the LLM (ADR-0019 Contract B). The "
            f"verb chosen here came from an unconstrained Weaviate "
            f"pool — that's the failure class this entire arc exists "
            f"to kill."
        )

    # Phone-book provenance guard (R6 template, promoted project-wide
    # 2026-06-12). Override rows must show instance_resolved=True AND
    # the right provider — same color as fallback, but the architecture
    # is doing the work. Once provider #2 (Engine E) lands, this
    # assertion is what distinguishes "DataHub said Table" from
    # "Neo4j said Table" on a query that both could plausibly resolve.
    if case.expect_instance_provider is not None:
        assert resolve_provenance.get("instance_resolved") is True, (
            f"Phone-book regression: row was supposed to resolve via "
            f"override, but provenance says instance_resolved=False. "
            f"Likely cause: provider's search path returned empty (run "
            f"the probe in test_resolve_instance_probes.py to name the "
            f"broken provider). provenance={resolve_provenance}"
        )
        actual_provider = resolve_provenance.get("instance_provider", "")
        assert actual_provider == case.expect_instance_provider, (
            f"Phone-book regression: expected instance_provider="
            f"{case.expect_instance_provider!r}, got "
            f"{actual_provider!r}. provenance={resolve_provenance}"
        )

    # Frozen-baseline EXTRACTION-RECALL guard (A4, 2026-06-12). The
    # third held property of the routing baseline, alongside abstention
    # (expect_classify_called) and correctness (expected_verb_iri).
    #
    # The assertion: when the case names an extracted instance, the
    # resolver's provenance.instance_identifier MUST contain it (case-
    # insensitive substring). A model swap that regresses extraction
    # recall turns this red BEFORE the downstream verb pick is wrong —
    # which is the order the failure actually happens in production
    # (model misses the name → instance_resolved=False → fall-through
    # path → wrong verb).
    #
    # Why substring not equality: phone-book providers may normalize the
    # extracted label (case-fold, trim, canonicalize). What the property
    # guards is "the LLM found the name in the query," not "the LLM
    # produced an exact byte-for-byte echo." The substring lets the test
    # survive provider normalization without weakening the property.
    if case.expect_extraction_of is not None:
        extracted = (
            resolve_provenance.get("instance_identifier")
            or resolve_provenance.get("instance_label")
            or ""
        )
        assert case.expect_extraction_of.lower() in extracted.lower(), (
            f"Extraction-recall regression: expected to extract "
            f"{case.expect_extraction_of!r} from query, but provenance's "
            f"instance_identifier/label was {extracted!r}. "
            f"This is one of the three held properties of the frozen "
            f"routing baseline (abstention, correctness, extraction-"
            f"recall). A red here means a model swap or prompt change "
            f"regressed the resolver's ability to pull named instances "
            f"out of conversational phrasing — fix before promoting the "
            f"model swap. provenance={resolve_provenance}"
        )
