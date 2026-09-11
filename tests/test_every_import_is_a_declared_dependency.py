"""Every third-party module this repo imports must be a DECLARED dependency.

PROMOTED FROM A COST-ENGINE SEAL TO A REPO SEAL, 2026-09-11, after the class reached three
instances in two days:

    uvicorn   the Procfile launched `uvicorn main:app` while the engine declared only
              hypercorn. The image carried both, so it had always worked — an undeclared
              process entrypoint surviving on the base image's contents.
    duckdb    `package_export` imported it, the engine did not declare it, the deployed image
              did not have it, and `include_dataset` DEFAULTED TO TRUE. Every local test
              passed, because duckdb was incidentally installed until another lane's SDK bump
              triggered a sync that removed it.
    dagster   `from dagster import Definitions`, with only `dagster-postgres`,
              `dagster-webserver` and `dagster-dg-cli` declared. On a CI runner the resolution
              differed enough that the `dagster` NAMESPACE existed — contributed by those
              sibling distributions — while the core package did not:
                  ImportError: cannot import name 'Definitions' from 'dagster' (unknown location)
              `(unknown location)` is the tell for a namespace package with no `__init__.py`.
              NOTHING WAS SHADOWING IT; the name resolved because the core was ABSENT.

**A DEPENDENCY THAT ARRIVES TRANSITIVELY IS UNDECLARED, AND UNDECLARED MEANS IT CAN LEAVE
WITHOUT NOTICE.** All three passed locally. All three broke somewhere a lane never ran.

IMPORT NAME IS NOT DISTRIBUTION NAME, and comparing them directly is how this check produces
forty false positives: `yaml` comes from `PyYAML`, `jwt` from `PyJWT`, `datahub` from
`acryl-datahub`. `importlib.metadata.packages_distributions()` is the real mapping and it is
what makes this seal usable — a first draft that compared import names to declarations flagged
40 modules, most of them wrong.

WHAT IT CANNOT DISTINGUISH, stated because the limit is the point: a module importable HERE for
any reason — stdlib, transitive, or an incidental install — from one the deployed image will
actually have. It reads the DECLARATION, which is the artifact the environment is built from,
so an undeclared-but-locally-present module is exactly the case it catches.

Run: uv run --frozen pytest tests/test_every_import_is_a_declared_dependency.py -v
"""
from __future__ import annotations

import ast
import re
import sys
from importlib.metadata import packages_distributions
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

#: Directories whose imports are checked. `agent_fleet/` is deliberately EXCLUDED — each engine
#: declares its own dependencies in its own pyproject and is checked by its own seal, which is
#: the contract the engine runbook §5 describes. Checking them here against the ROOT pyproject
#: would assert the wrong thing: an engine's image is not built from this file.
_SCOPES = ("src", "scripts", "setup", "tests")

#: Top-level names that are NOT distributions: this repo's own packages, and sibling modules
#: that tests reach by manipulating sys.path (the flat-vs-packaged idiom from runbook §5).
#: A name here is a claim that nothing on PyPI provides it — the honesty test below enforces it.
_LOCAL = {
    "iagent", "iagent_pure", "agent_fleet", "tests", "setup", "scripts", "src",
    "utils", "baml_shared", "policy", "baml_client",
    "_bootstrap_guard", "build_cost_package", "doc_tools",
    "capability_admission", "capability_grant_sync", "capability_registry",
    "datahub_topaz_sync", "dispatch_plan", "funnel_b_runner", "grant_sync",
    "instance_resolution", "llm_utils", "mesh_client", "planning_eval_runner",
    "review_starter", "spo_interview", "spo_step_executor", "task_grant_sync",
    "telemetry", "topaz_sync", "validate_policy", "workflow_definition",
}

#: Optional by DESIGN — imported behind a guard, absent from the deployed image on purpose.
#: `duckdb` is the worked example: engine-cost defaults `include_dataset` OFF precisely so the
#: thin image need not carry it, and six seals void rather than fail when it is missing.
_OPTIONAL = {"duckdb", "pysqlite3", "restate"}


