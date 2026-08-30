"""Seals for Engine F. Each one corresponds to a defect this build actually hit.

WHY THESE AND NOT COVERAGE. Every test below was written because something went wrong while
building the engine, or because a neighbouring engine's incident says it will. A test that
merely re-states what the code says is a test that passes when the code is wrong in the same
way — the class this repo names "assert on the claim, not its neighbour".

The five findings sealed here, in the order they were found:

  1. The seed's roundness assertion refused thirty-six rows of a perfectly round seed
     ($75,000 is not a multiple of $50,000). The DATA was right; the ASSERTION was wrong.
  2. Constant performance factors made every period's CPI identical to four decimal places,
     so the series verb could not demonstrate the trend it exists to show.
  3. One name shared by a control account, a WBS element and an OBS element made
     `resolve_instance` return two exact matches in different classes — the router's
     mixed-class abstain, and the flagship question becomes unroutable.
  4. `fin:FundingLine` — the `input_uri` of a registered verb — could not be enumerated, so
     an elicitation for it would fall back to free text believing a provider had considered
     the question.
  5. Widening `_ACCOUNTS` from five columns to seven moved the BAC out from under a
     positional read.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent import measures, slots  # noqa: E402
from agent_fleet.finance_agent.entities import MethodRequired  # noqa: E402
from agent_fleet.finance_agent.seed import build_seed, check_consistency  # noqa: E402

FIN = "http://invincible-agent/fin#"
STATE = build_seed()


# ─────────────────────────────────────────────────────────────────────────────
# The seed
# ─────────────────────────────────────────────────────────────────────────────

def test_seed_is_structurally_consistent():
    """Finding 1 and 5. `check_consistency` is the boot gate; if it has anything to say,
    every measure below is computing over a model whose totals do not add up."""
    assert check_consistency(STATE) == []


def test_program_bac_rolls_up_from_the_control_accounts():
    """Finding 5, stated independently of the guard that caught it.

    `build_seed` reads the BAC out of a tuple that has already been widened once. A
    positional read that survived the widening by luck would leave this failing while
    `check_consistency` passed — so the roll-up is asserted here from the OBJECTS, not from
    the table the objects were built from.
    """
    program = STATE.programs[0]
    assert program.bac == sum(c.bac for c in STATE.control_accounts) == 12_000_000


def test_no_two_entities_share_a_label():
    """Finding 3. Two exact matches in different classes make the router abstain, and the
    symptom is a question that cannot be routed while every component reports healthy."""
    labels: dict[str, str] = {}
    for kind, items, key in (
        ("program", STATE.programs, "program_id"),
        ("control_account", STATE.control_accounts, "ca_id"),
        ("work_package", STATE.work_packages, "wp_id"),
        ("wbs", STATE.wbs, "wbs_id"),
        ("obs", STATE.obs, "obs_id"),
        ("funding", STATE.funding, "line_id"),
    ):
        for item in items:
            here = f"{kind}:{getattr(item, key)}"
            prior = labels.setdefault(item.name.lower(), here)
            assert prior == here, f"label {item.name!r} is held by both {prior} and {here}"


def test_the_index_series_actually_moves():
    """Finding 2, and it is the one a coverage-shaped test would never have caught.

    `fin_performance_indices` exists because the DIRECTION OF TRAVEL is the question. With
    constant seed factors it returned CPI 0.8367 six times — a uniform extreme result, which
    is what a broken instrument returns and is indistinguishable from one.

    ASSERTED IN BOTH DIRECTIONS, deliberately: cumulative CPI must FALL and cumulative SPI
    must RISE across the window. One moving series could be read as the whole program
    drifting; two opposing ones can only be two packages behaving differently.
    """
    rows = measures.fin_performance_indices(STATE, program_id="NP-MERIDIAN")
    assert len(rows) >= 4
    cpis = [r["cum_cpi"] for r in rows]
    spis = [r["cum_spi"] for r in rows]
    assert len(set(round(c, 4) for c in cpis)) > 1, "cumulative CPI is flat — no trend to show"
    assert cpis[-1] < cpis[0], "cumulative CPI must degrade across this seed's window"
    assert spis[-1] > spis[0], "cumulative SPI must recover across this seed's window"


def test_notional_data_carries_no_cents():
    """ADR-0045 Decision 4. Notional data must be OBVIOUSLY notional; a figure with cents
    reads as measured rather than invented, and a screenshot of it is a liability."""
    for f in STATE.facts:
        for amount in (f.bcws, f.bcwp, f.acwp):
            assert amount % 5_000 == 0, f"{f.wp_id} {f.period}: {amount} is not round"


# ─────────────────────────────────────────────────────────────────────────────
# The declarations — this engine is born declaring, so the declarations are a contract
# ─────────────────────────────────────────────────────────────────────────────

def test_every_verb_declares_slots_derived_from_its_signature():
    """The declaration must come from `inspect.signature`, not from a remembered list — so
    a parameter added to a measure without a declaration is a failure, not a silence."""
    import inspect
    for fn in measures.OUTPUT_URI:
        declared = {s["name"] for s in slots.slots_for(fn)}
        actual = set(inspect.signature(getattr(measures, fn)).parameters) - {"state"}
        assert declared == actual, f"{fn}: declared {declared} != signature {actual}"


def test_the_eac_method_values_come_out_of_the_literal():
    """The refusal names three methods. If those names were typed into a message rather than
    read from `EACMethod`, a fourth formula would ship with a refusal that omits it."""
    method = next(s for s in slots.slots_for("fin_eac_calculation") if s["name"] == "method")
    assert method["kind"] == "spoken-mandatory"
    assert method["required"] is True
    assert method["values"] == list(measures.EAC_METHODS)
    assert "default" not in method, "a default method is the one thing ADR-0045 forbids"
    for name in measures.EAC_METHODS:
        assert name in slots.refusal_for("fin_eac_calculation", [method])


def test_window_declares_a_container_not_a_scalar():
    """Lane 1's measured bug, which this module must not reinstate: an over-eager Optional
    unwrap declared a `list[str]` slot as `str`, a router sent the bare string, and the
    engine refused by naming CHARACTERS — blaming itself for the declaration's lie."""
    for fn in measures.OUTPUT_URI:
        window = next((s for s in slots.slots_for(fn) if s["name"] == "window"), None)
        if window is not None:
            assert window["type"].startswith("list["), f"{fn}.window declared {window['type']}"


