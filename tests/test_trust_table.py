"""TRUST TABLE — deny-by-default for autonomy, computed from ABSENCE.

ADR-0034 Phase 1. Three properties carry the whole design, and each has a way of being
quietly weakened into uselessness:

  1. AN UNLISTED FORMAT IS SUPERVISED, and the default is computed from absence rather than
     written down per format. A table that must LIST a format in order to supervise it fails
     OPEN on the format nobody added — and the format nobody added is precisely the one nobody
     has looked at.
  2. A RUNG IS EARNED UNDER A PIPELINE VERSION and does not carry to another. The three
     notices that broke this pipeline in a week broke on format variation WITHIN a vendor
     while the extractor changed underneath them (vision -> text-layer), so "the thing that
     earned the trust" and "the thing now running" are routinely different objects.
  3. `supervised -> trusted` IS FORBIDDEN. `monitored` is the only rung producing
     COUNTERFACTUAL evidence — what the pipeline would have done vs. what a human did, on
     traffic it already handles. Skipping it promotes on evidence from a different regime.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_trust_table.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.iagent.trust_table import (  # noqa: E402
    MONITORED,
    SUPERVISED,
    TRUSTED,
    TrustTableInvalid,
    load_trust_table,
    parse_trust_table,
    promotion_is_permitted,
    table_ref,
)

_PV = "doc-tools@446fbae"


def _table(formats: dict):
    return parse_trust_table({"version": 1, "formats": formats}, ref="trust@test")


def _promoted(rung=MONITORED, pv=_PV, **over):
    e = {"rung": rung, "pipeline_version": pv,
         "ratified_by": "cnogradi", "evidence": "correction rate over N records"}
    e.update(over)
    return e


# ── 1. deny-by-default, computed from absence ──────────────────────────────
def test_an_unlisted_format_is_supervised():
    """The default that must never be a lookup. If supervising required an entry, the format
    nobody added would run unsupervised."""
    t = _table({})
    assert t.rung_for("vendor/pcn/never-seen", _PV) == SUPERVISED
    assert t.is_autonomy_permitted("vendor/pcn/never-seen", _PV) is False


def test_an_empty_table_permits_no_autonomy_at_all():
    """The honest starting state: the corpus is empty, so nothing has earned anything."""
    t = _table({})
    for fp in ("a/b/c", "qorvo/pcn/v1", ""):
        assert t.is_autonomy_permitted(fp, _PV) is False


# ── 2. a rung is earned UNDER a pipeline version ───────────────────────────
def test_a_pipeline_upgrade_re_supervises():
    """THE KEY CORRECTION to the original model. A rung keyed on vendor alone would survive
    an upgrade — exactly when the evidence stops applying, because the thing that earned the
    trust is no longer the thing running."""
    t = _table({"qorvo/pcn/v1": _promoted(TRUSTED)})
    assert t.rung_for("qorvo/pcn/v1", _PV) == TRUSTED
    assert t.rung_for("qorvo/pcn/v1", "doc-tools@NEWER") == SUPERVISED, (
        "a rung survived a pipeline upgrade — the accumulated evidence was produced by a "
        "different extractor"
    )


def test_a_promotion_without_a_pipeline_version_is_refused():
    with pytest.raises(TrustTableInvalid) as exc:
        _table({"qorvo/pcn/v1": {"rung": TRUSTED, "ratified_by": "x", "evidence": "y"}})
    assert "pipeline_version" in str(exc.value)


# ── 3. the forbidden transition ────────────────────────────────────────────
def test_supervised_to_trusted_is_forbidden():
    """`monitored` is not a formality — it is the only rung that produces counterfactual
    evidence, so skipping it means promoting on evidence gathered under a different regime."""
    assert promotion_is_permitted(SUPERVISED, TRUSTED) is False


@pytest.mark.parametrize("cur,nxt", [(SUPERVISED, MONITORED), (MONITORED, TRUSTED)])
def test_one_rung_at_a_time_is_permitted(cur, nxt):
    assert promotion_is_permitted(cur, nxt) is True


@pytest.mark.parametrize("cur,nxt", [
    (TRUSTED, MONITORED), (TRUSTED, SUPERVISED), (MONITORED, SUPERVISED),
])
def test_demotion_is_always_permitted(cur, nxt):
    """The road back from autonomy must never be the harder path — a demotion blocked by
    policy is an outage waiting to be argued about."""
    assert promotion_is_permitted(cur, nxt) is True


def test_an_unknown_rung_is_never_permitted():
    assert promotion_is_permitted(SUPERVISED, "yolo") is False
    assert promotion_is_permitted("yolo", TRUSTED) is False


# ── an unexplained trust grant is not a grant ──────────────────────────────
@pytest.mark.parametrize("missing", ["ratified_by", "evidence"])
def test_a_promotion_needs_an_accountable_human_and_a_basis(missing):
    """Same rule capability_grants.yaml enforces, for the same reason: this authorizes the
    pipeline to act UNSUPERVISED, and an approval with no stated basis cannot be audited or
    revisited."""
    e = _promoted(TRUSTED)
    del e[missing]
    with pytest.raises(TrustTableInvalid):
        _table({"qorvo/pcn/v1": e})


def test_a_supervised_entry_needs_no_ratification():
    """Declaring the DEFAULT explicitly grants nothing, so it demands no justification."""
    t = _table({"qorvo/pcn/v1": {"rung": SUPERVISED, "pipeline_version": _PV}})
    assert t.rung_for("qorvo/pcn/v1", _PV) == SUPERVISED


def test_a_bad_rung_is_refused():
    with pytest.raises(TrustTableInvalid):
        _table({"x/y/z": {"rung": "mostly", "pipeline_version": _PV}})


# ── sampling is policy, not a constant ─────────────────────────────────────
def test_only_monitored_samples():
    t = _table({
        "a/b/mon": _promoted(MONITORED, sample_rate=0.25),
        "a/b/tru": _promoted(TRUSTED, sample_rate=0.9),
    })
    assert t.sample_rate_for("a/b/mon", _PV) == 0.25
    assert t.sample_rate_for("a/b/tru", _PV) == 0.0
    assert t.sample_rate_for("a/b/unlisted", _PV) == 0.0


# ── the ref is content-addressed, like ruleset_ref ─────────────────────────
def test_table_ref_moves_with_content():
    """It rides into every decision record as governing.trust_table_ref, so a corpus spanning
    a table edit can tell its halves apart."""
    assert table_ref("a") != table_ref("b")
    assert table_ref("a") == table_ref("a")
    assert table_ref("a").startswith("trust@")


# ── the shipped file loads, and grants nothing ─────────────────────────────
def test_the_committed_table_loads_and_promotes_nobody():
    """Phase 1 ships an EMPTY table on purpose: the corpus starts empty, so every real format
    sits at the born-default until there is something to read."""
    t = load_trust_table(str(_ROOT / "policy" / "trust_table.yaml"))
    assert t.ref.startswith("trust@")
    assert t.rung_for("qorvo/pcn/v1", _PV) == SUPERVISED
    assert t.is_autonomy_permitted("anything", _PV) is False


def test_a_missing_table_raises_rather_than_inferring_a_policy():
    """An absent table is a DEPLOY problem. Treating it as "no promotions" would make a
    missing file indistinguishable from a deliberate reset — the caller supervises everything
    on failure, but loudly, at a layer that can say why."""
    with pytest.raises(TrustTableInvalid):
        load_trust_table(str(_ROOT / "policy" / "does-not-exist.yaml"))


def test_a_malformed_table_raises_rather_than_degrading_quietly():
    with pytest.raises(TrustTableInvalid):
        parse_trust_table({"formats": ["not", "a", "mapping"]}, ref="trust@x")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