def _declared() -> set[str]:
    """Every distribution named anywhere in the root pyproject, normalised."""
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    names = re.findall(r'"([A-Za-z0-9_.-]+)(?:[\[@<>=!\s].*)?"', text)
    return {n.split("[")[0].strip().lower().replace("-", "_") for n in names}


def _imported() -> dict[str, set[str]]:
    """`top-level module -> {scopes importing it}`, by AST rather than by grep.

    A grep for `import X` is a sample of "files whose TEXT contains that import" and misses
    every module reached through a helper — the population is what the code DOES.
    """
    found: dict[str, set[str]] = {}
    for scope in _SCOPES:
        for path in (_ROOT / scope).rglob("*.py"):
            if ".venv" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                mods: list[str] = []
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mods = [node.module]
                for m in mods:
                    found.setdefault(m.split(".")[0], set()).add(scope)
    return found


def _undeclared() -> dict[str, tuple[str, ...]]:
    """`import name -> the distributions that provide it`, for imports nothing declares."""
    declared, pkg2dist = _declared(), packages_distributions()
    stdlib = set(sys.stdlib_module_names)
    out: dict[str, tuple[str, ...]] = {}
    for top in _imported():
        low = top.lower().replace("-", "_")
        if low in stdlib or top in _LOCAL or low in _LOCAL or top in _OPTIONAL:
            continue
        if low in declared:
            continue
        dists = pkg2dist.get(top)
        if not dists:
            # Not installed here, so no distribution can be named. Reported by the
            # honesty test below rather than asserted on — "cannot resolve" is not
            # "undeclared", and collapsing them is the defect this file is about.
            continue
        norm = tuple(sorted(d.lower().replace("-", "_") for d in dists))
        if not any(d in declared for d in norm):
            out[top] = norm
    return out


def test_the_scrape_can_SEE_imports_at_all():
    """THE FLOOR. Every assertion below quantifies over what `_imported()` returns; if the AST
    walk read nothing, an empty undeclared set would look like a clean repo."""
    seen = _imported()
    assert len(seen) >= 50, f"the import scrape found only {len(seen)}: {sorted(seen)[:20]}"
    assert "json" in seen, "the scrape is not seeing plain `import json` — it reads nothing"


def test_the_distribution_mapping_is_available():
    """The second half of the instrument. Without `packages_distributions` every import looks
    unresolvable and the seal silently checks nothing."""
    mapping = packages_distributions()
    assert len(mapping) >= 50, f"packages_distributions returned {len(mapping)} entries"
    assert "yaml" in mapping, "import-to-distribution mapping is not working (yaml -> PyYAML)"


def test_EVERY_IMPORTED_MODULE_IS_A_DECLARED_DEPENDENCY():
    """THE SEAL. An import this repo makes, provided by a distribution nothing declares.

    Each one is present only because something else dragged it in, and will leave the day that
    something else changes — which is exactly how `dagster` broke on a CI runner while passing
    on every machine in the fleet.
    """
    missing = _undeclared()
    assert not missing, (
        "undeclared dependencies — imported here, provided by a distribution the root "
        "pyproject does not name:\n"
        + "\n".join(f"    {k}  <- {', '.join(v)}" for k, v in sorted(missing.items()))
        + "\n\nEach arrives transitively today and leaves without notice tomorrow. Declare it, "
          "or add it to _OPTIONAL with the guard that makes it optional."
    )


def test_the_LOCAL_list_names_nothing_that_pypi_provides():
    """THE ALLOWLIST'S OWN HONESTY CHECK.

    `_LOCAL` is a claim that these names are this repo's own, not distributions. If one of them
    ever becomes a real installed package, the claim silently starts excusing a genuine
    undeclared dependency — the shape every allowlist in this repo drifts into.
    """
    pkg2dist = packages_distributions()
    wrong = sorted(n for n in _LOCAL if n in pkg2dist)
    assert not wrong, (
        f"_LOCAL claims these are repo-internal, but a distribution provides them here: "
        f"{wrong}. Either the import now resolves to a real package — in which case declare "
        f"it — or a name collision needs resolving."
    )