def test_instance_slots_declare_a_referent_class():
    """A spoken id slot with no referent leaves the filler emitting a NAME into an id slot —
    the largest single failure class in the planning engine's corpus."""
    for fn in measures.OUTPUT_URI:
        for slot in slots.slots_for(fn):
            if slot["name"].endswith("_id") and slot["kind"].startswith("spoken"):
                assert slot.get("referent", "").startswith(FIN), f"{fn}.{slot['name']}"


# ─────────────────────────────────────────────────────────────────────────────
# Registration and routing surface
# ─────────────────────────────────────────────────────────────────────────────

def test_every_verb_has_both_ends_of_contract_d_declared_in_the_ttl():
    """THE PLANNING ENGINE'S TWELVE 422s, PREVENTED. Contract D refuses a batch ATOMICALLY
    and the engine keeps serving healthy while none of its verbs route — a failure invisible
    to `kubectl get pods`. Every input and output URI is checked against the TTL FILE here,
    which is the only check available before a prime runs."""
    ttl = (REPO / "setup" / "ontologies" / "finance_extension.ttl").read_text(encoding="utf-8")
    mesh_ttl = (REPO / "setup" / "ontologies" / "mesh_system.ttl").read_text(encoding="utf-8")
    declared = ttl + mesh_ttl
    for v in engine.VERBS:
        for uri in (v["input_uri"], measures.OUTPUT_URI[v["fn"]]):
            local = uri.rsplit("#", 1)[-1]
            prefix = "fin:" if uri.startswith(FIN) else "mesh:"
            assert f"{prefix}{local} a owl:Class" in declared, (
                f"{uri} is registered by {v['verb']} but declared in no seeded TTL — "
                f"Contract D would refuse the whole batch with a 422"
            )


