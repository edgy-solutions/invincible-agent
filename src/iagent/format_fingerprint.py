"""FORMAT FINGERPRINT — re-export shim. The ONE implementation lives in
``agent_fleet/utils/format_fingerprint.py``.

Same shape and same reason as ``src/iagent/trust_table.py``: engine-a's image does NOT contain
``src/`` (verified on the running pod — ``/app/src`` does not exist), so anything ``ReviewStarter``
must compute has to live in ``agent_fleet/utils/`` — the only tree BOTH runtimes carry. This shim
keeps every existing ``src/iagent`` importer working unchanged, which is what makes the move
provably behaviour-preserving: the proven tests import through here and still pass.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

try:
    from agent_fleet.utils.format_fingerprint import format_fingerprint  # noqa: F401
except ImportError:  # pragma: no cover — repo root not on sys.path (script/test invocations)
    _repo_root = _Path(__file__).resolve().parents[2]
    if str(_repo_root) not in _sys.path:
        _sys.path.insert(0, str(_repo_root))
    from agent_fleet.utils.format_fingerprint import format_fingerprint  # noqa: F401

__all__ = ["format_fingerprint"]
