"""The chart-version seal (scripts/chart_version_seal.py): its three verdicts, and the wiring.

The architect, via Chris, 2026-11-08: the seal "accepts a '## 0.4.82 — not yet cut' changelog
entry as the pending bump, and fails only when helm/ changes with neither a bump nor that entry."

Run: uv run --no-sync python -m pytest -c pyproject.toml --rootdir=. -p no:cacheprovider tests/test_chart_version_seal.py
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("chart_version_seal",
                                               _REPO / "scripts" / "chart_version_seal.py")
seal = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seal)

PUBLISHED = {"0.4.80", "0.4.81"}


def _pub(v: str) -> bool:
    return v in PUBLISHED


def _log(*headings: str) -> str:
    return "# changelog\n\n" + "\n\n- an entry\n\n".join(headings) + "\n\n- an entry\n"


def test_an_unpublished_version_releases():
    assert seal.decide("0.4.82", _log("## 0.4.82 — 2026-11-08", "## 0.4.81 — 2026-11-07"),
                       _pub)[0] == "release"


def test_a_published_version_with_a_pending_entry_is_pending_not_red():
    verdict, msg = seal.decide("0.4.81", _log("## 0.4.82 — not yet cut", "## 0.4.81 — 2026-11-07"),
                               _pub)
    assert verdict == "pending" and "0.4.82" in msg


def test_a_published_version_with_NEITHER_bump_NOR_entry_is_refused():
    # the 0.3.36 failure: contents moved under a published version and nothing says a bump is owed
    verdict, msg = seal.decide("0.4.81", _log("## 0.4.81 — 2026-11-07"), _pub)
    assert verdict == "refuse" and "invincible-agent-0.4.81" in msg


@pytest.mark.parametrize("heading", [
    "## Unreleased",                 # names no version, so it declares no bump
    "## 0.4.80 — not yet cut",       # names a published version
    "## 0.4.79 — not yet cut",       # names a version below the Chart's
    "### 0.4.82 — not yet cut",      # not a release heading
    "## 0.4.82 — not yet cut, maybe",
])
def test_an_entry_that_does_not_declare_an_owed_bump_is_refused(heading):
    assert seal.decide("0.4.81", _log(heading, "## 0.4.81 — 2026-11-07"), _pub)[0] == "refuse"


def test_the_cut_must_date_the_heading_it_releases():
    verdict, msg = seal.decide("0.4.82", _log("## 0.4.82 — not yet cut", "## 0.4.81 — 2026-11-07"),
                               _pub)
    assert verdict == "refuse" and "dates that heading" in msg


def test_the_REAL_chart_and_changelog_parse():
    chart = _REPO / "helm" / "invincible-agent"
    version = seal.VERSION.search((chart / "Chart.yaml").read_text(encoding="utf-8")).group(1)
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    # whatever this tree's own verdict, it is one of the three, decided on the real files
    changelog = (chart / "CHANGELOG.md").read_text(encoding="utf-8")
    assert seal.decide(version, changelog, lambda v: v != version)[0] in {"release", "refuse"}
    assert seal.decide(version, changelog, lambda v: True)[0] in {"pending", "refuse"}


def test_the_workflow_runs_the_seal_and_every_publishing_step_honours_pending():
    wf = (_REPO / ".github" / "workflows" / "release-helm-charts.yml").read_text(encoding="utf-8")
    steps = re.split(r"\n      - name: ", wf)[1:]
    by_name = {s.splitlines()[0].strip(): s for s in steps}
    seal_steps = [n for n, s in by_name.items()
                  if re.search(r"^        run: python scripts/chart_version_seal\.py ", s, re.MULTILINE)]
    assert len(seal_steps) == 1, seal_steps
    body = by_name[seal_steps[0]]
    assert "id: version_seal" in body
    assert "github.event_name != 'workflow_dispatch'" in body
    after = list(by_name)[list(by_name).index(seal_steps[0]) + 1:]
    assert after, "no step follows the seal"
    ungated = [n for n in after if "steps.version_seal.outputs.pending != 'true'" not in by_name[n]]
    assert ungated == [], f"steps that would publish while the bump is only pending: {ungated}"
