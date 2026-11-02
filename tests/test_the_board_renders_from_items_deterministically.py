"""The cross-lane board renders deterministically from one file per item.

Fixture boards use generic slugs (alpha, beta); the real slugs live only in board/PRIORITIES.md.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "render_board.py"

_spec = importlib.util.spec_from_file_location("render_board", SCRIPT)
rb = importlib.util.module_from_spec(_spec)
import sys  # noqa: E402

sys.modules["render_board"] = rb
_spec.loader.exec_module(rb)

A = "01ARZ3NDEKTSV4RRFFQ69G5FAA"
B = "01ARZ3NDEKTSV4RRFFQ69G5FAB"
C = "01ARZ3NDEKTSV4RRFFQ69G5FAC"
D = "01ARZ3NDEKTSV4RRFFQ69G5FAD"

PRIORITIES = """# Priorities

## Features

| rank | feature | name |
| --- | --- | --- |
| 1 | `alpha` | Alpha Feature |
| 2 | `beta` | Beta Feature |

## Item priority

| priority | meaning |
| --- | --- |
| `now` | n |
| `next` | x |

## Reorders

- 2026-01-01 initial order
"""

SWEEP = "---\nswept_at:\n---\n\n| item | flag |\n| --- | --- |\n"


def item(**over) -> str:
    fm = {
        "title": "An item", "feature": "alpha", "lane": "repo-x/lane-1", "repo": "repo-x",
        "status": "claimed", "priority": "now", "blocked_on": "[]", "pr": "[]",
        "ruling_ref": "", "updated": "2026-01-02",
    }
    fm.update(over)
    fm = {k: v for k, v in fm.items() if v is not None}
    return "---\n" + "".join(f"{k}: {v}\n" for k, v in fm.items()) + "---\n\nbody text\n"


def make(tmp, items: dict[str, str], sweep: str = SWEEP, order=None) -> Path:
    bd = Path(tmp)
    (bd / "items").mkdir(parents=True, exist_ok=True)
    (bd / "PRIORITIES.md").write_text(PRIORITIES, encoding="utf-8")
    (bd / "SWEEP.md").write_text(sweep, encoding="utf-8")
    names = list(items) if order is None else order
    for n in names:
        (bd / "items" / (n if n.endswith(".md") else n + ".md")).write_text(items[n], encoding="utf-8")
    return bd


def errors_of(bd) -> list[str]:
    with pytest.raises(rb.BoardError) as ei:
        rb.load(bd)
    return ei.value.errors


def base_items() -> dict[str, str]:
    return {
        A: item(title="Alpha one", priority="next"),
        B: item(title="Alpha two", feature="alpha", priority="now", status="open", lane=""),
        C: item(title="Beta one", feature="beta", status="review", pr="[repo-x#12, repo-y#3]"),
    }


def test_render_is_deterministic(tmp_path):
    items = base_items()
    d1 = make(tmp_path / "one", items)
    d2 = make(tmp_path / "two", items, order=list(reversed(list(items))))
    r1 = rb.render(rb.load(d1))
    assert r1 == rb.render(rb.load(d1))
    assert r1 == rb.render(rb.load(d2))
    assert "\r" not in r1 and r1.endswith("\n") and not r1.endswith("\n\n")
    assert r1.index("Alpha two") < r1.index("Alpha one")  # now before next


def test_zero_items_render(tmp_path):
    out = rb.render(rb.load(make(tmp_path, {})))
    assert "0 items" in out and "never swept" in out
    assert out.count("Where it is: no items") == 2
    assert "## Waiting on Chris\n\n(none)" in out


def test_gitkeep_is_ignored(tmp_path):
    bd = make(tmp_path, {})
    (bd / "items" / ".gitkeep").write_text("", encoding="utf-8")
    rb.load(bd)


@pytest.mark.parametrize(
    "over,field",
    [
        ({"feature": "nope"}, "feature"),
        ({"priority": "nope"}, "priority"),
        ({"status": "nope"}, "status"),
        ({"status": "blocked", "blocked_on": "[]"}, "blocked_on"),
        ({"status": "review", "pr": "[]"}, "pr"),
        ({"status": "claimed", "lane": ""}, "lane"),
        ({"blocked_on": "[" + B + "]"}, "blocked_on"),  # non-blocked with blockers
    ],
)
def test_field_errors_name_file_and_field(tmp_path, over, field):
    bd = make(tmp_path, {A: item(**over)})
    errs = errors_of(bd)
    assert any(e.startswith(f"items/{A}.md: {field}: ") for e in errs), errs


def test_missing_and_extra_key(tmp_path):
    bd = make(tmp_path, {A: item(pr=None, bogus="1")})
    errs = errors_of(bd)
    assert f"items/{A}.md: pr: missing key" in errs
    assert f"items/{A}.md: bogus: unknown key" in errs


def test_bad_filename(tmp_path):
    bd = make(tmp_path, {"not-a-ulid": item()})
    assert any(e.startswith("items/not-a-ulid.md: filename: ") for e in errors_of(bd))


def test_blocked_on_unknown_id_or_self(tmp_path):
    ghost = "01ARZ3NDEKTSV4RRFFQ69G5FZZ"
    bd = make(tmp_path, {A: item(status="blocked", blocked_on=f"[{ghost}]"),
                         B: item(status="blocked", blocked_on=f"[{B}]")})
    errs = errors_of(bd)
    assert any(e.startswith(f"items/{A}.md: blocked_on: unknown") for e in errs), errs
    assert any(e.startswith(f"items/{B}.md: blocked_on: item cannot") for e in errs), errs


def test_every_error_is_printed(tmp_path, capsys):
    bd = make(tmp_path, {A: item(feature="nope", priority="nope"), "bad": item()})
    assert rb.main(["--board-dir", str(bd)]) == 2
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) >= 3 and all(re.match(r"^\S.*: \S.*: .+", ln) for ln in lines)


def test_sweep_unknown_item(tmp_path):
    sweep = SWEEP + "| 01ARZ3NDEKTSV4RRFFQ69G5FZZ | stale |\n"
    errs = errors_of(make(tmp_path, base_items(), sweep=sweep))
    assert any(e.startswith("SWEEP.md: item: ") for e in errs), errs


def test_sweep_row_renders_against_item(tmp_path):
    sweep = SWEEP + f"| {A} | looks stale |\n"
    out = rb.render(rb.load(make(tmp_path, base_items(), sweep=sweep)))
    assert "⚑ looks stale" in out


def test_chris_blocker_is_waiting_on_chris(tmp_path):
    items = {A: item(title="Needs Chris", status="blocked", blocked_on="[chris:approve the thing]")}
    out = rb.render(rb.load(make(tmp_path, items)))
    sec = out.split("## Waiting on Chris")[1].split("## Flags")[0]
    assert "[Needs Chris](items/" in sec and "approve the thing" in sec and "Alpha Feature" in sec
    assert "blocked on chris:approve the thing" in out


def test_done_blocker_is_flagged(tmp_path):
    items = {A: item(title="Finished", status="done"),
             B: item(title="Stuck", status="blocked", blocked_on=f"[{A}]")}
    out = rb.render(rb.load(make(tmp_path, items)))
    flags = out.split("## Flags")[1].split("## 1.")[0]
    assert "blocker Finished is done" in flags
    assert "⚑ blocker Finished is done" in out


def test_done_items_are_counted_not_listed(tmp_path):
    items = {A: item(title="Finished", status="done"), B: item(title="Live", status="open", lane="")}
    out = rb.render(rb.load(make(tmp_path, items)))
    assert "1 done" in out and "[Finished]" not in out and "[Live]" in out
    assert "next: Live" in out


def test_new_id_pattern_and_uniqueness(capsys):
    assert rb.main(["--new-id"]) == 0
    a = capsys.readouterr().out.strip()
    assert rb.main(["--new-id"]) == 0
    b = capsys.readouterr().out.strip()
    assert rb.ULID_RE.match(a) and rb.ULID_RE.match(b) and a != b


def test_check_reports_drift(tmp_path, capsys):
    bd = make(tmp_path, base_items())
    assert rb.main(["--board-dir", str(bd)]) == 0
    assert rb.main(["--board-dir", str(bd), "--check"]) == 0
    (bd / "BOARD.md").write_text("stale\n", encoding="utf-8")
    assert rb.main(["--board-dir", str(bd), "--check"]) == 1
    assert capsys.readouterr().out.startswith("DRIFT")


def test_committed_board_equals_render():
    """The drift reader."""
    want = rb.render(rb.load(REPO / "board"))
    have = (REPO / "board" / "BOARD.md").read_bytes().decode("utf-8")
    assert have == want, "board/BOARD.md is stale; run scripts/render_board.py"


def test_no_real_slug_in_script():
    text = (REPO / "board" / "PRIORITIES.md").read_text(encoding="utf-8")
    slugs = [f[1] for f in rb.load(REPO / "board").features]
    assert slugs and all(s in text for s in slugs)
    code = SCRIPT.read_text(encoding="utf-8")
    assert [s for s in slugs if s in code] == []
