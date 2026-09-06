"""A SLOT THE USER PICKED FROM A MENU MUST APPEAR IN THE DISCLOSURE.

WALKED 2026-09-05, and the strip was blank under the gantt. Nine options rendered, the person
tapped *Inventory Visibility*, `validate_bound_slots` accepted `C4`, the verb ran, the answer
drew — and the disclosure strip showed nothing about the one thing the person had most
directly done.

THE STRIP WAS CORRECT BY ITS OWN RULES. It renders rows from `slot_resolution` and draws
nothing on absence, by design. There were no rows. `slot_resolution` is produced by the FILLER,
and a BIND never reaches the filler — that is what makes it a BIND. So a pick was a third
provenance with no record: not spoken-and-narrowed, not refused, simply absent.

Same family as `too_many`'s count living only in prose and refusals serialised as sentences:
**the fact existed and the field did not.** And the label was thrown away one line after the
only point that knew it — `validate_bound_slots` built its offered list as ids alone, having
just read `{instance_id, label}` from the enumerator.

`BOUND` IS ITS OWN OUTCOME, not a reuse. Engine O's resolver vocabulary is
`exact | fuzzy | mixed | not_specific | empty | not-attempted`; calling a pick `exact` would
claim the resolver did work it never did. A pick is a different act and says so.

ON THE SPEC: the dispatch asked that a RESPEAK's row carry `outcome: "resolved"`. **There is no
`resolved` in the vocabulary** — a RESPEAK answer becomes a spoken slot value and the resolver
gives it `exact` (or `fuzzy`, or `empty`) like anything else a person said. Asserting `resolved`
would pin a state the system never enters, which is the law this repo spent the week learning.
So the RESPEAK half is sealed on what it must DO — reach the filler and get a row that renders
— not on a literal nothing emits.

Run: uv run --frozen pytest tests/routing/test_a_pick_gets_a_row.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent_pure.slot_disposition import BOUND, validate_bound_slots  # noqa: E402

_SUP = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")
_EO = (_REPO / "agent_fleet" / "ontology_service" / "main.py").read_text(encoding="utf-8")

_DECL = '[{"name": "capability_id", "kind": "spoken-mandatory", "referent": "idp#Capability"}]'


def _menu(*members):
    return lambda _cls: {"outcome": "members", "members": list(members)}


_NINE = _menu(
    {"instance_id": "C1", "label": "Financial Close Automation"},
    {"instance_id": "C4", "label": "Inventory Visibility"},
    {"instance_id": "C7", "label": "Integration Platform"},
)


# ── the row exists and says what the person clicked ─────────────────────────

def test_a_bound_slot_produces_a_resolution_row():
    _, refusals, resolution = validate_bound_slots(
        {"capability_id": "C4"}, declared=_DECL, enumerate_class=_NINE,
    )
    assert not refusals
    assert "capability_id" in resolution, "a pick still has no row — the strip stays blank"


def test_spoken_is_the_LABEL_the_user_clicked():
    """THE WHOLE POINT. `C4` is what the system stores; *Inventory Visibility* is what the
    person read and tapped. A strip that says `capability_id: C4 → C4` discloses nothing —
    it shows the machine its own value back."""
    _, _, resolution = validate_bound_slots(
        {"capability_id": "C4"}, declared=_DECL, enumerate_class=_NINE,
    )
    row = resolution["capability_id"]
    assert row["spoken"] == "Inventory Visibility"
    assert row["instance_id"] == "C4"


def test_the_outcome_is_BOUND_and_not_borrowed():
    """`exact` would claim the resolver narrowed something. It did not — the menu did."""
    _, _, resolution = validate_bound_slots(
        {"capability_id": "C4"}, declared=_DECL, enumerate_class=_NINE,
    )
    assert resolution["capability_id"]["outcome"] == BOUND == "bound"


def test_BOUND_is_outside_engine_os_resolver_vocabulary():
    """A new value must not collide with one the resolver already means something by."""
    assert "outcome\": exact|fuzzy|mixed|not_specific|empty|not-attempted" in _EO or (
        "exact|fuzzy|mixed" in _EO
    ), "engine-o's documented outcome vocabulary moved — re-check the collision"
    assert BOUND not in ("exact", "fuzzy", "mixed", "not_specific", "empty", "not-attempted")


def test_the_row_has_the_same_shape_a_FILLED_slot_has():
    """The strip renders both through one path. A row missing a key the renderer reads is a
    row that draws as blank, which is the defect wearing a new hat."""
    _, _, resolution = validate_bound_slots(
        {"capability_id": "C4"}, declared=_DECL, enumerate_class=_NINE,
    )
    assert set(resolution["capability_id"]) >= {"outcome", "spoken", "instance_id"}


# ── the honest edges ────────────────────────────────────────────────────────

def test_a_REFUSED_pick_gets_no_row():
    """A refusal already has its own record in `refused_slots`. Writing a resolution row for
    it too would render a value the verb never received as though it had been used."""
    _, refusals, resolution = validate_bound_slots(
        {"capability_id": "C99"}, declared=_DECL, enumerate_class=_NINE,
    )
    assert refusals and "capability_id" not in resolution


def test_a_pick_with_no_label_falls_back_to_the_value():
    """An enumerator that returns ids without labels must still yield a renderable row —
    `C4 → C4` says little, but a missing row says nothing at all."""
    _, _, resolution = validate_bound_slots(
        {"capability_id": "C4"}, declared=_DECL,
        enumerate_class=_menu({"instance_id": "C4"}),
    )
    assert resolution["capability_id"]["spoken"] == "C4"


def test_every_return_path_has_the_same_arity():
    """The error return and the happy return are ~60 lines apart, and a caller unpacking
    three names from a two-tuple raises deep inside routing. One of these WAS a 2-tuple when
    the third field was added."""
    import ast
    import inspect

    src = inspect.getsource(validate_bound_slots)
    lens = {
        len(n.value.elts)
        for n in ast.walk(ast.parse(src.lstrip()))
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple)
    }
    assert lens == {3}, f"validate_bound_slots returns tuples of {sorted(lens)}"


# ── the supervisor actually merges it ───────────────────────────────────────

def test_the_supervisor_merges_bound_rows_into_the_artifact():
    """A row the validator produces and the supervisor drops is the orphan shape — and it
    would leave the strip exactly as blank as before."""
    assert "picked, refusals, bound_resolution = validate_bound_slots(" in _SUP
    assert "resolution = {**resolution, **bound_resolution}" in _SUP


def test_the_merge_happens_where_the_artifact_can_still_see_it():
    """`slot_resolution` is emitted at the disposition point. A merge after that emission
    would be correct code writing to a record already sent."""
    merge = _SUP.index("resolution = {**resolution, **bound_resolution}")
    emit = _SUP.index('"slot_resolution": MetadataValue.text(')
    assert merge < emit, "the bound rows are merged after the artifact is written"
