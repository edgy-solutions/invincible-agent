"""contracts/ev_fixture.yaml marks, line by line, what every contract has and what is only this one's.

A deployment writing its own contract copies this template. Without marks it cannot tell the shape
the reader requires (`format`) from the values the earned-value fixture happens to carry
(`ev_fixture`). Every line ends with tags (the legend is the file's own header), and the tags are
a claim, so each is derived here from the reader rather than typed twice:

  * a top-level key's tag is found by deleting the key and loading the file through the shared
    parser: it raises (`format`), it loads to a different contract (`optional`), it loads to the
    same one (`unread`);
  * a column sub-key's tag is read from `_parse`'s source: `col["k"]` is `format`, `col.get("k")` is
    `optional`, any other sub-key the template's columns use is `unread`;
  * a rule id's tag is read from the sets that raise it.

Marking the file moves nothing the reader sees: the parse with every comment stripped equals the
parse of the file as shipped.

Run: uv run --no-sync python -I -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/finance/test_the_ev_contract_marks_format_from_instance.py
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest
import yaml

from agent_fleet.finance_agent import asset_inputs
from agent_fleet.utils import dataset_contracts

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "ev_fixture.yaml"
TEXT = CONTRACT.read_text(encoding="utf-8")
LINES = TEXT.split("\n")

KEY_TAGS = {"format", "optional", "unread"}
VALUE_TAGS = {"ev_fixture", "general"}
RULE_TAGS = {"shared", "engine-fin", "ev_fixture"}
ALL_TAGS = KEY_TAGS | VALUE_TAGS | RULE_TAGS
TRAILER = re.compile(r"\s#((?:\s\[[a-z_-]+\])+)\s*$")
TAG = re.compile(r"\[([a-z_-]+)\]")
TOP_KEY = re.compile(r"^([A-Za-z_][\w/]*):(.*)$")


def tags_of(line: str) -> list[str]:
    m = TRAILER.search(line)
    return TAG.findall(m.group(1)) if m else []


def _top_lines() -> dict[str, tuple[int, str]]:
    out = {}
    for i, line in enumerate(LINES):
        m = TOP_KEY.match(line)
        if m:
            out[m.group(1)] = (i, m.group(2).strip())
    return out


TOP = _top_lines()


def _section_of(index: int) -> str | None:
    owner = None
    for i in range(index + 1):
        m = TOP_KEY.match(LINES[i])
        if m:
            owner = m.group(1)
    return owner


def _shipped():
    return dataset_contracts.load_contracts(CONTRACT)["ev_fixture"]


def _without_key(key: str, tmp_path: Path):
    raw = yaml.safe_load(TEXT)
    del raw[key]
    path = tmp_path / "ev_fixture.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return dataset_contracts.load_contracts(path)["ev_fixture"]


def test_every_tag_in_the_file_is_one_the_legend_names():
    seen = {t for line in LINES for t in tags_of(line)}
    assert seen <= ALL_TAGS, sorted(seen - ALL_TAGS)
    assert {"format", "optional", "unread", "ev_fixture", "general", "shared", "engine-fin"} <= seen


@pytest.mark.parametrize("key", sorted(TOP))
def test_a_top_level_key_carries_one_key_tag_and_it_is_the_derived_one(key, tmp_path):
    index, _ = TOP[key]
    tags = [t for t in tags_of(LINES[index]) if t in KEY_TAGS]
    assert len(tags) == 1, f"{key}: {tags_of(LINES[index])}"
    try:
        other = _without_key(key, tmp_path)
    except (ValueError, KeyError, TypeError):
        derived = "format"
    else:
        derived = "optional" if other != _shipped() else "unread"
    assert tags[0] == derived, f"{key} is tagged [{tags[0]}], and deleting it says [{derived}]"


def _column_subkeys_from_parse() -> dict[str, set[str]]:
    """How `_parse` reads each column sub-key: subscript (format) or `.get` (optional)."""
    tree = ast.parse(inspect.getsource(dataset_contracts._parse))
    subscript, getter = set(), set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                and node.value.id == "col" and isinstance(node.slice, ast.Constant)):
            subscript.add(node.slice.value)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "col" and node.args
                and isinstance(node.args[0], ast.Constant)):
            getter.add(node.args[0].value)
    used = {k for col in yaml.safe_load(TEXT)["columns"] for k in col}
    return {"format": subscript, "optional": getter, "unread": used - subscript - getter}


def test_the_column_keys_line_states_what_the_parser_reads():
    line = next((l for l in LINES if l.startswith("# Column keys:")), None)
    assert line is not None, "no `# Column keys:` line above `columns:`"
    derived = _column_subkeys_from_parse()
    stated: dict[str, set[str]] = {}
    for group in re.findall(r"([\w, ]+?)\s*\[(format|optional|unread)\]", line.split(":", 1)[1]):
        names = {n.strip() for n in group[0].split(",") if n.strip()}
        stated[group[1]] = names
    assert stated == derived, f"the line says {stated}; the parser says {derived}"


def test_the_column_keys_line_sits_in_the_comment_block_above_columns():
    at = next(i for i, l in enumerate(LINES) if l.startswith("# Column keys:"))
    assert LINES[at + 1].startswith("columns:")


def _items(section: str) -> list[str]:
    start = TOP[section][0]
    out = []
    for line in LINES[start + 1:]:
        if TOP_KEY.match(line):
            break
        if re.match(r"^  - ", line):
            out.append(line)
    return out


@pytest.mark.parametrize("section", ["columns", "dependencies"])
def test_every_item_of_the_section_carries_ev_fixture(section):
    items = _items(section)
    assert items
    for line in items:
        assert tags_of(line) == ["ev_fixture"], line[:60]


def _value_lines() -> list[tuple[int, str]]:
    """Every line carrying a value: `key: value` with a non-empty value, or a list item. Rule
    entries are excluded: their tag names who raises the rule, not whose value it is."""
    out = []
    for i, line in enumerate(LINES):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if _section_of(i) == "rules":
            continue
        top = TOP_KEY.match(TRAILER.sub("", line))
        if top:
            if top.group(2).strip():
                out.append((i, line))
            continue
        nested = re.match(r"^  ([\w/]+):\s*(\S.*)$", line)
        if nested and not re.match(r"^  - ", line):
            out.append((i, line))
        elif re.match(r"^  - ", line):
            out.append((i, line))
    return out


def test_every_line_with_a_value_names_whose_it_is():
    lines = _value_lines()
    assert len(lines) > 25
    for i, line in lines:
        values = [t for t in tags_of(line) if t in VALUE_TAGS]
        assert len(values) == 1, f"line {i + 1}: {line[:70]}"


def test_a_key_under_an_unread_parent_is_unread():
    for i, line in enumerate(LINES):
        if re.match(r"^  [\w/]+:", line) and _section_of(i) in {
                "dataset", "limits", "cadence", "tags"}:
            assert "unread" in tags_of(line), f"line {i + 1}: {line[:70]}"


def test_under_period_only_the_calendar_is_read():
    """The parser reads `period.calendar` and nothing else under `period` (ruled 2026-11-23)."""
    seen = set()
    for i, line in enumerate(LINES):
        m = re.match(r"^  ([\w/]+):", line)
        if m and _section_of(i) == "period":
            seen.add(m.group(1))
            read = "unread" not in tags_of(line)
            assert read == (m.group(1) == "calendar"), f"line {i + 1}: {line[:70]}"
    assert "calendar" in seen


def _rules_tagged() -> dict[str, set[str]]:
    start = TOP["rules"][0]
    out: dict[str, set[str]] = {t: set() for t in RULE_TAGS}
    for line in LINES[start + 1:]:
        if TOP_KEY.match(line):
            break
        m = re.match(r"^  ([a-z_]+):", line)
        if m:
            tags = [t for t in tags_of(line) if t in RULE_TAGS]
            assert len(tags) == 1, f"{m.group(1)}: {tags_of(line)}"
            out[tags[0]].add(m.group(1))
    return out


def test_the_rule_tags_partition_the_rules():
    rules = set(yaml.safe_load(TEXT)["rules"])
    tagged = _rules_tagged()
    assert tagged["shared"] == rules & set(dataset_contracts.RULES)
    own = tagged["engine-fin"] | tagged["ev_fixture"]
    assert own == rules - set(dataset_contracts.RULES)
    assert not tagged["engine-fin"] & tagged["ev_fixture"]
    assert own <= asset_inputs.RULES | dataset_contracts.PRODUCER_CHECKED


def test_the_ev_fixture_rules_are_the_earned_value_shape_s_own():
    """Not engine-fin's on every dataset: the key and dependencies of this template."""
    assert _rules_tagged()["ev_fixture"] == {
        "program_name_not_unique", "program_bac_not_unique",
        "work_package_in_two_accounts", "duplicate_work_package_period"}


