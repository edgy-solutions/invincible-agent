"""The demo dataset — engineered so THE DEMO MOMENTS EXIST IN THE DATA.

A seed that merely "looks realistic" produces a demo where the presenter has to manufacture
the tension live, which is the shape that fails in a room. Five tensions are placed here
deliberately, each one is asserted by a test, and each one is a beat in the script:

  (a) FY26-Q3 requirements exceed the cap line          -> "why is Q3 red?"
  (b) an FS dependency a natural drag-left would violate -> the diff card's red line
  (c) Site B over threshold in FY26-Q4                   -> "which sites are hammered in Q4?"
  (d) an org whose commitments leave a visible gap       -> the funding-gap card
  (e) a capability path that misses its process plateau  -> the capability question
  (f) a capability NO project contributes to             -> the coverage-gap question

If a test asserting one of these ever fails, the DATA changed, not the measure — check here
before touching a verb.

The store behind this is a placeholder that will move (in-memory -> Postgres -> graph) per
ADR-0042 §3. What must not move is where the measures run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

try:  # flat in the image (/app), packaged in the repo — see tests/test_agent_modules_survive_flat_layout.py
    from entities import (
            BusinessProcess, Capability, CapabilityContribution, Dependency, FundingCommitment,
            FundingRequirement, Initiative, Interval, MaturityAssessment, Organization, Phase,
            PlanState, Plateau, Portfolio, Project, Site, SiteImpact, TechEnablesCapability,
            TechInProject, Technology,
    )
except ImportError:
    from agent_fleet.planning_agent.entities import (
            BusinessProcess, Capability, CapabilityContribution, Dependency, FundingCommitment,
            FundingRequirement, Initiative, Interval, MaturityAssessment, Organization, Phase,
            PlanState, Plateau, Portfolio, Project, Site, SiteImpact, TechEnablesCapability,
            TechInProject, Technology,
    )

M = 1_000_000.0


# The label collections an overlay may address. NOTHING ELSE IS ADDRESSABLE, and that is the
# C-series promise made mechanical rather than disciplinary: an overlay swaps NAMES, and there
# is no code path by which customer STRUCTURE enters this repo because the overlay has no
# vocabulary for it.
_OVERLAY_COLLECTIONS = {
    "portfolios": ("portfolios", "portfolio_id"),
    "initiatives": ("initiatives", "initiative_id"),
    "phases": ("phases", "phase_id"),
    "projects": ("projects", "project_id"),
    "processes": ("processes", "process_id"),
    "capabilities": ("capabilities", "capability_id"),
    "sites": ("sites", "site_id"),
    "organizations": ("organizations", "org_id"),
    "technologies": ("technologies", "tech_id"),
}


def _apply_overlay(s: PlanState, overlay: dict) -> PlanState:
    """Swap display names. Structure, intervals, amounts and thresholds are untouched.

    WHY LABELS AND NOT A DATASET REPLACEMENT. The gates depend on the shipped dataset's
    STRUCTURE -- six seeded tensions, each asserted by a test, each a beat in the demo script.
    A full-replacement overlay would run the demo on a dataset no gate has ever seen, and the
    first time anyone noticed a flattened tension would be in the room.

    Unknown keys and unknown ids are REFUSED, never ignored. An overlay that appears to apply
    and does not is how a demo runs half-themed and nobody notices until a screenshot.
    """
    unknown_keys = sorted(set(overlay) - set(_OVERLAY_COLLECTIONS))
    if unknown_keys:
        raise ValueError(
            "seed overlay may only rename known collections; refused: "
            + ", ".join(unknown_keys)
            + ". An overlay swaps NAMES -- it cannot express structure."
        )
    for key, mapping in overlay.items():
        attr, id_field = _OVERLAY_COLLECTIONS[key]
        entities = getattr(s, attr)
        by_id = {getattr(e, id_field): e for e in entities}
        missing = sorted(set(mapping) - set(by_id))
        if missing:
            raise ValueError(
                f"seed overlay names unknown {key}: {', '.join(missing)}. "
                "A typo that silently does nothing leaves a demo half-themed."
            )
        for ident, label in mapping.items():
            by_id[ident].name = label
    return s


def build_seed(overlay_path: Optional[str] = None) -> PlanState:  # noqa: C901
    """The shipped generic dataset, optionally re-labelled by a private overlay.

    ABSENT BY DEFAULT: with no overlay configured this returns the invented dataset every gate
    and every test runs against. `overlay_path` falls back to the PLANNING_SEED_OVERLAY
    environment variable so a deployment can point at a file OUTSIDE this repo.

    Configured-but-missing is a LOUD error, never a silent fallback -- falling back would run a
    customer demo on the generic dataset and look entirely normal doing it.
    """
    s = PlanState()

    s.portfolios = [Portfolio("PF1", "Enterprise Transformation", "tenant-demo")]

    s.initiatives = [
        Initiative("I1", "PF1", "ERP Modernization", "active"),
        Initiative("I2", "PF1", "Plant Floor Connectivity", "active"),
        Initiative("I3", "PF1", "Supply Chain Visibility", "approved"),
    ]

    # ── phases: 4 per initiative ──────────────────────────────────────────────
    s.phases = [
        Phase("I1-P1", "I1", "Assess",   1, Interval("2025-10-01", "2025-12-31")),
        Phase("I1-P2", "I1", "Design",   2, Interval("2026-01-01", "2026-03-31")),
        Phase("I1-P3", "I1", "Build",    3, Interval("2026-04-01", "2026-09-30")),
        Phase("I1-P4", "I1", "Deploy",   4, Interval("2026-10-01", "2027-03-31")),
        Phase("I2-P1", "I2", "Survey",   1, Interval("2025-10-01", "2025-12-31")),
        Phase("I2-P2", "I2", "Pilot",    2, Interval("2026-01-01", "2026-06-30")),
        Phase("I2-P3", "I2", "Rollout",  3, Interval("2026-04-01", "2026-12-31")),
        Phase("I2-P4", "I2", "Sustain",  4, Interval("2027-01-01", "2027-09-30")),
        Phase("I3-P1", "I3", "Charter",  1, Interval("2026-01-01", "2026-03-31")),
        Phase("I3-P2", "I3", "Integrate",2, Interval("2026-04-01", "2026-09-30")),
        Phase("I3-P3", "I3", "Extend",   3, Interval("2026-10-01", "2027-06-30")),
        Phase("I3-P4", "I3", "Optimize", 4, Interval("2027-04-01", "2027-09-30")),
    ]

    # ── projects: 14 ──────────────────────────────────────────────────────────
    s.projects = [
        Project("P1",  "I1-P1", "Current-State Assessment", Interval("2025-10-01", "2025-12-15"), capex_budget=0.4 * M, opex_budget=0.2 * M),
        Project("P2",  "I1-P2", "Target Architecture",      Interval("2026-01-05", "2026-03-20"), capex_budget=0.6 * M, opex_budget=0.3 * M),
        Project("P3",  "I1-P3", "Finance Module Build",     Interval("2026-04-01", "2026-06-30"), capex_budget=2.2 * M, opex_budget=0.4 * M),
        Project("P4",  "I1-P3", "Procurement Module Build", Interval("2026-04-15", "2026-06-30"), capex_budget=1.8 * M, opex_budget=0.3 * M),
        Project("P5",  "I1-P4", "Wave 1 Cutover",           Interval("2026-10-01", "2026-12-31"), capex_budget=0.9 * M, opex_budget=0.6 * M),
        Project("P6",  "I2-P1", "Network Survey",           Interval("2025-10-01", "2025-12-31"), capex_budget=0.3 * M, opex_budget=0.1 * M),
        Project("P7",  "I2-P2", "Line 3 Pilot",             Interval("2026-04-01", "2026-06-30"), capex_budget=1.4 * M, opex_budget=0.2 * M),
        Project("P8",  "I2-P3", "Site B Rollout",           Interval("2026-07-01", "2026-09-30"), capex_budget=1.1 * M, opex_budget=0.3 * M),
        Project("P9",  "I2-P3", "Site C Rollout",           Interval("2026-04-01", "2026-06-30"), capex_budget=1.3 * M, opex_budget=0.3 * M),
        Project("P10", "I2-P4", "MES Sustainment",          Interval("2027-01-01", "2027-06-30"), capex_budget=0.2 * M, opex_budget=0.8 * M),
        Project("P11", "I3-P1", "Data Contract Charter",    Interval("2026-01-10", "2026-03-25"), capex_budget=0.2 * M, opex_budget=0.2 * M),
        Project("P12", "I3-P2", "Supplier Feed Integration",Interval("2026-04-01", "2026-09-30"), capex_budget=1.0 * M, opex_budget=0.4 * M),
        Project("P13", "I3-P2", "Inventory Signal Build",   Interval("2026-05-01", "2026-09-15"), capex_budget=0.8 * M, opex_budget=0.3 * M),
        Project("P14", "I3-P3", "Partner Extension",        Interval("2026-10-01", "2027-06-30"), capex_budget=0.7 * M, opex_budget=0.5 * M),
    ]

    # ── processes + plateaus ──────────────────────────────────────────────────
    s.processes = [
        BusinessProcess("BP1", "Order to Cash", [
            Plateau("BP1-T1", "Manual reconciliation retired", "2026-06-30"),
            Plateau("BP1-T2", "Straight-through invoicing",    "2026-12-31"),
            Plateau("BP1-T3", "Predictive collections",        "2027-06-30"),
        ]),
        BusinessProcess("BP2", "Plan to Produce", [
            Plateau("BP2-T1", "Line telemetry available",  "2026-06-30"),
            Plateau("BP2-T2", "Closed-loop scheduling",    "2026-12-31"),
            Plateau("BP2-T3", "Autonomous replanning",     "2027-09-30"),
        ]),
    ]

    s.capabilities = [
        Capability("C1", "Financial Close Automation",   ["BP1"]),
        Capability("C2", "Supplier Collaboration",       ["BP1"]),
        Capability("C3", "Shop Floor Telemetry",         ["BP2"]),
        Capability("C4", "Production Scheduling",        ["BP2"]),
        Capability("C5", "Inventory Visibility",         ["BP1", "BP2"]),
        Capability("C6", "Master Data Governance",       ["BP1", "BP2"]),
        Capability("C7", "Integration Platform",         ["BP1", "BP2"]),
        Capability("C8", "Analytics & Reporting",        ["BP1"]),
        # TENSION (f): NOTHING contributes to C9. Added because plan_coverage_gap found
        # the seed had FULL capability coverage on its first run -- a verb that answers
        # "what is nobody working on" needs something nobody is working on, or the demo
        # beat is a green checkmark. It enables BP1, so the absence is not merely tidy:
        # a modelled process depends on a capability with no project behind it.
        Capability("C9", "Regulatory Reporting",         ["BP1"]),
    ]

    s.contributions = [
        CapabilityContribution("P3",  "C1", 0.7),
        CapabilityContribution("P3",  "C8", 0.2),
        CapabilityContribution("P4",  "C2", 0.6),
        CapabilityContribution("P4",  "C6", 0.3),
        CapabilityContribution("P5",  "C1", 0.3),
        CapabilityContribution("P7",  "C3", 0.5),
        CapabilityContribution("P8",  "C3", 0.4),
        CapabilityContribution("P9",  "C3", 0.4),
        CapabilityContribution("P8",  "C4", 0.5),
        CapabilityContribution("P12", "C2", 0.4),
        CapabilityContribution("P12", "C7", 0.6),
        CapabilityContribution("P13", "C5", 0.8),
        CapabilityContribution("P14", "C5", 0.3),
        # TENSION (e): C4 "Production Scheduling" enables BP2, whose plateau BP2-T2
        # "Closed-loop scheduling" targets 2026-12-31 — but its only other contributor
        # (P10, below) does not finish until 2027-06-30. The path MISSES the plateau.
        CapabilityContribution("P10", "C4", 0.5),
    ]

    # ── sites ─────────────────────────────────────────────────────────────────
    s.sites = [
        Site("S1", "Site A — Aurora",    "US-Central", saturation_threshold=2.0),
        Site("S2", "Site B — Brandon",   "US-Central", saturation_threshold=2.0),
        Site("S3", "Site C — Calder",    "US-West",    saturation_threshold=2.5),
        # 2.5, not 1.5. At 1.5 the P5+P14 overlap put S4 at 2.0 in FY27-Q1 — a SECOND
        # red cell, which would have given "which sites are getting hammered" two
        # answers and blunted the beat. At 2.5 it sits at 80% utilisation: a visible
        # near-miss the room can notice without it being an alarm.
        Site("S4", "Site D — Dorchester","EU-West",    saturation_threshold=2.5),
    ]

    q4 = Interval("2026-07-01", "2026-09-30")
    s.site_impacts = [
        SiteImpact("P3",  "S1", Interval("2026-05-01", "2026-06-30"), 1.0),
        SiteImpact("P4",  "S1", Interval("2026-05-15", "2026-06-30"), 0.8),
        SiteImpact("P7",  "S3", Interval("2026-04-01", "2026-06-30"), 1.2),
        SiteImpact("P9",  "S3", Interval("2026-05-01", "2026-06-30"), 1.0),
        # TENSION (c): THREE overlapping impacts on Site B in FY26-Q4, summing to 2.7
        # against a threshold of 2.0. Visible on first load, no interaction required.
        SiteImpact("P8",  "S2", q4, 1.2),
        SiteImpact("P12", "S2", Interval("2026-07-15", "2026-09-30"), 0.9),
        SiteImpact("P13", "S2", Interval("2026-07-01", "2026-08-31"), 0.6),
        SiteImpact("P5",  "S4", Interval("2026-10-01", "2026-12-31"), 1.1),
        SiteImpact("P14", "S4", Interval("2026-11-01", "2027-02-28"), 0.9),
    ]

    # INVENTED PRODUCTS, not real ones. The first draft named actual vendor products; in a
    # public repo's demo data that reads as somebody's actual stack, and the seed is supposed
    # to be a fictional manufacturer. Generic CATEGORY names carry the same modelling weight
    # (a technology enables capabilities and participates in projects) and imply nothing.
    s.technologies = [
        Technology("T1", "Core ERP Platform"),
        Technology("T2", "Device Telemetry Bus"),
        Technology("T3", "Event Streaming Backbone"),
        Technology("T4", "Analytics Warehouse"),
        Technology("T5", "Manufacturing Execution Suite"),
    ]
    s.tech_capabilities = [
        TechEnablesCapability("T1", "C1"), TechEnablesCapability("T1", "C6"),
        TechEnablesCapability("T2", "C3"), TechEnablesCapability("T3", "C7"),
        TechEnablesCapability("T3", "C5"), TechEnablesCapability("T4", "C8"),
        TechEnablesCapability("T5", "C4"),
    ]
    s.tech_projects = [
        TechInProject("T1", "P3"), TechInProject("T1", "P4"), TechInProject("T1", "P5"),
        TechInProject("T2", "P7"), TechInProject("T2", "P8"), TechInProject("T2", "P9"),
        TechInProject("T3", "P12"), TechInProject("T3", "P13"),
        TechInProject("T4", "P13"), TechInProject("T5", "P8"), TechInProject("T5", "P10"),
    ]

    # ── dependencies ──────────────────────────────────────────────────────────
    s.dependencies = [
        Dependency("D1", "project", "P1", "project", "P2", "FS", 0),
        Dependency("D2", "project", "P2", "project", "P3", "FS", 0),
        Dependency("D3", "project", "P2", "project", "P4", "FS", 0),
        # TENSION (b): P3 (Finance Module, ends 2026-06-30) must finish 14 days before
        # P5 (Wave 1 Cutover, starts 2026-10-01) — satisfied today with ~93 days of slack.
        # Dragging P5 LEFT to relieve the Q3 cost peak is the natural first move in the
        # room, and it violates this the moment P5 starts before 2026-07-14.
        Dependency("D4", "project", "P3", "project", "P5", "FS", 14),
        Dependency("D5", "project", "P6", "project", "P7", "FS", 0),
        Dependency("D6", "project", "P7", "project", "P8", "FS", 0),
        Dependency("D7", "project", "P11", "project", "P12", "FS", 0),
        # Lag 0, not 30. At lag 30 this fired as a BASELINE violation (P12 ends
        # 2026-09-30, P14 starts 2026-10-01, 29 days short) — caught by
        # test_tension_b_baseline_has_no_violations on its first run. A baseline that
        # already shows red teaches the room to ignore red, which destroys the diff
        # card's only signal. The trap must be UNSPRUNG at rest; D4 is the sprung one.
        Dependency("D8", "project", "P12", "project", "P14", "FS", 0),
        Dependency("D9", "phase",   "I2-P2", "phase", "I2-P4", "FS", 0),
    ]

    s.organizations = [
        Organization("O1", "Corporate Capital Committee"),
        Organization("O2", "Manufacturing Operations"),
        Organization("O3", "Supply Chain Function"),
    ]

    # ── funding: demand ───────────────────────────────────────────────────────
    # TENSION (a): FY26-Q3 capex+expense requirements total 5.05M against a 4.0M cap.
    reqs: list[tuple[str, str, str, float]] = [
        ("P1",  "FY26-Q1", "capex", 0.40 * M), ("P1",  "FY26-Q1", "expense", 0.20 * M),
        ("P6",  "FY26-Q1", "capex", 0.30 * M), ("P6",  "FY26-Q1", "expense", 0.10 * M),
        ("P2",  "FY26-Q2", "capex", 0.60 * M), ("P2",  "FY26-Q2", "expense", 0.30 * M),
        ("P11", "FY26-Q2", "capex", 0.20 * M), ("P11", "FY26-Q2", "expense", 0.20 * M),
        # the Q3 peak
        ("P3",  "FY26-Q3", "capex", 2.20 * M), ("P3",  "FY26-Q3", "expense", 0.40 * M),
        ("P4",  "FY26-Q3", "capex", 1.80 * M), ("P4",  "FY26-Q3", "expense", 0.30 * M),
        ("P7",  "FY26-Q3", "capex", 0.20 * M), ("P9",  "FY26-Q3", "expense", 0.15 * M),
        # Q4
        ("P8",  "FY26-Q4", "capex", 1.10 * M), ("P8",  "FY26-Q4", "expense", 0.30 * M),
        ("P12", "FY26-Q4", "capex", 1.00 * M), ("P12", "FY26-Q4", "expense", 0.40 * M),
        ("P13", "FY26-Q4", "capex", 0.80 * M), ("P13", "FY26-Q4", "expense", 0.30 * M),
        ("P9",  "FY26-Q4", "capex", 1.30 * M),
        # FY27
        ("P5",  "FY27-Q1", "capex", 0.90 * M), ("P5",  "FY27-Q1", "expense", 0.60 * M),
        ("P14", "FY27-Q1", "capex", 0.70 * M), ("P14", "FY27-Q1", "expense", 0.50 * M),
        ("P10", "FY27-Q2", "capex", 0.20 * M), ("P10", "FY27-Q2", "expense", 0.80 * M),
    ]
    s.requirements = [
        FundingRequirement(f"R{i+1}", pid, per, kind, amt)  # type: ignore[arg-type]
        for i, (pid, per, kind, amt) in enumerate(reqs)
    ]

    # ── funding: supply ───────────────────────────────────────────────────────
    # TENSION (d): O3 (Supply Chain Function) under-commits on Initiative 3. P12 and P13
    # need 2.50M in FY26-Q4 and O3 has committed 1.40M — a visible 1.10M gap on ONE org
    # and ONE initiative, which is what makes the gap card readable rather than a wash.
    commits: list[tuple[str, str, str, str, float]] = [
        ("P1",  "O1", "FY26-Q1", "capex", 0.40 * M), ("P1",  "O1", "FY26-Q1", "expense", 0.20 * M),
        ("P6",  "O2", "FY26-Q1", "capex", 0.30 * M), ("P6",  "O2", "FY26-Q1", "expense", 0.10 * M),
        ("P2",  "O1", "FY26-Q2", "capex", 0.60 * M), ("P2",  "O1", "FY26-Q2", "expense", 0.30 * M),
        ("P11", "O3", "FY26-Q2", "capex", 0.20 * M), ("P11", "O3", "FY26-Q2", "expense", 0.20 * M),
        ("P3",  "O1", "FY26-Q3", "capex", 2.20 * M), ("P3",  "O1", "FY26-Q3", "expense", 0.40 * M),
        ("P4",  "O1", "FY26-Q3", "capex", 1.80 * M), ("P4",  "O1", "FY26-Q3", "expense", 0.30 * M),
        ("P7",  "O2", "FY26-Q3", "capex", 0.20 * M), ("P9",  "O2", "FY26-Q3", "expense", 0.15 * M),
        ("P8",  "O2", "FY26-Q4", "capex", 1.10 * M), ("P8",  "O2", "FY26-Q4", "expense", 0.30 * M),
        ("P9",  "O2", "FY26-Q4", "capex", 1.30 * M),
        ("P12", "O3", "FY26-Q4", "capex", 0.90 * M),   # needs 1.00 capex + 0.40 expense
        ("P13", "O3", "FY26-Q4", "capex", 0.50 * M),   # needs 0.80 capex + 0.30 expense
        ("P5",  "O1", "FY27-Q1", "capex", 0.90 * M), ("P5",  "O1", "FY27-Q1", "expense", 0.60 * M),
        ("P14", "O3", "FY27-Q1", "capex", 0.70 * M), ("P14", "O3", "FY27-Q1", "expense", 0.50 * M),
        ("P10", "O2", "FY27-Q2", "capex", 0.20 * M), ("P10", "O2", "FY27-Q2", "expense", 0.80 * M),
    ]
    s.commitments = [
        FundingCommitment(f"K{i+1}", pid, org, per, kind, amt)  # type: ignore[arg-type]
        for i, (pid, org, per, kind, amt) in enumerate(commits)
    ]

    # ── assessments: 2–3 per cell so "as of" is demonstrable ──────────────────
    # Append-only. The LATEST per (capability, site) is the current level; the earlier rows
    # are the trajectory, and they are what make an as-of query mean something.
    cells = [
        ("C1", "S1", [(1.0, "2025-06-30"), (1.5, "2025-12-31"), (2.0, "2026-06-30")], 4.0),
        ("C1", "S2", [(1.0, "2025-06-30"), (1.2, "2025-12-31")], 4.0),
        ("C3", "S2", [(2.0, "2025-06-30"), (2.5, "2025-12-31"), (3.0, "2026-06-30")], 4.0),
        ("C3", "S3", [(1.5, "2025-06-30"), (2.0, "2026-06-30")], 4.0),
        ("C4", "S2", [(1.0, "2025-12-31"), (1.5, "2026-06-30")], 4.0),
        ("C5", "S1", [(2.0, "2025-12-31"), (2.2, "2026-06-30")], 3.0),
        ("C5", "S4", [(1.0, "2025-12-31"), (1.0, "2026-06-30")], 3.0),
        ("C7", "S1", [(2.5, "2025-12-31"), (3.0, "2026-06-30")], 4.0),
    ]
    n = 0
    for cap_id, site_id, history, target in cells:
        for level, when in history:
            n += 1
            s.assessments.append(MaturityAssessment(
                assessment_id=f"A{n}", capability_id=cap_id, site_id=site_id,
                level=level, target_level=target, assessed_at=when,
                assessed_by="capability-council", evidence_ref=f"evidence://{cap_id}/{site_id}/{when}",
            ))

    # The governance cap line. FY26-Q3 is deliberately below its requirement sum.
    s.period_caps = {
        "FY26-Q1": 1.5 * M,
        "FY26-Q2": 1.5 * M,
        "FY26-Q3": 4.0 * M,   # requirements total 5.05M -> TENSION (a)
        "FY26-Q4": 5.5 * M,
        "FY27-Q1": 3.0 * M,
        # FY27-Q2 deliberately has NO cap — honestly uncapped, not capped at zero.
    }

    path = overlay_path or os.getenv("PLANNING_SEED_OVERLAY")
    if path:
        f = Path(path)
        if not f.is_file():
            raise FileNotFoundError(
                f"seed overlay configured but not found: {path}. Configured-but-absent is a "
                "different state from not-configured, and silently using the generic dataset "
                "would look entirely normal."
            )
        s = _apply_overlay(s, json.loads(f.read_text(encoding="utf-8")))
    return s


def check_consistency(s: PlanState) -> list[str]:
    """Gate 0's consistency check. Returns problems; empty means clean.

    Returns a LIST rather than raising, because the first broken FK is rarely the only one
    and a seed author wants the whole set in one run.
    """
    problems: list[str] = []
    proj_ids = {p.project_id for p in s.projects}
    phase_ids = {p.phase_id for p in s.phases}
    init_ids = {i.initiative_id for i in s.initiatives}
    site_ids = {x.site_id for x in s.sites}
    cap_ids = {c.capability_id for c in s.capabilities}
    org_ids = {o.org_id for o in s.organizations}
    tech_ids = {t.tech_id for t in s.technologies}
    proc_ids = {p.process_id for p in s.processes}

    for ph in s.phases:
        if ph.initiative_id not in init_ids:
            problems.append(f"phase {ph.phase_id} -> unknown initiative {ph.initiative_id}")
        if not ph.planned.is_well_formed():
            problems.append(f"phase {ph.phase_id} interval is inverted")
    for p in s.projects:
        if p.phase_id not in phase_ids:
            problems.append(f"project {p.project_id} -> unknown phase {p.phase_id}")
        if not p.planned.is_well_formed():
            problems.append(f"project {p.project_id} interval is inverted")
    for c in s.contributions:
        if c.project_id not in proj_ids:
            problems.append(f"contribution -> unknown project {c.project_id}")
        if c.capability_id not in cap_ids:
            problems.append(f"contribution -> unknown capability {c.capability_id}")
    for si in s.site_impacts:
        if si.project_id not in proj_ids:
            problems.append(f"site_impact -> unknown project {si.project_id}")
        if si.site_id not in site_ids:
            problems.append(f"site_impact -> unknown site {si.site_id}")
        if not si.window.is_well_formed():
            problems.append(f"site_impact {si.project_id}/{si.site_id} window is inverted")
    for d in s.dependencies:
        for kind, ident, role in ((d.predecessor_kind, d.predecessor_id, "predecessor"),
                                  (d.successor_kind, d.successor_id, "successor")):
            pool = proj_ids if kind == "project" else phase_ids
            if ident not in pool:
                problems.append(f"dependency {d.dependency_id} {role} -> unknown {kind} {ident}")
    for r in s.requirements:
        if r.project_id not in proj_ids:
            problems.append(f"requirement {r.req_id} -> unknown project {r.project_id}")
    for k in s.commitments:
        if k.project_id not in proj_ids:
            problems.append(f"commitment {k.commit_id} -> unknown project {k.commit_id}")
        if k.org_id not in org_ids:
            problems.append(f"commitment {k.commit_id} -> unknown org {k.org_id}")
    for tc in s.tech_capabilities:
        if tc.tech_id not in tech_ids or tc.capability_id not in cap_ids:
            problems.append(f"tech_capability {tc.tech_id}/{tc.capability_id} dangles")
    for tp in s.tech_projects:
        if tp.tech_id not in tech_ids or tp.project_id not in proj_ids:
            problems.append(f"tech_project {tp.tech_id}/{tp.project_id} dangles")
    for cap in s.capabilities:
        for pid in cap.enables_process_ids:
            if pid not in proc_ids:
                problems.append(f"capability {cap.capability_id} -> unknown process {pid}")
    for a in s.assessments:
        if a.capability_id not in cap_ids or a.site_id not in site_ids:
            problems.append(f"assessment {a.assessment_id} dangles")

    # Gate 0 requires EVERY project to carry at least one funding requirement — a project
    # with none renders an honest empty, but a seed full of them makes the cost curve a lie
    # by omission rather than by error.
    funded = {r.project_id for r in s.requirements}
    for pid in sorted(proj_ids - funded):
        problems.append(f"project {pid} has no funding requirement")

    return problems
