"""`src/iagent/origin_resolver.py` -- the origin RESOLVER (ingest/origin seam section 6,
architect ruling 2026-10-02 "ORIGIN, not audience", item 2; SDK 0.9.7
`iagent_mesh.systems_of_record`).

WHAT THESE DEFEND:
  * `systems()` composes the seed (empty) with `SYSTEMS_OF_RECORD_OVERLAY_DIRS` overlays and
    validates every composed row's connector against `CONNECTORS` -- an unknown connector name
    raises `UnknownConnector` at load, never a silent miss.
  * `resolve()`'s hit path: a TEST-ONLY `SystemOfRecord` row pointing at
    `CONNECTORS["sandbox-fake"]` proves identity -> pattern -> connector -> suggestion end to
    end, built from the SDK's own `SystemOfRecord` constructor (never a stand-in class).
  * `resolve()`'s miss path (no system matches, or the matched system's connector misses)
    returns `None`, never raises.
  * the SEAL: every key `policy/triggers/origin_suggestion.yaml`'s own `requires:` list names
    is present and non-empty in a built suggestion -- read from the file, never restated here.

Run: uv run pytest tests/test_origin_resolver.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

iagent_mesh = pytest.importorskip("iagent_mesh")
from iagent_mesh.systems_of_record import (  # noqa: E402
    ConnectorLookup, IdentityMatch, SystemOfRecord, UnknownConnector)

from src.iagent import origin_resolver as orr  # noqa: E402

_TRIGGER_PATH = (
    Path(__file__).resolve().parents[1] / "policy" / "triggers" / "origin_suggestion.yaml"
)


def _row(**kw):
    base = dict(
        id="sor-test", kind="fracas", owner_domain="aviation",
        identity=IdentityMatch(pattern=r"^SANDBOX-FAKE-0001$", fields=("work_order_ref",)),
        lookup=ConnectorLookup(connector="sandbox-fake", returns=("owner_domain", "program")),
        program_field="program",
    )
    base.update(kw)
    return SystemOfRecord(**base)


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    monkeypatch.setattr(orr, "_SYSTEMS_CACHE", None)
    yield
    monkeypatch.setattr(orr, "_SYSTEMS_CACHE", None)


def _artifact(**metadata):
    return {
        "ingest_id": "ART-9",
        "dropped_by": {"authz_id": "alice@example.com"},
        "metadata": metadata,
    }


# ── systems() / CONNECTORS validation ──────────────────────────────────────────────────────

def test_systems_composes_the_env_overlay_the_same_way_content_kinds_does(monkeypatch, tmp_path):
    overlay = tmp_path / "sor"
    overlay.mkdir()
    (overlay / "one.yaml").write_text(
        "id: sor-overlay\nkind: fracas\nowner_domain: aviation\n"
        "identity:\n  pattern: '^X$'\n  fields: [x]\n"
        "lookup:\n  connector: sandbox-fake\n  returns: [owner_domain, program]\n"
        "program_field: program\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(orr._OVERLAY_DIRS_ENV, str(overlay))
    rows = orr.systems()
    assert [r.id for r in rows] == ["sor-overlay"], rows


def test_an_unknown_connector_raises_at_load_not_a_silent_miss(monkeypatch, tmp_path):
    overlay = tmp_path / "sor"
    overlay.mkdir()
    (overlay / "one.yaml").write_text(
        "id: sor-bad\nkind: fracas\nowner_domain: aviation\n"
        "identity:\n  pattern: '^X$'\n  fields: [x]\n"
        "lookup:\n  connector: nobody-registered-this\n  returns: [owner_domain, program]\n"
        "program_field: program\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(orr._OVERLAY_DIRS_ENV, str(overlay))
    # MUTANT target (section 6): dropping the `validate_connectors_known` call would make this
    # miss silently instead -- the exact fragment this reds is "pytest.raises(UnknownConnector)".
    with pytest.raises(UnknownConnector):
        orr.systems()


# ── resolve(): hit, miss ────────────────────────────────────────────────────────────────────

def test_resolve_hit_builds_the_full_suggestion(monkeypatch):
    monkeypatch.setattr(orr, "systems", lambda: (_row(),))
    artifact = _artifact(work_order_ref="SANDBOX-FAKE-0001")
    suggestion = orr.resolve(artifact)
    assert suggestion == {
        "kind": "origin_suggestion",
        "suggestion_id": "origin:ART-9:sor-test",
        "artifact_id": "ART-9",
        "dropped_by": {"authz_id": "alice@example.com"},
        "suggested": {
            "owner_domain": "aviation",  # SystemOfRecord.owner_domain -- fixed per row, not
                                         # the connector's returned record (ruling 2's split).
            "program": "sandbox-program",
            "obtained_via": "authoritative_source",
        },
        "evidence": {
            "source": "sor-test",
            "citation": "sandbox-fake:SANDBOX-FAKE-0001",
        },
    }, suggestion


def test_resolve_miss_when_no_system_matches(monkeypatch):
    monkeypatch.setattr(orr, "systems", lambda: (_row(),))
    artifact = _artifact(work_order_ref="not-the-fixed-value")
    assert orr.resolve(artifact) is None


def test_resolve_miss_when_the_connector_itself_misses(monkeypatch):
    # The pattern matches ("ANYTHING" satisfies ".*"), but the fake connector only hits its own
    # fixed value -- proving the miss can come from the CONNECTOR, not only the pattern.
    row = _row(identity=IdentityMatch(pattern=r".*", fields=("work_order_ref",)))
    monkeypatch.setattr(orr, "systems", lambda: (row,))
    artifact = _artifact(work_order_ref="ANYTHING")
    assert orr.resolve(artifact) is None


def test_resolve_miss_when_no_identity_field_is_present(monkeypatch):
    monkeypatch.setattr(orr, "systems", lambda: (_row(),))
    assert orr.resolve(_artifact()) is None


# ── THE SEAL: built against the trigger's OWN requires: list, never restated ───────────────

def _get(d: dict, dotted: str):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def test_every_required_key_the_trigger_names_is_present_and_nonempty(monkeypatch):
    import yaml

    requires = yaml.safe_load(_TRIGGER_PATH.read_text(encoding="utf-8"))["requires"]
    assert requires, "the trigger file's own requires: list must not be empty"
    monkeypatch.setattr(orr, "systems", lambda: (_row(),))
    suggestion = orr.resolve(_artifact(work_order_ref="SANDBOX-FAKE-0001"))
    assert suggestion is not None
    for key in requires:
        value = _get(suggestion, key)
        # MUTANT target (section 6, "drop a required key"): deleting any one of these from
        # resolve()'s returned dict reds this exact assertion for that key.
        assert value not in (None, "", {}), (key, suggestion)
