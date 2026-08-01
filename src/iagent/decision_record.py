"""DECISION RECORDS — the auditable answer to "why was this notice NOT reviewed?"

ADR-0034 Phase 1. The requirement behind the "review everything" ask was never review; it was
that a skipped notice leaves **no artifact explaining why**, so the only way to inspect the
decision is to RE-RUN the pipeline that made it. A record makes the answer readable from the
artifact instead of reproducible only by replay.

THE ONE RULE THAT MAKES THIS WORTH BUILDING — INPUTS AND THRESHOLDS, NEVER BARE VERDICTS.
`check_x: pass` is re-derivable only by re-running the pipeline that produced it, which IS the
audit gap. A record must say WHAT WAS COMPARED AGAINST WHAT. This is the clause most likely to
be quietly weakened, because a schema full of booleans validates, looks complete, and silently
makes every future promotion decision rest on the pipeline's self-report.

IDENTITY IS THE ARTIFACT'S, and this is its FOURTH consumer after the sensor's `run_key`, the
triage `task_id` and the ingress idempotency key. If a fifth consumer ever derives its own,
that drift is how one artifact becomes "the same work" to one mechanism and "new work" to
another — the failure this codebase has now paid for four times.

Everything here is PURE. Persistence is deliberately NOT decided in this module: the store
choice (graph triples vs. a relational table) is an architectural decision flagged in the
build directive as needing justification, and a pure builder + validator is worth landing
without pre-empting it. `emit()` takes a writer.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Optional

SCHEMA_VERSION = "1"

# How a notice came to its outcome. `policy` = the trust posture decided it (a supervised
# format forces review regardless of content); `content` = the extraction/ruleset decided it;
# `escalation` = an autonomous run tripped a check and handed the notice back to a human
# (ADR-0034 §7 — the road back from autonomy, which must be paved rather than improvised).
ADMITTED_BY = ("policy", "content", "escalation")

# WHICH OF ITS OWN RECORDS THE CORPUS COUNTS. The first records come from witness re-drives,
# CROPFAIL synthetics and hand-clicking — legitimate emissions, but NOT promotion evidence.
# Declared at emit rather than inferred later from dates, because records are IMMUTABLE by
# construction: "which era was this?" is impossible to retrofit honestly once written, and
# "everyone remembers which week was the shakedown" is exactly the institutional memory that
# stops being true the moment it matters. Flip DECISION_RECORD_ERA to `production` when the
# system is declared commissioned.
COMMISSIONING, PRODUCTION = "commissioning", "production"
ERAS = (COMMISSIONING, PRODUCTION)

# A notice can be decided BEFORE any ruleset is consulted (zero parts extracted -> the sensor
# never composes). `governing.ruleset_ref` is still REQUIRED, because a record that omits its
# policy state is unclassifiable — so the honest answer is a DECLARED sentinel rather than an
# empty string. Empty would read as "we forgot"; this reads as "composition never ran", which
# is a different and true fact.
NOT_COMPOSED = "none:no-composition"


class DecisionRecordInvalid(ValueError):
    """The record is not admissible evidence. Raised at EMIT, never swallowed."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise DecisionRecordInvalid(msg)


def make_check(name: str, *, verdict: str, inputs: dict, threshold: Any = None,
               detail: str = "") -> dict:
    """One check's finding, carrying WHAT IT LOOKED AT — not just how it came out.

    `inputs` is mandatory and must be non-empty. That is the whole discipline: a check that
    records only its verdict is a check whose reasoning died with the process that ran it, and
    a promotion decided on such records is a promotion decided on the pipeline's self-report.

    Example — the cross-check that fired two false positives at work:
        make_check("summary_part_count",
                   verdict="mismatch",
                   inputs={"stated": 89, "extracted": 2, "source": "SOT-89 package parts"},
                   threshold={"tolerance": 0})
    A reader can see the 89 came from a package type. `{"verdict": "mismatch"}` alone could
    never have shown that, and the false positive would have entered the corpus as evidence
    the extraction was unreliable.
    """
    _require(bool(name), "a check needs a name")
    _require(bool(verdict), f"check {name!r} needs a verdict")
    _require(isinstance(inputs, dict) and len(inputs) > 0,
             f"check {name!r} records a verdict with NO inputs — that is a bare verdict, and it "
             f"is re-derivable only by re-running the pipeline, which is the audit gap this "
             f"record exists to close")
    out = {"name": name, "verdict": verdict, "inputs": dict(inputs)}
    if threshold is not None:
        out["threshold"] = threshold
    if detail:
        out["detail"] = detail
    return out


