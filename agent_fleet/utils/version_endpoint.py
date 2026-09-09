"""`/version` — what commit is THIS process running, asked of the process itself.

WHY IT IS NOT THE POD SPEC. On 2026-09-08 the question "is the fix on the pod?" was answered
twice by a person squinting at pod age and then importing a symbol by hand. Under `:latest`
pod age is not evidence: a pod started an hour ago may run a week-old image, and a week-old
pod may have been running the newest image the whole time. The image tag in the spec is a
claim about what was REQUESTED, and under `:latest` it is not even that.

`IAGENT_GIT_SHA` is baked into the image at build time (`ARG GIT_SHA` in the three inline
Dockerfiles in `.github/workflows/build-containers.yml`), so it cannot drift from the code in
the layer beside it. This endpoint reports that, and nothing it was told by a chart.

EACH THING IS THE THING THAT WAS PUSHED — NOT "everything has the same number". The frontend
is a separate repo with its own head and its own roll; comparing its sha to the backend's
would be comparing two unrelated histories. So `/version` reports a sha AND the repo it came
from, and the census compares each service to the head of ITS OWN repo.

ONE IMPLEMENTATION, THIRTEEN MOUNTS. A per-service copy is how twelve services come to
report eleven different shapes, and the aggregator then needs a special case per engine —
which is the same copy problem this repo paid for in the routing record.

`unknown` IS REPORTED HONESTLY rather than smoothed to a blank or to a plausible default:
an image built before the stamp existed genuinely cannot say what it is, and that is exactly
what a stale pod looks like. See [[optimistic-defaults-are-dishonest]].
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict

__all__ = ["version_payload", "mount_version", "SHA_ENV", "REPO"]

#: Baked by the image build. Absent on any image built before 2026-09-09.
SHA_ENV = "IAGENT_GIT_SHA"
#: Set by the image build alongside the sha; absent is honest rather than "now".
BUILT_ENV = "IAGENT_BUILT_AT"
#: Which repository the sha belongs to. Every service in this image tree is this one; the
#: frontend answers with its own. The census needs it to know which head to compare against.
REPO = "invincible-agent"

_STARTED_AT = time.time()


def version_payload(component: str) -> Dict[str, Any]:
    """The whole answer, in one shape every service returns.

    `image_tag` is what the ORCHESTRATOR asked for and `git_sha` is what the process IS.
    Both are reported because a disagreement between them is a finding: the pod did not
    restart, or something is serving that the spec did not describe. Collapsing them into
    one field would remove the only way to tell those apart.
    """
    sha = (os.getenv(SHA_ENV) or "").strip()
    return {
        "component": component,
        "repo": REPO,
        # `null`, never "unknown" as a string: a consumer testing truthiness must not be
        # handed a value that reads as a real sha.
        "git_sha": sha if sha and sha != "unknown" else None,
        "built_at": (os.getenv(BUILT_ENV) or "").strip() or None,
        # The chart's claim, for the disagreement above. Absent unless the chart sets it.
        "image_tag": (os.getenv("IAGENT_IMAGE_TAG") or "").strip() or None,
        "uptime_s": round(time.time() - _STARTED_AT, 1),
    }


def mount_version(app: Any, component: str) -> Any:
    """Add `GET /version` to a FastAPI app. Idempotent and never fatal.

    NEVER FATAL BY CONSTRUCTION: a service that fails to start because its version endpoint
    could not be mounted would be an observability aid causing an outage. A missing endpoint
    shows up in the census as an unreachable service, which is the honest signal.
    """
    try:
        if any(getattr(r, "path", None) == "/version" for r in app.routes):
            return app

        @app.get("/version", tags=["ops"])
        async def _version() -> Dict[str, Any]:  # noqa: D401
            return version_payload(component)

    except Exception as exc:  # noqa: BLE001
        print(f"[{component}] /version not mounted ({type(exc).__name__}: {exc})")
    return app
