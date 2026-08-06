"""TRUST TABLE loader — the ADMISSION posture, as ratifiable data.

ADR-0034 Phase 1. Answers exactly one question: **may the pipeline act on this class of input
without a human?** It does not decide whether a review starts (that is the starter: posture AND
content) and it does not decide what the process is (that is the workflow definition).

DENY-BY-DEFAULT FOR AUTONOMY, COMPUTED FROM ABSENCE. An unlisted vendor-format is `supervised`.
A table that must LIST a format in order to supervise it fails OPEN on the format nobody added
— and the format nobody added is precisely the one nobody has looked at.

FAILS LOUD, NEVER TO A PERMISSIVE DEFAULT. A malformed table raises. The tempting alternative
— "on a bad table, treat everything as supervised and carry on" — sounds conservative and is
not: it silently converts a broken overlay into a working one, so a typo that erases every
promotion looks exactly like a deliberate reset. Refusing to load is the honest failure; and
because the CALLER of this module treats a load failure as "supervise everything", the safe
behaviour still happens, LOUDLY, at a layer that can say why.

Same family as `capability_grants.yaml` / `task_grants.yaml`: git-asserted, content-hashed,
validated at load. The hash rides into every decision record as `governing.trust_table_ref`,
so a corpus spanning a table edit can tell its halves apart.
"""
from __future__ import annotations

import hashlib
import os
from typing import Optional

# The rung vocabulary. Ordered weakest-to-strongest autonomy; the ORDER is load-bearing for
# the promotion rule below, not decoration.
SUPERVISED, MONITORED, TRUSTED = "supervised", "monitored", "trusted"
RUNGS = (SUPERVISED, MONITORED, TRUSTED)

DEFAULT_RUNG = SUPERVISED

# SENTINEL VERSIONS — values that mean "provenance is MISSING". Never a version.
#
# `unset` is the consumer side's env-var default; `unstamped` is the producer's build-arg default
# (doc-tools bakes `doc-tools@<sha>` and falls back to `doc-tools@unstamped`). Both are deliberately
# implausible so an unprovenanced artifact stands out in the corpus rather than blending in — and
# that same property is what makes them recognisable here.
#
# Matched on the whole string AND on the tail after '@', because the real shape is `<tool>@<sha>`
# and the sentinel rides in the sha position.
_SENTINEL_VERSIONS = frozenset({"unset", "unstamped", "unknown", "none", ""})


def _is_sentinel_version(value: str) -> bool:
    s = (value or "").strip().lower()
    tail = s.rsplit("@", 1)[-1] if "@" in s else s
    return s in _SENTINEL_VERSIONS or tail in _SENTINEL_VERSIONS


# SENTINEL FINGERPRINTS — the SAME rule on the other axis, completed 2026-08-06.
#
# The fingerprint is `<manufacturer>/<doc_type>/<layout-era>`, and `format_fingerprint()` emits
# `unknown` in the manufacturer position when the extraction carried no `header.mfr`. That is a
# sentinel by exactly the test that made `unset` one: it means "this artifact was not IDENTIFIED",
# not "this artifact is from a vendor called unknown".
#
# MEASURED, NOT HYPOTHETICAL: 4 of 16 real artifacts in `processing-artifacts` derive
# `unknown/pcn/v1` — four unrelated vendors already sharing one key. A rung above `supervised` on
# that key would grant autonomy to every unidentifiable artifact at once, which is the
# matches-everything-on-absence hazard the version rule already forbids.
#
# The scope was never "the version axis" — it was "no rung above supervised may key on a value
# meaning INFORMATION MISSING". This is the same rule; only its implementation was one-sided.
# NB no "n/a": `/` is the fingerprint's own separator, so such a value can never survive as a clean
# vendor SEGMENT (it splits to "n"). Listing it would be an entry that can never match — a guard
# claiming coverage it does not have, which is the day's theme in miniature.
_SENTINEL_VENDORS = frozenset({"unknown", "", "none", "unidentified"})


def _is_sentinel_fingerprint(value: str) -> bool:
    """True iff the fingerprint's MANUFACTURER segment identifies nothing.

    Only the vendor segment is examined. The `doc_type` segment CANNOT be checked, and that gap is
    deliberate and documented rather than papered over: `format_fingerprint()` defaults a missing
    `doc_type` to `pcn`, which is INDISTINGUISHABLE from a genuine PCN — measured at 9 of 16 real
    artifacts. Per the default-collision rule, a guard whose asserted value the system can produce
    by default cannot tell "identified" from "defaulted", so guarding it here would be theatre.
    The fix is upstream (make `doc_type` explicit-or-sentinel at emission), and it is filed as the
    fingerprint-normalization item — NOT smuggled in as a check that cannot work.
    """
    vendor = (value or "").strip().lower().split("/", 1)[0].strip()
    return vendor in _SENTINEL_VENDORS


