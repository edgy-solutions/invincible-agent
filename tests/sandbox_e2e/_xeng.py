# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""Cross-engine composed-path seal driver: one /orchestrate query as agent-user,
observe (in the engine logs, separately) that identity threads to each engine's
gate along the chain."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mesh_client import run
for q in ["Search the maintenance manuals for the microphone boom removal procedure and summarize the steps."]:
    r = run(q, session_prefix="xeng")
    print("elapsed", round(r.get("elapsed_s",0),1))
    fp = r.get("final")
    print("final_payload present:", fp is not None)
