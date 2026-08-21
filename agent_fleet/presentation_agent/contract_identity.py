"""Content-addressed identity for presentation contracts (ADR-0017, graph-backed form).

WHY CONTENT-ADDRESSING, and not a version string. A version is an ASSERTION about change; a
content hash is a FACT about it. Under a version string, a client can edit a contract and
forget to bump — the graph then serves the OLD contract under a version that claims to be
current, and nothing detects it. Under content-addressing, a changed contract IS a different
node, so a mismatch between what the client would publish and what the graph holds is not an
inference, it is an equality check.

AND IT FIRES AT REGISTRATION TIME, WHICH IS THE POINT. The alternative -- a reference pointing
at a contract that changed underneath it -- serves the NEW contract under the OLD row's
authority, which is quiet in the worst way. Here the divergence surfaces when the client
registers, before any render depends on it.

WHY THE CONTRACT IS ITS OWN NODE and not inlined into the Predicate row: contracts are
DOCUMENTS -- encodings, cardinality, refusal vocabulary. Inlining a typed document into row
properties creates serialization surface exactly where compact-vs-full form drift has bitten
this project repeatedly. The row keeps ONE reference field; the contract is a first-class
graph citizen with its own identity.

CANONICALISATION IS LOAD-BEARING. Two clients that publish the same contract with keys in a
different order, or with different float spellings, MUST produce the same hash -- otherwise
"the same contract" registers as two nodes and the drift signal fires on a non-difference.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


#: Bumped only when the CANONICAL FORM changes -- i.e. when two inputs that used to hash the
#: same would stop doing so. Prefixed onto the digest so a canonicalisation change is visible
#: in the id rather than silently re-addressing every contract in the graph.
CANONICAL_FORM_VERSION = "cf1"


def canonical_contract_json(contract: Dict[str, Any]) -> str:
    """The canonical serialization a hash is taken over.

    `sort_keys` makes key order irrelevant; `separators` removes incidental whitespace;
    `ensure_ascii=False` keeps a non-ASCII refusal reason from hashing differently depending
    on who serialized it. Tuples and lists both land as arrays, which is intended: a contract
    that declares its fields as a tuple in Python and an array in TypeScript is the SAME
    contract, and the whole point is that two publishers of one contract agree.
    """
    return json.dumps(
        contract,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def contract_id(contract: Dict[str, Any]) -> str:
    """Stable content address for a contract document.

    Returned as `cf1:<sha256-hex>` -- the canonical-form version is part of the id so a
    change to canonicalisation cannot masquerade as a change to contracts.
    """
    payload = canonical_contract_json(contract).encode("utf-8")
    return f"{CANONICAL_FORM_VERSION}:{hashlib.sha256(payload).hexdigest()}"


def contracts_agree(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """True when two contract documents are the same contract.

    An equality check, never a similarity judgement. This is the drift signal: the client
    computes its id and compares against the graph's, and disagreement means REGISTER, not
    "probably fine".
    """
    return contract_id(a) == contract_id(b)