_TRUST_TABLE_FILE = os.getenv("TRUST_TABLE_FILE", "policy/trust_table.yaml")


class TrustTableInvalid(RuntimeError):
    """The overlay is malformed. Nothing is applied; the caller supervises everything."""


class TrustTable:
    """An immutable, content-hashed view of the admission policy."""

    def __init__(self, formats: dict, *, ref: str):
        self._formats = formats
        self.ref = ref                      # e.g. "trust@a1b2c3d4e5f6"

    def rung_for(self, format_fingerprint: str, pipeline_version: str) -> str:
        """The posture for this input class.

        BOTH parts of the key must match. A rung earned under one pipeline version does NOT
        carry to another: the three notices that broke this pipeline in a week broke on format
        variation within a vendor while the extractor changed underneath them, so "the thing
        that earned the trust" and "the thing now running" are routinely different objects.
        A version mismatch silently re-supervises, which is the safe direction and is why the
        version is IN the key rather than merely recorded beside it.
        """
        entry = self._formats.get(format_fingerprint)
        if not entry:
            return DEFAULT_RUNG
        if entry.get("pipeline_version") != pipeline_version:
            return DEFAULT_RUNG
        return entry.get("rung", DEFAULT_RUNG)

    def sample_rate_for(self, format_fingerprint: str, pipeline_version: str) -> float:
        """Sampling is the evidence engine of the middle rung, so it is POLICY, not a constant.
        Anything not `monitored` samples 0 — `supervised` sends everything to a human anyway,
        and `trusted` sampling is optional and separately declared."""
        if self.rung_for(format_fingerprint, pipeline_version) != MONITORED:
            return 0.0
        entry = self._formats.get(format_fingerprint) or {}
        try:
            return float(entry.get("sample_rate", 0.0))
        except (TypeError, ValueError):
            return 0.0

    def is_autonomy_permitted(self, format_fingerprint: str, pipeline_version: str) -> bool:
        """May the pipeline proceed without a human for this class?

        NB this is NOT "may it skip checks". The starter still applies the content chain; a
        content refusal refuses regardless of rung. Trust buys the absence of a human, never
        the absence of a check.
        """
        return self.rung_for(format_fingerprint, pipeline_version) in (MONITORED, TRUSTED)


def promotion_is_permitted(current: str, proposed: str) -> bool:
    """`supervised -> trusted` is NOT a permitted transition.

    `monitored` is not a formality en route to automation — it is the ONLY rung that produces
    counterfactual evidence: what the pipeline would have done, checked against what a human
    did, on traffic it is already handling. Skipping it means promoting on evidence gathered
    under a different regime. Demotion in any direction is always permitted; the road back
    from autonomy must never be the harder path.
    """
    if current not in RUNGS or proposed not in RUNGS:
        return False
    if RUNGS.index(proposed) <= RUNGS.index(current):
        return True                                   # demotion / no-op: always allowed
    return RUNGS.index(proposed) - RUNGS.index(current) == 1


