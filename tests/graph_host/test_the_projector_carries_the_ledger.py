"""Runbook site 5 — the SOURCE_LEDGER producer conformance case, and it is about the SEAM.

The producer side of this archetype is already well sealed: `test_the_brief_payload_is_rows.py`
proves every outcome emits exactly one row, `test_the_ledger_vocabulary_is_shared.py` proves
both graphs share one vocabulary object and that a `fail` graph reaches no hole. The card side
is sealed in cortex-ui. **Nothing asserted the PROJECTOR between them**, which is the layer that
has silently dropped an envelope field on this table three times — `reference`/`verdict`
(2026-09-03), the EAC low/high pair (2026-09-15), W4-2's bound (2026-09-19) — and every layer's
own tests stayed green on all three, because each side was right about its own half.

Rows pass through VERBATIM, so a row-level addition needs no projector edit. An ENVELOPE-level
one needs exactly one line. That asymmetry is the defect generator and it is what this file
watches.

── THE ARM THAT IS NOT LIKE THE OTHERS ─────────────────────────────────────────────────────

`test_the_projector_REFUSES_to_carry_identity` is not hygiene. **Measured 2026-09-19 against the
rolled sandbox**: the live NP-MERIDIAN response carries a real JWT at `identity.authorization` —
the graph threads the initiator's own credential through state and returns it, by design, because
engine-lg holds no standing credential of its own.

The projector builds its component from scratch and copies only the fields the tuple names, so
that token cannot reach a browser today. **The way it would reach one is somebody widening the
tuple in good faith** — `identity` reads like framing, it sits at the top level beside `summary`,
and a card that wanted to show "who asked" is a reasonable thing to want. A comment would be read
after the edit. This fails during it.

── WHAT THE POPULATION IS READ FROM ────────────────────────────────────────────────────────

cortex-ui's own contract file when the sibling repo is on disk, and a mirror otherwise, with the
two asserted EQUAL whenever both are available — the pattern
`tests/planning/test_producers_speak_their_archetype.py` established after a hand-copied list
nobody checked went stale.

⛔ **THE CONDITIONAL HALF IS THE CROSS-CHECK, NEVER THE ASSERTION.** Every claim here runs against
the mirror on every machine; only the "is the mirror still true of cortex" arm can be unavailable.
A seal that skips wholesale where the sibling repo is absent is a seal that does not run on the
machine gating merges, and this repo has already shipped a scan that announced *"cortex-ui not
checked out beside this repo"* on a machine where it was checked out.

**And the skip reason names the path it resolved**, so a false reason is visible rather than
plausible.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

#: cortex-ui's ledger package. A DIFFERENT directory from the one
#: tests/planning/test_producers_speak_their_archetype.py resolves (components/planning), which
#: is why SOURCE_LEDGER is exempt there and conformed here rather than repointing that name.
_LEDGER_CONTRACT = (_ROOT.parent / "cortex-ui" / "src" / "components" / "ledger"
                    / "SourceLedger.contract.ts")

# ── THE MIRRORS ─────────────────────────────────────────────────────────────────────────────
# Required and optional are kept apart because the projector's passthrough must carry BOTH (a
# field the producer may omit is still a field the card reads when present), while `rows` alone
# is what the payload key must resolve to.

#: `SOURCE_LEDGER_CONTRACT.fields` — every declared field, required or not.
_MIRROR_DECLARED = {"rows", "summary"}
#: the subset marked `required: true`
_MIRROR_REQUIRED = {"rows"}
#: `interface LedgerRow` — the per-row shape. `source` is the CARD's name for the wire's `row`.
_MIRROR_ROW_FIELDS = {"source", "label", "disposition", "artifact", "verdict", "reason"}
#: `LEDGER_DISPOSITIONS`
_MIRROR_DISPOSITIONS = {"finding", "unsummarised", "empty", "unentitled", "unavailable"}

#: The one renamed field, declared on BOTH sides and asserted below in both directions.
#: The wire says `row`; the card says `source`, because `row.row` reads as a mistake.
_WIRE_TO_CARD = {"row": "source"}


# ── reading the projector's own table ───────────────────────────────────────────────────────

def _projector_source() -> str:
    return (_ROOT / "agent_fleet" / "presentation_agent" / "main.py").read_text(encoding="utf-8")


def _projector_table_text() -> str:
    src = _projector_source()
    block = re.search(r"_PROJECTED_ARCHETYPES: Dict\[str, tuple\] = \{(.*?)^\}", src, re.S | re.M)
    assert block, "could not find _PROJECTED_ARCHETYPES -- the projector's shape moved"
    return block.group(1)


def _table() -> dict:
    """The projector's table, READ rather than imported.

    `presentation_agent/main.py` imports `baml_client`, which is that engine's declared
    dependency and not this one's -- importing it here would make a graph-host seal skip or
    error on a correctly provisioned lane venv, which is a seal that stops running for a reason
    that has nothing to do with what it checks. The planning suite's own coverage test reads
    this same table textually for the same reason.

    `ast.literal_eval` over the parsed assignment gives the REAL tuples (not a regex's idea of
    them) without executing a single import.
    """
    import ast

    tree = ast.parse(_projector_source())
    for node in ast.walk(tree):
        targets = getattr(node, "targets", None) or ([node.target] if hasattr(node, "target") else [])
        for t in targets:
            if isinstance(t, ast.Name) and t.id == "_PROJECTED_ARCHETYPES":
                return ast.literal_eval(node.value)
    raise AssertionError("_PROJECTED_ARCHETYPES is not assigned in main.py -- the table moved")


def _spec():
    return _table().get("SOURCE_LEDGER")


# ── reading cortex-ui's contract ────────────────────────────────────────────────────────────

def _contract_text():
    if not _LEDGER_CONTRACT.is_file():
        return None
    return _LEDGER_CONTRACT.read_text(encoding="utf-8")


def _strip_comments(body: str) -> str:
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return re.sub(r"//[^\n]*", "", body)


def _parse_declared_fields(text: str):
    """(all declared field names, the subset marked required) from SOURCE_LEDGER_CONTRACT."""
    m = re.search(r"fields:\s*\{(.*?)\n  \},", text, re.S)
    if not m:
        return None, None
    body = _strip_comments(m.group(1))
    declared, required = set(), set()
    for entry in re.finditer(r"^\s*(\w+):\s*\{([^}]*)\}", body, re.M):
        declared.add(entry.group(1))
        if re.search(r"required:\s*true", entry.group(2)):
            required.add(entry.group(1))
    return declared, required


def _parse_interface(text: str, name: str):
    """Field names of a TS interface, or None when it is not there."""
    m = re.search(r"export interface " + name + r" \{(.*?)^\}", text, re.S | re.M)
    if not m:
        return None
    body = _strip_comments(m.group(1))
    return {g for g in re.findall(r"^\s*(\w+)\??\s*:", body, re.M)}


def _parse_dispositions(text: str):
    m = re.search(r"LEDGER_DISPOSITIONS\s*=\s*\[(.*?)\]", text, re.S)
    if not m:
        return None
    return set(re.findall(r'"(\w+)"', m.group(1)))


_no_sibling = pytest.mark.skipif(
    not _LEDGER_CONTRACT.is_file(),
    reason=(
        "cortex-ui's ledger contract is not readable at the resolved path "
        + str(_LEDGER_CONTRACT)
        + " -- ONLY the mirror cross-check is unavailable; every assertion in this file still "
        "ran against the mirror. A skip here is not a pass and is not a claim about the card."
    ),
)


# ── the instrument, before anything it measures ─────────────────────────────────────────────

@_no_sibling
def test_the_PARSERS_actually_read_something_and_can_also_say_no():
    """Every matcher below returns a set, and an empty set from a broken regex reads exactly
    like a contract that declares nothing. Both directions, on the real file."""
    text = _contract_text()
    declared, required = _parse_declared_fields(text)
    assert declared, "the fields parser read NOTHING -- it is broken, not the contract"
    assert required, "the required parser read NOTHING"
    assert _parse_interface(text, "LedgerRow"), "the interface parser read NOTHING"
    assert _parse_dispositions(text), "the disposition parser read NOTHING"

    # ... and can say no. A parser that matches anything makes every agreement below vacuous.
    assert _parse_interface(text, "DefinitelyNotAnInterfaceInThisFile") is None


# ── site 2 exists, exactly once, and is shaped the way the table is ─────────────────────────

def test_the_projector_HAS_a_SOURCE_LEDGER_row():
    spec = _spec()
    assert spec is not None, (
        "SOURCE_LEDGER is bound in PRESENTATION_CAPABILITIES and has no projector row. "
        "The card mounts and refuses, and no test on either side catches it -- runbook site 2."
    )
    payload_key, passthrough = spec
    assert isinstance(payload_key, str) and isinstance(passthrough, tuple)


def test_SOURCE_LEDGER_is_declared_EXACTLY_ONCE_in_the_table():
    """A duplicate key in a dict literal is LAST-WINS and silent -- no SyntaxError, no warning,
    and `test_no_module_level_name_is_bound_twice` cannot see inside a dict.

    This is not hypothetical here. Two lanes were editing this table on the same night, both
    told to add this archetype; a textual merge of two additions to one dict conflicts on
    nothing, and the survivor is whichever landed lower in the file. That is the 2026-09-19
    `_EXEMPT` defect one level down, in a place with even less to announce it.
    """
    keys = re.findall(r'^\s*"(\w+)":', _projector_table_text(), re.M)
    assert len(keys) >= 5, "parsed " + str(keys) + " -- the regex is not reading the table"
    assert keys.count("SOURCE_LEDGER") == 1, (
        "SOURCE_LEDGER appears " + str(keys.count("SOURCE_LEDGER")) + " times in "
        "_PROJECTED_ARCHETYPES. Python keeps the LAST one silently; reconcile the two rows "
        "into one rather than deleting whichever looks unfamiliar."
    )


# ── the passthrough is what the card declares, and nothing else ─────────────────────────────

def test_the_PASSTHROUGH_is_the_cards_declared_ENVELOPE_fields():
    """The projector carries the payload key plus these fields and NOTHING ELSE, so a declared
    field missing here renders blank with every layer green."""
    payload_key, passthrough = _spec()
    carried = {payload_key} | set(passthrough)
    assert carried == _MIRROR_DECLARED, (
        "the projector carries " + str(sorted(carried)) + " and the card declares "
        + str(sorted(_MIRROR_DECLARED)) + ".\n"
        "  declared but not carried (renders blank): "
        + str(sorted(_MIRROR_DECLARED - carried)) + "\n"
        "  carried but not declared (advertised to nobody): "
        + str(sorted(carried - _MIRROR_DECLARED))
    )


def test_the_PAYLOAD_KEY_is_the_required_field_and_is_what_the_GRAPH_EMITS():
    payload_key, _ = _spec()
    assert _MIRROR_REQUIRED == {payload_key}, (
        "the payload key must be the card's REQUIRED field; required="
        + str(sorted(_MIRROR_REQUIRED)) + " payload_key=" + payload_key
    )
    # and the producer actually answers under that key -- read from the graph's state, not typed
    from agent_fleet.graph_host.graphs.fin_program_brief import BriefState

    assert payload_key in BriefState.__annotations__, (
        "the projector looks for '" + payload_key + "' and the brief's state has no such key"
    )


def test_the_projector_REFUSES_to_carry_identity():
    """⛔ `identity` holds the INITIATOR'S BEARER TOKEN. Measured on the rolled fleet
    2026-09-19: the live NP-MERIDIAN response carries a real JWT at `identity.authorization`.

    It is in the graph's state legitimately -- engine-lg holds no standing credential and
    threads the caller's own. It must never become a component field, and the way it would is
    an edit that looks like adding framing.
    """
    payload_key, passthrough = _spec()
    carried = {payload_key} | set(passthrough)
    assert "identity" not in carried, (
        "the SOURCE_LEDGER projector is carrying `identity`, which is the CALLER'S CREDENTIAL. "
        "This is a live bearer token on its way to a browser. Remove it; if a card needs to "
        "show who asked, the producer emits a name, not an authorization header."
    )
    # the same fact stated where an edit would be made, so the reason survives the next reader
    assert "identity" in BriefStateKeys(), (
        "this arm has gone vacuous: `identity` is no longer in the brief's state, so it is no "
        "longer a field anyone could add here by accident. Re-derive what this is guarding."
    )


def BriefStateKeys():
    from agent_fleet.graph_host.graphs.fin_program_brief import BriefState

    return set(BriefState.__annotations__)


def test_the_projector_carries_NEITHER_holes_NOR_findings():
    """Both are second copies of what `rows` already says. `holes` is a PROJECTION of rows and
    `findings` is the pre-rows accumulation; a card reading either alongside rows holds one
    fact in two places, and the derived copy is the one that keeps passing after someone edits
    the source. capabilities.py's site-4 row excludes `holes` in the same words."""
    payload_key, passthrough = _spec()
    carried = {payload_key} | set(passthrough)
    for second_copy in ("holes", "findings"):
        assert second_copy not in carried, (
            "the projector carries `" + second_copy + "` beside `rows`, which is one fact in "
            "two places"
        )


