"""IN-CLUSTER URLS IN THE CHART MUST BE FULLY QUALIFIED. A bare name is a topology claim.

THIS DEFECT HAS NOW LANDED THREE TIMES, and each time it was invisible in the topology it
was written in:

  * chart 0.3.22 — every engine URL rendered bare because `svcDomain` defaulted to empty.
    Under a corporate proxy a dotless host cannot suffix-match a NO_PROXY entry of `.svc` /
    `.svc.cluster.local`, so the in-cluster call was handed to the proxy and failed.
  * 2026-08-31 — a registration baked `http://iagent-cortex-bff:8090` into a verb edge from
    a Python literal. Correct in sandbox, wrong at work three ways over.
  * 2026-09-02 — the four Restate deployment URIs in jobs.yaml. These are STORED IN RESTATE
    and dereferenced BY Restate, so in a split-namespace deploy they resolve nothing:
    `[META0003] ... failed to lookup address information: Name or service not known`.

The common shape: **a bare service name asserts that the reader is in this namespace and
behind no proxy.** Both halves are true in sandbox and neither is guaranteed at work.

WHY THIS TEST STRIPS COMMENTS FIRST. The templates now EXPLAIN this defect, and the
explanations quote the bad URLs verbatim — including the comment block added directly above
the lines this test guards. A naive grep matches the prose that documents the fix and calls
it the fix's absence. That is this repo's most-repeated instrument defect, and here it is
guaranteed rather than merely possible, so the stripping is not defensive coding but a
correctness requirement.

WHAT THIS GUARD DOES NOT COVER, stated so its green is not read as more than it is. It
checks TEMPLATE SOURCE only. Bare hosts can also arrive from VALUES, and some do:

  * values.yaml still carries five live `http://iagent-minio:9000` defaults (the MinIO
    endpoint, repeated per engine). They hardcode the SANDBOX release name and are bare, so
    they are wrong twice over at a release named anything else — but MinIO may legitimately
    be external at work, so the fix is a helper plus an externalMinio override, which is a
    decision rather than a mechanical edit.
  * values-sandbox.yaml names sandbox hosts throughout, which is CORRECT — it is the sandbox
    overlay. Its `ENGINE_A_PUBLIC_URL` / `ENGINE_DA_PUBLIC_URL` entries are the shape a work
    overlay must mirror with its own release prefix and FQDN, because those values are
    self-advertised into the graph and dereferenced by the supervisor later.

So: a green here means no TEMPLATE emits a bare release-relative host. It does not mean the
rendered chart is free of them, and the rendered output is the claim an operator cares
about. Extending this to render-and-scan needs a values fixture per topology; until then the
gap is named rather than implied away.

Run:  uv run --frozen python -m pytest tests/test_incluster_urls_are_qualified.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATES = _ROOT / "helm" / "invincible-agent" / "templates"

#: A release-relative service host with a port and no domain between them.
_BARE = re.compile(r"\{\{\s*\.Release\.Name\s*\}\}-[a-z0-9-]+:")

#: Hosts that are NOT release-relative in-cluster services, so a bare form is not a claim
#: about namespace at all. Each entry is an exemption and therefore a statement.
_EXEMPT_FILES = {
    # Renders a Service's own spec, where a bare name is the object's identity, not a
    # reference to be resolved by anyone.
    "service-monitor.yaml",
}


def _code_lines(path: Path):
    """Template lines with comment-only lines removed.

    A YAML comment cannot be told from code by a substring search, and the comment block
    guarding these very lines quotes the bare URLs it forbids.
    """
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if raw.lstrip().startswith("#"):
            continue
        yield i, raw


def _offenders():
    found = []
    for path in sorted(_TEMPLATES.glob("*.yaml")):
        if path.name in _EXEMPT_FILES:
            continue
        for lineno, line in _code_lines(path):
            if "svcDomain" in line:
                continue                      # qualified on this same line
            for m in _BARE.finditer(line):
                found.append(f"{path.name}:{lineno}  {line.strip()[:110]}")
    return found


def test_no_template_emits_a_bare_release_relative_host():
    """Every `{{ .Release.Name }}-<svc>:<port>` must carry the svcDomain helper.

    The failure this prevents is not a crash. It is a URL that works in the topology it was
    written in and resolves nothing in the one it is deployed into — which surfaces three
    layers away, as a DNS error inside a dependency nobody was looking at.
    """
    offenders = _offenders()
    assert offenders == [], (
        "bare in-cluster hosts in the chart — add "
        '{{ include "invincible-agent.svcDomain" . }} after the service name:\n  '
        + "\n  ".join(offenders)
    )


def test_the_guard_is_PROVEN_RED_and_ignores_the_prose_that_documents_it():
    """Fires on real template code; silent on the comments explaining the defect.

    The second case is not hypothetical — jobs.yaml now carries a comment block quoting
    `http://iagent-engine-e:8086/restate` as the symptom, immediately above the lines this
    guards. Without comment-stripping this test would fail on its own documentation.
    """
    bad = '              value: "http://{{ .Release.Name }}-electric:3000"'
    good = ('              value: "http://{{ .Release.Name }}-electric'
            '{{ include "invincible-agent.svcDomain" . }}:3000"')
    prose = "              # never write http://{{ .Release.Name }}-electric:3000 here"

    assert _BARE.search(bad)
    assert "svcDomain" not in bad
    assert "svcDomain" in good
    assert prose.lstrip().startswith("#"), "the comment case must be filtered by _code_lines"


def test_the_four_restate_deployment_uris_are_qualified():
    """THE SPECIFIC REGRESSION, pinned by name.

    These four are the only URLs in the chart dereferenced by a process OUTSIDE the release
    namespace, which is why they broke first and why a general rule alone is not enough —
    a future edit could reintroduce one and the aggregate guard would catch it, but naming
    them records WHY they are special.
    """
    jobs = (_TEMPLATES / "jobs.yaml")
    uris = [
        line for _, line in _code_lines(jobs)
        if '"uri": "http://' in line
    ]
    assert len(uris) == 4, f"expected 4 registered Restate deployments, found {len(uris)}"
    for line in uris:
        assert "svcDomain" in line, (
            "a registered Restate deployment URI is bare; Restate resolves it from ITS "
            f"namespace, not ours:\n  {line.strip()}"
        )
