"""The cost image carries what `package_export` needs — and the code looks for what it carries.

THE DEFECT THIS CLOSES. `cost_agent.measures.package_export` builds a self-contained artifact
from the package builder plus the pinned Pyodide runtime. Both lived ONLY in a developer
checkout, so every deployed engine refused the work by name:

    this deployment cannot build the artifact: the package builder and the pinned Pyodide
    runtime live in the repository checkout, and this process is running from a flattened
    image that carries neither.

The refusal was honest and permanent. `v0.10.0` and the export button waited on it.

**AND `_repo_root()` TESTED A PROXY, NOT THE REQUIREMENT.** It looked for `scripts/` AND
`agent_fleet/` — a fair definition of "a developer checkout", and the wrong question. A flattened
`/app` carrying the builder and the runtime can build a package perfectly well and has neither
directory. The proxy and the requirement came apart the moment the runtime shipped inside an
image.

The alternative was to create a bare `agent_fleet/` in the image so the marker would pass. **A
marker built to lie** — the function would answer "yes" on the strength of an empty directory
added to satisfy it. The docstring already claimed it walks upward for "a tree that actually
contains what the caller needs"; it now does.

**THIS SEAL IS THE JOIN**, and it is the half neither side can assert alone: the workflow copies
paths, the code looks for paths, and nothing before this compared them. Either can be correct
while the pair is wrong — which is how a build succeeds and an engine refuses.

Run: uv run --frozen pytest tests/test_the_cost_image_can_build_a_package.py -v
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
#: THE DOCKERFILE, not the workflow that used to embed it. The heredoc crossed GitHub's
#: 21000-char expression limit on 2026-09-19 and the three Dockerfiles became real files
#: under .github/docker/ — which is what lets this seal read a Dockerfile instead of a
#: shell string inside a YAML scalar.
_WORKFLOW = _REPO / ".github" / "docker" / "Dockerfile.agent"
_MEASURES = _REPO / "agent_fleet" / "cost_agent" / "measures.py"
_BUILDER = _REPO / "scripts" / "build_cost_package.py"


def _wf() -> str:
    # BOTH SOURCES, because this file asserts two different things: the MATRIX rows
    # (`package_runtime: ".pyodide-cache"`) which live in the workflow, and the COPY
    # directives which live in the Dockerfile since the 2026-09-19 move. Repointing the
    # whole constant at the Dockerfile silently dropped the matrix half — green on the
    # COPY arms, red on the one that reads a matrix row.
    return (
        _WORKFLOW.read_text(encoding="utf-8")
        + (_REPO / ".github" / "workflows" / "build-containers.yml").read_text(
            encoding="utf-8")
    )


def test_THE_ROOT_CHECK_TESTS_THE_REQUIREMENT_not_a_checkout_shape():
    """`can I build a package here`, which is what the function is asked."""
    src = _MEASURES.read_text(encoding="utf-8")
    assert "def _can_build_a_package_here(" in src
    proxy = '(candidate / "scripts").is_dir() and (candidate / "agent_fleet").is_dir()'
    assert proxy not in src, (
        "the root check is back to detecting a checkout shape, so a flattened image carrying "
        "everything it needs will answer None and refuse work it can do"
    )


def test_THE_ROOT_CHECK_REQUIRES_BOTH_HALVES(tmp_path):
    """Either alone produces a refusal one layer later — the builder with no runtime raises the
    missing-files refusal, the runtime with no builder raises the import one. Accepting a root
    on one half moves the failure without removing it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("cost_measures_probe", _MEASURES)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # ⛔ THIS ASSERTED `_can_build_a_package_here(_REPO) is True` — a property of a WORKING COPY,
    # not of the repository. `.pyodide-cache/` is gitignored, so it exists in whichever checkout
    # last fetched it and in no other: the assertion passed in the original tree and failed the
    # moment this suite ran from a worktree. The same absent-from-git shape the endpoint itself
    # is about (R-064), reappearing in the seal written for it.
    #
    # Both halves are CONSTRUCTED now, so the check is about the predicate rather than about
    # whose machine is running it.
    both = tmp_path / "both"
    (both / "scripts").mkdir(parents=True)
    (both / "scripts" / "build_cost_package.py").write_text("# builder", encoding="utf-8")
    (both / ".pyodide-cache").mkdir()
    assert mod._can_build_a_package_here(both) is True

    builder_only = tmp_path / "builder-only"
    (builder_only / "scripts").mkdir(parents=True)
    (builder_only / "scripts" / "build_cost_package.py").write_text("# b", encoding="utf-8")
    assert mod._can_build_a_package_here(builder_only) is False, (
        "a tree with the builder and NO runtime resolves as a root — the refusal moves from "
        "`not a checkout` to a missing-files list one layer later instead of being avoided"
    )

    runtime_only = tmp_path / "runtime-only"
    (runtime_only / ".pyodide-cache").mkdir(parents=True)
    assert mod._can_build_a_package_here(runtime_only) is False