# ── the cross-repo joins: the rename, and the vocabulary ────────────────────────────────────

def test_the_RENAME_between_the_wire_and_the_card_is_declared_on_BOTH_sides():
    """`row` on the wire, `source` on the card. Each side is internally consistent and correct;
    the JOIN is the thing no per-side test can see, and a silent rename on either end leaves
    both suites green and the column blank."""
    from iagent_mesh import row as _row

    emitted = set(_row("fin_burn_rate", "cash burn", "finding", verdict="v"))
    translated = {_WIRE_TO_CARD.get(k, k) for k in emitted}
    assert translated == _MIRROR_ROW_FIELDS, (
        "the producer's row, translated through the declared rename, is "
        + str(sorted(translated)) + " and the card's LedgerRow is "
        + str(sorted(_MIRROR_ROW_FIELDS)) + ".\n"
        "If a field was renamed on one side, add it to _WIRE_TO_CARD *and* say so in both "
        "files -- an undeclared rename is indistinguishable from a dropped field."
    )
    # the rename is not a no-op smuggled in as one
    assert "row" in emitted and "source" not in emitted
    assert "source" in _MIRROR_ROW_FIELDS and "row" not in _MIRROR_ROW_FIELDS


def test_the_DISPOSITION_vocabulary_is_ONE_vocabulary():
    from iagent_mesh import HOLE_DISPOSITIONS, ROW_DISPOSITIONS

    assert set(ROW_DISPOSITIONS) == _MIRROR_DISPOSITIONS, (
        "the SDK emits " + str(sorted(ROW_DISPOSITIONS)) + " and the card knows "
        + str(sorted(_MIRROR_DISPOSITIONS)) + ". A term on one side only is a row the card "
        "names as unknown -- which it does deliberately, so this never shows up as a crash."
    )
    assert set(HOLE_DISPOSITIONS) <= _MIRROR_DISPOSITIONS


