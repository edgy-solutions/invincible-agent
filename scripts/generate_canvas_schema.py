#!/usr/bin/env python3
"""Generate `policy/canvases/canvas_template.schema.json` from the Pydantic models (ADR-0050 §1.2).

    python scripts/generate_canvas_schema.py            # write the schema
    python scripts/generate_canvas_schema.py --check    # exit 1 if the committed schema is stale
    python scripts/generate_canvas_schema.py --validate # validate every policy/canvases/*.yaml
    python scripts/generate_canvas_schema.py --check --validate

THE MODELS ARE THE SOURCE. The schema is a projection of `src/iagent/canvas_template.py`, so the
two cannot disagree — the drift test is what makes that a fact rather than an intention. This is
the same generated-not-hand-written discipline as `generate_board.py`, one config family over,
and §1.3 requires the NEXT schema (ADR-0039's workflow definitions) to reuse THIS generator: two
generators for one law is ADR-0036's two-escapers problem, and it produces two schemas that
disagree once, in production.

── ARG HANDLING IS DELIBERATE, AND IT IS A FIXED BUG, NOT A STYLE CHOICE ────────────────────────
`generate_board.py`'s only arg test was once `if "--check" in sys.argv`, so EVERY other
invocation — including the `--help` its own positive control ran to prove the script was
runnable — took the WRITE path. The drift suite's control silently regenerated the artifact it
was about to check, which made the seal vacuous AND clobbered a neighbour's uncommitted edit in a
shared tree (fixed in `7387ef2`). Unknown args and `--help` here never write.

── EMPTY OUTPUT IS NOT SUCCESS ─────────────────────────────────────────────────────────────────
`--validate` reports the COUNT it validated and fails when it validated nothing. A validator that
finds no files and exits 0 is indistinguishable from one that passed — the same false green that
nearly shipped when `helm template` returned zero occurrences of a retired name because the
render had failed with no output.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "policy" / "canvases" / "canvas_template.schema.json"
CANVAS_DIR = ROOT / "policy" / "canvases"
MODELS_PATH = ROOT / "src" / "iagent" / "canvas_template.py"

_USAGE = __doc__.split("\n\n")[1].strip()


def _load_models():
    """Load the models BY FILE PATH, deliberately bypassing the `iagent` package.

    `src/iagent/__init__.py` imports `.definitions` — the Dagster graph — so a plain
    `from iagent.canvas_template import ...` opens Postgres connections and emits cortex-bff
    proxy warnings before it ever reaches a Pydantic class. Observed here on the first run.

    A schema is a PROJECTION OF A TYPE. It must not need a database, a cluster, or a network to
    produce, or the drift seal becomes a thing that only goes green where infrastructure happens
    to be reachable — and a seal whose colour depends on the environment teaches people to
    ignore it. Loading the module by path keeps the generator hermetic, which is also what lets
    the CI job of §1.3 be a few seconds of pure Python.
    """
    spec = importlib.util.spec_from_file_location("_canvas_template_models", MODELS_PATH)
    if spec is None or spec.loader is None:            # pragma: no cover - defensive
        raise ImportError(f"cannot load models from {MODELS_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_schema() -> dict:
    """Project the model into a JSON Schema, with the identity fields a reader needs."""
    schema = _load_models().CanvasTemplate.model_json_schema()
    # Stamped so a reader of the committed artifact can tell what produced it and never edits it
    # by hand. `$schema` makes it usable by an off-the-shelf validator in CI.
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$comment"] = (
        "GENERATED from src/iagent/canvas_template.py by scripts/generate_canvas_schema.py "
        "(ADR-0050 §1.2). Do not edit by hand — run the generator. Sealed by "
        "tests/test_canvas_schema_drift.py."
    )
    return schema


def _serialise(schema: dict) -> str:
    # sort_keys so a model reordering does not churn the artifact; trailing newline so the file
    # is POSIX-clean and diffs stay one-line.
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def _templates() -> list[pathlib.Path]:
    return sorted(CANVAS_DIR.glob("*.yaml"))


def validate() -> int:
    """Validate every ratified template against the COMMITTED schema. Returns an exit code."""
    try:
        import yaml
        from jsonschema import Draft202012Validator
    except ImportError as e:                                    # pragma: no cover - env-dependent
        print(f"VALIDATE UNAVAILABLE: {e}. Install pyyaml + jsonschema.", file=sys.stderr)
        return 2

    if not SCHEMA_PATH.exists():
        print(f"NO SCHEMA at {SCHEMA_PATH} — run the generator first.", file=sys.stderr)
        return 1

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    files = _templates()
    if not files:
        # THE FALSE-GREEN GUARD. Zero files validated is a broken glob or a moved directory, and
        # it must never read as "everything passed".
        print(f"NOTHING TO VALIDATE: no *.yaml under {CANVAS_DIR}. A validator that validates "
              f"nothing is not a passing validator.", file=sys.stderr)
        return 1

    rc = 0
    for path in files:
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            print(f"INVALID YAML: {path.name}: {e}", file=sys.stderr)
            rc = 1
            continue
        if doc is None:
            print(f"EMPTY TEMPLATE: {path.name}", file=sys.stderr)
            rc = 1
            continue
        errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
        for err in errors:
            loc = "/".join(str(p) for p in err.path) or "(root)"
            print(f"SCHEMA VIOLATION: {path.name}: {loc}: {err.message}", file=sys.stderr)
            rc = 1
        # §1.1 — one file, one template, and the id must equal the filename stem. Not expressible
        # in the schema (it is a relation between content and filename), so it is checked here.
        if rc == 0 or not errors:
            declared = doc.get("template_id")
            if declared != path.stem:
                print(f"ID MISMATCH: {path.name} declares template_id={declared!r}; §1.1 requires "
                      f"it to equal the filename stem {path.stem!r}", file=sys.stderr)
                rc = 1

    print(f"validated {len(files)} template(s) against {SCHEMA_PATH.name}")
    return rc


def main() -> int:
    argv = sys.argv[1:]
    if "--help" in argv or "-h" in argv:
        print(_USAGE)
        return 0
    unknown = [a for a in argv if a not in ("--check", "--validate")]
    if unknown:
        print(f"unknown argument(s): {unknown}\n\n{_USAGE}", file=sys.stderr)
        return 2

    rc = 0
    generated = _serialise(build_schema())

    if "--check" in argv:
        if not SCHEMA_PATH.exists():
            print(f"DRIFT: {SCHEMA_PATH} does not exist — run the generator.", file=sys.stderr)
            rc = 1
        elif SCHEMA_PATH.read_text(encoding="utf-8") != generated:
            print(f"DRIFT: {SCHEMA_PATH.relative_to(ROOT)} does not match the models in "
                  f"src/iagent/canvas_template.py.\nRun: python "
                  f"scripts/generate_canvas_schema.py", file=sys.stderr)
            rc = 1
    elif "--validate" not in argv:
        SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_PATH.write_text(generated, encoding="utf-8")
        print(f"wrote {SCHEMA_PATH.relative_to(ROOT)}")

    if "--validate" in argv:
        rc = validate() or rc

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
