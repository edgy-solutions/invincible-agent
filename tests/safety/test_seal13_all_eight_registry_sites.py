"""ADR-0051 seal 13 — engine-safety is present at all EIGHT registry sites.

THE SITE LIST IS DERIVED, NOT REMEMBERED. It comes from
`docs/plans/adding-an-engine-has-more-registry-sites-than-the-runbook-names.md`, the packet whose
whole finding is that the runbook names four and at least eight exist. A hand-kept copy here would
be the ninth instance of the defect the packet describes — and this repo has paid for remembered
lists more times than for anything else.

WHY A PER-ENGINE SEAL WHEN GENERIC ONES EXIST. Several of these sites already have derived
checks — `test_reregister_covers_every_registering_engine`, `test_mirror_covers_the_build_matrix`,
`test_service_urls_are_real`. They are better than this file and this file does not duplicate
them. What they cannot do is answer **"is THIS engine complete?"** in one place at one moment,
which is the question a lane asks before a roll and the question whose wrong answer is a partly
wired engine that passes every probe.

**SITE 6 IS THE ONE TO WATCH AND IT IS ASSERTED AS PRESENCE, NOT ABSENCE-OF-FAILURE.** An engine
missing from `_KEY_TO_AGENT_DIR` is not *failing* that file's checks — it is UNEXAMINED by them.
A skip reads as a pass, which is how `engineFinance` went five days unchecked. So this asserts the
key is THERE rather than trusting that file to be green.

The two failure modes worth naming, because they are opposite:
  site 8 (`ENGINE_*_PUBLIC_URL`)  fails SILENTLY — the engine registers against its default and
                                  the verb resolves to an address nothing is listening on
  build matrix                    fails with NO ERROR AT ALL — no image is ever built, and
                                  nothing complains until a deploy asks for a tag
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_PACKET = _REPO / "docs" / "plans" / "adding-an-engine-has-more-registry-sites-than-the-runbook-names.md"

#: This file, read as text: the derived coverage check below asks which `test_site_<n>` functions
#: exist rather than being told. Reading the source is deliberate — introspecting `globals()` would
#: see only what has already been defined when the module is executing.
_SELF = Path(__file__).read_text(encoding="utf-8")

#: Engine S's four names (runbook §0). They DIFFER, which is normal and is exactly why grepping
#: any one of them finds only part of the wiring.
VALUES_KEY = "engineSafety"
COMPONENT = "engine-safety"
IMAGE = "safety-agent"
KEYCLOAK_CLIENT = "iagent-safety-agent"
AGENT_DIR = "safety_agent"


def _read(rel: str) -> str:
    p = _REPO / rel
    assert p.exists(), f"{rel} does not exist — the seal's instrument is broken, not the wiring"
    return p.read_text(encoding="utf-8")


def test_the_seal_covers_every_site_the_packet_lists():
    """THE COUNT IS DERIVED FROM THE PACKET AT BOTH ENDS, and neither end is a literal.

    Without this, the seal below silently keeps checking eight while the real number is ten —
    which is precisely the shape the packet was written about.

    **THE FIRST VERSION OF THIS TEST WAS ITSELF THE DEFECT IT GUARDS.** It asserted `"9" not in
    rows` — a hardcoded boundary that told the next author to *"add it here"*, so growing the
    packet meant editing a literal in the seal. It fired correctly when the packet grew to ten
    (`invincible-agent-01`, 2026-09-12), and the right repair was not to change 9 to 11: it was
    to stop naming a number at all. This now reads the packet's site numbers and asserts a
    `test_site_<n>` exists for each, so the packet and the seal cannot drift in either
    direction, and a NEW site is red until it is checked rather than until someone notices.

    **A hand-written list of a population is a sample — and so is a hand-written count of one.**
    """
    text = _PACKET.read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*(\d+(?:–\d+)?)\s*\|", text, re.M)
    assert rows, "no site rows parsed from the packet — instrument failure"
    assert "1–4" in rows, (
        f"the packet's site numbering changed: {rows}. This seal reads it rather than restating "
        "it, so the parse must be repaired, not the expectation."
    )

    covered = set(re.findall(r"^def test_sites?_(\d+)(?:_to_(\d+))?_", _SELF, re.M))
    have = {int(a) for a, _ in covered} | {
        n for a, b in covered if b for n in range(int(a), int(b) + 1)
    }
    want = set()
    for r in rows:
        if "–" in r:
            lo, hi = r.split("–")
            want |= set(range(int(lo), int(hi) + 1))
        else:
            want.add(int(r))

    missing = sorted(want - have)
    assert not missing, (
        f"the packet lists site(s) {missing} and this seal has no `test_site_{missing[0]}_*` for "
        f"them — the seal would quietly under-report completeness, which is the packet's own "
        f"thesis turned on its instrument. Covered: {sorted(have)}."
    )
    assert have >= want and len(want) >= 8, (
        f"the packet shrank to {sorted(want)} — fewer sites than have ever been found, which is "
        f"more likely a parse failure than a real deletion"
    )

def test_sites_1_to_4_the_four_name_registries():
    """values key, component/service, image, Keycloak client — all four, each in its own file."""
    values = _read("helm/invincible-agent/values.yaml")
    engines = _read("helm/invincible-agent/templates/engines.yaml")

    assert re.search(rf"^{VALUES_KEY}:$", values, re.M), f"site 1: no `{VALUES_KEY}:` block"
    assert f'"component" "{COMPONENT}"' in engines, f"site 2: {COMPONENT} not in the $engines list"
    assert f'"key" "{VALUES_KEY}"' in engines, f"site 2: $engines entry does not key off {VALUES_KEY}"
    assert f"name: {IMAGE}" in values, f"site 3: image `{IMAGE}` not declared"
    assert f'clientId: "{KEYCLOAK_CLIENT}"' in values, f"site 4: no Keycloak client {KEYCLOAK_CLIENT}"
    # The secret the client id resolves through — one value feeding both the realm import and the
    # env var, so the two cannot drift into a silent 401.
    assert "safetyAgentClientSecret" in values, "site 4: client declared with no secretRef target"


def test_site_5_the_reregister_list():
    """Absent here the engine never restarts on a re-prime, so it never re-registers — and the
    graph comes back missing exactly this engine's verbs while every other one returns."""
    values = _read("helm/invincible-agent/values.yaml")
    block = values.split("reregisterEngines:", 1)[1].split("\n\n", 1)[0]
    assert f"- {COMPONENT}" in block, f"site 5: {COMPONENT} missing from reregisterEngines"


