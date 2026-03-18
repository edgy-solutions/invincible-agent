import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Configuration from environment
DAGSTER_URL = os.environ.get("DAGSTER_URL", "http://localhost:3000/graphql")
POLL_INTERVAL_SECONDS = 2
MAX_POLLS = 120  # 4 minutes max

app = FastAPI(title="Invincible Agent Gateway (Decoupled)")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")

class OrchestrationRequest(BaseModel):
    user_query: str
    thread_id: str
    persona: str = "MECHANIC"

# GraphQL Mutations & Queries
SUBMIT_RUN_MUTATION = """
mutation SubmitRun($runConfigData: RunConfigData!) {
  submitRun(executionParams: {
    selector: { jobName: "supervisor_query_job" },
    runConfigData: $runConfigData
  }) {
    __typename
    ... on SubmitRunSuccess {
      runId
    }
    ... on PythonError {
      message
      stack
    }
    ... on ConflictingRunIdError {
      message
    }
  }
}
"""

GET_RUN_STATUS_QUERY = """
query GetRunStatus($runId: String!) {
  pipelineRunOrError(runId: $runId) {
    __typename
    ... on Run {
      status
    }
    ... on PythonError {
      message
    }
  }
}
"""

GET_STEP_OUTPUT_QUERY = """
query GetStepOutput($runId: String!) {
  pipelineRunOrError(runId: $runId) {
    ... on Run {
      events(after: -1) {
        __typename
        ... on HandledOutputEvent {
          stepKey
          metadataEntries {
            label
            value {
              ... on TextMetadataValue { text }
              ... on JsonMetadataValue { data }
            }
          }
        }
        ... on EngineEvent {
          message
          error {
            message
            stack
          }
        }
      }
    }
  }
}
"""

async def call_dagster_graphql(query: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            DAGSTER_URL,
            json={"query": query, "variables": variables or {}},
            timeout=30
        )
        response.raise_for_status()
        return response.json()

@app.post("/orchestrate")
async def orchestrate(request: OrchestrationRequest) -> Dict[str, Any]:
    """
    Submits a Dagster run, polls for completion, and returns the final UI instruction.
    """
    # 1. Prepare run config
    run_config = {
        "ops": {
            "create_task_plan": {
                "config": {
                    "user_query": request.user_query,
                    "thread_id": request.thread_id,
                    "persona": request.persona,
                }
            },
            "synthesize_stateful": {
                "config": {
                    "user_query": request.user_query,
                    "thread_id": request.thread_id,
                    "persona": request.persona,
                }
            },
            "generate_ui_payload": {
                "config": {
                    "user_query": request.user_query,
                    "thread_id": request.thread_id,
                    "persona": request.persona,
                }
            }
        }
    }

    # 2. Submit Run
    logger.info(f"Submitting run for user_query='{request.user_query}'")
    submit_result = await call_dagster_graphql(
        SUBMIT_RUN_MUTATION,
        {"runConfigData": run_config}
    )

    data = submit_result.get("data", {}).get("submitRun", {})
    if data.get("__typename") != "SubmitRunSuccess":
        error_msg = data.get("message", "Unknown error submitting run")
        logger.error(f"SubmitRun failed: {error_msg}")
        raise HTTPException(status_code=500, detail=f"Dagster SubmitRun failed: {error_msg}")

    run_id = data["runId"]
    logger.info(f"Run submitted successfully. RunId: {run_id}")

    # 3. Poll for Status
    status = "STARTING"
    polls = 0
    while status not in ["SUCCESS", "FAILURE", "CANCELED"] and polls < MAX_POLLS:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        status_result = await call_dagster_graphql(GET_RUN_STATUS_QUERY, {"runId": run_id})
        status_data = status_result.get("data", {}).get("pipelineRunOrError", {})
        
        if status_data.get("__typename") != "Run":
            raise HTTPException(status_code=500, detail="Failed to fetch run status")
            
        status = status_data["status"]
        polls += 1
        logger.info(f"Polling RunId {run_id}: Status={status}")

    if status != "SUCCESS":
        # Attempt to find error message in logs
        events_result = await call_dagster_graphql(GET_STEP_OUTPUT_QUERY, {"runId": run_id})
        events = events_result.get("data", {}).get("pipelineRunOrError", {}).get("events", [])
        error_msg = "Run failed or timed out"
        for event in events:
            if event.get("__typename") == "EngineEvent" and event.get("error"):
                error_msg = event["error"]["message"]
                break
        
        logger.error(f"Run {run_id} failed with status {status}: {error_msg}")
        raise HTTPException(status_code=500, detail=f"Dagster run failed: {error_msg}")

    # 4. Fetch Output
    logger.info(f"Run {run_id} successful. Fetching output...")
    output_result = await call_dagster_graphql(GET_STEP_OUTPUT_QUERY, {"runId": run_id})
    events = output_result.get("data", {}).get("pipelineRunOrError", {}).get("events", [])
    
    # Search for the HandledOutputEvent of the final step 'generate_ui_payload'
    final_output_str = None
    for event in events:
        if event.get("__typename") == "HandledOutputEvent" and event.get("stepKey") == "generate_ui_payload":
            # Extract UI payload from metadata (redundant safety) or search for the result string
            metadata = event.get("metadataEntries", [])
            for entry in metadata:
                if entry.get("label") == "ui_json_payload" and entry.get("value", {}).get("data"):
                    # This is the full JSON dict from MetadataValue.json
                    return {
                        "status": "success",
                        "run_id": run_id,
                        "ui_instruction": entry["value"]["data"]
                    }
            
            # Fallback: Find the TextMetadataValue if we logged it as a string
            for entry in metadata:
                if entry.get("value", {}).get("text"):
                    try:
                        return {
                            "status": "success",
                            "run_id": run_id,
                            "ui_instruction": json.loads(entry["value"]["text"])
                        }
                    except:
                        pass

    # If we didn't find specific metadata, we fallback to a generic message
    # In a real environment, the above MetadataValue.json check is extremely reliable.
    return {
        "status": "success",
        "run_id": run_id,
        "message": "Orchestration completed. Results available in Dagster UI.",
    }

@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "gateway": "decoupled", "dagster_endpoint": DAGSTER_URL}

if __name__ == "__main__":
    port = int(os.environ.get("GATEWAY_PORT", 8888))
    uvicorn.run(app, host="0.0.0.0", port=port)