# ── the mirror is still true of cortex-ui ───────────────────────────────────────────────────

@_no_sibling
def test_the_MIRRORS_still_match_cortex_uis_contract():
    text = _contract_text()
    declared, required = _parse_declared_fields(text)
    assert declared == _MIRROR_DECLARED, (
        "_MIRROR_DECLARED has drifted.\n  contract has, mirror lacks: "
        + str(sorted(declared - _MIRROR_DECLARED)) + "\n  mirror has, contract lacks: "
        + str(sorted(_MIRROR_DECLARED - declared)) + "\n"
        "Update the mirror AND the projector passthrough -- widening the contract without "
        "widening the tuple is the blank-field defect this file exists for."
    )
    assert required == _MIRROR_REQUIRED
    assert _parse_interface(text, "LedgerRow") == _MIRROR_ROW_FIELDS
    assert _parse_dispositions(text) == _MIRROR_DISPOSITIONS


@_no_sibling
def test_the_cards_archetype_id_is_the_one_the_projector_keys_on():
    """The two repos agree on the STRING, which is the only thing joining them at runtime."""
    text = _contract_text()
    assert re.search(r'archetype:\s*"SOURCE_LEDGER"', text), (
        "cortex's contract does not declare archetype SOURCE_LEDGER at "
        + str(_LEDGER_CONTRACT) + " -- the id the projector keys on is not the id the card "
        "registers, and nothing at runtime would say so."
    )
