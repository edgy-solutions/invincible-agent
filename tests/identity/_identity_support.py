"""Shared support for the three identity seals (not a test module).

`declared_delegates()` reads the delegate -> principals pairs from where the deploy declares them
(the chart's sandbox values, mirroring `templates/configmap.yaml`'s DELEGATE_ON_BEHALF_OF
rendering), and `install_delegates()` puts them where the SERVER reads them (the
DELEGATE_ON_BEHALF_OF environment variable, via `gateway._delegate_principals()`). No principal is
typed in a seal: a pair is whatever the chart declares, read back through the server's own reader.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
VALUES = ROOT / "helm" / "invincible-agent" / "values-sandbox.yaml"


def declared_delegates() -> dict[str, list[str]]:
    """{delegate authz id: [principal authz ids]} as the chart renders DELEGATE_ON_BEHALF_OF:
    a local user's email, or a brokered principal's upstream `sub`. A client with no onBehalfOf
    gets no key."""
    kc = yaml.safe_load(VALUES.read_text(encoding="utf-8"))["keycloak"]
    local = {u["username"]: u["email"] for u in kc.get("nonInteractiveUsers") or []}
    brokered = {p["username"]: p["sub"]
                for b in (kc.get("brokers") or {}).values() for p in b.get("principals") or []}
    out: dict[str, list[str]] = {}
    for c in list(kc.get("serviceClients") or []) + list(kc.get("extraServiceClients") or []):
        if c.get("kind", "service") != "delegate" or not c.get("onBehalfOf"):
            continue
        ids = [local[o["user"]] for o in c["onBehalfOf"] if o["user"] in local]
        ids += [brokered[o["user"]] for o in c["onBehalfOf"] if o["user"] in brokered]
        out[c["authzId"]] = sorted(ids)
    return out


def install_delegates(monkeypatch) -> dict[str, frozenset]:
    """Set the env the server reads and return what the SERVER's reader makes of it."""
    from src.iagent import gateway
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", json.dumps(declared_delegates()))
    served = gateway._delegate_principals()
    assert served, "the server's reader found no declared delegate: nothing to seal"
    return served


def pair_and_outsider(served: dict[str, frozenset], delegate: str):
    """(a principal declared for `delegate`, a principal declared for ANOTHER delegate and not for
    this one). Both read off the served map."""
    own = sorted(served[delegate])
    others = sorted({p for d, ps in served.items() if d != delegate for p in ps} - set(own))
    assert own and others, f"{delegate}: need a declared principal and an outsider in the served map"
    return own[0], others[0]