def test_site_6_the_key_to_agent_dir_map_ASSERTED_AS_PRESENCE():
    """SITE 6, AND THE ASSERTION IS DELIBERATELY POSITIVE.

    An engine absent from this map is not failing that file's checks — every one of them SKIPS
    it. A skip reads as a pass. So presence is asserted here rather than inferred from that
    suite being green.
    """
    src = _read("tests/test_reregister_covers_every_registering_engine.py")
    assert f'"{VALUES_KEY}": "{AGENT_DIR}"' in src, (
        f"site 6: {VALUES_KEY} is not in _KEY_TO_AGENT_DIR — every check in that file SKIPS this "
        "engine, and a skip is not a pass"
    )


def test_site_7_the_artifactory_mirror():
    """A work cluster cannot fall back to ghcr, so an unmirrored image is an ImagePullBackOff the
    moment the chart flag flips. Default-off is a default, not protection."""
    mirror = _read("scripts/mirror-to-artifactory.ps1")
    assert f"invincible-agent/{IMAGE}:latest" in mirror, f"site 7: {IMAGE} not mirrored"


def test_site_8_the_public_url_THE_SILENT_ONE():
    """Missing or wrong, this does not error: the engine registers against whatever default it
    has, every probe stays green, and the verb resolves to an address nothing is listening on."""
    cm = _read("helm/invincible-agent/templates/configmap.yaml")
    assert "ENGINE_SAFETY_PUBLIC_URL" in cm, "site 8: no ENGINE_SAFETY_PUBLIC_URL"
    line = next(l for l in cm.splitlines() if "ENGINE_SAFETY_PUBLIC_URL" in l)
    assert COMPONENT in line, f"site 8: the URL does not name {COMPONENT}"
    assert "svcDomain" in line, (
        "site 8: bare service name — it resolves differently depending on where the reader stands"
    )
    assert f".Values.{VALUES_KEY}.port" in line, (
        "site 8: the port is hardcoded rather than read from the values key, so the URL and the "
        "container port can drift apart"
    )


