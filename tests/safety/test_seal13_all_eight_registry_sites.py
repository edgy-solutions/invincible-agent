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


def test_the_packet_still_says_eight_so_this_seal_is_not_stale():
    """THE COUNT IS DERIVED FROM THE PACKET, and if the packet grows a ninth site this goes red.

    Without this, the seal below silently keeps checking eight while the real number is nine —
    which is precisely the shape the packet was written about.
    """
    text = _PACKET.read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*(\d+(?:–\d+)?)\s*\|", text, re.M)
    assert rows, "no site rows parsed from the packet — instrument failure"
    # Rows are numbered `1–4` (the four name registries) then 5, 6, 7, 8.
    assert "1–4" in rows and "8" in rows, (
        f"the packet's site numbering changed: {rows}. Re-derive this seal from it rather than "
        "updating the number here."
    )
    assert "9" not in rows, (
        "the packet now lists a NINTH registry site and this seal only checks eight — add it "
        "here rather than letting the seal quietly under-report completeness"
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
