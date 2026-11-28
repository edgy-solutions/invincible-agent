"""A built-in's row may declare restatement templates over its own computed ranking (Q6).

The architect's ruling, verbatim: "The engine never names a cause and never chooses the selection.
It may write a sentence restating its own computed ranking, filled from the numbers, for example:
'Cost variance is -1.2M; control account 1.2 contributes 60%.' Each such sentence is a template a
row declares. The narrative of why stays a person's."

Seals: the ruling's own sentence byte for byte (U+2212); the served total reaching the rows; the fill
indexing the SERVED order (never the max); a sentence the rows cannot fill withheld, never part
filled; every load refusal with its message; the one formatter.

Run: uv run --no-sync pytest tests/finance/test_a_row_declares_its_restatements.py -q
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent import measure_verbs, measures  # noqa: E402
from agent_fleet.finance_agent.seed import build_seed  # noqa: E402

SEED_DIR = REPO / "policy" / "measure_verbs"
SHIPPED = SEED_DIR / "fin_variance_drivers.yaml"
BUILTINS = (measures.OUTPUT_URI, [v["verb"].split(":", 1)[-1] for v in engine.VERBS])
VERB = "fin_variance_drivers"
MINUS = "−"
RULING = "{kind} is {total}; {top_label} contributes {top_share}."


def _ranked(*triples, total="-1234567.00", kind="Cost variance"):
    """Served rows as the verb emits them: (label, contribution, share), in SERVED order."""
    return [{"entity_name": n, "contribution_exact": c, "share_of_total_exact": s,
             "property_label": kind, "value_unit": "USD", "variance_total_exact": total,
             "rank": i} for i, (n, c, s) in enumerate(triples, start=1)]


def _fill(template, rows, ident="x"):
    return measures.explanations_for(VERB, ((ident, template),), rows)


# -- the ruling's own sentence ------------------------------------------------------------------

def test_the_rulings_example_sentence_byte_for_byte():
    rows = _ranked(("control account 1.2", "-740740.20", "0.6"), ("other", "-493826.80", "0.4"))
    done, withheld = _fill(RULING, rows, "top_share")
    assert withheld == []
    assert done == [{
        "id": "top_share",
        "text": f"Cost variance is {MINUS}1.2M; control account 1.2 contributes 60%.",
        "filled_from": {"kind": "Cost variance", "total": "-1234567.00",
                        "top_label": "control account 1.2", "top_share": "0.6"},
    }]
    assert done[0]["text"].encode("utf-8") == (
        b"Cost variance is \xe2\x88\x921.2M; control account 1.2 contributes 60%.")


# -- end to end ---------------------------------------------------------------------------------

def _envelope(**params):
    return engine._measure_envelope(VERB, {"program_id": "NP-MERIDIAN", **params},
                                    caller="alice@example.com")


def test_the_ranking_serves_its_total_and_the_envelope_restates_it():
    env = _envelope(top_n=100)
    rows = env["rows"]
    assert len(rows) > 2, "this seal would pass vacuously on a one-row ranking"
    state = build_seed()
    wps = {w.wp_id for c in state.accounts_of("NP-MERIDIAN") for w in state.packages_of(c.ca_id)}
    total = measures._variance("cost", *measures._totals_exact(state, wps, None))
    for r in rows:
        assert Decimal(r["variance_total_exact"]) == total
        assert r["variance_total"] == float(total)
    assert sum(Decimal(r["contribution_exact"]) for r in rows) == total
    shipped = env["explanations"][0]
    top = rows[0]
    assert shipped["id"] == "top_share"
    assert shipped["text"] == (
        f"{top['property_label']} is {measures.prose_money(Decimal(top['variance_total_exact']))}; "
        f"{top['entity_name']} contributes "
        f"{measures.prose_share(Decimal(top['share_of_total_exact']))}.")
    assert shipped["filled_from"] == {
        "kind": top["property_label"], "total": top["variance_total_exact"],
        "top_label": top["entity_name"], "top_share": top["share_of_total_exact"]}
    assert "explanations_withheld" not in env


def test_the_total_rides_on_every_row_of_a_truncated_ranking():
    rows = _envelope(top_n=1)["rows"]
    assert len(rows) == 1 and rows[0]["withheld_contributors"] > 0
    assert "variance_total_exact" in rows[0]


def test_CONTROL_a_row_declaring_nothing_serves_neither_key(monkeypatch):
    monkeypatch.setitem(engine.SOURCES, VERB, measure_verbs.SourceRow(VERB, "asset"))
    env = _envelope()
    assert "explanations" not in env and "explanations_withheld" not in env
    assert env["rows"], "a control over an empty answer proves nothing"


# -- the selection is the engine's ranking, not the fill's --------------------------------------

def test_the_fill_names_the_first_SERVED_row_not_the_max():
    # served by |contribution|: the top row is the favourable (negative) one, so neither the max
    # contribution (rank 2) nor a re-sort could be mistaken for the served first row.
    rows = _ranked(("favourable ca", "-1500.00", "-15"), ("big ca", "1000.00", "10"),
                   ("small ca", "400.00", "4"), total="100.00")
    done, _ = _fill("{top_label} {top_contribution} {top_share}; {rank2_label} {rank3_label}", rows)
    assert done[0]["text"] == f"favourable ca {MINUS}1.5K {MINUS}1500%; big ca small ca"


# -- a sentence the rows cannot fill is withheld ------------------------------------------------

def test_a_placeholder_with_no_row_withholds_the_sentence():
    rows = _ranked(("a", "-10.00", "0.5"), ("b", "-10.00", "0.5"))
    done, withheld = _fill("{rank1_label} then {rank3_share}", rows, "third")
    assert done == []
    assert withheld == [{"id": "third", "reason": "the answer serves no field for {rank3_share}"}]


def test_no_rows_and_no_share_withhold_too():
    assert _fill(RULING, [])[0] == []
    done, withheld = _fill("{top_share}", _ranked(("a", "0.00", None)))
    assert done == [] and withheld[0]["id"] == "x"


# -- load refusals ------------------------------------------------------------------------------

def _row(*explanations, **extra):
    return {"measure_id": VERB, "source": "asset", "name": "Variance drivers",
            "description": "d", "explanations": list(explanations), **extra}


def _load(tmp_path, raw):
    d = tmp_path / "ov"
    d.mkdir(exist_ok=True)
    (d / "row0.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return measure_verbs.load_measure_sources(policy_dir=tmp_path / "no-seed",
                                              overlay_dirs=[d], builtins=BUILTINS)


def _refused(tmp_path, raw, *fragments):
    with pytest.raises(measure_verbs.MeasureVerbError) as ei:
        _load(tmp_path, raw)
    msg = str(ei.value)
    assert "row0.yaml" in msg, f"the refusal does not name the file: {msg}"
    for f in fragments:
        assert f in msg, f"expected {f!r} in: {msg}"


def _t(template, ident="s1"):
    return {"id": ident, "template": template}


def test_an_unknown_placeholder_is_refused(tmp_path):
    _refused(tmp_path, _row(_t("{kind} and {worst_label}")), "'s1'",
             "unknown placeholder {worst_label}")


@pytest.mark.parametrize("bad", ["{total:.0f}", "{top_label!r}"])
def test_a_format_spec_or_conversion_is_refused(tmp_path, bad):
    _refused(tmp_path, _row(_t(bad)), "'s1'", "format spec or conversion")


@pytest.mark.parametrize("bad,why", [("{kind", "unbalanced brace"), ("kind}", "unbalanced brace"),
                                     ("{ki{nd}}", "nested brace")])
def test_an_unbalanced_or_nested_brace_is_refused(tmp_path, bad, why):
    _refused(tmp_path, _row(_t(bad)), "'s1'", why)


def test_an_empty_template_is_refused(tmp_path):
    _refused(tmp_path, _row(_t("  ")), "'s1'", "the template is empty")


def test_a_duplicate_id_is_refused(tmp_path):
    _refused(tmp_path, _row(_t("{kind}", "a"), _t("{unit}", "a")), "'a' is declared twice")


@pytest.mark.parametrize("bad", ["not a list", [{"id": "a"}], [{"id": "a", "template": "x", "z": 1}],
                                 ["{kind}"], []])
def test_explanations_must_be_a_list_of_id_template_mappings(tmp_path, bad):
    _refused(tmp_path, _row() | {"explanations": bad}, "exactly `id` and `template`")


def test_an_id_must_be_a_slug(tmp_path):
    _refused(tmp_path, _row(_t("{kind}", "Top Share")), "^[a-z0-9_]+$")


@pytest.mark.parametrize("word", ["because", "due to", "caused", "causes", "driven by", "owing to",
                                  "as a result of", "reason", "attributable to", "on account of"])
def test_a_cause_word_in_the_literal_text_is_refused(tmp_path, word):
    _refused(tmp_path, _row(_t(f"{{kind}} fell {word.upper()} {{top_label}}")), "'s1'",
             repr(word), "the narrative of why stays a person's")


def test_the_cause_words_are_exactly_the_ten_ruled():
    assert set(measures.CAUSE_WORDS) == {
        "because", "due to", "caused", "causes", "driven by", "owing to", "as a result of",
        "reason", "attributable to", "on account of"}


def test_the_tripwire_reads_words_not_fragments(tmp_path):
    assert _load(tmp_path, _row(_t("{kind} is reasonable at {top_label}.")))[0].explanations


def test_a_builtin_with_no_vocabulary_is_refused_naming_the_verbs_that_have_one(tmp_path):
    raw = {"measure_id": "fin_funding_status", "source": "seed", "reason": "r", "ratified_by": "o",
           "name": "Funding", "description": "d", "explanations": [_t("{kind}")]}
    _refused(tmp_path, raw, "'fin_funding_status'", "no placeholder vocabulary", VERB)


def test_a_declared_measure_row_still_refuses_the_key(tmp_path):
    sample = yaml.safe_load((REPO / "policy" / "overlays" / "sample" / "measure_verbs"
                             / "fin_vac.yaml").read_text(encoding="utf-8"))
    sample["explanations"] = [_t("{kind}")]
    d = tmp_path / "ov"
    d.mkdir()
    (d / "row0.yaml").write_text(yaml.safe_dump(sample, sort_keys=False), encoding="utf-8")
    with pytest.raises(measure_verbs.MeasureVerbError, match="explanations"):
        measure_verbs.load_measure_verbs(policy_dir=tmp_path / "no-seed", overlay_dirs=[d],
                                         builtins=BUILTINS)


def test_CONTROL_the_shipped_row_loads_and_is_read_from_disk():
    on_disk = yaml.safe_load(SHIPPED.read_text(encoding="utf-8"))
    assert on_disk["explanations"] == [{"id": "top_share", "template": RULING}]
    row = {r.measure_id: r for r in measure_verbs.load_measure_sources(
        policy_dir=SEED_DIR, overlay_dirs=[], builtins=BUILTINS)}[VERB]
    assert row.explanations == (("top_share", RULING),)
    assert engine.SOURCES[VERB].explanations == row.explanations


# -- the one formatter --------------------------------------------------------------------------

@pytest.mark.parametrize("value,want", [
    ("-1234567", f"{MINUS}1.2M"), ("350000", "350K"), ("999950", "1M"), ("999949.99", "999.9K"),
    ("2500000000", "2.5B"), ("0", "0"), ("0.01", "0.01"), ("999.50", "999.50"), ("12.00", "12"),
    ("-0.01", f"{MINUS}0.01"), ("1000", "1K"), ("999999999", "1B"), ("-350000", f"{MINUS}350K"),
])
def test_prose_money(value, want):
    got = measures.prose_money(Decimal(value))
    assert got == want
    assert "-" not in got


@pytest.mark.parametrize("value,want", [("0.6", "60%"), ("-0.114", f"{MINUS}11%"), ("0.005", "1%"),
                                        ("-0.001", "0%"), ("1.2", "120%"), ("0", "0%")])
def test_prose_share(value, want):
    got = measures.prose_share(Decimal(value))
    assert got == want
    assert "-" not in got