def test_every_registered_input_class_can_be_resolved_or_enumerated():
    """Finding 4. A verb registered on a class no provider holds is a verb nobody can be
    asked for, and the only symptom is an elicitation offering free text."""
    assert engine._unroutable_classes() == []


def test_the_two_provider_verbs_target_classes_lane_1_declared():
    """Contract D again, on the provider registrations. `mesh:InstanceClass` and
    `mesh:InstanceEnumeration` are Lane 1's, and Engine F's seed queues behind them — a
    permanent 422 with no retry if they are absent when this engine registers."""
    mesh_ttl = (REPO / "setup" / "ontologies" / "mesh_system.ttl").read_text(encoding="utf-8")
    for local in ("InstanceIdentifier", "InstanceResolution",
                  "InstanceClass", "InstanceEnumeration"):
        assert f"mesh:{local} a owl:Class" in mesh_ttl


def test_the_ttl_is_registered_with_the_prime():
    """A TTL nothing ingests is a declaration the graph never sees. The ontology-seed hook
    runs ONE hardcoded MRO script; the prime's manifest is the path a domain TTL takes."""
    prime = (REPO / "setup" / "prime_databases.py").read_text(encoding="utf-8")
    assert '"path": "ontologies/finance_extension.ttl"' in prime
    # The domain must match what the verbs register under, or the resolver's domain-scoped
    # query returns nothing and the cascade is silent.
    # THE DOMAIN THE VERBS REGISTER UNDER AND THE DOMAIN THE TTL IS SEEDED UNDER MUST BE
    # THE SAME NAME. The resolver queries by semantic domain, so a mismatch produces a
    # silent UNKNOWN cascade — no error, just an answer that never arrives. Compared against
    # `engine.DOMAINS` rather than a literal typed twice here, because a test that repeats
    # the value it is checking cannot detect the value being wrong.
    for domain in engine.DOMAINS:
        assert f'"domain": "{domain}"' in prime, (
            f"engine-fin registers verbs under {domain} but no seeded TTL carries that domain"
        )


def test_engine_f_does_not_squat_on_the_presentation_agent_name():
    """§0 of the runbook, sealed. `engine-f` is the presentation agent; a finance engine
    answering at that name takes /render_ui down fleet-wide, and the first symptom is cards
    failing to draw three layers away."""
    assert engine.VERBS, "catalogue is empty"
    chart = (REPO / "helm" / "invincible-agent" / "templates" / "engines.yaml").read_text(
        encoding="utf-8")
    assert '"component" "engine-fin" "values" .Values.engineFinance' in chart
    assert '"component" "engine-f" "values" .Values.engineF' in chart, (
        "the presentation agent's entry must survive unchanged"
    )
    values = (REPO / "helm" / "invincible-agent" / "values.yaml").read_text(encoding="utf-8")
    assert "name: presentation-agent" in values, "engineF must still be the presentation agent"


# ─────────────────────────────────────────────────────────────────────────────
# The designed refusal — ADR-0045's demo beat
# ─────────────────────────────────────────────────────────────────────────────

def test_a_bare_eac_is_refused_and_the_refusal_names_the_choice():
    """ADR-0045: a bare 'what's the EAC' is REFUSED, with the refusal naming the choice.
    Refusing without naming the alternative is a dead end wearing a gate's clothes."""
    with pytest.raises(MethodRequired) as exc:
        measures.fin_eac_calculation(STATE, program_id="NP-MERIDIAN", method=None)
    message = str(exc.value)
    for name in measures.EAC_METHODS:
        assert name in message
    assert "no default" in message.lower()


def test_the_three_eac_methods_disagree_materially():
    """THE ARGUMENT FOR THE MANDATORY SLOT, ASSERTED IN DATA. If the three formulas agreed
    on this seed, the refusal would be pedantry rather than honesty — so the seed is
    required to keep them apart by a margin that changes a decision."""
    eacs = {
        m: measures.fin_eac_calculation(STATE, program_id="NP-MERIDIAN", method=m)[0]["eac"]
        for m in measures.EAC_METHODS
    }
    bac = STATE.programs[0].bac
    spread = max(eacs.values()) - min(eacs.values())
    assert spread / bac > 0.10, (
        f"the EAC methods span only {spread:,.0f} on a {bac:,.0f} budget; the mandatory "
        f"method slot is only defensible while they disagree materially"
    )


