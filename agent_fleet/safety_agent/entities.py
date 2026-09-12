"""Engine S's safety model, and the fixture the verbs are proven against.

NOTIONAL BY RULE, on Engine F's precedent (ADR-0045 Decision 4). Every tail number, part
number, hazard and person here is invented, and nothing from any programme's real hazard log
appears — not as a fixture, not as a test case, not as an example in a docstring. Stated
rather than left to be inferred from absence, because absence is not a thing a later
contributor can read.

── THE FIXTURE HAS THE ERRORS BUILT IN, AND THAT IS THE DESIGN ─────────────────────────────
**`findOrphanedHazards` over a clean fixture returns zero and proves nothing.** A verb that
finds nothing is indistinguishable from a verb that looks nowhere, and seal 8 needs N to be a
number the FIXTURE CHOSE rather than a number the graph happened to contain. So this fixture
seeds each of ADR-0051's four failures deliberately, with controls beside them:

  ORPHANED HAZARDS        exactly THREE, one per distinct way a hazard is orphaned:
                          no mitigation at all; a mitigation with no owner; a mitigation
                          owned but never verified in the field (the paper-closed case).
  PAPER-CLOSED            HAZ-1003 / MIT-2103 — the mitigation exists, is owned, and its
                          `verified_in_field` is `not_verified`. The hazard reads as handled
                          in every view that checks only for the mitigation's existence.
  BLIND DEFERRAL          WO-3001 is deferred and its item IS on the critical items list;
                          WO-3002 is deferred and its item is NOT. One of each, so the verb
                          must discriminate rather than flag every deferral.
  DUPLICATE HAZARD        WU-4001, WU-4002 and WU-4003 are three write-ups of ONE condition
                          (HAZ-1001). A classifier that opens a hazard per write-up produces
                          three; the correct answer is one existing hazard and two links.

── AND THE CONTROLS, WITHOUT WHICH THE COUNT IS NOT A MEASUREMENT ──────────────────────────
HAZ-1004 is open, mitigated, owned AND field-verified — a hazard that must NOT be returned.
HAZ-1005 is closed. HAZ-1006 is `not_assessed`, which is neither open nor closed and must not
be silently sorted into either: it is the three-state control, and a verb that treats it as
open returns four instead of three.

── EVERY IDENTITY-SHAPED FIELD HOLDS A DIFFERENT VALUE, ON PURPOSE ─────────────────────────
Hazard ids, mitigation ids, part numbers, work-order ids, write-up ids and owner names share
no value anywhere in this file, and none is a prefix of another. A read keyed on the wrong
field therefore FAILS rather than coincidentally passing — the law from `c849b1e`, where a
fixture used one identity for two fields and nine tests passed over a defect that rendered
`404 "no artifact for you"` for 285 of 286 artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Vocabularies — the closed sets, mirroring safety_risk_matrix.ttl
#
# DUPLICATED HERE AS TYPES, NOT AS TRUTH. The matrix TTL is the authority
# (ADR-0051 §2); these Literals let the signature carry the vocabulary so
# `slots.py` can derive an enum from it, which is the one thing a TTL cannot do
# for `inspect.signature`. The seal that matters asserts the two AGREE — a
# drifted copy of a policy table is the defect this ADR spent §2 avoiding.
# ─────────────────────────────────────────────────────────────────────────────
Severity = Literal["I", "II", "III", "IV"]
Probability = Literal["A", "B", "C", "D", "E"]

#: open | mitigated | closed | not_assessed — NO DEFAULT anywhere (ADR-0051 §1).
HazardStatus = Literal["open", "mitigated", "closed", "not_assessed"]

#: true | false | not_verified. Three-state for the same reason a boolean cannot
#: express "nobody has been to look": a mitigation closed on paper and never
#: verified in the field is ADR-0051's second failure, and `False` would claim
#: somebody checked and found it wanting.
FieldVerification = Literal["true", "false", "not_verified"]

Scope = Literal["fleet", "platform", "tail"]


@dataclass(frozen=True)
class Mitigation:
    mitigation_id: str
    description: str
    #: None means NO OWNER, which is one of the three ways a hazard is orphaned.
    #: Deliberately not "" — an empty string reads as a name nobody filled in,
    #: and None reads as a field nobody answered.
    owner: Optional[str]
    verified_in_field: FieldVerification


@dataclass(frozen=True)
class Hazard:
    hazard_id: str
    description: str
    status: HazardStatus
    #: Both may be None — a hazard nobody has assessed has no severity and no
    #: probability, and seeding them to the bottom of the matrix would read as
    #: assessed-and-negligible.
    severity: Optional[Severity]
    probability: Optional[Probability]
    tail: str
    platform: str
    opened_on: str
    #: S3000L failure-mode IRIs. The cause vocabulary is NOT minted — see
    #: safety_extension.ttl's survey header and `safety:hasCause`.
    cause_failure_modes: tuple[str, ...] = ()
    mitigations: tuple[Mitigation, ...] = ()


@dataclass(frozen=True)
class SafetyCriticalItem:
    csi_id: str
    part_number: str
    description: str
    #: The hazard this item's failure or omission opens.
    opens_hazard_id: str


@dataclass(frozen=True)
class WorkOrder:
    work_order_id: str
    part_number: str
    description: str
    deferred: bool
    tail: str
    deferred_reason: Optional[str]


@dataclass(frozen=True)
class WriteUp:
    write_up_id: str
    narrative: str
    tail: str
    reported_on: str
    #: The hazard this write-up is ABOUT. Three of these share one value, which
    #: is the duplicate-hazard case classifyWriteUp must resolve to a link.
    reports_hazard_id: Optional[str]


# ─────────────────────────────────────────────────────────────────────────────
# THE FIXTURE
# ─────────────────────────────────────────────────────────────────────────────

#: THREE orphans, one per distinct mechanism. This number is the fixture's
#: CHOICE and seal 8 asserts it exactly, in both directions.
EXPECTED_ORPHAN_COUNT = 3

HAZARDS: tuple[Hazard, ...] = (
    # ORPHAN 1 — open, no mitigation at all.
    Hazard(
        hazard_id="HAZ-1001",
        description="Chafed wiring loom in the aft equipment bay can short the primary bus.",
        status="open",
        severity="I",
        probability="D",
        tail="TN-7701",
        platform="PLT-ALPHA",
        opened_on="2026-03-14",
        cause_failure_modes=("http://www.lksoft.com/s3kl#FailureMode",),
        mitigations=(),
    ),
    # ORPHAN 2 — open, a mitigation exists but NOBODY OWNS IT.
    Hazard(
        hazard_id="HAZ-1002",
        description="Cargo door actuator can back-drive under hydraulic pressure loss.",
        status="open",
        severity="II",
        probability="C",
        tail="TN-7702",
        platform="PLT-ALPHA",
        opened_on="2026-04-02",
        cause_failure_modes=("http://www.lksoft.com/s3kl#FunctionalFailure",),
        mitigations=(
            Mitigation(
                mitigation_id="MIT-2102",
                description="Placard the bay and add a pressure-loss checklist step.",
                owner=None,
                verified_in_field="not_verified",
            ),
        ),
    ),
    # ORPHAN 3 — THE PAPER-CLOSED CASE. Owned, described, and never verified in
    # the field. Every view that checks only "is there a mitigation" reads this
    # hazard as handled.
    Hazard(
        hazard_id="HAZ-1003",
        description="Fuel quantity probe seal degrades, allowing vapour ingress to the sense line.",
        status="mitigated",
        severity="II",
        probability="D",
        tail="TN-7703",
        platform="PLT-BRAVO",
        opened_on="2026-01-28",
        cause_failure_modes=("http://www.lksoft.com/s3kl#TechnicalFailureMode",),
        mitigations=(
            Mitigation(
                mitigation_id="MIT-2103",
                description="Seal replacement at next phase inspection per TCTO 12-3.",
                owner="quality.lead@example.invalid",
                verified_in_field="not_verified",
            ),
        ),
    ),
    # CONTROL — open, mitigated, OWNED, and VERIFIED. Must NOT be returned.
    Hazard(
        hazard_id="HAZ-1004",
        description="Ground power cart can be connected with reverse polarity.",
        status="mitigated",
        severity="III",
        probability="B",
        tail="TN-7704",
        platform="PLT-BRAVO",
        opened_on="2026-02-11",
        cause_failure_modes=("http://www.lksoft.com/s3kl#FailureModeEffect",),
        mitigations=(
            Mitigation(
                mitigation_id="MIT-2104",
                description="Keyed connector retrofit; cart placarded and inspected.",
                owner="ground.ops@example.invalid",
                verified_in_field="true",
            ),
        ),
    ),
    # CONTROL — closed. Not open, not an orphan.
    Hazard(
        hazard_id="HAZ-1005",
        description="Obsolete torque wrench calibration procedure referenced in the manual.",
        status="closed",
        severity="IV",
        probability="E",
        tail="TN-7705",
        platform="PLT-ALPHA",
        opened_on="2025-11-05",
        mitigations=(
            Mitigation(
                mitigation_id="MIT-2105",
                description="Manual revised; superseded procedure withdrawn.",
                owner="tech.pubs@example.invalid",
                verified_in_field="true",
            ),
        ),
    ),
    # THE THREE-STATE CONTROL — nobody has assessed this. It is neither open nor
    # closed, and it has NO severity and NO probability. A verb that sorts
    # not_assessed into "open" returns four orphans instead of three.
    Hazard(
        hazard_id="HAZ-1006",
        description="Reported vibration in the No.2 accessory drive; not yet characterised.",
        status="not_assessed",
        severity=None,
        probability=None,
        tail="TN-7706",
        platform="PLT-CHARLIE",
        opened_on="2026-08-30",
        mitigations=(),
    ),
)

CRITICAL_ITEMS: tuple[SafetyCriticalItem, ...] = (
    SafetyCriticalItem(
        csi_id="CSI-5001",
        part_number="PN-8801",
        description="Aft bay wiring loom assembly.",
        opens_hazard_id="HAZ-1001",
    ),
    SafetyCriticalItem(
        csi_id="CSI-5002",
        part_number="PN-8802",
        description="Fuel quantity probe seal kit.",
        opens_hazard_id="HAZ-1003",
    ),
)

WORK_ORDERS: tuple[WorkOrder, ...] = (
    # DEFERRED, AND THE ITEM IS SAFETY-CRITICAL. This deferral re-opens HAZ-1001.
    WorkOrder(
        work_order_id="WO-3001",
        part_number="PN-8801",
        description="Inspect and re-clamp aft bay loom.",
        deferred=True,
        tail="TN-7701",
        deferred_reason="Awaiting parts; deferred to next phase.",
    ),
    # DEFERRED, item NOT on the critical items list — the discriminating control.
    # A verb that flags every deferral returns this one too and is not measuring
    # criticality at all.
    WorkOrder(
        work_order_id="WO-3002",
        part_number="PN-8803",
        description="Replace worn cargo liner panel.",
        deferred=True,
        tail="TN-7704",
        deferred_reason="Cosmetic; deferred indefinitely.",
    ),
    # NOT deferred, and the item IS critical — the other half of the control
    # pair, so the verb cannot pass by keying on criticality alone.
    WorkOrder(
        work_order_id="WO-3003",
        part_number="PN-8802",
        description="Replace fuel probe seal per TCTO 12-3.",
        deferred=False,
        tail="TN-7703",
        deferred_reason=None,
    ),
)

WRITE_UPS: tuple[WriteUp, ...] = (
    # THREE WRITE-UPS, ONE CONDITION. The duplicate-hazard case.
    WriteUp(
        write_up_id="WU-4001",
        narrative="Crew reports intermittent bus fault on climb-out; reset restored power.",
        tail="TN-7701",
        reported_on="2026-03-14",
        reports_hazard_id="HAZ-1001",
    ),
    WriteUp(
        write_up_id="WU-4002",
        narrative="Chafing observed on loom near aft bay bulkhead during walkaround.",
        tail="TN-7701",
        reported_on="2026-05-02",
        reports_hazard_id="HAZ-1001",
    ),
    WriteUp(
        write_up_id="WU-4003",
        narrative="Primary bus transient logged by maintenance download, cause not isolated.",
        tail="TN-7701",
        reported_on="2026-07-19",
        reports_hazard_id="HAZ-1001",
    ),
    # A DIFFERENT condition, so "group everything on one tail" is not a passing
    # strategy either.
    WriteUp(
        write_up_id="WU-4004",
        narrative="Fuel quantity indication fluctuates on the ground with tanks static.",
        tail="TN-7703",
        reported_on="2026-06-08",
        reports_hazard_id="HAZ-1003",
    ),
)

#: Part numbers on the critical items list, derived rather than restated — a
#: second hand-kept list of the same fact is the shape ADR-0051 §4 spent an
#: extraction removing.
CRITICAL_PART_NUMBERS = frozenset(c.part_number for c in CRITICAL_ITEMS)

BY_HAZARD_ID = {h.hazard_id: h for h in HAZARDS}