def test_THE_IMAGE_COPIES_THE_BUILDER():
    """Unconditional: one small module, and the engine cannot import it from anywhere else."""
    assert "COPY scripts/build_cost_package.py /app/scripts/build_cost_package.py" in _wf(), (
        "the package builder is not in the image, so the import raises and the engine refuses "
        "by name forever"
    )


def test_THE_IMAGE_COPIES_THE_RUNTIME_UNDER_A_BUILD_ARG():
    """14 MB. Copying it into all eleven images buys nothing for the ten that never export, and
    a COPY needs a source that EXISTS — hence a default pointing at an empty tracked directory
    rather than a conditional COPY, which Docker has no syntax for."""
    wf = _wf()
    assert "ARG PACKAGE_RUNTIME_SRC=.docker-empty" in wf
    assert "COPY ${PACKAGE_RUNTIME_SRC}/ /app/.pyodide-cache/" in wf
    assert (_REPO / ".docker-empty").is_dir(), (
        "the default COPY source does not exist, so EVERY agent image fails to build"
    )


def test_THE_DESTINATION_IS_THE_PATH_THE_CODE_LOOKS_FOR():
    """THE JOIN. The workflow writes paths and the code reads paths; nothing else compares them.

    Both can be internally correct while the pair is wrong — the image builds, the tests pass,
    and the engine refuses at answer time because the runtime landed one directory over.
    """
    src = _MEASURES.read_text(encoding="utf-8")
    m = re.search(r'_RUNTIME_DIR\s*=\s*"([^"]+)"', src)
    assert m, "the runtime directory name is no longer a named constant"
    runtime_dir = m.group(1)
    assert "/app/" + runtime_dir + "/" in _wf(), (
        "the image copies the runtime somewhere other than " + runtime_dir + ", which is where "
        "the engine looks. The build succeeds and the export refuses."
    )
    b = re.search(r'_BUILDER_REL\s*=\s*pathlib\.Path\("([^"]+)"\)\s*/\s*"([^"]+)"', src)
    assert b, "the builder path is no longer a named constant"
    assert "/app/" + b.group(1) + "/" + b.group(2) in _wf(), (
        "the image copies the builder somewhere other than where the engine adds to sys.path"
    )


def test_ONLY_THE_DECLARING_SERVICE_CARRIES_THE_RUNTIME():
    """Named in the matrix rather than inferred from the service name, so a second exporting
    engine is a decision somebody makes in that table rather than a surprise 14 MB."""
    wf = _wf()
    assert 'package_runtime: ".pyodide-cache"' in wf
    assert wf.count("package_runtime:") == 1, (
        "more than one service declares the runtime; if that is intended, the matrix comment "
        "should say so rather than this seal being edited"
    )


