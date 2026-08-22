"""The sandbox tracks master, so every image it runs must RESOLVE to `latest`.

WHY THIS EXISTS. Engine P was deployed with `enginePlanning.image.tag: ""` in values.yaml
and no override in values-sandbox.yaml, and went straight to ImagePullBackOff asking for
`planning-agent:2026.07.02` — a tag that has never existed, because the planning agent was
built for the first time today.

The chart has TWO working conventions for the same outcome, and nothing named them:

  * declare `tag: "latest"` in values.yaml            (engineA, engineE, engineW, ...)
  * declare `tag: ""` + override in values-sandbox    (engineO, engineD, engineF, ...)

Both resolve to `latest`. A new component that does NEITHER falls through
`_helpers.tpl`'s `.tag | default .root.Chart.AppVersion` to the chart appVersion, which
pins a July snapshot. For components that existed in July that tag resolves and the
mistake is invisible; for anything built since, the pod cannot start.

So the assertion is on the RESOLVED value, not on which convention was used — the chart
is allowed to keep both, and neither is the "right" one to imitate.
"""

from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

CHART = pathlib.Path(__file__).resolve().parents[1] / "helm" / "invincible-agent"


def _load(name: str) -> dict:
    return yaml.safe_load((CHART / name).read_text(encoding="utf-8")) or {}


def _built_image_components(values: dict) -> list[str]:
    """Components whose image WE build (they declare image.name), not upstream charts."""
    return [
        key
        for key, block in values.items()
        if isinstance(block, dict)
        and isinstance(block.get("image"), dict)
        and "name" in block["image"]
    ]


def _resolve_tag(key: str, values: dict, sandbox: dict, app_version: str) -> str:
    """Mirror templates/_helpers.tpl: `.tag | default .root.Chart.AppVersion`."""
    for source in (sandbox.get(key) or {}, values.get(key) or {}):
        tag = (source.get("image") or {}).get("tag")
        if tag:  # helm's `default` treats "" as unset, and so must we
            return tag
    return app_version


def test_every_sandbox_enabled_built_image_resolves_to_latest() -> None:
    values = _load("values.yaml")
    sandbox = _load("values-sandbox.yaml")
    app_version = str(_load("Chart.yaml").get("appVersion", ""))

    offenders = []
    for key in _built_image_components(values):
        enabled = (sandbox.get(key) or {}).get(
            "enabled", (values.get(key) or {}).get("enabled")
        )
        if not enabled:
            continue  # a disabled component ships no pod, so its tag cannot fail
        resolved = _resolve_tag(key, values, sandbox, app_version)
        if resolved != "latest":
            offenders.append(f"{key} -> {resolved!r}")

    assert not offenders, (
        "sandbox-enabled components resolve to a tag other than 'latest':\n  "
        + "\n  ".join(offenders)
        + f"\n\nAn unset tag falls through to Chart.yaml appVersion ({app_version!r}), "
        "which only resolves for images that were built when that version was cut. "
        'Fix by declaring image.tag: "latest" in values.yaml OR in values-sandbox.yaml.'
    )
