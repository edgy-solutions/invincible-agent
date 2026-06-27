"""Run the projector as a process: `python -m iagent.projector`.

In production, the helm template `templates/projector.yaml` invokes
uvicorn directly against `iagent.projector.app:app`. This module-main
shape exists for local-run during Hop 2 probe development.
"""
from __future__ import annotations

import logging
import os

import uvicorn

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def main() -> None:
    uvicorn.run(
        "iagent.projector.app:app",
        host=os.getenv("PROJECTOR_HOST", "0.0.0.0"),
        port=int(os.getenv("PROJECTOR_PORT", "8095")),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
