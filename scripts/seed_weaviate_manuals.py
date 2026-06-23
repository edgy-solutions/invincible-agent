# /// script
# requires-python = ">=3.10"
# dependencies = ["weaviate-client>=4.7"]
# ///
"""Seed Weaviate's DocumentChunk collection with canned maintenance/mfg manual
chunks for Engine W testing.

Run via:
    kubectl -n sandbox port-forward svc/iagent-weaviate      18082:8080  &
    kubectl -n sandbox port-forward svc/iagent-weaviate-grpc 50051:50051 &
    uv run scripts/seed_weaviate_manuals.py

Requires the Weaviate cluster to have `text2vec-ollama` in
ENABLE_MODULES and to be able to reach the ollama embedding endpoint
configured below (the default points at the sandbox's ai1 host).
"""

import os
import sys

import weaviate
from weaviate.connect import ConnectionParams
import weaviate.classes as wvc

WEAVIATE_HTTP_HOST = os.getenv("WEAVIATE_HTTP_HOST", "localhost")
WEAVIATE_HTTP_PORT = int(os.getenv("WEAVIATE_HTTP_PORT", "18082"))
WEAVIATE_GRPC_HOST = os.getenv("WEAVIATE_GRPC_HOST", "localhost")
WEAVIATE_GRPC_PORT = int(os.getenv("WEAVIATE_GRPC_PORT", "50051"))
OLLAMA_API = os.getenv("OLLAMA_API_ENDPOINT", "http://192.168.1.126:11434")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
COLLECTION = os.getenv("WEAVIATE_DOC_COLLECTION", "DocumentChunk")


# 12 canned manual chunks across MAINTENANCE + MANUFACTURING domains.
# Engine W applies strict domain segregation, so each chunk must have
# `domain` set to one of the labels Engine W will pass in.
CHUNKS = [
    # ---------------- MAINTENANCE ----------------
    {
        "doc_id": "TM-1H-130H-2-28JG-00-1",
        "domain": "MAINTENANCE",
        "section": "APU Inspection",
        "text": (
            "C-130H Auxiliary Power Unit (APU) inspection schedule: visual "
            "inspection every 50 flight hours, oil sample analysis every "
            "100 flight hours, and full borescope inspection at 600 flight "
            "hours. Replace fuel control unit at 2400 flight hours. The APU "
            "shall not be started if ambient temperature exceeds 49 deg C "
            "(120 deg F) or oil pressure indication is below 35 psi."
        ),
    },
    {
        "doc_id": "TM-1H-130H-2-28JG-00-2",
        "domain": "MAINTENANCE",
        "section": "Auxiliary Fuel Pump",
        "text": (
            "Aircraft auxiliary fuel pump common failure modes: (1) impeller "
            "wear due to particulate contamination, manifesting as reduced "
            "delivery pressure; (2) seal leakage at the drive shaft, "
            "typically caused by exceeding service life of the elastomer "
            "seal; (3) electrical commutator pitting in brushed DC pumps. "
            "Mean Time Between Failure (MTBF) for the C-130 auxiliary fuel "
            "pump is approximately 4,800 flight hours under standard "
            "operating conditions. Recommended scheduled replacement is at "
            "3,500 flight hours."
        ),
    },
    {
        "doc_id": "TM-1H-130H-2-12-01",
        "domain": "MAINTENANCE",
        "section": "Hydraulic System",
        "text": (
            "C-130 utility hydraulic system operates at 3000 psi nominal. "
            "Reservoir level shall be checked prior to each flight; minimum "
            "level is 75% of FULL mark when measured at cold-soak condition "
            "(below 0 deg C). Filter element replacement is required every "
            "300 flight hours OR when delta-P indicator extends to red, "
            "whichever occurs first."
        ),
    },
    {
        "doc_id": "TM-1H-130H-2-29-01",
        "domain": "MAINTENANCE",
        "section": "Tire Pressure",
        "text": (
            "C-130H main landing gear tire pressure: 150 psi cold. Nose gear "
            "tire pressure: 110 psi cold. Pressure shall be checked within "
            "24 hours of flight. A tire which has been operated at a "
            "pressure 10% below the placarded minimum must be removed and "
            "tagged for shop inspection."
        ),
    },
    {
        "doc_id": "T.O. 00-20-1",
        "domain": "MAINTENANCE",
        "section": "Inspection Concept",
        "text": (
            "Time Compliance Technical Order (TCTO) compliance is mandatory "
            "for safety-of-flight items. TCTO classifications: IMMEDIATE "
            "(complete before next flight), URGENT (complete within 30 days "
            "or 25 flight hours), and ROUTINE (complete by stated calendar "
            "date). Non-compliance with an IMMEDIATE TCTO shall ground the "
            "aircraft."
        ),
    },
    {
        "doc_id": "TM-1H-130H-2-11-01",
        "domain": "MAINTENANCE",
        "section": "Engine T56",
        "text": (
            "T56-A-15 turboprop engine TBO (Time Between Overhaul) is 4,500 "
            "flight hours for hot section, 9,000 flight hours for cold "
            "section. Engine oil consumption rate exceeding 1.0 quart per "
            "hour requires investigation. EGT (Exhaust Gas Temperature) "
            "limit during takeoff is 977 deg C; sustained operation above "
            "this limit reduces hot section life by approximately 50 percent "
            "per 10 deg C of overage."
        ),
    },
    # ---------------- MANUFACTURING ----------------
    {
        "doc_id": "MFG-PROC-001",
        "domain": "MANUFACTURING",
        "section": "Composite Layup",
        "text": (
            "Carbon fiber prepreg layup procedure: ambient temperature in "
            "clean room shall be maintained between 18 and 24 deg C with "
            "relative humidity 40-60 percent. Prepreg material removed from "
            "freezer shall reach room temperature (minimum 4 hours) before "
            "the sealed bag is opened to prevent condensation. Maximum "
            "out-of-freezer life is 30 days cumulative."
        ),
    },
    {
        "doc_id": "MFG-PROC-002",
        "domain": "MANUFACTURING",
        "section": "Autoclave Cure",
        "text": (
            "Standard cure cycle for epoxy/carbon fiber laminate: ramp at "
            "1.7 deg C/min to 121 deg C, hold for 60 minutes at 100 psi, "
            "ramp at 1.7 deg C/min to 177 deg C, hold for 120 minutes at "
            "100 psi, cool at 2.0 deg C/min to 60 deg C before vent. "
            "Deviations exceeding +/- 5 deg C from target ramp rate shall "
            "be documented and reviewed by Materials Engineering."
        ),
    },
    {
        "doc_id": "MFG-PROC-003",
        "domain": "MANUFACTURING",
        "section": "Rivet Inspection",
        "text": (
            "Inspection of installed flush head rivets shall verify head "
            "protrusion within +/- 0.005 inch of flush. Eddy current "
            "inspection is mandatory for safety-of-flight structural joints "
            "after rivet installation. Acceptable indication threshold is "
            "less than 30 percent of reference standard. Indications above "
            "this threshold require removal and re-inspection."
        ),
    },
    {
        "doc_id": "MFG-QMS-001",
        "domain": "MANUFACTURING",
        "section": "AS9100",
        "text": (
            "First Article Inspection (FAI) per AS9102 is required for: "
            "(1) initial production article, (2) any change to design, "
            "manufacturing process, or material that affects fit, form, or "
            "function, (3) lapses in production exceeding 24 months. The "
            "FAI Report shall be retained for the operational life of the "
            "part."
        ),
    },
    {
        "doc_id": "MFG-PROC-004",
        "domain": "MANUFACTURING",
        "section": "Surface Treatment",
        "text": (
            "Aluminum alloy 2024-T3 surface preparation prior to bonding: "
            "phosphoric acid anodize per BAC 5555 within 16 hours of bonding "
            "operation; surface energy shall test at >70 dyne/cm using "
            "calibrated dyne pen kit. Bond shall be initiated within 4 hours "
            "of surface preparation."
        ),
    },
    {
        "doc_id": "MFG-PROC-005",
        "domain": "MANUFACTURING",
        "section": "Torque Specifications",
        "text": (
            "Standard fastener torque values for cadmium-plated steel "
            "fasteners on aluminum substrate: 1/4-28 = 100 in-lb, "
            "5/16-24 = 200 in-lb, 3/8-24 = 360 in-lb. Torque shall be "
            "applied as a smooth continuous motion; impact wrenches are "
            "PROHIBITED for primary structural fasteners."
        ),
    },
]


