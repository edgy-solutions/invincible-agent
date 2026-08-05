"""TRUST TABLE — re-export shim. The ONE implementation lives in ``agent_fleet/utils/trust_table.py``.

WHY IT MOVED (2026-08-05, ADR-0034 phase 1.3). The table's resolver acquired a SECOND caller:
``ReviewStarter`` (engine-a) must compute ``rung_for`` server-side to choose which workflow
definition to start. Engine-a's image does NOT contain ``src/`` — verified on the running pod,
``/app/src`` does not exist — so ``iagent.trust_table`` was unimportable there and the resolver was
physically unreachable from the component that now needs it.

``agent_fleet/utils/`` is the only tree BOTH runtimes carry: engine-a flattens it to ``/app/utils/``
and the Dagster user-code image has ``/app/agent_fleet/utils/``. This is the identical relocation
``utils/service_identity.py`` made for the same reason, and for the same rule — ONE home, never two:
two copies of an admission-policy resolver are two chances to disagree about whether a pipeline may
act unsupervised.

This shim keeps every existing importer (`iagent.defs.extraction_review_sensor`,
`iagent.decision_record*`, `tests/test_trust_table.py`) working UNCHANGED, which is what makes the
move provably behaviour-preserving: the proven tests import through here and still pass.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

# The fleet tree is a sibling of `src/` in the repo and is flattened to /app/utils in the images.
# Try the package path first (repo + Dagster layout), then the flattened one (engine-a layout).
try:
    from agent_fleet.utils.trust_table import *  # noqa: F401,F403
    from agent_fleet.utils.trust_table import (  # noqa: F401
        DEFAULT_RUNG, MONITORED, RUNGS, SUPERVISED, TRUSTED, TrustTable, TrustTableInvalid,
        load_trust_table, parse_trust_table, promotion_is_permitted, table_ref,
    )
except ImportError:  # pragma: no cover — repo-root not on sys.path (script/test invocations)
    _repo_root = _Path(__file__).resolve().parents[2]
    if str(_repo_root) not in _sys.path:
        _sys.path.insert(0, str(_repo_root))
    from agent_fleet.utils.trust_table import *  # noqa: F401,F403
    from agent_fleet.utils.trust_table import (  # noqa: F401
        DEFAULT_RUNG, MONITORED, RUNGS, SUPERVISED, TRUSTED, TrustTable, TrustTableInvalid,
        load_trust_table, parse_trust_table, promotion_is_permitted, table_ref,
    )
