"""The canvas-template schema has a PRODUCTION READER — this file. ADR-0050 §1.2, seal 5.

The generator projects `src/iagent/canvas_template.py` into
`policy/canvases/canvas_template.schema.json`. Nothing enforces that projection unless something
runs `--check`, and an unenforced generator is an ASPIRATIONAL seal: indistinguishable from a
real one while nobody looks. This is the reader, built on `tests/test_board_drift.py`'s shape
because §1.2 names that shape explicitly.

THE POSITIVE CONTROL IS NOT DECORATION, and seal 5 says so in as many words: *"without the
control, deleting the generator makes the drift seal green."* Every assertion below runs the
generator in a subprocess; if the script were missing or unrunnable, they would all pass
vacuously and the schema could drift freely. The control is what converts that from a hope into
a checked fact.

AND THE CONTROL MUST NOT WRITE. `generate_board.py` once took the write path on EVERY argument
including `--help`, so its own control regenerated the artifact it was about to check — vacuous
seal, and a clobbered neighbour edit in a shared tree (`7387ef2`). This file's control asserts
`--help` is BOTH runnable AND side-effect-free, so that specific defect cannot reappear here
silently.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_GEN = _ROOT / "scripts" / "generate_canvas_schema.py"
_SCHEMA = _ROOT / "policy" / "canvases" / "canvas_template.schema.json"
_MODELS = _ROOT / "src" / "iagent" / "canvas_template.py"
_CANVAS_DIR = _ROOT / "policy" / "canvases"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_GEN), *args],
                          cwd=_ROOT, capture_output=True, text=True)


# ── POSITIVE CONTROLS ───────────────────────────────────────────────────────────────────────
def test_the_generator_exists_and_is_runnable():
    """Seal 5's control. Without this, a deleted generator makes every seal below green."""
    assert _GEN.exists(), f"{_GEN} is missing — the schema has no generator"
    assert _MODELS.exists(), f"{_MODELS} is missing — the schema has no source"
    r = _run("--help")
    assert r.returncode == 0, f"generator is not runnable: {r.stderr[:400]}"
    assert "--check" in r.stdout, "usage text does not mention --check; wrong script?"


def test_help_does_not_write():
    """`--help` must not take the write path — the exact defect fixed in `7387ef2` next door.

    Asserted by mtime AND content: a regeneration that happened to produce identical bytes is
    still a write, and in a shared tree it is still capable of clobbering someone's edit.
    """
    before_mtime = _SCHEMA.stat().st_mtime_ns
    before_bytes = _SCHEMA.read_bytes()
    _run("--help")
    assert _SCHEMA.stat().st_mtime_ns == before_mtime, "--help rewrote the schema"
    assert _SCHEMA.read_bytes() == before_bytes, "--help changed the schema's content"


def test_unknown_args_do_not_write():
    """Same guard, one step out: an unrecognised flag must refuse, not silently regenerate."""
    before = _SCHEMA.read_bytes()
    r = _run("--obviously-not-a-real-flag")
    assert r.returncode == 2, "unknown argument was accepted"
    assert _SCHEMA.read_bytes() == before, "an unknown argument took the write path"


def test_the_generator_is_hermetic():
    """It must not need a database, a cluster, or a network.

    `src/iagent/__init__.py` imports the Dagster definitions, so a package-path import of the
    models opens Postgres connections and emits cortex-bff proxy warnings. The generator loads
    the models BY FILE PATH to avoid that. If someone 'simplifies' it back to a package import,
    this test is what says so — a seal whose colour depends on reachable infrastructure trains
    people to ignore it.
    """
    r = _run("--check")
    noise = [ln for ln in (r.stdout + r.stderr).splitlines()
             if "Postgres" in ln or "cortex-bff" in ln or "NO_PROXY" in ln]
    assert not noise, ("the generator pulled in infrastructure imports:\n  "
                       + "\n  ".join(noise[:6]))


# ── THE SEAL ────────────────────────────────────────────────────────────────────────────────
def test_schema_matches_the_models():
    r = _run("--check")
    assert r.returncode == 0, (
        "policy/canvases/canvas_template.schema.json is out of sync with "
        "src/iagent/canvas_template.py.\nRun:  python scripts/generate_canvas_schema.py\n"
        f"--- generator said ---\n{(r.stdout + r.stderr).strip()[:1200]}")