def test_site_9_the_endpoint_gating_manifest_FAILS_BY_SKIP():
    """SITE 9. Same shape as site 6, and the same reason the assertion is positive.

    `SERVICE_FILES` is the population `test_endpoint_gating_manifest.py` parametrises over. An
    engine absent from it is not FAILING endpoint gating — it is **not being asked about it**,
    and that file reports green over a service it never opened.
    """
    src = _read("tests/test_endpoint_gating_manifest.py")
    assert f'"{AGENT_DIR}": "agent_fleet/{AGENT_DIR}/main.py"' in src, (
        f"site 9: {AGENT_DIR} is not in SERVICE_FILES — the endpoint-gating manifest does not "
        "examine this service at all, and a skip reads as a pass"
    )


def test_site_10_the_census_url_var_map():
    """SITE 10, and it is the only site in the packet that was GUARDED BEFORE IT WAS MISSED.

    `_COMPONENT_TO_URL_VAR` derives the set of components that must appear in it from the
    chart's `$engines` list, so an absent engine is red WITH A NAME rather than skipped. It
    earns a check here anyway: a site being well-guarded does not make it not a site, and this
    seal's job is to assert the engine is registered everywhere it must be — not to re-audit
    which of those places happen to police themselves.
    """
    src = _read("tests/test_the_census_population_covers_every_engine.py")
    assert f'"{COMPONENT}": "ENGINE_SAFETY"' in src, (
        f"site 10: {COMPONENT} is in neither _COMPONENT_TO_URL_VAR nor _NOT_CENSUSED — the "
        "census would print a complete-looking table with this engine missing from it"
    )

def test_the_build_matrix_THE_ONE_WITH_NO_ERROR_AT_ALL():
    """Named in the packet beside the eight. Without it no image is ever built at any pinned sha,
    and nothing complains until a deploy asks for a tag that was never produced."""
    wf = _read(".github/workflows/build-containers.yml")
    assert f"service: {IMAGE}" in wf, f"build matrix: {IMAGE} is never built"
    assert f"path: agent_fleet/{AGENT_DIR}" in wf, "build matrix: wrong source path"


def test_the_port_agrees_everywhere_it_is_written():
    """THE PORT IS WRITTEN IN TWO PLACES AND A MISMATCH IS A CLOSED-PORT READINESS PROBE.

    Derived from the chart rather than asserted as a literal, so re-porting the engine needs one
    edit and this seal follows it.
    """
    values = _read("helm/invincible-agent/values.yaml")
    block = values.split(f"\n{VALUES_KEY}:\n", 1)[1].split("\nengine", 1)[0]
    m = re.search(r"^\s*port:\s*(\d+)", block, re.M)
    assert m, f"no port in the {VALUES_KEY} block"
    port = m.group(1)
    wf = _read(".github/workflows/build-containers.yml")
    matrix_block = wf.split(f"service: {IMAGE}", 1)[1].split("- service:", 1)[0]
    assert f'port: "{port}"' in matrix_block, (
        f"the chart says port {port} and the build matrix disagrees — the readiness probe hits a "
        "closed port and the engine never becomes ready"
    )


def test_no_other_engine_claimed_these_names():
    """RUNBOOK §0's CHECK, KEPT RUNNING. `engine-f` was already the presentation agent when
    ADR-0045 called the finance engine "Engine F"; reusing it would have pointed
    PRESENTATION_AGENT_SVC_URL at a finance engine and taken /render_ui down fleet-wide.

    A name is claimed at implementation time, not at ADR time, so the check belongs in the suite
    rather than in a commit message.
    """
    engines = _read("helm/invincible-agent/templates/engines.yaml")
    rows = re.findall(r'"key" "(\w+)" "component" "([\w-]+)"', engines)
    by_component: dict[str, list[str]] = {}
    for key, component in rows:
        by_component.setdefault(component, []).append(key)
    dupes = {c: k for c, k in by_component.items() if len(k) > 1}
    assert not dupes, f"two engines share a component name: {dupes}"
    assert by_component.get(COMPONENT) == [VALUES_KEY], (
        f"{COMPONENT} is claimed by {by_component.get(COMPONENT)}, not solely by {VALUES_KEY}"
    )
