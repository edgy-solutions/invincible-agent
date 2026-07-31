"""Tier-3 fix — URN propagation contract test (2026-06-16).

Locks in the three-layer URN propagation contract added by the
Tier-3 fix:

  /resolve.provenance.instance_id
       -> _resolve_subject returns it as the 4th tuple element
       -> _classify_route puts it in telemetry["subject_instance_id"]
       -> dispatch payload includes it as `resolved_instance_id`

And the dual presentation contract in Engine DA's prompt:

  resolved_instance_id non-empty -> prompt instructs to use that EXACT URN
  resolved_instance_id empty      -> prompt instructs honest not-found

The bug this guards against: any of these layers silently dropping
the URN (the pre-fix behavior), which forced Engine DA's smolagent
into fabricating a URN from training data or schema-map context.

Acceptance B from the architect's fix recipe — "DA must not fabricate
when the real URN is absent" — is structurally enforced here: when
`resolved_instance_id` is empty, the prompt explicitly forbids
inventing a URN and forbids calling `query_datahub_asset` with one.
The smolagent's compliance with the prompt is a separate live-test
concern; this test pins the prompt to the right shape.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest


_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ---------------------------------------------------------------------------
# Stub the heavy import chain (shared with test_routing_fallback.py shape)
# ---------------------------------------------------------------------------
def _install_stubs():
    if "baml_client" not in sys.modules:
        bc = types.ModuleType("baml_client")
        bc.b = object()
        sys.modules["baml_client"] = bc
    if "dagster" not in sys.modules:
        d = types.ModuleType("dagster")

        class _Cfg:
            def __init__(self, **kwargs):
                for name, default in self.__class__.__dict__.items():
                    if name.startswith("_") or callable(default):
                        continue
                    setattr(self, name, default)
                for k, v in kwargs.items():
                    setattr(self, k, v)

        d.Config = _Cfg
        d.In = lambda *a, **k: None
        d.Out = lambda *a, **k: None
        d.DynamicOut = lambda *a, **k: None
        d.DynamicOutput = lambda *a, **k: None
        d.Output = lambda *a, **k: None
        d.MetadataValue = type("MetadataValue", (), {
            "text": staticmethod(lambda s: s),
            "json": staticmethod(lambda j: j),
        })
        d.AssetMaterialization = lambda *a, **k: None
        d.op = lambda *a, **k: (lambda f: f)
        d.job = lambda *a, **k: (lambda f: f)
        d.in_process_executor = object()

        class _Cfg2:
            @staticmethod
            def configured(_cfg): return object()

        d.multiprocess_executor = _Cfg2()
        sys.modules["dagster"] = d


@pytest.fixture(scope="module")
def supervisor_mod():
    _install_stubs()
    spec = importlib.util.spec_from_file_location(
        "dynamic_supervisor_tier3_test",
        str(_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeLog:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


class _FakeCtx:
    def __init__(self):
        self.log = _FakeLog()


class _FakeResp:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


# ===========================================================================
# Layer 1 — _resolve_subject extracts provenance.instance_id
# ===========================================================================
def test_resolve_subject_extracts_instance_id_from_provenance(supervisor_mod):
    """The supervisor's /resolve wrapper must extract provenance.instance_id
    as the 4th tuple element. Pre-fix behavior was to drop it; that
    silently sent every downstream layer URN-less.
    """
    fake_resolve_response = {
        "resolved_uri": "http://invincible-agent/idp#Table",
        "confidence_score": 0.99,
        "reasoning": "Routed via mesh:resolveInstance (provider=engine_d).",
        "provenance": {
            "instance_resolved": True,
            "instance_id": "urn:li:dataset:(urn:li:dataPlatform:snowflake,gold.sales.revenue_summary,PROD)",
        },
    }
    with patch.object(supervisor_mod.requests, "post",
                      return_value=_FakeResp(fake_resolve_response)):
        result = supervisor_mod._resolve_subject(
            _FakeCtx(), "Fetch revenue summary", "DATA_ENGINEERING"
        )

    # Tuple shape: (subject_uri, confidence, reasoning, instance_id,
    # subject_candidates, abstention_reason, instance_label). 2026-07-02
    # (decision-path Part 0) added the 5th element (resolver candidate pool with
    # scores); 2026-07-03 (abstention-gate arc) added the 6th — the structural
    # instance_not_found marker Engine O sets in provenance; 2026-07-10
    # (answer-first instance headline, f9a9be0) added the 7th — the FRIENDLY
    # instance label the summary leads with.
    #
    # THIS PIN WAS STALE FOR THREE WEEKS. f9a9be0 grew the tuple and did not
    # update this assertion, so the file has been red since 2026-07-10 and the
    # redness was read past as "the usual failures". An arity pin is exactly the
    # test that SHOULD fail when a tuple grows — it did its job; nobody claimed
    # the result. Growing this tuple again means updating this line, and the
    # per-element assertions below, in the same commit.
    assert len(result) == 7, (
        f"_resolve_subject returns (uri, conf, reasoning, instance_id, "
        f"candidates, abstention_reason, instance_label) — length 7. Got tuple "
        f"of length {len(result)}: {result!r}"
    )
    (subject_uri, confidence, reasoning, instance_id,
     _candidates, _abstention, instance_label) = result
    assert subject_uri == "http://invincible-agent/idp#Table"
    assert confidence == 0.99
    assert "engine_d" in reasoning
    assert instance_id == "urn:li:dataset:(urn:li:dataPlatform:snowflake,gold.sales.revenue_summary,PROD)", (
        f"Tier-3 fix: provenance.instance_id must propagate as the 4th "
        f"tuple element. Got instance_id={instance_id!r}; expected the "
        f"URN from provenance.instance_id."
    )
    # The 7th element gets a real assertion, not just an arity bump: this
    # fixture's provenance carries NO instance_label, and the contract is that a
    # missing label is "" (not None), so the answer summary's truthy check falls
    # back to the class label uniformly — the same empty-string discipline the
    # instance_id assertions above enforce.
    assert instance_label == "", (
        f"instance_label must be empty string when provenance carries no label "
        f"(not None). Got {instance_label!r}."
    )


def test_resolve_subject_empty_instance_id_when_no_provenance(supervisor_mod):
    """When /resolve doesn't return a provenance fan-out (LLM-only path
    against a class-shaped query), instance_id must be empty string —
    NOT None, so downstream truthy checks work uniformly.
    """
    fake_resolve_response = {
        "resolved_uri": "http://edgy-solutions.com/ontology/mil#ProcedureDataModule",
        "confidence_score": 0.97,
        "reasoning": "Class-resolved query; no instance to fan out.",
        "provenance": None,
    }
    with patch.object(supervisor_mod.requests, "post",
                      return_value=_FakeResp(fake_resolve_response)):
        result = supervisor_mod._resolve_subject(
            _FakeCtx(), "What procedure data module covers X", "MAINTENANCE"
        )

    _, _, _, instance_id, _, _, _ = result
    assert instance_id == "", (
        f"When provenance is None, instance_id must be empty string "
        f"(not None). Got {instance_id!r}."
    )


def test_resolve_subject_empty_instance_id_when_instance_resolved_false(supervisor_mod):
    """When /resolve fans out to instance providers but they all abstain
    (provenance.instance_resolved=false), instance_id must be empty
    string. This is the negative-control path that Engine DA's prompt
    will route to "honest not-found" rather than fabrication.
    """
    fake_resolve_response = {
        "resolved_uri": "http://invincible-agent/idp#Table",
        "confidence_score": 0.85,
        "reasoning": "LLM guess; instance providers abstained.",
        "provenance": {
            "instance_resolved": False,
            "instance_id": None,
            "instance_match": "empty",
        },
    }
    with patch.object(supervisor_mod.requests, "post",
                      return_value=_FakeResp(fake_resolve_response)):
        result = supervisor_mod._resolve_subject(
            _FakeCtx(), "Fetch absent_table_xyz", "DATA_ENGINEERING"
        )

    _, _, _, instance_id, _, _, _ = result
    assert instance_id == "", (
        f"When provenance.instance_resolved=False, instance_id must be "
        f"empty (not None). This is the structural negative-control "
        f"path: DA's prompt will route empty instance_id to "
        f"honest-not-found, NOT fabrication."
    )


def test_resolve_subject_empty_instance_id_on_resolve_failure(supervisor_mod):
    """When /resolve is unreachable, the failure path returns
    ("UNKNOWN", 0.0, "<reason>", "") — instance_id is empty string,
    matching the absent-URN contract.
    """
    with patch.object(supervisor_mod.requests, "post",
                      side_effect=RuntimeError("connection refused")):
        result = supervisor_mod._resolve_subject(
            _FakeCtx(), "Anything", "MAINTENANCE"
        )

    assert len(result) == 7, "the unreachable path must return the SAME arity as the happy path"
    (subject_uri, confidence, reasoning, instance_id,
     _candidates, _abstention, instance_label) = result
    assert instance_label == "", "the failure path must fill instance_label too, not drop it"

    assert subject_uri == "UNKNOWN"
    assert confidence == 0.0
    assert "unreachable" in reasoning
    assert instance_id == "", (
        f"Failure-path return must include empty instance_id (not "
        f"missing). Got tuple {result!r}."
    )


# ===========================================================================
# Layer 4 — Engine DA prompt branches structurally on resolved_instance_id
# ===========================================================================
#
# These tests inspect the prompt-construction logic in
# agent_fleet/data_analyst/main.py. The handler runs in Restate; we test
# the prompt-building branches by importing the module's source text
# directly and confirming the two branches are present and
# correctly-shaped. (Full handler execution requires Restate + smolagents
# + a live Ollama backend; that's the live-test concern banked for
# deploy-day. Prompt-shape pinning is doable today.)
def _read_da_main_source() -> str:
    da_main = _REPO / "agent_fleet" / "data_analyst" / "main.py"
    return da_main.read_text(encoding="utf-8")


def test_da_handler_extracts_resolved_instance_id():
    """The Tier-3 fix adds extraction of `resolved_instance_id` from the
    handler's request payload. Before, the URN was dropped silently.
    """
    src = _read_da_main_source()
    assert 'request.get("resolved_instance_id"' in src, (
        "Engine DA's analyze_data handler must extract "
        "`resolved_instance_id` from the request payload. The pre-fix "
        "handler silently dropped the URN even when the supervisor "
        "passed it."
    )


def test_da_prompt_has_urn_present_branch():
    """When resolved_instance_id is non-empty, the prompt must instruct
    the agent to use that EXACT URN — no modification, no substitution,
    no invention.
    """
    src = _read_da_main_source()
    assert "if resolved_instance_id:" in src, (
        "Engine DA's prompt must branch on resolved_instance_id being "
        "non-empty (URN-present case)."
    )
    # Check the URN-present block names the prompt expectations
    assert "EXACT URN" in src or "exact URN" in src.lower(), (
        "URN-present branch must instruct the agent to use the URN "
        "EXACTLY (no modification or substitution)."
    )


def test_da_prompt_has_urn_absent_honest_not_found_branch():
    """The correctness assertion: when resolved_instance_id is empty,
    the prompt must instruct the agent to return honest not-found and
    explicitly forbid fabrication.

    This is structurally pinned here because Acceptance B from the
    architect's fix recipe — "DA must not fabricate when the real URN
    is absent" — requires the prompt to explicitly forbid the
    fabrication path. If the prompt only handles the happy path, the
    fix is incomplete.
    """
    src = _read_da_main_source()
    # The else branch must exist
    assert "No DataHub URN" in src or "no DataHub URN" in src.lower(), (
        "URN-absent branch must explicitly state that no URN was "
        "resolved."
    )
    # The forbidden behaviors must be named
    forbid_invent = "Do NOT invent" in src or "do not invent" in src.lower()
    forbid_guess = "Do NOT" in src and ("guess" in src.lower() or "fabricat" in src.lower())
    assert forbid_invent or forbid_guess, (
        "URN-absent branch must explicitly forbid inventing or "
        "fabricating a URN. This is the structural enforcement of "
        "Acceptance B (no fabrication on catalog-miss)."
    )


def test_da_prompt_drops_search_datahub_instruction():
    """The pre-fix prompt told the agent to call `search_datahub` — a
    tool not in DA's roster — which is what forced the fabrication
    fallback. The fix removes that instruction entirely.
    """
    src = _read_da_main_source()
    # The augmented_prompt construction block should NOT instruct the
    # agent to call search_datahub. (Code comments mentioning the tool
    # for historical context are fine; the actual prompt text must not
    # tell the agent to call it.)
    # Match the previous instruction line specifically.
    assert "call search_datahub first to discover" not in src, (
        "The fabrication-trigger instruction ('call search_datahub "
        "first to discover the URN') must be removed from DA's prompt. "
        "search_datahub isn't in DA's tool roster, so the instruction "
        "forces the agent into the invention fallback."
    )