def test_the_marking_does_not_move_the_parse(tmp_path):
    stripped = "\n".join(re.sub(r"\s+#\s.*$", "", l) if not l.lstrip().startswith("#") else ""
                         for l in LINES)
    path = tmp_path / "ev_fixture.yaml"
    path.write_text(stripped, encoding="utf-8")
    assert dataset_contracts.load_contracts(path)["ev_fixture"] == _shipped()


def test_the_template_names_no_fiscal_year_constant():
    raw = yaml.safe_load(TEXT)
    # The template names its calendar by id, an instance value; the periods live in the calendar.
    assert raw["period"]["calendar"] == "us_federal_fy26"
    line = next(x for x in LINES if re.match(r"^  calendar:", x))
    assert "ev_fixture" in tags_of(line)
    assert "FISCAL_PERIODS" not in TEXT
    assert "FY27" not in TEXT


GUIDE = ROOT / "docs" / "contracts" / "adding-a-measure-by-declaration.md"


def _guide_table() -> dict[str, set[str]]:
    """The three rows of the rule-id table in the guide, each row's ids from its backticks."""
    section = GUIDE.read_text(encoding="utf-8").split("### Which rule ids are general", 1)[1]
    section = section.split("\n## ", 1)[0]
    rows = {}
    for line in section.split("\n"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 3 and cells[0].startswith("**"):
            rows[cells[0].strip("*")] = set(re.findall(r"`([a-z_]+)`", cells[1]))
    return rows


def test_the_guide_s_rule_table_is_the_template_s_and_the_reader_s():
    rows = _guide_table()
    assert set(rows) == {"every contract", "every finance read", "the earned-value shape only"}
    tagged = _rules_tagged()
    # the shared row lists every id the shared reader raises, so it holds the template's
    # [shared] ids and may hold more (personal_data is raised by the reader, named by no template rule)
    assert rows["every contract"] == set(dataset_contracts.RULES)
    assert tagged["shared"] <= rows["every contract"]
    assert rows["every finance read"] == tagged["engine-fin"]
    assert rows["the earned-value shape only"] == tagged["ev_fixture"]


def test_the_guide_names_the_producer_checked_ids_the_reader_names():
    assert dataset_contracts.PRODUCER_CHECKED == {"interval_overlap", "orphan_reference"}
    text = GUIDE.read_text(encoding="utf-8")
    assert "`interval_overlap` and `orphan_reference` are checked by the producer" in text
