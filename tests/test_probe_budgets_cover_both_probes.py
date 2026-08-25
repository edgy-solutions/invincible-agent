"""A container with an HTTP probe must budget BOTH probes, not one.

WHY THIS EXISTS. On 2026-08-22 a sweep gave `livenessProbe` an explicit budget on five
deployments after cortex-bff was SIGKILLed (exit 137) for being busy. It left every
`readinessProbe` inheriting Kubernetes' defaults — `timeoutSeconds: 1`, `failureThreshold: 3`.

On 2026-08-25 that omission produced a night of contradictory evidence:

    Liveness probe failed:  /health context deadline exceeded
    Readiness probe failed: /health context deadline exceeded

A retry storm saturated cortex-bff's single-threaded event loop, `/health` missed its
ONE-SECOND readiness window, Kubernetes pulled the pod from the service endpoints, and Traefik
— with no healthy backend — answered every browser call with **404 and no CORS headers**. The
app never saw the request, so it never added them.

Three observers then spent hours reconciling "the backend returns 200 with nine cells" against
"the browser gets 404 with no CORS". Both were true, seconds apart, because readiness was
flapping. Hypotheses burned along the way: persisted state, a missing ingress route, DNS-over-
HTTPS, a stale bundle. None were wrong about their own evidence; all were looking at a system
whose availability was oscillating.

**FIXING THE PROBE THAT KILLS AND LEAVING THE PROBE THAT DISCONNECTS is a smaller blast radius,
not a safe one.** Liveness restarts a pod; readiness silently removes it from every load
balancer while it stays "Running" and "healthy" to anyone reading `kubectl get pods`.

This seal exists because the first fix was applied where the symptom was seen rather than to the
population that shares the cause — the same shape as the re-register list and the phantom
service URL, both of which also took a second occurrence to enumerate.
"""
from __future__ import annotations

import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TEMPLATES = _ROOT / "helm" / "invincible-agent" / "templates"

# Engines deliberately use a TCP liveness probe so "only a true port loss restarts the
# container" (templates/engines.yaml says so, with its reasoning). A TCP probe has no event
# loop to starve, so this rule does not apply to it — the rule is about HTTP probes that must
# be ANSWERED by the application.
_HTTP_PROBE = re.compile(
    r"(readinessProbe|livenessProbe):\s*\n(?P<body>(?:[ \t]+.*\n|\n)*?)(?=^[ \t]{0,10}\w|\Z)",
    re.MULTILINE,
)


def _probe_blocks(text: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r"^(\s*)(readinessProbe|livenessProbe):\s*$", text, re.MULTILINE):
        indent, kind = m.group(1), m.group(2)
        rest = text[m.end():]
        lines = []
        for line in rest.splitlines():
            if line.strip() and not line.startswith(indent + " "):
                break
            lines.append(line)
        out.append((kind, "\n".join(lines)))
    return out


def _templates() -> list[pathlib.Path]:
    return sorted(p for p in _TEMPLATES.glob("*.yaml") if p.is_file())


def test_the_inputs_are_readable():
    """Positive control — a glob that matched nothing would pass over nothing."""
    assert len(_templates()) >= 5
    blocks = [b for p in _templates() for b in _probe_blocks(p.read_text(encoding="utf-8"))]
    assert len(blocks) >= 6, f"only {len(blocks)} probe blocks parsed — the shape moved"


def test_every_HTTP_probe_declares_its_own_budget():
    """THE SEAL, and it covers BOTH probe kinds.

    An HTTP probe must be ANSWERED by the app, so it inherits the app's worst moment. A TCP
    probe cannot starve and is exempt — engines use one deliberately.
    """
    offenders = []
    for path in _templates():
        text = path.read_text(encoding="utf-8")
        for kind, body in _probe_blocks(text):
            if "httpGet" not in body:
                continue  # tcpSocket / exec — nothing to starve
            if "timeoutSeconds" not in body or "failureThreshold" not in body:
                missing = [
                    f for f in ("timeoutSeconds", "failureThreshold") if f not in body
                ]
                offenders.append(f"{path.name}: {kind} missing {', '.join(missing)}")

    assert not offenders, (
        "HTTP probes inheriting Kubernetes' defaults (timeoutSeconds 1, failureThreshold 3):\n  "
        + "\n  ".join(offenders)
        + "\n\nOne second asks a single-threaded event loop to answer inside a tick. A READINESS "
        "probe that fails does not restart anything — it silently removes the pod from every "
        "load balancer while `kubectl get pods` still reads Running."
    )


def test_readiness_is_never_tighter_than_liveness_in_one_container():
    """The asymmetry that caused this. If readiness is stricter than liveness, a pod
    disconnects before it restarts — invisible in pod status and fatal at the edge."""
    for path in _templates():
        text = path.read_text(encoding="utf-8")
        blocks = dict(_probe_blocks(text))
        if "readinessProbe" not in blocks or "livenessProbe" not in blocks:
            continue
        if "httpGet" not in blocks["readinessProbe"]:
            continue

        def _num(body: str, field: str, default: int) -> int:
            m = re.search(rf"{field}:\s*(\d+)", body)
            return int(m.group(1)) if m else default

        r = _num(blocks["readinessProbe"], "timeoutSeconds", 1)
        live_has_http = "httpGet" in blocks["livenessProbe"]
        lv = _num(blocks["livenessProbe"], "timeoutSeconds", 1) if live_has_http else r
        assert r >= lv or not live_has_http, (
            f"{path.name}: readiness timeout {r}s is tighter than liveness {lv}s — the pod "
            f"leaves the load balancer before anything restarts it"
        )