def test_the_check_can_actually_fail():
    """BREAK-ON-PURPOSE. A seal that has never gone red is not yet a check."""
    # BYTES FOR SAVE AND RESTORE. `write_text` on Windows re-emits CRLF for content read
    # with universal newlines, so a "restored" file shows MODIFIED with a ZERO-LINE DIFF
    # — observed 2026-09-11 in a fresh worktree, where this test left the schema dirty
    # after PASSING. In a shared tree that noise hides real changes and invites someone
    # to stage a line-ending churn. AGENTS.md names this hazard; here it is, in my file.
    original = _SCHEMA.read_bytes()
    try:
        doc = json.loads(original.decode("utf-8"))
        doc["properties"]["fabricated_field"] = {"type": "string"}
        # chr(10), not a written escape: this line was first patched through a heredoc and the
        # escape COLLAPSED into a real newline, breaking the file it was fixing. Name the
        # character, never write it — the third instance of that in this repo.
        _SCHEMA.write_bytes((json.dumps(doc, indent=2, sort_keys=True) + chr(10)).encode("utf-8"))
        assert _run("--check").returncode != 0, (
            "--check PASSED against a schema carrying a field the models do not declare — it is "
            "not comparing what it claims to compare")
    finally:
        _SCHEMA.write_bytes(original)
    assert _run("--check").returncode == 0, "schema was not restored after the break-on-purpose"


# ── TEMPLATE VALIDATION (§1.3's check, run here too so it is not CI-only) ───────────────────
def test_every_ratified_template_validates():
    r = _run("--validate")
    assert r.returncode == 0, f"a ratified template does not satisfy the schema:\n{r.stderr[:1200]}"


def test_validate_refuses_to_pass_on_zero_files():
    """EMPTY OUTPUT IS NOT SUCCESS.

    A validator that finds no files and exits 0 is indistinguishable from one that passed — the
    false green that nearly shipped when `helm template` returned zero matches for a retired name
    *because the render had failed with no output*. Asserted by reading the generator's own
    guard, since the directory cannot be emptied safely in a shared tree.
    """
    src = (_ROOT / "scripts" / "generate_canvas_schema.py").read_text(encoding="utf-8")
    assert "NOTHING TO VALIDATE" in src, (
        "the validator has no zero-files guard — an empty glob would report success")


def test_a_template_referencing_an_undeclared_verb_is_rejected():
    """ADR-0050 acceptance seal 1, broken-on-purpose: *a schema check that never rejects is
    indistinguishable from no check.*

    NOTE THE SCOPE, because overclaiming here would be worse than not testing it. This asserts
    the SHAPE gate — a malformed verb is refused. The verb-EXISTENCE half of seal 1 (the verb is
    registered in the mesh) is NOT implemented yet and is named in the packet as owed; a test
    that implied otherwise would be the decorative seal this ADR is written against.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("_ct_models_test", _MODELS)
    models = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = models
    spec.loader.exec_module(models)

    with pytest.raises(Exception):
        models.CanvasTemplate(
            template_id="bad", title="t", description="d",
            panels=[{"verb": "not a verb iri", "role": "anchor"}])


def test_template_ref_is_content_not_bytes():
    """§1.5 — a reflowed comment or a changed description must NOT mint a new ref; a changed
    panel must. This is `ruleset_ref`'s content-only property, inherited deliberately."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_ct_models_ref", _MODELS)
    models = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = models
    spec.loader.exec_module(models)

    base = models.CanvasTemplate(
        template_id="t", title="Title", description="D",
        panels=[{"verb": "mesh:planSchedule", "role": "anchor", "slots": {"group_by": "initiative"}}])
    reworded = base.model_copy(update={"title": "Different", "description": "Also different"})
    assert models.template_ref(base) == models.template_ref(reworded), (
        "rewording the prose minted a new template_ref — the hash is covering bytes, not content")

    changed = models.CanvasTemplate(
        template_id="t", title="Title", description="D",
        panels=[{"verb": "mesh:planSchedule", "role": "anchor", "slots": {"group_by": "capability"}}])
    assert models.template_ref(base) != models.template_ref(changed), (
        "changing a declared slot did NOT mint a new template_ref — the ref is not identifying "
        "the panel set")

    assert models.template_ref(base).startswith("t@"), "ref format must be <template_id>@<hex>"
    assert len(models.template_ref(base).split("@")[1]) == 12, "ref must carry 12 hex chars"


def test_the_committed_schema_is_not_hand_edited():
    """The artifact says what produced it, so a reader never treats it as authorable."""
    doc = json.loads(_SCHEMA.read_text(encoding="utf-8"))
    assert "GENERATED" in doc.get("$comment", ""), (
        "the committed schema does not declare itself generated — the next reader will edit it")


def test_template_ids_match_their_filenames():
    """§1.1 — one file, one template, id equal to the stem. A relation between content and
    filename, so it cannot live in the schema and is checked here and in the generator."""
    import yaml
    files = sorted(_CANVAS_DIR.glob("*.yaml"))
    assert files, "no ratified templates found — the glob or the directory moved"
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert doc["template_id"] == path.stem, (
            f"{path.name} declares template_id={doc['template_id']!r}, expected {path.stem!r}")
