"""Tests that call a live cluster are marked `live` and leave the default run.

Order: "Tests that call a live cluster are marked live and leave the default run"
(architect, 2026-11-17). Reason: tests in tests/routing reach whatever answers on
http://localhost:18084 (`tests/_responder_identity.py` `routing_base_url()`), which is a kubectl
port-forward of the LIVE sandbox engine-o whenever one is up; a default run then went red against
a service it never owned. A default run must not depend on a cluster.

The rule, enforced in tests/conftest.py `pytest_collection_modifyitems`: a test carrying `live`
(or the older `requires_engine_o` / `requires_cluster`) is DESELECTED unless the `-m` expression
names `live`. The existing skip / VOID gates stay; the mark is in addition.

Run the live tests:  uv run pytest -m live tests/routing
with the port-forward named in tests/routing/conftest.py's void message
(kubectl -n sandbox port-forward svc/iagent-engine-o 18084:8084). Everything:
`-m "live or not live"`.

Three seals here:
  1. CENSUS BY FORM. Every module under tests/ whose source holds a live-call FORM carries
     `pytest.mark.live`, or is in NOT_LIVE with a reason. An unknown module fails, by name.
  2. POSITIVE / NEGATIVE CONTROLS for the detector, so the census cannot pass by being blind.
  3. BEHAVIOUR. A real collect-only run deselects a live file by default and collects it under
     `-m live`; a non-live file is untouched (the control).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TESTS = _ROOT / "tests"

# Live-call FORMS: what the code does, not what its prose says.
LIVE_FORMS = [
    re.compile(r"routing_base_url\("),
    re.compile(r"ROUTING_TEST_BASE_URL"),
    re.compile(r"requires_engine_o"),
    re.compile(r"requires_cluster"),
    re.compile(r"\[\s*\"kubectl\""),
    re.compile(r"from mesh_client import"),
    re.compile(r"shlex\.split\(kubectl"),
    re.compile(r"['\"]BFF_URL['\"]"),
    re.compile(r"GraphDatabase\.driver\("),
    re.compile(r"weaviate\.connect_to"),
    re.compile(r"psycopg2?\.connect\("),
    re.compile(r"urllib\.request\.urlopen\("),
]
# `pytest.mark.live` as code (a comment or prose line does not count).
_MARKED = re.compile(r"^[^#\n]*pytest\.mark\.live\b", re.M)

# Modules that hold a live-call FORM but do not call a cluster when they run.
NOT_LIVE = {
    "tests/test_live_tests_leave_the_default_run.py": "this seal: the forms appear in its detector and its synthetic sources",
    "tests/conftest.py": "names the marks; makes no call",
    "tests/routing/conftest.py": "the engine-o precondition probe runs only for tests already marked requires_engine_o",
    "tests/_responder_identity.py": "helper that defines routing_base_url; the probe runs only from live tests",
    "tests/_mesh_verbs.py": "helper; its consumers carry the live mark on the tests that use it",
    "tests/routing/test_a_foreign_responder_is_void_not_red.py": "starts its own local stub servers on ephemeral ports and an in-process TestClient; asserts the void LOGIC",
    "tests/routing/test_adr0019_engine_o_contract_a.py": "every dependency stubbed, Engine O in-process (its own header says so)",
    "tests/routing/test_no_legacy_dns_references.py": "text scan of the repo; names helm and kubectl only as strings",
    "tests/test_networkpolicy_flows_survive.py": "helm template on the local chart (local rendering), no cluster",
    "tests/test_roll_lock.py": "runs roll-lock.sh against a stub kubectl in a temp dir",
    "tests/security/test_every_engine_o_caller_is_classified.py": "AST scan of call sites; the requests.post forms are synthetic sources",
    "tests/test_extraction_review_sensor.py": "httpx.post is monkeypatched by hand; no network",
    "tests/test_engine_w_identity_census.py": "Topaz and httpx are doubles",
    "tests/sdk_adoption/test_direct_store_clients_only_fall.py": "scans synthetic source files for the constructors",
    "tests/finance/test_the_refusal_live_test_can_go_red.py": "drives the live test's logic with injected fakes; no kubectl runs",
    "tests/finance/test_the_variance_live_test_can_go_red.py": "drives the live test's logic with injected fakes; no kubectl runs",
    "tests/sandbox_e2e/mesh_client.py": "helper module of the sandbox_e2e scripts, not a test",
    "tests/sandbox_e2e/_xeng.py": "helper for the hand-run sandbox_e2e scripts, not a test; not collected",
    "tests/sandbox_e2e/_probe_domain_agnostic_rows.py": "not collected (no test_ prefix); a script run by hand against the sandbox",
    "tests/sandbox_e2e/_probe_registered_services.py": "not collected (no test_ prefix); a script run by hand against the sandbox",
    "tests/eval/funnel_b_runner.py": "not collected (no test_ prefix); an eval runner run by hand",
    "tests/eval/planning_eval_runner.py": "not collected (no test_ prefix); an eval runner run by hand",
    "tests/test_engine_images.py": "runs local docker containers and polls their own mapped port; no cluster",
    "tests/sandbox_e2e/_seal_haz1003_acceptance.py": "not collected (no test_ prefix); a script run by hand against the sandbox",
}


def _live_form(source: str) -> str | None:
    for rx in LIVE_FORMS:
        if rx.search(source):
            return rx.pattern
    return None


def _is_marked(source: str) -> bool:
    return bool(_MARKED.search(source))


def _unclassified(rel: str, source: str, not_live: dict[str, str]) -> str | None:
    """The form found when `rel` calls a cluster, is unmarked, and is not excused; else None."""
    form = _live_form(source)
    if form is None or _is_marked(source):
        return None
    if (not_live.get(rel) or "").strip():
        return None
    return form


def _modules():
    for p in sorted(_TESTS.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p.relative_to(_ROOT).as_posix(), p.read_text(encoding="utf-8", errors="replace")


def test_every_module_that_calls_a_live_cluster_is_marked_live_or_excused():
    bad = []
    for rel, src in _modules():
        form = _unclassified(rel, src, NOT_LIVE)
        if form:
            bad.append(f"{rel}  (form {form})")
    assert not bad, (
        "these modules hold a live-call form and carry neither `pytest.mark.live` nor a NOT_LIVE "
        "reason:\n  " + "\n  ".join(bad))


def test_every_not_live_entry_names_a_file_and_gives_a_reason():
    for rel, why in NOT_LIVE.items():
        assert (_ROOT / rel).is_file(), f"NOT_LIVE names a file that does not exist: {rel}"
        assert why.strip(), f"NOT_LIVE entry without a reason: {rel}"


# --- controls: the detector can say yes and can say no ----------------------------------------

_UNMARKED = 'import subprocess\n\ndef test_x():\n    subprocess.run(["kubectl", "get", "pods"])\n'
_MARKED_SRC = ('import subprocess\nimport pytest\n\npytestmark = pytest.mark.live\n\n'
               'def test_x():\n    subprocess.run(["kubectl", "get", "pods"])\n')
_PROSE = '"""pytest.mark.live is mentioned here only."""\n# pytest.mark.live\n'


def test_control_an_unmarked_kubectl_module_is_flagged():
    assert _unclassified("tests/x.py", _UNMARKED, {}) is not None


def test_control_a_marked_module_passes():
    assert _unclassified("tests/x.py", _MARKED_SRC, {}) is None


def test_control_a_comment_naming_the_mark_is_not_the_mark():
    assert not _is_marked("# pytest.mark.live\n")
    assert _unclassified("tests/x.py", _UNMARKED + "# pytest.mark.live\n", {}) is not None


def test_control_a_blank_reason_does_not_excuse():
    assert _unclassified("tests/x.py", _UNMARKED, {"tests/x.py": "  "}) is not None
    assert _unclassified("tests/x.py", _UNMARKED, {"tests/x.py": "stub only"}) is None


# --- behaviour: a real collect-only run ---------------------------------------------------------

def _collect(path: str, *extra: str) -> tuple[str, int, int]:
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
           "-c", "pyproject.toml", "--rootdir=.", *extra, path]
    r = subprocess.run(cmd, cwd=str(_ROOT), capture_output=True, text=True, timeout=300)
    out = r.stdout + r.stderr
    ids = [ln for ln in out.splitlines() if ln.startswith(path + "::")]
    m = re.search(r"(\d+) deselected", out)
    return out, len(ids), int(m.group(1)) if m else 0


_LIVE_FILE = "tests/routing/test_classify_route.py"
_PLAIN_FILE = "tests/routing/test_embed_contract.py"


def test_a_live_file_is_deselected_by_default_and_collected_under_m_live():
    out, n, deselected = _collect(_LIVE_FILE)
    assert n == 0, f"a live test was collected in the default run:\n{out[-800:]}"
    assert deselected > 0, f"the default run does not report the live tests as deselected:\n{out[-800:]}"
    out2, n2, _ = _collect(_LIVE_FILE, "-m", "live")
    assert n2 > 0, f"-m live does not select the live file:\n{out2[-800:]}"


def test_control_a_plain_file_is_collected_and_nothing_is_deselected():
    out, n, deselected = _collect(_PLAIN_FILE)
    assert n > 0, out[-800:]
    assert deselected == 0, out[-800:]


# --- behaviour, per test: a requires_* mark is a live mark under every -m -----------------------

_PROBE = "tests/fixtures/live_marks/probe_live_marks.py"
_PROBE_LIVE = {"test_live", "test_requires_cluster_only", "test_requires_engine_o_only"}


def _ids(*extra: str) -> tuple[str, set[str]]:
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
           "-c", "pyproject.toml", "--rootdir=.", *extra, _PROBE]
    r = subprocess.run(cmd, cwd=str(_ROOT), capture_output=True, text=True, timeout=300)
    out = r.stdout + r.stderr
    return out, {ln.split("::", 1)[1] for ln in out.splitlines() if ln.startswith(_PROBE + "::")}


@pytest.mark.parametrize("extra", [(), ("-m", "not live")], ids=["default", "m-not-live"])
def test_a_requires_only_test_leaves_the_run_under_the_default_and_not_live(extra):
    """gov on #442: under `-m "not live"` a test marked only `requires_cluster` ran."""
    out, ids = _ids(*extra)
    assert ids == {"test_plain"}, f"{extra or 'default'} kept {sorted(ids)}:\n{out[-800:]}"


def test_m_live_selects_every_live_and_requires_test_and_nothing_else():
    out, ids = _ids("-m", "live")
    assert ids == _PROBE_LIVE, f"-m live kept {sorted(ids)}:\n{out[-800:]}"
