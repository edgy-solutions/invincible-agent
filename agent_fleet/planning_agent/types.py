"""Planning domain types — the ONE canonical definition.

Ruled by ADR-0042. These types live SERVER-SIDE because the measures over them are verbs
(ADR-0042 §3), and a verb runs where verbs run. The frontend receives payloads shaped by
renderer contracts; it does not hold a second copy of this file.

EVERY FIELD CARRIES WHY IT EXISTS. That is not decoration — the plan's Gate 0 requires it,
because the failure this guards against is a future pass deleting a field it reads as
incidental. `saturation_threshold` looks like a magic number until you read why it is
governance-defined; `Dependency` looks over-modelled until you notice the source model had
ONE end and was therefore unanswerable.

ALIGNMENT (shapes only — no OWL/RDF plumbing this cycle; ADR is Phase 7):
  OWL-Time   intervals, never bare dates
  P-Plan     plan vs execution are distinct (`planned` vs `actual`)
  PROV       assessments carry who/when/evidence
  ORG        a funder is an entity, never a string
  ArchiMate  Plateau — how a process evolves over time
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

ISODate = str  # YYYY-MM-DD


# ─────────────────────────────────────────────────────────────────────────────
# Time
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Interval:
    """OWL-Time alignment: a temporal thing is an INTERVAL, never a bare date.

    The source model carried bare dates, which is why nothing in it was drawable on a
    timeline and why no dependency could be checked — a constraint between two things needs
    two intervals, not two instants.
    """
    start: ISODate
    end: ISODate

    def overlaps(self, other: "Interval") -> bool:
        """Allen 'not (before or after)'. Half-open at neither end: two projects that touch
        on the same day DO overlap, because a site absorbing both on that day carries both
        loads. Chosen deliberately — the alternative silently under-reports saturation."""
        return self.start <= other.end and other.start <= self.end

    def is_well_formed(self) -> bool:
        return self.start <= self.end


# Fiscal periods are STRINGS in the model ("FY26-Q3") because that is the vocabulary the
# room speaks, and a date-range would force every card to re-derive the label. The mapping
# to real intervals lives here, ONCE, so a measure never invents it.
FiscalPeriod = str

# US federal fiscal year: FY26 runs 2025-10-01 .. 2026-09-30. Named explicitly rather than
# computed, because a computed fiscal calendar is a second place for the convention to live
# and this one is read by every period-scoped measure.
FISCAL_PERIODS: dict[FiscalPeriod, Interval] = {
    "FY26-Q1": Interval("2025-10-01", "2025-12-31"),
    "FY26-Q2": Interval("2026-01-01", "2026-03-31"),
    "FY26-Q3": Interval("2026-04-01", "2026-06-30"),
    "FY26-Q4": Interval("2026-07-01", "2026-09-30"),
    "FY27-Q1": Interval("2026-10-01", "2026-12-31"),
    "FY27-Q2": Interval("2027-01-01", "2027-03-31"),
    "FY27-Q3": Interval("2027-04-01", "2027-06-30"),
    "FY27-Q4": Interval("2027-07-01", "2027-09-30"),
}

PERIOD_ORDER: list[FiscalPeriod] = list(FISCAL_PERIODS.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Structure
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Portfolio:
    portfolio_id: str
    name: str
    tenant_id: str  # multi-tenant from birth; retrofitting a tenant key is a migration
    # REV 3 — three DISTINCT owner roles at the upper tiers. A single owner field forces a
    # choice the organisation has not made: "who signs off on the money" and "who is
    # accountable for the outcome" have different answers.
    executive_owner: Optional[str] = None
    business_owner: Optional[str] = None
    technology_owner: Optional[str] = None
    # REV 3 — the extras map. Answers "highly configurable attributes" without becoming a
    # document store: the graph substrate at Phase 8 is the real answer, and this is the seam
    # that makes waiting survivable. NOT a place to hide modelled fields — a date or an amount
    # in here is invisible to every measure that reads a typed field, and a test guards it.
    attributes: dict = field(default_factory=dict)


@dataclass
class Initiative:
    initiative_id: str
    portfolio_id: str
    name: str
    # ENUM, not a free string. A free status field becomes six spellings of "active" within
    # a quarter and every filter silently under-counts.
    status: Literal["proposed", "approved", "active", "paused", "done"]
    executive_owner: Optional[str] = None
    business_owner: Optional[str] = None
    technology_owner: Optional[str] = None
    # REV 3 — priority and criticality are SEPARATE questions. Priority is "what do we do
    # first" (a sequencing choice the room makes); criticality is "what happens if this fails"
    # (a property of the thing). Collapsing them loses the case that matters most: low
    # priority, high criticality. Ordinals; the LABELS are data (see the rev-3 delta §C).
    priority: Optional[int] = None
    criticality: Optional[int] = None
    # REV 3 — the extras map. Answers "highly configurable attributes" without becoming a
    # document store: the graph substrate at Phase 8 is the real answer, and this is the seam
    # that makes waiting survivable. NOT a place to hide modelled fields — a date or an amount
    # in here is invisible to every measure that reads a typed field, and a test guards it.
    attributes: dict = field(default_factory=dict)


@dataclass
class Phase:
    phase_id: str
    initiative_id: str
    name: str
    sequence_order: int
    # WITHOUT THIS NO TIMELINE IS DRAWABLE. The source model had phases with no dates — a
    # fatal gap, since the anchor projection is a timeline of exactly these.
    planned: Interval
    actual: Optional[Interval] = None  # P-Plan: plan and execution are distinct records
    # REV 3 — one owner at the working tiers. Three roles here would be ceremony; the
    # distinction only exists where accountability actually splits.
    owner: Optional[str] = None
    # How FIRM the interval is. Without it a Q3 date and a Q3 guess draw identically, and a
    # room cannot tell which bars it may safely move.
    timing_confidence: Optional[str] = None
    # REV 3 — the extras map. Answers "highly configurable attributes" without becoming a
    # document store: the graph substrate at Phase 8 is the real answer, and this is the seam
    # that makes waiting survivable. NOT a place to hide modelled fields — a date or an amount
    # in here is invisible to every measure that reads a typed field, and a test guards it.
    attributes: dict = field(default_factory=dict)


@dataclass
class Project:
    project_id: str
    phase_id: str
    name: str
    planned: Interval
    actual: Optional[Interval] = None
    # Budget is the ROLLUP CHECK, not the source of truth — the truth is the set of
    # FundingRequirements. Keeping both lets a consistency check catch a project whose
    # requirements silently drifted from what was approved.
    capex_budget: float = 0.0
    opex_budget: float = 0.0
    owner: Optional[str] = None
    priority: Optional[int] = None
    criticality: Optional[int] = None
    # REV 3 — the extras map. Answers "highly configurable attributes" without becoming a
    # document store: the graph substrate at Phase 8 is the real answer, and this is the seam
    # that makes waiting survivable. NOT a place to hide modelled fields — a date or an amount
    # in here is invisible to every measure that reads a typed field, and a test guards it.
    attributes: dict = field(default_factory=dict)


@dataclass
class Plateau:
    """ArchiMate Plateau — a named, dated state a process passes through."""
    plateau_id: str
    name: str
    target_date: ISODate


@dataclass
class BusinessProcess:
    process_id: str
    name: str
    plateaus: list[Plateau] = field(default_factory=list)


@dataclass
class Capability:
    capability_id: str
    name: str
    # Q2's edge, absent from the source model: a capability ENABLES processes. Without it,
    # "which capabilities does this process depend on" has no answer.
    enables_process_ids: list[str] = field(default_factory=list)
    # REV 3 — the extras map. Answers "highly configurable attributes" without becoming a
    # document store: the graph substrate at Phase 8 is the real answer, and this is the seam
    # that makes waiting survivable. NOT a place to hide modelled fields — a date or an amount
    # in here is invisible to every measure that reads a typed field, and a test guards it.
    attributes: dict = field(default_factory=dict)


@dataclass
class CapabilityContribution:
    """Q7. PROJECT-level maturation.

    Initiative→capability is DERIVED from this (a project's phase's initiative), never
    asserted in parallel — two writers for one fact is how the two drift.
    """
    project_id: str
    capability_id: str
    weight: float


@dataclass
class Site:
    site_id: str
    name: str
    region: str
    # THE METRIC MUST BE DEFINED, NOT IMPLIED. "Overloaded" is a governance judgement about
    # how much concurrent change a site absorbs; a measure that invents the line is an
    # invented measure. This field is where the judgement is recorded and owned.
    saturation_threshold: float
    # REV 3 (B3) — Site generalises to a DEPLOYMENT TARGET. A program is a target too: it
    # absorbs concurrent change and has a saturation line, which is the whole of what the load
    # machinery needs. `SiteImpact` already carries its own window and the threshold is already
    # a per-subject governance field, so the load machinery is UNCHANGED and THRESHOLD_GRID
    # needs no edit at all — it draws "subjects x periods against a threshold the subject
    # owns" and has never known what a subject is.
    target_type: Literal["site", "program"] = "site"
    active: Optional[Interval] = None
    status: Optional[str] = None
    # REV 3 — the extras map. Answers "highly configurable attributes" without becoming a
    # document store: the graph substrate at Phase 8 is the real answer, and this is the seam
    # that makes waiting survivable. NOT a place to hide modelled fields — a date or an amount
    # in here is invisible to every measure that reads a typed field, and a test guards it.
    attributes: dict = field(default_factory=dict)


@dataclass
class SiteImpact:
    """Q9 — "which sites are affected AND WHEN". The EDGE carries the interval.

    Not the project's interval: a 9-month project may touch a site for three weeks. Putting
    the window on the edge is what makes site load a real measure rather than a proxy.
    """
    project_id: str
    site_id: str
    window: Interval
    load_weight: float


@dataclass
class Technology:
    tech_id: str
    name: str
    # REV 3 — the extras map. Answers "highly configurable attributes" without becoming a
    # document store: the graph substrate at Phase 8 is the real answer, and this is the seam
    # that makes waiting survivable. NOT a place to hide modelled fields — a date or an amount
    # in here is invisible to every measure that reads a typed field, and a test guards it.
    attributes: dict = field(default_factory=dict)


@dataclass
class TechEnablesCapability:
    tech_id: str
    capability_id: str


@dataclass
class TechInProject:
    tech_id: str
    project_id: str


DepEnd = Literal["project", "phase"]
DepType = Literal["FS", "SS", "FF", "SF"]


@dataclass
class Dependency:
    """The source model had ONE end, which made every dependency question unanswerable.

    Two ends plus an Allen-flavoured type plus lag. FS/SS/FF/SF are the four standard
    scheduling constraints; anything else is a modelling error, not a new type.
    """
    dependency_id: str
    predecessor_kind: DepEnd
    predecessor_id: str
    successor_kind: DepEnd
    successor_id: str
    dep_type: DepType
    lag_days: int = 0


@dataclass
class Organization:
    """ORG alignment: a funder is an ENTITY, never a string on a funding row.

    A string funder cannot be asked "what else are you funding," which is half of Q13–Q15.
    """
    org_id: str
    name: str
    # REV 3 — the extras map. Answers "highly configurable attributes" without becoming a
    # document store: the graph substrate at Phase 8 is the real answer, and this is the seam
    # that makes waiting survivable. NOT a place to hide modelled fields — a date or an amount
    # in here is invisible to every measure that reads a typed field, and a test guards it.
    attributes: dict = field(default_factory=dict)


FundingKind = Literal["capex", "expense"]


@dataclass
class FundingRequirement:
    """DEMAND side. What the project needs, per period, by kind."""
    req_id: str
    project_id: str
    period: FiscalPeriod
    kind: FundingKind
    amount: float


@dataclass
class FundingCommitment:
    """SUPPLY side — split from requirement DELIBERATELY.

    One row carrying both "needed" and "secured" cannot express a multi-funder gap: two orgs
    each covering part leaves the shortfall ambiguous. Split, the gap is arithmetic.
    """
    commit_id: str
    project_id: str
    org_id: str
    period: FiscalPeriod
    kind: FundingKind
    amount: float
    # REV 3 — a PENDING commitment is a hope, not money. The enum is what lets the gap verb
    # separate SECURED (committed + approved) from AT-RISK, and a gap measure that counts
    # hopes as money is the measure a portfolio review exists to replace.
    #
    # THERE IS NO STORED GAP FIELD ANYWHERE, deliberately: at-risk is DERIVED from these rows
    # by plan_funding_gap. Storing it beside its own inputs is stored-beside-derivable, the
    # two-masters defect this arc has already paid for twice.
    status: Literal["pending", "committed", "approved"] = "committed"
    attributes: dict = field(default_factory=dict)


@dataclass
class MaturityAssessment:
    """APPEND-ONLY. Current level = the latest assessment for that (capability, site).

    Never updated in place. PROV alignment: who assessed, when, against what evidence. An
    in-place update destroys the trajectory, which is the thing Q3 is actually asking about,
    and makes "as of last quarter" unanswerable.
    """
    assessment_id: str
    capability_id: str
    site_id: str
    level: float
    target_level: float
    assessed_at: ISODate
    assessed_by: str
    evidence_ref: Optional[str] = None
    # REV 3 (B2) — which named ordinal scale these levels belong to. The LABELS are data, not
    # code: the repo ships a neutral default and customer labels load from an overlay.
    scale_id: str = "generic-1-5"
    attributes: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# The whole model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PlanState:
    """One immutable snapshot of the plan. Verbs are pure functions of this.

    ADR-0042 §3: the STORE behind this is a placeholder that will move (in-memory seed →
    Postgres → graph). The SHAPE is the fixed contract, and a verb never learns which store
    produced it.
    """
    portfolios: list[Portfolio] = field(default_factory=list)
    initiatives: list[Initiative] = field(default_factory=list)
    phases: list[Phase] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    processes: list[BusinessProcess] = field(default_factory=list)
    capabilities: list[Capability] = field(default_factory=list)
    contributions: list[CapabilityContribution] = field(default_factory=list)
    sites: list[Site] = field(default_factory=list)
    site_impacts: list[SiteImpact] = field(default_factory=list)
    technologies: list[Technology] = field(default_factory=list)
    tech_capabilities: list[TechEnablesCapability] = field(default_factory=list)
    tech_projects: list[TechInProject] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    organizations: list[Organization] = field(default_factory=list)
    requirements: list[FundingRequirement] = field(default_factory=list)
    commitments: list[FundingCommitment] = field(default_factory=list)
    assessments: list[MaturityAssessment] = field(default_factory=list)
    # The cap line the room governs against. Optional per period — a period with no cap is
    # honestly uncapped, NOT capped at zero, which would paint every bar red.
    period_caps: dict[FiscalPeriod, float] = field(default_factory=dict)

    # ── indexes, built on demand; never a second source of truth ──
    def project(self, project_id: str) -> Optional[Project]:
        return next((p for p in self.projects if p.project_id == project_id), None)

    def phase(self, phase_id: str) -> Optional[Phase]:
        return next((p for p in self.phases if p.phase_id == phase_id), None)

    def site(self, site_id: str) -> Optional[Site]:
        return next((s for s in self.sites if s.site_id == site_id), None)

    def capability(self, capability_id: str) -> Optional[Capability]:
        return next((c for c in self.capabilities if c.capability_id == capability_id), None)

    def initiative_of_project(self, project_id: str) -> Optional[Initiative]:
        """Q7's DERIVED edge. Project → phase → initiative, computed, never stored."""
        proj = self.project(project_id)
        if proj is None:
            return None
        ph = self.phase(proj.phase_id)
        if ph is None:
            return None
        return next(
            (i for i in self.initiatives if i.initiative_id == ph.initiative_id), None
        )

    def interval_of(self, kind: DepEnd, ident: str) -> Optional[Interval]:
        """The planned interval of either dependency end. One function, so a dependency
        between a phase and a project is not a special case anywhere."""
        if kind == "project":
            p = self.project(ident)
            return p.planned if p else None
        ph = self.phase(ident)
        return ph.planned if ph else None
