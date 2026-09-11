"""The Engine B removal list must cover every reference, and hold nothing already gone.

Engine B was RETIRED on 2026-09-06 (ADR-0046 §8.4). The retirement landed in two commits —
the Dagster caller, then the chart default — and deliberately did NOT remove the chart block,
because removal waits on the prime and on every remaining reference going first. What makes
that follow-up finishable is a list, left at the site where the trigger asset used to be
(``src/iagent/defs/agent_routers.py``).

**A list nobody checks is a list that goes blind, and this one already had.** Written from a
grep of what came to mind, it named eleven references and missed five — including
``.github/workflows/build-containers.yml``, which still BUILDS the retired engine's container
image on every run, and ``examples/docker-compose.yml``, which still stands the service up for
local development. Those are the two that cost something, and they are exactly the two a
from-memory list omits: nobody thinks of CI when they think of an engine.

So the list gets the treatment this repo already established for hand-kept mappings it cannot
derive: **keep the list, and put a derived floor under it that fails when it drifts** — the
``test_service_enumerations_agree`` pattern. The population here IS derivable (grep the tracked
tree), so the floor is exact rather than approximate, and the list survives only as the
human-readable ordering at the call site.

TWO DIRECTIONS, AND THE SECOND IS THE ONE PEOPLE FORGET.

  * **Nothing unlisted.** A new reference to Engine B — or an old one nobody noticed — fails
    here rather than being discovered when the chart block will not come out.
  * **Nothing stale.** When a reference IS removed, this list must shrink with it. Without
    this direction the list decays into a monument: every entry removed one by one, the list
    unchanged, and the last person reading it cannot tell which entries are real. That is the
    same defect as a control kept past the thing it controls.

WHY ``docs/`` IS EXCLUDED, deliberately rather than by convenience. The ADR, the packets and
the board DESCRIBE the retirement; requiring them on a removal list would mean deleting the
record of why Engine B is gone in order to finish removing it. The list is about live
references — code, chart, CI, compose — not about the history.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SELF = "tests/test_engine_b_removal_list_is_complete.py"

#: Anything naming Engine B by any of its four names (the four-namespace problem in miniature:
#: a chart key, a k8s component, a source directory, an env var).
_MARKER = re.compile(r"engineB|engine-b|langgraph_support|langgraph-support|LANGGRAPH_SUPPORT")

_SCANNED_SUFFIXES = {".py", ".yaml", ".yml", ".toml", ".sh"}

#: THE LIST, mirroring the comment in src/iagent/defs/agent_routers.py where the trigger asset
#: used to be. Each entry says what still has to happen to it, because "still references it" is
#: not the same instruction as "delete it" — some of these lose a line, one loses a directory.
_DOCUMENTED: dict[str, str] = {
    ".github/workflows/build-containers.yml": "drop the langgraph-support matrix row; CI builds a retired engine's image on every run",
    "agent_fleet/langgraph_support/main.py": "the service itself; goes with the directory",
    "agent_fleet/langgraph_support/pyproject.toml": "the service itself; goes with the directory",
    "examples/docker-compose.yml": "drop the langgraph-support service and the LANGGRAPH_SUPPORT_SVC_URL override",
    "helm/invincible-agent/templates/configmap.yaml": "drop LANGGRAPH_SUPPORT_SVC_URL — and the residue control in test_chart_renders_on_bare_defaults in the SAME change",
    "helm/invincible-agent/templates/engines.yaml": "drop the engineB row",
    "helm/invincible-agent/values-sandbox.yaml": "only the note explaining why the override is gone; delete with the block",
    "helm/invincible-agent/values.yaml": "THE BLOCK ITSELF — the last thing to go, and only after everything above",
    "src/iagent/defs/agent_routers.py": "the removal list and its coupling note; delete last, with this test",
    "src/iagent/defs/dynamic_supervisor.py": "LANGGRAPH_SUPPORT_SVC_URL and synthesize_stateful — the remaining caller",
    "tests/test_agent_router_triggers_send_a_body.py": "docstring names Engine B as one of the three original defects; history, trim when convenient",
    "tests/test_chart_renders_on_bare_defaults.py": "the workload assertion and the residue control",
    "tests/test_the_census_population_covers_every_engine.py": "the engine-b entry in _NOT_CENSUSED, waiving it from the census; delete WITH the engineB row in engines.yaml, since that seal derives its population from that list and the waiver goes stale the moment the row does",
    "tests/test_endpoint_gating_manifest.py": "drop the langgraph_support SERVICE_FILES row",
    "tests/test_reregister_covers_every_registering_engine.py": "drop engineB from _KEY_TO_AGENT_DIR and the _NOT_A_REGISTERING_AGENT waiver",
    "tests/test_service_urls_are_real.py": "drop the langgraph-support row",
    "tests/test_user_id_plumbing.py": "imports SupportRequest from the retired service; rewrite or drop",
}


def _tracked_references() -> set[str]:
    """Every tracked non-docs source file that still names Engine B. DERIVED, not remembered."""
    files = subprocess.run(
        ["git", "ls-files"], cwd=_REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    found = set()
    for rel in files:
        rel = rel.strip().replace("\\", "/")
        if not rel or rel.startswith("docs/") or rel == _SELF:
            continue
        if Path(rel).suffix not in _SCANNED_SUFFIXES:
            continue
        try:
            text = (_REPO / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _MARKER.search(text):
            found.add(rel)
    return found


def test_the_population_is_not_empty():
    """The floor under the other two. A scan that finds nothing would make both pass."""
    assert _tracked_references(), (
        "no Engine B references found at all — either the retirement is complete (in which "
        "case delete this test, the list, and the chart block together) or the scan is broken. "
        "Both other assertions pass vacuously in this state, so it is checked first."
    )


def test_nothing_references_engine_b_off_the_list():
    unlisted = sorted(_tracked_references() - set(_DOCUMENTED))
    assert not unlisted, (
        "these still reference Engine B and are NOT on the removal list in "
        "src/iagent/defs/agent_routers.py — the chart block cannot come out until they are "
        "handled, and an unlisted reference is one nobody will handle:\n  "
        + "\n  ".join(unlisted)
    )


def test_the_list_holds_nothing_already_removed():
    stale = sorted(set(_DOCUMENTED) - _tracked_references())
    assert not stale, (
        "these are on the removal list but no longer reference Engine B. That is PROGRESS, "
        "not a failure — remove them from _DOCUMENTED and from the comment in "
        "src/iagent/defs/agent_routers.py in the same change, so the list keeps saying what "
        "is actually left:\n  "
        + "\n  ".join(stale)
    )