def test_the_route_refuses_a_missing_mandatory_slot_before_calling_the_verb():
    """The refusal must be reachable by the ROUTER, not only by a direct caller — that is
    what declaring slots from day one buys, and it is why the message is built from the
    declaration rather than from a string."""
    from fastapi.testclient import TestClient
    with TestClient(engine.app) as client:
        r = client.post("/measure/fin_eac_calculation",
                        json={"params": {"program_id": "NP-MERIDIAN"}})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["needs_slots"] == ["method"]
        for name in measures.EAC_METHODS:
            assert name in detail["question"]


def test_an_unknown_subject_is_not_an_empty_result():
    """'The model does not capture X' and 'the query found nothing' are different claims,
    and collapsing them is how a typo becomes a confident zero."""
    from fastapi.testclient import TestClient
    with TestClient(engine.app) as client:
        r = client.post("/measure/fin_burn_rate", json={"params": {"program_id": "NOPE"}})
        assert r.status_code == 422
        assert "not_in_model" in r.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# Arithmetic that a reader will check by hand
# ─────────────────────────────────────────────────────────────────────────────

def test_variance_drivers_sum_to_the_variance_they_explain():
    """FAVOURABLE CONTRIBUTORS ARE RANKED TOO. Ranking only the unfavourable rows produces
    magnitudes summing to MORE than the variance they claim to explain, and the first reader
    who adds them up finds the numbers do not work."""
    total = measures.fin_variance_analysis(STATE, program_id="NP-MERIDIAN")[0]["variance"]
    drivers = measures.fin_variance_drivers(
        STATE, program_id="NP-MERIDIAN", level="work_package", top_n=99)
    assert drivers, "a program with a variance has contributors"
    assert abs(sum(d["contribution"] for d in drivers) - total) < 1e-6
    assert any(d["favourable"] for d in drivers), "the seed's favourable tail must be ranked"


def test_the_decomposition_accounts_for_everything_it_drops():
    """A tree whose material children do not sum to the parent must say so. Contributors
    that silently do not add up is the arithmetic lie this engine is most able to tell."""
    root = measures.fin_variance_analysis(STATE, program_id="NP-MERIDIAN")[0]
    kids = sum(c["variance"] for c in root.get("contributors", []))
    assert abs(kids + root.get("residual", 0.0) - root["variance"]) < 1e-6


def test_the_funding_grid_shows_all_three_states_and_the_ladder_holds():
    """SHORTFALL_GRID is REUSED, not re-minted (ADR-0045 Decision 3), so the cells must
    carry the grid's own vocabulary — a finance-specific state string would leave the card
    with no colour and the fix in another repository."""
    rows = measures.fin_funding_status(STATE, program_id="NP-MERIDIAN", window=["FY26-06"])
    assert {r["state"] for r in rows} == {"short", "pledged-not-firm", "met"}
    for r in rows:
        assert r["expended"] <= r["obligated"] <= r["authorized"], "the ladder is an invariant"
        # Both vocabularies on every cell: the grid's names so the existing renderer works,
        # and IPMDAR's so the payload speaks the analyst's words.
        assert (r["required"], r["committed"], r["secured"]) == (
            r["authorized"], r["obligated"], r["expended"])
        for field in ("value_label", "value_unit", "scope_label"):
            assert r.get(field), f"SHORTFALL_GRID's contract requires {field}"


