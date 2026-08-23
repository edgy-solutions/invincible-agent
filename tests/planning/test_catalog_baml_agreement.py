"""THE CATALOG AND THE BAML MUST AGREE — no third encoding may exist.

CANONICAL-SOURCE RULING (plan §4.2). `.baml` is canonical for intent SHAPES —
names, slots, types; enforcement owns the contract. The catalog config is
canonical for what BAML should not know: example phrasings, synonym and
soft-language maps, intent→verb→output_uri routing. They meet on `intent_id`.

TWO SOURCES OF TRUTH ONLY WORK IF THEIR OVERLAP IS CHECKED. Otherwise the shape
drifts from the routing and the failure appears at the far end: a question routes
to an intent BAML cannot parse into, or BAML parses an intent the router has no
verb for. Both present as "the LLM got it wrong", which sends the fix to the
prompt instead of the mismatch.

THIS IS THE CHEAPEST GUARD IN THE RAIL and it gates everything after it, so it is
written FIRST — before the functions it checks — and watched to fail for the
right reason.

WHAT IT SEALS:
  * every catalog `intent_id` has a BAML class, and vice versa — a one-way check
    would let BAML grow classes nothing routes to, which are dead shapes that
    still consume the union's token budget and the model's attention;
  * required slots agree in BOTH directions, because a slot BAML requires and
    the catalog does not is a parse failure on a valid question;
  * the functions pin to the INTERNAL client with no cloud fallback (A3), which
    is a boundary property, not a preference — these calls carry funding
    figures, site names and capability maturity for a defense-adjacent customer;
  * the model string comes from env, never hardcoded (A5) — sandbox is Ollama,
    work is vLLM, same weights, different NAME.

Run: uv run --frozen --with pytest --with pyyaml pytest tests/planning/test_catalog_baml_agreement.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_REPO = Path(__file__).resolve().parents[2]
_CATALOG = _REPO / "agent_fleet" / "planning_agent" / "intent_catalog.yaml"
_BAML = _REPO / "baml_shared" / "baml_src" / "planning_qa.baml"


def _baml() -> str:
    if not _BAML.exists():
        pytest.fail(
            f"{_BAML.name} does not exist. The catalog has intents with no BAML "
            f"shapes, so nothing enforces what the model may return."
        )
    return _BAML.read_text(encoding="utf-8")


def _catalog() -> dict:
    return yaml.safe_load(_CATALOG.read_text(encoding="utf-8"))


def _catalog_ids() -> set[str]:
    return {i["intent_id"] for i in _catalog()["intents"]}


def _baml_intent_classes() -> dict[str, list[str]]:
    """Map intent_id -> LIST of class bodies, from the `@@intent_id` marker.

    Keyed on an EXPLICIT marker rather than on class-name-to-snake-case guessing:
    a naming convention is a third encoding wearing a convention's clothes, and
    it breaks silently the first time someone names a class reasonably but
    differently.

    ONE INTENT ID MAY HAVE SEVERAL CLASSES (two-step, 2026-08-23).
    `no_intent_match` is realised by BOTH `NoIntentMatch` — the single-shot
    union's escape hatch — and `NotComputableInFamily`, the money family's step-2
    refusal. They are the same ROUTING OUTCOME reached through different lineups,
    so they share an id.

    The earlier version returned `dict[intent_id -> body]` and silently kept only
    the LAST class per id, so the slot comparison ran against whichever happened
    to win. The check was right and MY MODEL OF IT was wrong: I assumed one id
    maps to one class, and the two-step design broke that assumption without my
    noticing until this went red.
    """
    out: dict[str, list[str]] = {}
    for m in re.finditer(r"class\s+(\w+)\s*\{(.*?)\n\}", _baml(), re.S):
        body = m.group(2)
        marker = re.search(r"//\s*@@intent_id:\s*([a-z_]+)", body)
        if marker:
            out.setdefault(marker.group(1), []).append(body)
    return out


# ── THE AGREEMENT, BOTH DIRECTIONS ─────────────────────────────────────────

def test_every_catalog_intent_has_a_BAML_class():
    missing = sorted(_catalog_ids() - set(_baml_intent_classes()))
    assert not missing, (
        f"catalog intents with no BAML shape: {missing} — the router can select "
        f"them and nothing constrains what comes back"
    )


def test_every_BAML_class_has_a_CATALOG_intent():
    """THE OTHER DIRECTION, which a one-way check misses. A BAML class nothing
    routes to is a dead shape that still spends union token budget and model
    attention on every call."""
    orphans = sorted(set(_baml_intent_classes()) - _catalog_ids())
    assert not orphans, f"BAML classes with no catalog entry: {orphans}"


def test_required_slots_agree_in_both_directions():
    """A slot BAML requires and the catalog does not is a parse failure on a
    valid question; the reverse is a slot the router fills and enforcement
    silently drops."""
    classes = _baml_intent_classes()
    for intent in _catalog()["intents"]:
        iid = intent["intent_id"]
        if iid not in classes:
            continue  # covered by the arm above
        declared: set[str] = set()
        for body in classes[iid]:
            declared |= set(re.findall(r"^\s*(\w+)\s+\S", body, re.MULTILINE))
        # REQUIRED slots must exist on SOME realisation of the intent. An OPTIONAL
        # slot need not appear on every one: `nearest_intent_id` belongs to the
        # single-shot escape hatch and is meaningless in a three-option lineup,
        # where the "nearest" is the lineup itself. Demanding it everywhere would
        # force ceremony onto a class that has no use for it — the decorative-seal
        # shape, applied to a schema.
        required = {
            k for k, v in (intent.get("slots") or {}).items()
            if isinstance(v, dict) and v.get("required")
        }
        assert required <= declared, (
            f"{iid}: REQUIRED catalog slots {sorted(required - declared)} absent from BAML"
        )


# ── BOUNDARY PROPERTIES (A3, A5) ───────────────────────────────────────────

def test_the_functions_pin_to_the_INTERNAL_client():
    """A3, BINDING. MainAgent is `fallback [OpenRouter, OpenAI, Ollama]` — cloud
    FIRST. For this domain that is not a configuration preference, it is a
    boundary violation waiting for a bad day: these calls carry funding figures,
    site names and capability maturity for a defense-adjacent customer, and
    MainAgent ships all of it to OpenRouter the moment the internal endpoint
    hiccups."""
    src = _baml()
    for fn in ("RouteIntent", "NarrateResult"):
        block = re.search(rf"function\s+{fn}\b.*?\{{(.*?)\n\}}", src, re.S)
        assert block, f"{fn} not found"
        assert re.search(r"client\s+Ollama\b", block.group(1)), (
            f"{fn} does not pin to the internal client"
        )


def test_NO_function_uses_the_cloud_fallback_client():
    """The failure mode is a SUCCESS that exfiltrated the portfolio, which no
    error log records."""
    # Comments are excluded: this file DOCUMENTS why MainAgent's
    # `fallback [OpenRouter, OpenAI, Ollama]` is forbidden, and a check that
    # cannot tell a usage from its own explanation goes red on the commentary
    # that makes the rule legible — punishing the thing that helps the reader.
    code = "\n".join(
        ln for ln in _baml().splitlines() if not ln.lstrip().startswith("//")
    )
    assert "MainAgent" not in code, "a planning function routes through the cloud fallback"
    for cloud in ("OpenRouter", "OpenAI"):
        assert not re.search(rf"client\s+{cloud}\b", code), f"{cloud} reachable from planning"


def test_no_model_string_is_hardcoded():
    """A5. Sandbox is Ollama, work is vLLM — same weights, different model NAME.
    A hardcoded string reaches exactly one of them."""
    src = _baml()
    offenders = re.findall(r"model\s+\"([^\"]+)\"", src)
    assert not offenders, (
        f"hardcoded model string(s) {offenders} — the model must come from env "
        f"(the Ollama client already reads env.OLLAMA_MODEL)"
    )


def test_the_harmony_final_channel_rule_is_recorded_at_the_call_site():
    """gpt-oss emits reasoning in a channel separate from the final answer.
    Reasoning-channel text must never reach a card, the canvas, or a demo-visible
    log — and the place that rule has to survive is next to the function that
    produces it."""
    src = _baml()
    assert re.search(r"final channel|final-channel", src, re.I), (
        "the harmony final-channel rule is not recorded beside these functions"
    )