def main() -> int:
    print(f"[seed] connecting to weaviate at "
          f"{WEAVIATE_HTTP_HOST}:{WEAVIATE_HTTP_PORT} (grpc "
          f"{WEAVIATE_GRPC_HOST}:{WEAVIATE_GRPC_PORT})")
    client = weaviate.WeaviateClient(
        connection_params=ConnectionParams.from_params(
            http_host=WEAVIATE_HTTP_HOST,
            http_port=WEAVIATE_HTTP_PORT,
            http_secure=False,
            grpc_host=WEAVIATE_GRPC_HOST,
            grpc_port=WEAVIATE_GRPC_PORT,
            grpc_secure=False,
        ),
        skip_init_checks=True,
    )
    client.connect()
    try:
        # Drop & recreate so seeds are deterministic.
        if client.collections.exists(COLLECTION):
            print(f"[seed] dropping existing collection {COLLECTION}")
            client.collections.delete(COLLECTION)

        print(f"[seed] creating collection {COLLECTION} with text2vec-ollama "
              f"({EMBED_MODEL} @ {OLLAMA_API})")
        client.collections.create(
            name=COLLECTION,
            vectorizer_config=wvc.config.Configure.Vectorizer.text2vec_ollama(
                api_endpoint=OLLAMA_API,
                model=EMBED_MODEL,
            ),
            properties=[
                wvc.config.Property(name="text", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="doc_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="domain", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="section", data_type=wvc.config.DataType.TEXT),
            ],
        )

        coll = client.collections.get(COLLECTION)
        print(f"[seed] inserting {len(CHUNKS)} chunks")
        with coll.batch.dynamic() as batch:
            for chunk in CHUNKS:
                batch.add_object(properties=chunk)

        # Verify
        result = coll.aggregate.over_all(total_count=True)
        print(f"[seed] collection now has {result.total_count} objects")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
