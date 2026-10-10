"""ORIGIN ENTITLEMENT — re-export shim. The ONE implementation lives in
``agent_fleet/utils/origin_entitlement.py``.

Same shape and same reason as ``src/iagent/format_fingerprint.py``: engine images do NOT contain
``src/``, and engine-o's notice_parts read check must evaluate the SAME decider the BFF does, so
the pure core lives in ``agent_fleet/utils/`` — the only tree BOTH runtimes carry. This shim keeps
every existing ``src/iagent`` importer working unchanged. ``DropperNotProgramMember`` is the one
class object, re-exported, never redefined.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

try:
    from agent_fleet.utils.origin_entitlement import (  # noqa: F401
        DropperNotProgramMember,
        Origin,
        can_consume,
        check_dropper_bound,
        load_domain_consumption,
        origin_visible,
    )
except ImportError:  # pragma: no cover — repo root not on sys.path (script/test invocations)
    _repo_root = _Path(__file__).resolve().parents[2]
    if str(_repo_root) not in _sys.path:
        _sys.path.insert(0, str(_repo_root))
    from agent_fleet.utils.origin_entitlement import (  # noqa: F401
        DropperNotProgramMember,
        Origin,
        can_consume,
        check_dropper_bound,
        load_domain_consumption,
        origin_visible,
    )

__all__ = [
    "DropperNotProgramMember",
    "Origin",
    "can_consume",
    "check_dropper_bound",
    "load_domain_consumption",
    "origin_visible",
]
