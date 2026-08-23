"""Run the planning routing suite against the REAL endpoint, with per-arm attribution.

── WHAT THIS EXERCISES, AND WHAT IT DOES NOT ──────────────────────────────────

EXERCISES: the provider path (internal endpoint, no cloud), the MODEL NAME as
configured (`OLLAMA_MODEL`, currently `gpt-oss-128k:120b` — the extended-context
variant, not `gpt-oss:120b`), the routing prompt, and routing/slot quality on
real phrasings.

ALSO EXERCISES BAML'S PARSER, as of the 2026-08-22 regeneration. An earlier
version of this runner sent the same prompt to the same model and parsed the JSON
itself, because `baml_shared/baml_client/` is generated code shared with other
lanes and regenerating it was a build step needing coordination. With that
authorized and the client regenerated (verified purely additive — every
pre-existing class survived), the runner now calls `b.RouteIntent` and the
measurement covers the WHOLE pipeline: provider path, model name, prompt, the
typed union parse, and routing quality.

That distinction mattered enough to state while it was true, because a runner
that quietly skips a layer reports a number for a pipeline that does not exist.

── PER-ARM ATTRIBUTION (the deliverable) ──────────────────────────────────────

    routing  -> wrong intent_id                 -> few-shot exemplars
    slot     -> right intent, wrong slot values -> two-step classify-then-fill
    refusal  -> an out-of-model question answered -> a gate failure, absolute

The levers target different arms, so an aggregate cannot choose between them.

── n>=2 BY DEFAULT ────────────────────────────────────────────────────────────

This host is bimodal under load (measured during the latency work), so a single
pass is a moment rather than a number. Cases are run twice and a case counts as
correct only if it is correct in BOTH passes — nondeterminism is a failure mode
for a router, not noise to average away.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

_TIMEOUT = float(os.getenv("PLANNING_EVAL_TIMEOUT", "120"))
_PASSES = int(os.getenv("PLANNING_EVAL_PASSES", "2"))
_CATALOG = Path(__file__).resolve().parents[2] / "agent_fleet" / "planning_agent" / "intent_catalog.yaml"


def _endpoint() -> tuple[str, str]:
    base = os.getenv("OLLAMA_BASE_URL", "http://192.168.1.126:11434/v1").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "gpt-oss-128k:120b")
    return base, model


def _catalog_prompt() -> str:
    """Build the intent menu from the CATALOG, never a hand-written copy.

    A prompt listing intents by hand is the third encoding the canonical-source
    ruling forbids: it drifts from the catalog, and the drift shows up as the
    model routing to an intent that no longer exists.
    """
    import yaml  # noqa: PLC0415

    cat = yaml.safe_load(_CATALOG.read_text(encoding="utf-8"))
    lines = []
    for i in cat["intents"]:
        slots = ", ".join((i.get("slots") or {}).keys()) or "none"
        lines.append(f"- {i['intent_id']}: {i['description']} | slots: {slots}")
    soft = "\n".join(
        f'- "{p}" means {t["intent_id"]}' + (f" with {t['slots']}" if t.get("slots") else "")
        for p, t in cat["soft_language"].items()
    )
    oom = "\n".join(f"- {c['concept']}: {', '.join(c['phrases'])}" for c in cat["out_of_model"])
    return (
        "INTENTS:\n" + "\n".join(lines)
        + "\n\nSOFT LANGUAGE:\n" + soft
        + "\n\nOUT OF MODEL (these must return no_intent_match):\n" + oom
    )


def _intent_id_by_class() -> dict[str, str]:
    """Map generated CLASS NAME -> intent_id, from the `@@intent_id` markers.

    Read from the .baml rather than guessing a snake_case conversion of the class
    name: a naming convention is a third encoding wearing a convention's clothes,
    and it breaks silently the first time someone names a class reasonably but
    differently.
    """
    baml = (Path(__file__).resolve().parents[2] / "baml_shared" / "baml_src"
            / "planning_qa.baml").read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in re.finditer(r"class\s+(\w+)\s*\{(.*?)\n\}", baml, re.S):
        marker = re.search(r"//\s*@@intent_id:\s*([a-z_]+)", m.group(2))
        if marker:
            out[m.group(1)] = marker.group(1)
    return out


def _ask_baml(question: str) -> dict[str, Any]:
    """Route through the REAL BAML function — typed union, real parse."""
    import sys as _sys  # noqa: PLC0415

    root = Path(__file__).resolve().parents[2] / "baml_shared" / "baml_client"
    if str(root) not in _sys.path:
        _sys.path.insert(0, str(root))
    from baml_client.sync_client import b  # noqa: PLC0415

    try:
        result = b.RouteIntent(question=question, context="")
    except Exception as exc:  # noqa: BLE001
        # A PARSE FAILURE IS A REAL OUTCOME, not an error to retry away: BAML
        # refusing malformed model output is the enforcement working, and it must
        # show up in the table as its own arm rather than as a crash.
        return {"intent_id": "__parse_failure__", "slots": {},
                "error": f"{type(exc).__name__}: {exc}"[:200]}

    cls = type(result).__name__
    intent_id = _intent_id_by_class().get(cls, f"__unmapped__{cls}")
    slots = {k: v for k, v in vars(result).items() if not k.startswith("_")}
    return {"intent_id": intent_id, "slots": slots}


def _ask_raw(question: str) -> dict[str, Any]:
    base, model = _endpoint()
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You route a planning question to exactly one intent. You do NOT answer it.\n"
                    "Return ONLY JSON: {\"intent_id\": \"...\", \"slots\": {...}}\n"
                    "Fill a slot ONLY from the question. Never invent a value; omit what the "
                    "question does not determine.\n"
                    "If nothing matches, or the question needs something the model does not carry, "
                    "return intent_id \"no_intent_match\" with "
                    "{\"out_of_model_concept\": \"roi|risk_owner|headcount|null\"}.\n\n"
                    + _catalog_prompt()
                ),
            },
            {"role": "user", "content": question},
        ],
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer ollama"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        payload = json.load(resp)
    text = payload["choices"][0]["message"]["content"]
    # HARMONY: take the FINAL channel only. Reasoning-channel text is a draft and
    # a draft read as an answer is the failure this rule exists to prevent.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"intent_id": "__unparseable__", "slots": {}, "raw": text[:200]}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"intent_id": "__unparseable__", "slots": {}, "raw": text[:200]}


def _slots_match(expected: dict, got: dict) -> bool:
    """Expected slots must be present and equal; EXTRA slots are tolerated.

    Tolerated because the catalog carries optional slots with defaults and a
    model volunteering `window: null` is not wrong. A missing or DIFFERENT
    expected slot is wrong.
    """
    for k, v in (expected or {}).items():
        if k not in (got or {}):
            return False
        gv = got[k]
        if isinstance(v, bool) or isinstance(gv, bool):
            if bool(gv) != bool(v):
                return False
        elif str(gv).strip().lower() != str(v).strip().lower():
            return False
    return True


def _require_env() -> None:
    """Fail LOUDLY and EARLY when the client's env is unset.

    BAML's Ollama client reads `env.OLLAMA_MODEL` and `env.OLLAMA_BASE_URL`. With
    either missing, every call raises and the runner would report 105 parse
    failures — a number that reads as catastrophic routing quality when the real
    cause is an unset variable. A measurement that can fail for an environmental
    reason WHILE LOOKING LIKE A RESULT is worse than no measurement, so this
    refuses to start rather than producing one.
    """
    missing = [v for v in ("OLLAMA_MODEL", "OLLAMA_BASE_URL") if not os.getenv(v)]
    if missing:
        raise RuntimeError(
            f"{missing} unset — BAML's Ollama client reads them from env. "
            f"Sandbox values live in the iagent-config ConfigMap "
            f"(OLLAMA_BASE_URL=http://192.168.1.126:11434/v1, "
            f"OLLAMA_MODEL=gpt-oss-128k:120b). Refusing to run: every call would "
            f"fail and the table would read as a routing collapse."
        )


def run_suite(fixture: dict) -> dict:
    _require_env()
    cases = fixture["cases"]
    refusals = fixture["refusals"]

    routing_ok = slots_ok = 0
    refusal_ok = 0
    failures: list[dict] = []

    latencies: list[float] = []

    for case in cases:
        exp = case["expect"]
        observations = []
        for _ in range(_PASSES):
            _t0 = time.time()
            observations.append(_ask_baml(case["question"]))
            latencies.append(time.time() - _t0)

        # NONDETERMINISM IS A FAILURE, NOT NOISE. A router that answers
        # differently on identical input has no answer; averaging hides exactly
        # the property a demo depends on.
        intents = {o.get("intent_id") for o in observations}
        if len(intents) > 1:
            failures.append({
                "id": case["id"], "arm": "routing",
                "expected": exp["intent_id"], "got": f"UNSTABLE {sorted(intents)}",
            })
            continue

        got = observations[0]
        if got.get("intent_id") != exp["intent_id"]:
            failures.append({
                "id": case["id"], "arm": "routing",
                "expected": exp["intent_id"], "got": got.get("intent_id"),
            })
            continue
        routing_ok += 1

        if not all(_slots_match(exp.get("slots") or {}, o.get("slots") or {}) for o in observations):
            failures.append({
                "id": case["id"], "arm": "slot",
                "expected": exp.get("slots"), "got": got.get("slots"),
            })
            continue
        slots_ok += 1

    for r in refusals:
        got = _ask_baml(r["question"])
        if got.get("intent_id") == "no_intent_match":
            refusal_ok += 1
        else:
            failures.append({
                "id": r["id"], "arm": "refusal",
                "expected": "no_intent_match", "got": got.get("intent_id"),
            })

    soft_ids = {c["id"] for c in cases if c.get("soft")}
    lat = sorted(latencies)
    def _pct(p: float) -> float:
        return round(lat[min(int(len(lat) * p), len(lat) - 1)], 1) if lat else 0.0

    return {
        "latency_s": {
            "n": len(lat),
            "median": _pct(0.5),
            "p90": _pct(0.9),
            "max": round(lat[-1], 1) if lat else 0.0,
        },
        "total": len(cases),
        "routing_ok": routing_ok,
        "slots_ok": slots_ok,
        "refusal_total": len(refusals),
        "refusal_ok": refusal_ok,
        "failures": failures,
        "soft_failures": [f["id"] for f in failures if f["id"] in soft_ids],
        "passes": _PASSES,
    }
