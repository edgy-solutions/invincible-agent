"""THE ROW MUST CARRY THE MENU, NOT JUST THE TRIPLE.

WHAT WAS WRONG (2026-08-21, found by reading the writer before writing the
reader). The gateway learned the Presentation species and landed 10 rendersAs
rows in Weaviate -- subject, predicate, object, all correct. But
``upsert_weaviate_predicate_row`` writes a FIXED VERB-SHAPED property set, so the
presentation payload the gateway assembles for DataHub was dropped at the
Weaviate boundary. The row carried the EDGE and not the MENU.

Same defect species as the manifest one layer up: a writer correct for its
population (verb edges) and blind to the second species' payload.

WHY IT HAD TO BE CAUGHT BEFORE THE READ WAS BUILT:

  * ``menu_for(frontend_id)`` cannot scope without ``frontend_id`` -- every row
    looks like it belongs to everyone, so Cortex's capabilities would reach
    OpenDDIL;
  * ``_satisfies()`` cannot evaluate fit without ``expected_fields`` -- every
    candidate trivially "fits";
  * ``_is_live_view()`` is ALWAYS FALSE without ``recomputes``, so ADR-0042
    Ruling 9 never fires. The refusal would read as implemented and be defeated
    -- ruled-but-unimplemented rebuilt one layer beneath the commit (ab0bcfd)
    that closed exactly that back door, with a green suite on top.

Run: uv run --frozen --with pytest pytest tests/test_predicate_row_carries_the_menu.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_MESH = "http://invincible-agent/mesh#"


def _sub():
    spec = importlib.util.spec_from_file_location(
        "v2_substrate__menu_row_test",
        _REPO / "agent_fleet" / "mesh_registrar" / "v2_substrate.py",
    )
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # noqa: BLE001
        sys.modules.pop(spec.name, None)
        pytest.skip(f"v2_substrate not importable: {type(exc).__name__}: {exc}")
    return m


class _Captor:
    """Minimal Weaviate stand-in that records the properties written."""

    def __init__(self):
        self.props = {}
        outer = self

        class _Coll:
            def __init__(self):
                self.data = self

            def exists(self, uuid=None):
                return False

            def insert(self, properties=None, uuid=None):
                outer.props.update(properties or {})

            def update(self, properties=None, uuid=None):
                outer.props.update(properties or {})

        class _Collections:
            @staticmethod
            def exists(name):
                return True

            @staticmethod
            def get(name):
                return _Coll()

        self.collections = _Collections()


def _write(v, client, **over):
    base = dict(
        weaviate_client=client,
        verb_iri="mesh:rendersAs",
        input_uri=f"{_MESH}OwnershipFact",
        output_uri=f"{_MESH}KnowledgeDocument",
        description="d",
        endpoint_url="",
        owner_persona="ANY",
        domains=[],
        cost_class="low",
        requires_human_approval=False,
        synonyms=[],
        anti_synonyms=[],
        tool_urn="urn:x",
        tool_kind="Presentation",
        frontend_id="cortex",
        archetype="KNOWLEDGE_DOCUMENT",
        expected_fields=["owner"],
    )
    base.update(over)
    v.upsert_weaviate_predicate_row(**base)


# ── THE FROZEN VERB KEY — the non-regression that breaks silently ──────────

def test_the_verb_row_key_is_BYTE_IDENTICAL_to_before():
    """THE ARM A SCHEMA CHANGE MOST LIKELY BREAKS WITHOUT ANYONE NOTICING.

    24 verb rows exist in the cluster under uuid5(NAMESPACE_DNS, "verb|input").
    If the key gains components for verbs those rows do not migrate -- new uuids
    are minted and the originals are ORPHANED as duplicates.
    """
    import hashlib
    from uuid import UUID

    v = _sub()
    verb, inp = "mesh:lookupOwnership", f"{_MESH}OwnershipFact"
    ns = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    digest = hashlib.sha1(ns.bytes + f"{verb}|{inp}".encode("utf-8")).digest()
    assert v._deterministic_predicate_uuid(verb, inp) == UUID(bytes=digest[:16], version=5)


def test_empty_extras_do_not_change_the_verb_key():
    """Passing "" for the new parts must land on the SAME row — this is what
    makes the payload additive rather than a migration."""
    v = _sub()
    verb, inp = "mesh:traceLineage", f"{_MESH}LineageTopology"
    assert v._deterministic_predicate_uuid(verb, inp) == \
        v._deterministic_predicate_uuid(verb, inp, "", "")


# ── THE DEFERRED COLLISION, NOW CLOSED ─────────────────────────────────────

def test_two_frontends_rendering_the_SAME_subject_do_not_collide():
    """THE PACKET'S DEFERRED COLLISION, arriving because the read path makes it
    bite. Under the verb-shaped key both hash to (mesh:rendersAs, OwnershipFact)
    and the second silently overwrites the first — which makes per-frontend
    scoping impossible for exactly the subjects two frontends both care about."""
    v = _sub()
    subj = f"{_MESH}OwnershipFact"
    # SAME subject AND SAME archetype on purpose. An earlier version of this arm
    # used different archetypes, so ARCHETYPE alone separated the two rows and
    # the assertion passed even with frontend_id removed from the key -- it read
    # as a scoping test while proving nothing about scoping. Break-on-purpose
    # caught it: dropping frontend_id left all nine arms green.
    #
    # Two surfaces rendering the same subject the same way is also the COMMON
    # case, not the exotic one: both Cortex and OpenDDIL render OwnershipFact as
    # a KNOWLEDGE_DOCUMENT. Only frontend_id can tell those rows apart.
    cortex = v._deterministic_predicate_uuid("mesh:rendersAs", subj, "cortex", "KNOWLEDGE_DOCUMENT")
    openddil = v._deterministic_predicate_uuid("mesh:rendersAs", subj, "openddil", "KNOWLEDGE_DOCUMENT")
    assert cortex != openddil, (
        "two frontends offering the same subject as the same archetype collapsed "
        "to one row — the second overwrites the first and per-frontend menus "
        "become impossible for exactly the capabilities both surfaces share"
    )


def test_one_frontend_offering_TWO_archetypes_for_a_subject_keeps_both():
    """A menu entry is (subject, archetype). One surface may offer a subject as a
    document AND as a chart; keying only on the frontend would collapse them."""
    v = _sub()
    subj = f"{_MESH}OwnershipFact"
    a = v._deterministic_predicate_uuid("mesh:rendersAs", subj, "cortex", "KNOWLEDGE_DOCUMENT")
    b = v._deterministic_predicate_uuid("mesh:rendersAs", subj, "cortex", "CHART_WIDGET")
    assert a != b


def test_the_SAME_menu_entry_is_STABLE_across_re_registration():
    """Idempotency: a redeploy upserts in place rather than accumulating. The
    cluster measured 34 rows twice for exactly this reason."""
    v = _sub()
    args = ("mesh:rendersAs", f"{_MESH}OwnershipFact", "cortex", "KNOWLEDGE_DOCUMENT")
    assert v._deterministic_predicate_uuid(*args) == v._deterministic_predicate_uuid(*args)


# ── ABSENT MEANS NOTHING (ADR-0042 Ruling 9's honest default) ───────────────

def test_recomputes_is_OMITTED_when_undeclared_not_written_False():
    """THE RULING'S DEFAULT, held identically at the writer.

    ``_is_live_view()`` (ab0bcfd) reads absence as NOTHING. If the writer stamps
    False on every row that never declared it, the reader can no longer tell
    "declared not-live" from "never said" — and a later change reading False as
    meaningful would silently reclassify every legacy row.
    """
    v = _sub()
    c = _Captor()
    _write(v, c)
    assert "recomputes" not in c.props, "undeclared recomputes was stamped onto the row"


def test_the_presentation_payload_actually_reaches_the_row():
    """The whole point: without these the row carries the edge and not the menu."""
    v = _sub()
    c = _Captor()
    _write(v, c)
    assert c.props["tool_kind"] == "Presentation"
    assert c.props["frontend_id"] == "cortex"
    assert c.props["archetype"] == "KNOWLEDGE_DOCUMENT"
    assert c.props["expected_fields"] == ["owner"]


def test_a_declared_live_view_DOES_carry_recomputes():
    """The positive control: when the component says so the row must say so, or
    Ruling 9 has nothing to read."""
    v = _sub()
    c = _Captor()
    _write(v, c, recomputes=True)
    assert c.props["recomputes"] is True


def test_a_verb_row_carries_the_species_too():
    """The discriminator rides in the data for BOTH kinds, so a reader never
    infers the species from which fields happen to be present."""
    v = _sub()
    c = _Captor()
    _write(v, c, tool_kind="Engine", frontend_id="", archetype="", expected_fields=[])
    assert c.props["tool_kind"] == "Engine"
    assert c.props["frontend_id"] == ""