def test_CI_FETCHES_THE_RUNTIME_because_it_is_gitignored():
    """THE STEP WITHOUT WHICH THE MATRIX ROW NAMES A DIRECTORY THAT DOES NOT EXIST.

    `.pyodide-cache/` is gitignored — 0 tracked files — so a fresh checkout has nothing to copy.
    That is the "on disk, undeclared" shape one layer over from a TTL absent from the prime
    manifest: present on the machine that wrote it, absent everywhere it matters.
    """
    wf = _wf()
    assert "--fetch-runtime" in wf, (
        "nothing fetches the pinned runtime, so the COPY source does not exist in CI"
    )
    # ⛔ THE STRING BEING PRESENT IS NOT THE COMMAND BEING RUNNABLE, and that gap cost a build.
    # This asserted `--fetch-runtime` appeared in the workflow. It did. The invocation still
    # failed:
    #
    #     build_cost_package.py: error: the following arguments are required: --recipient
    #
    # `--recipient` was `required=True`, so the flag's own documented standalone use — "download
    # the pinned Pyodide runtime into --runtime-dir" — could not run. A check that a flag is
    # MENTIONED is not a check that the invocation PARSES.
    #
    # So the parser is asked directly, with the arguments the workflow actually passes.
    src_b = _BUILDER.read_text(encoding="utf-8")
    i = src_b.index("add_argument(")
    while "--recipient" not in src_b[i:i + 60]:
        i = src_b.index("add_argument(", i + 1)
    decl = src_b[i:src_b.index(")", i)]
    assert "required=True" not in decl, (
        "--recipient is required again, so `--fetch-runtime` alone cannot run and the image "
        "build fails before the COPY ever happens: " + decl
    )
    assert "if not a.recipient:" in src_b, (
        "nothing validates the recipient after parsing, so a build with no recipient now "
        "proceeds and fails somewhere less legible than argparse"
    )


def test_THE_RUNTIME_IS_NOT_EXPECTED_IN_GIT():
    """A control on the check above. If someone commits the 14 MB runtime the fetch step becomes
    redundant rather than wrong — but the assumption behind it would be silently false, and this
    says so instead of leaving two mechanisms for one file."""
    r = subprocess.run(
        ["git", "ls-files", ".pyodide-cache"], cwd=str(_REPO),
        capture_output=True, encoding="utf-8", errors="replace", timeout=60,
    )
    tracked = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    assert not tracked, (
        str(len(tracked)) + " runtime file(s) are now tracked in git. The CI fetch step is then "
        "a second source for the same bytes — decide which is authoritative and delete the "
        "other, rather than leaving a pinned version in two places."
    )


def test_A_FLATTENED_IMAGE_LAYOUT_RESOLVES(tmp_path):
    """THE FIXTURE THAT DISTINGUISHES THE TWO RULES, and without it this file proves nothing
    about which one is implemented.

    The earlier assertions matched the old predicate as a STRING, so restoring it under a
    different variable name killed nothing — measured, not supposed: that mutation left every
    test green. And a real checkout satisfies BOTH rules, so no fixture drawn from the repo can
    tell them apart.

    This is the discriminating case and it is precisely the deployed layout: `scripts/` holding
    the builder, `.pyodide-cache/` holding the runtime, and NO `agent_fleet/` anywhere. The old
    rule answers None here — the refusal that blocked the export — and the new one resolves.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("cost_measures_flat", _MEASURES)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    app = tmp_path / "app"
    (app / "scripts").mkdir(parents=True)
    (app / "scripts" / "build_cost_package.py").write_text("# builder", encoding="utf-8")
    (app / ".pyodide-cache").mkdir()
    assert not (app / "agent_fleet").exists(), "the fixture must NOT look like a checkout"

    assert mod._can_build_a_package_here(app) is True, (
        "a flattened image carrying the builder and the runtime is rejected, which is the "
        "checkout-shape proxy back in place under some spelling — the engine will refuse an "
        "export it is fully able to produce"
    )


def test_A_CHECKOUT_SHAPE_WITHOUT_THE_PARTS_IS_REFUSED(tmp_path):
    """THE CONTROL IN THE OTHER DIRECTION. `scripts/` and `agent_fleet/` present and the builder
    absent is what a checkout of a DIFFERENT repo looks like, and it must not resolve — or the
    engine promises an export and fails at the import instead of refusing by name."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("cost_measures_bare", _MEASURES)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    bare = tmp_path / "other-repo"
    (bare / "scripts").mkdir(parents=True)
    (bare / "agent_fleet").mkdir()
    assert mod._can_build_a_package_here(bare) is False, (
        "a tree with the checkout SHAPE and none of the parts resolves as a root"
    )
