import re

with open("agent_fleet/restate_analyst/main.py", "r") as f:
    content = f.read()

# Replace _run_smolagent and analyze
pattern = re.compile(r'def _run_smolagent.*?return response\.model_dump\(\)\n', re.DOTALL)

new_content = r"""@analyst_service.handler()
async def analyze(ctx: Context, request: dict) -> dict:
    \"\"\"Durable handler: resolve ontology → run smolagent → return AgentResponse.

    Every side-effectful operation is wrapped in ``ctx.run()`` so Restate
    can guarantee exactly-once execution even across pod restarts.
    \"\"\"
    # Parse the incoming AgentTask
    task = AgentTask(**request)
    dynamic_schema_map = request.get("dynamic_schema_map", "")
    user_id = request.get("user_id")

    # Step 1: Resolve semantic context via Engine O (durable HTTP call)
    semantic_ctx = await ctx.run(
        "resolve_ontology",
        lambda: _resolve_ontology(task.task_description),
    )

    # --------------------------------------------------------------------------
    # Initialize long-term memory via mem0 using Weaviate vector DB 
    # (Survives K8s ephemeral pod restarts)
    raw_http_env = os.getenv("WEAVIATE_HTTP_HOST", "weaviate")
    raw_grpc_env = os.getenv("WEAVIATE_GRPC_HOST", "weaviate-grpc")

    def parse_host_port(env_val: str, default_port: int):
        clean = env_val.replace("http://", "").replace("https://", "").replace("grpc://", "")
        if ":" in clean:
            h, p = clean.split(":", 1)
            try:
                return h, int(p)
            except ValueError:
                return h, default_port
        return clean, default_port

    weaviate_http_host, weaviate_http_port = parse_host_port(raw_http_env, 8080)
    weaviate_grpc_host, weaviate_grpc_port = parse_host_port(raw_grpc_env, 50051)

    connection_params = ConnectionParams.from_params(
        http_host=weaviate_http_host,
        http_port=weaviate_http_port,
        http_secure=False,
        grpc_host=weaviate_grpc_host,
        grpc_port=weaviate_grpc_port,
        grpc_secure=False,
    )
    
    weaviate_client = weaviate.WeaviateClient(connection_params=connection_params)
    try:
        weaviate_client.connect()

        from smolagents import tool
        import weaviate.classes as wvc

        vector_store = WeaviateVectorStore(
            client=weaviate_client,
            index_name="Mem0migrations",
            text_key="text",
            embedding=FakeEmbeddings(size=1536)
        )

        m = Memory.from_config({
            "vector_store": {
                "provider": "langchain",
                "config": {
                    "client": vector_store,
                    "collection_name": "Mem0migrations"
                }
            }
        })

        @safe_observe(as_type="retrieval", name="mem0_context_retrieval")
        def fetch_user_memory(query: str, user_id: str):
            results = m.search(query=query, user_id=user_id)
            safe_update_observation(input_data=query, output_data=results)
            return results

        @tool
        def search_datahub(query: str, entity_type: str = None) -> str:
            \"\"\"
            Searches the DataHub metadata catalog.
            
            Args:
                query: CRITICAL - You MUST extract 1-3 concise keywords (e.g. 'RSO Superset'). DO NOT pass full sentences.
                entity_type: The specific entity to search. You MUST choose a value from the 'Valid DataHub Entity Types' list provided in your system prompt. Do NOT use '*'.
            \"\"\"
            import requests
            import os
            DATAHUB_WRAPPER_URL = os.getenv("DATAHUB_WRAPPER_URL", "http://datahub-wrapper-svc.default.svc.cluster.local:8085")
            try:
                resp = requests.post(
                    f"{DATAHUB_WRAPPER_URL}/query_metadata",
                    json={"user_query": query, "persona": "DATA_STEWARD", "domain": "DATA_ENGINEERING"},
                    timeout=15.0
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("data", {}).get("short_answer", "No results found.")
            except Exception as e:
                return f"Error executing DataHub search via Engine D: {str(e)}"

        @safe_observe(name="smolagents_restate_execution")
        async def run_smolagent() -> tuple[str, str, float]:
            suggested_models = semantic_ctx.get("suggested_dbt_models", [])
            resolved_uri = semantic_ctx.get("resolved_uri", "unknown")
            confidence = semantic_ctx.get("confidence_score", 0.0)

            agent_prompt = (
                f"You are a sustainment data analyst. Analyze the following task.\n\n"
                f"Task: {task.task_description}\n"
                f"Dataset ID: {task.dataset_id}\n\n"
                f"Semantic Context (from IOF/MIMOSA ontology):\n"
                f"  Resolved URI: {resolved_uri}\n"
                f"  Confidence: {confidence}\n"
                f"  Relevant dbt models / tables: {', '.join(suggested_models)}\n\n"
            )

            if dynamic_schema_map:
                agent_prompt += f"{dynamic_schema_map}\n\n"

            agent_prompt += (
                f"Use ONLY the tables listed above. Produce a brief summary of your "
                f"analysis and any key metrics you extract."
            )

            if user_id:
                past_memories = fetch_user_memory(query=task.task_description, user_id=user_id)
                if past_memories:
                    memory_strings = "\n".join([f"- {mem['text']}" for mem in past_memories])
                    prompt_extension = f"\n\n### Relevant Past Experience\n{memory_strings}"
                    agent_prompt += prompt_extension

            model = get_smolagent_model()
            agent = CodeAgent(tools=[search_datahub], model=model)
            
            result = str(await asyncio.to_thread(agent.run, agent_prompt))

            formatted_trace = "--- Agent Execution Trace ---\n"
            if hasattr(agent, 'logs'):
                for log_entry in agent.logs:
                    if isinstance(log_entry, dict):
                        formatted_trace += f"Step: {log_entry.get('step', 'N/A')}\n"
                        if 'thought' in log_entry:
                            formatted_trace += f"Thought: {log_entry['thought']}\n"
                        if 'tool_call' in log_entry:
                            formatted_trace += f"Action: {log_entry['tool_call']}\n"
                        if 'tool_result' in log_entry:
                            formatted_trace += f"Result: {log_entry['tool_result']}\n"
                    else:
                        formatted_trace += f"Step: {getattr(log_entry, 'step', 'N/A')}\n"
                        if hasattr(log_entry, 'thought') and getattr(log_entry, 'thought'):
                            formatted_trace += f"Thought: {getattr(log_entry, 'thought')}\n"
                        if hasattr(log_entry, 'tool_call') and getattr(log_entry, 'tool_call'):
                            formatted_trace += f"Action: {getattr(log_entry, 'tool_call')}\n"
                        elif hasattr(log_entry, 'action') and getattr(log_entry, 'action'):
                            formatted_trace += f"Action: {getattr(log_entry, 'action')}\n"
                        if hasattr(log_entry, 'tool_result') and getattr(log_entry, 'tool_result'):
                            formatted_trace += f"Result: {getattr(log_entry, 'tool_result')}\n"
                        elif hasattr(log_entry, 'observation') and getattr(log_entry, 'observation'):
                            formatted_trace += f"Result: {getattr(log_entry, 'observation')}\n"
                    formatted_trace += "-" * 30 + "\n"

            return result, formatted_trace, confidence

        raw_agent_response, execution_trace, conf = await ctx.run("run-smolagent", run_smolagent)

        async def save_memory() -> str:
            if user_id:
                m.add(
                    messages=[
                        {"role": "user", "content": task.task_description},
                        {"role": "assistant", "content": raw_agent_response}
                    ],
                    user_id=user_id
                )
            return "saved"
        
        await ctx.run("save-memory", save_memory)

        agent_result = {
            "status": AgentStatus.SUCCESS.value,
            "summary": raw_agent_response,
            "extracted_metrics": {
                "ontology_confidence": conf,
            },
            "execution_trace": execution_trace,
        }

        response = AgentResponse(**agent_result)
        return response.model_dump()
    finally:
        weaviate_client.close()
"""

new_file_content = pattern.sub(new_content, content)

# Also we need to add imports to the top of the file
imports_to_add = """
import asyncio
from mem0 import Memory
import weaviate
from weaviate.connect import ConnectionParams
from langchain_weaviate import WeaviateVectorStore
from langchain_community.embeddings import FakeEmbeddings
from telemetry import safe_observe, safe_update_observation
"""

if "import asyncio" not in new_file_content:
    new_file_content = new_file_content.replace("import restate", "import restate\n" + imports_to_add)

with open("agent_fleet/restate_analyst/main.py", "w") as f:
    f.write(new_file_content)

print("Patched _run_smolagent and analyze")