def parse_trust_table(raw: dict, *, ref: str) -> TrustTable:
    """PURE: parsed YAML -> TrustTable. Raises TrustTableInvalid on a malformed overlay."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise TrustTableInvalid("trust table must be a mapping")
    formats = raw.get("formats")
    if formats is None:
        formats = {}
    if not isinstance(formats, dict):
        raise TrustTableInvalid("`formats` must be a mapping of fingerprint -> entry")

    for fp, entry in formats.items():
        if not isinstance(entry, dict):
            raise TrustTableInvalid(f"{fp!r}: entry must be a mapping")
        rung = entry.get("rung")
        if rung not in RUNGS:
            raise TrustTableInvalid(f"{fp!r}: rung must be one of {RUNGS}, got {rung!r}")
        if not entry.get("pipeline_version"):
            raise TrustTableInvalid(
                f"{fp!r}: pipeline_version is REQUIRED — a rung with no version would survive "
                f"a pipeline upgrade, which is exactly when its evidence stops applying"
            )
        # An unexplained trust grant is not a grant — the same rule capability_grants.yaml
        # enforces, for the same reason: this authorizes the pipeline to act unsupervised.
        if rung != SUPERVISED:
            # NO RUNG ABOVE `supervised` MAY KEY ON A SENTINEL VERSION.
            #
            # A sentinel is not a version — it is the marker for "provenance is MISSING", so a
            # trust rung keyed on one is a contradiction of this table's own semantics: it grants
            # autonomy on the ABSENCE of the very evidence the key exists to carry.
            #
            # THE THREAT IS THE DEGENERATE PROMOTION, and it is the worst shape this arc has found.
            # Promoting a SPECIFIC version prematurely fails SAFE — nothing matches, everything
            # falls to the floor, and `admitted_by` makes it legible. Promoting the SENTINEL
            # matches the ENTIRE unprovenanced corpus at once: not a ceremony that does nothing,
            # but one that does EVERYTHING, indiscriminately, keyed on missing information.
            #
            # PERMANENT, NOT INTERIM. This is not a pin guarding the window before the consumer
            # derive lands, so it carries no retirement condition: a future misconfigured build
            # can regress to emitting the sentinel at any time, and this rule is what keeps the
            # resulting artifacts unpromotable. It is a row in the definition of a well-formed
            # table, in the same idiom as the two checks around it.
            #
            # DELIBERATELY A SHAPE CHECK, NOT A CORPUS QUERY. Refusing promotions "while the
            # sentinel appears anywhere in the live corpus" was considered and REJECTED: a policy
            # validator that reads live state inverts the rails' direction (git validates git; the
            # corpus is reconciled TO policy, never consulted BY its validator), and it would make
            # validity time- and environment-dependent. The narrow rule captures the dangerous
            # case; the residual — a premature specific-version promotion — fails safe by
            # non-match. Narrow and permanent beats broad and stateful.
            # THE OTHER AXIS, same rule (completed 2026-08-06). A fingerprint whose manufacturer
            # segment is `unknown` identifies nothing, so promoting it keys trust on the ABSENCE of
            # identification and matches every unidentifiable artifact at once — four unrelated
            # vendors already share `unknown/pcn/v1` in the live corpus.
            #
            # STILL A SHAPE CHECK, NOT A CORPUS QUERY. The broad alternative — refusing while the
            # sentinel appears anywhere in live data — is declined again, for the reason it was
            # declined the first time: a policy validator that reads live state inverts the rails'
            # direction (git validates git) and makes validity time- and environment-dependent.
            if _is_sentinel_fingerprint(str(fp)):
                raise TrustTableInvalid(
                    f"{fp!r}: rung {rung!r} keys on a SENTINEL FINGERPRINT — the manufacturer "
                    f"segment identifies nothing, so this means 'provenance missing' on the format "
                    f"axis exactly as `unset` does on the version axis. A rung above 'supervised' "
                    f"here would match EVERY unidentifiable artifact at once, across unrelated "
                    f"vendors. Promote against a fingerprint whose manufacturer was extracted."
                )
            if _is_sentinel_version(str(entry.get("pipeline_version") or "")):
                raise TrustTableInvalid(
                    f"{fp!r}: rung {rung!r} keys on the SENTINEL version "
                    f"{entry.get('pipeline_version')!r}, which means 'provenance missing', not a "
                    f"version. A rung above 'supervised' keyed on a sentinel would match every "
                    f"unprovenanced artifact at once — granting autonomy on the ABSENCE of the "
                    f"evidence the key exists to carry. Promote against a real "
                    f"<tool>@<sha> emitted by the producer."
                )
            if not entry.get("ratified_by"):
                raise TrustTableInvalid(f"{fp!r}: rung {rung!r} needs an accountable ratified_by")
            if not entry.get("evidence"):
                raise TrustTableInvalid(
                    f"{fp!r}: rung {rung!r} needs `evidence` — promotion is an approval, and an "
                    f"approval with no stated basis cannot be audited or revisited"
                )
    return TrustTable(dict(formats), ref=ref)


def table_ref(content: str) -> str:
    """Content hash, mirroring `ruleset_ref`'s shape so both read alike in a record."""
    return "trust@" + hashlib.sha1(content.encode()).hexdigest()[:12]


def load_trust_table(path: Optional[str] = None) -> TrustTable:
    """Read + validate + hash. Raises TrustTableInvalid; callers supervise everything on
    failure (loudly), rather than this module quietly returning a permissive empty table."""
    import yaml

    p = path or _TRUST_TABLE_FILE
    try:
        with open(p, "r", encoding="utf-8") as fh:
            content = fh.read()
    except FileNotFoundError:
        raise TrustTableInvalid(
            f"trust table not found at {p!r} — refusing to infer a policy. An absent table is "
            f"a deploy problem, and treating it as 'no promotions' would make a missing file "
            f"indistinguishable from a deliberate reset"
        )
    return parse_trust_table(yaml.safe_load(content), ref=table_ref(content))