def build_decision_record(
    *,
    request_key: str,
    source_key: str,
    notice_id: Optional[str],
    pipeline_version: str,
    format_fingerprint: str,
    outcome: str,
    admitted_by: str,
    checks: list,
    governing: dict,
    trust_rung: str,
    era: str = COMMISSIONING,
    warnings: Optional[list] = None,
) -> dict:
    """Assemble a record. PURE and total — every rejection is a raise, never a silent default.

    `request_key` is the artifact identity (ETag + s3 key) already used by three other
    mechanisms; the record's own id is a hash of it, so the corpus joins to runs, triage tasks
    and invocations without inventing a fifth key.

    `governing` carries the POLICY STATE the decision was made under — the ruleset content
    hash and the trust table's content hash. Without it a record says what was decided and not
    what it was decided under, so a corpus spanning a ruleset change silently mixes two
    regimes and every trend computed over it is meaningless.
    """
    _require(bool(request_key), "request_key (the artifact identity) is required")
    _require(bool(source_key), "source_key is required")
    _require(bool(pipeline_version), "pipeline_version is required — trust is keyed on "
                                     "vendor-format x PIPELINE-VERSION, so a record without it "
                                     "cannot be attributed to the thing that produced it")
    _require(bool(format_fingerprint), "format_fingerprint is required")
    _require(bool(outcome), "outcome is required")
    _require(admitted_by in ADMITTED_BY,
             f"admitted_by must be one of {ADMITTED_BY}, got {admitted_by!r}")
    _require(isinstance(checks, list), "checks must be a list")
    _require(isinstance(governing, dict) and governing.get("ruleset_ref"),
             "governing.ruleset_ref is required — a record that does not say which policy "
             "state it was decided under cannot be compared with any other record")
    _require(bool(governing.get("trust_table_ref")),
             "governing.trust_table_ref is required — the admission posture is policy state "
             "too, and a corpus spanning a table edit must be able to tell the halves apart")
    _require(bool(trust_rung), "trust_rung is required")
    _require(era in ERAS,
             f"era must be one of {ERAS}, got {era!r} — promotion queries exclude the "
             f"commissioning period BY DECLARATION, never by remembering which dates were tests")

    for c in checks:
        _require(isinstance(c, dict), "each check must be a dict from make_check()")
        _require("inputs" in c and isinstance(c["inputs"], dict) and c["inputs"],
                 f"check {c.get('name')!r} carries no inputs — bare verdicts are not evidence")

    return {
        "schema_version": SCHEMA_VERSION,
        "record_id": record_id_for(request_key),
        "request_key": request_key,
        "source_key": source_key,
        "notice_id": notice_id or "",          # DISPLAY only — never an identity here
        "pipeline_version": pipeline_version,
        "format_fingerprint": format_fingerprint,
        "outcome": outcome,
        "admitted_by": admitted_by,
        "trust_rung": trust_rung,
        "era": era,
        "checks": list(checks),
        "governing": dict(governing),
        "warnings": list(warnings or []),
    }


def record_id_for(request_key: str) -> str:
    """Deterministic id from the ARTIFACT identity — the fourth consumer of one key."""
    return "dr-" + hashlib.sha1(request_key.encode()).hexdigest()[:16]


def validate_decision_record(rec: dict) -> None:
    """Re-validate an assembled record. Called at EMIT so a record built by some future path
    that bypasses the builder still cannot enter the corpus malformed."""
    _require(isinstance(rec, dict), "record must be a dict")
    for field in ("schema_version", "record_id", "request_key", "source_key",
                  "pipeline_version", "format_fingerprint", "outcome", "admitted_by",
                  "trust_rung", "era", "checks", "governing"):
        _require(field in rec, f"record is missing required field {field!r}")
    _require(rec["admitted_by"] in ADMITTED_BY, f"bad admitted_by {rec['admitted_by']!r}")
    _require(rec["era"] in ERAS, f"bad era {rec['era']!r}")
    _require(rec["record_id"] == record_id_for(rec["request_key"]),
             "record_id does not match its request_key — the corpus would not join to the "
             "run, the triage task or the invocation that share that identity")
    for c in rec["checks"]:
        _require(isinstance(c.get("inputs"), dict) and c["inputs"],
                 f"check {c.get('name')!r} has no inputs — bare verdict")


def emit(rec: dict, *, writer: Callable[[dict], Any]) -> Any:
    """Validate, then hand the record to a writer.

    SCHEMA-GATED AND LOUD. A record that fails validation is NOT dropped, NOT logged-and-
    skipped: it raises. Evidence that vanishes when malformed is worse than no evidence,
    because the corpus then looks complete while being selectively missing exactly the cases
    that went strangely — which are the cases promotion decisions most need to see.

    The writer is injected so persistence stays a separate decision (graph vs table, ADR-0034
    open question 4) and so the seal can exercise emission without a store.
    """
    validate_decision_record(rec)
    return writer(rec)


def canonical_json(rec: dict) -> str:
    """Stable serialization for hashing/storage — sorted keys, no incidental whitespace."""
    return json.dumps(rec, sort_keys=True, separators=(",", ":"))