def test_indices_rows_never_name_a_field_value_unit():
    """ACCOMMODATION A2, ENCODED SO A TIDY-UP GOES RED. This is the least discoverable
    decision in the engine and a comment is not enough to protect it.

    `fin_performance_indices` names its row-level unit field **`amount_unit`**, not
    `value_unit`, and the difference is load-bearing rather than stylistic. The presentation
    projector reads each archetype's passthrough fields from the response envelope and
    **falls back to `rows[0].get(field)`** (`_project_planning_archetype`). `PERIOD_SERIES`
    declares `value_unit` in its passthrough. So a row field spelled `value_unit` would be
    LIFTED TO THE CARD ENVELOPE and drawn as the series' unit — putting a dollar sign on a
    chart of CPI and SPI, by way of a field that was only ever describing the secondary
    amount columns beside them.

    The name defeats that lift deliberately. It LOOKS like a naming inconsistency with the
    other five verbs, which is exactly why someone will eventually "fix" it — and the fix is
    silent, because nothing errors: the card simply starts asserting that 0.85 is 0.85 US
    dollars.

    Same species as the assertion that `slots` crosses the wire as a list rather than a
    string: encode the REASON, so the well-meaning cleanup fails loudly instead of shipping.
    """
    rows = measures.fin_performance_indices(STATE, program_id="NP-MERIDIAN")
    assert rows, "the seed must produce a series for this seal to mean anything"
    for row in rows:
        assert "value_unit" not in row, (
            "fin_performance_indices row must NOT carry `value_unit` — the projector lifts "
            "it from rows[0] into PERIOD_SERIES's passthrough and the card would draw a "
            "currency on a dimensionless ratio. The field is `amount_unit` on purpose; see "
            "accommodation A2 in docs/plans/engine-f-archetype-bindings.md"
        )
        assert row.get("amount_unit"), (
            "the amounts beside the ratios still have a unit and it must be stated — "
            "just not under a name the archetype's passthrough will promote"
        )


def test_performance_indices_carry_no_currency():
    """CPI is a ratio. A dollar sign on 0.85 is a lie the producer told, and the absence of
    the verb from VALUE_UNIT is the assertion that prevents it."""
    assert "fin_performance_indices" not in measures.VALUE_UNIT
    from fastapi.testclient import TestClient
    with TestClient(engine.app) as client:
        body = client.post("/measure/fin_performance_indices",
                           json={"params": {"program_id": "NP-MERIDIAN"}}).json()
    assert "value_unit" not in body


def test_every_response_discloses_that_the_data_is_notional():
    """A finance figure that leaves this engine without saying it is notional is a figure
    somebody can paste into a deck. A docstring is not visible from a screenshot."""
    from fastapi.testclient import TestClient
    with TestClient(engine.app) as client:
        for fn in measures.OUTPUT_URI:
            params = {"program_id": "NP-MERIDIAN"}
            if fn == "fin_eac_calculation":
                params["method"] = "CPI"
            body = client.post(f"/measure/{fn}", json={"params": params}).json()
            assert "NOTIONAL" in body["data_provenance"]


# ─────────────────────────────────────────────────────────────────────────────
# The credential posture
# ─────────────────────────────────────────────────────────────────────────────

def test_the_engine_holds_no_standing_credential(tmp_path):
    """ADR-0045 Decision 5 / ADR-0044. The engine reads through the mesh with a ticket the
    BROKER mints, per request, carrying the CALLER'S identity. A source that could read a
    standing secret or a connection string is a source where the degraded mode can silently
    become the privileged one."""
    src = (REPO / "agent_fleet" / "finance_agent" / "main.py").read_text(encoding="utf-8")
    for forbidden in ("DATABASE_URL", "POSTGRES_PASSWORD", "AWS_SECRET_ACCESS_KEY",
                      "connection_string", "MESH_DEV_TOKEN"):
        assert forbidden not in src, f"engine-fin must not read {forbidden}"
    # The ONE secret it reads is its own registration identity, and it is named at the call
    # site rather than derived from the component name — the law that cost a silent 401.
    assert 'secret_env="ENGINE_FIN_CLIENT_SECRET"' in src
    assert 'client_id="iagent-finance-agent"' in src


def test_the_ticketed_read_refuses_without_a_callers_identity():
    """A read that cannot say who it is for must not be performed: the narrowing that makes
    it safe is keyed on exactly that, and an ambient-identity ticket narrows rows for
    whoever the ENGINE is rather than whoever ASKED."""
    import inspect
    src = inspect.getsource(engine.mesh_ticketed_read)
    assert "x-originator-sub" in src and "x-originator-email" in src
    assert "401" in src
