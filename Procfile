web: python -m dagster webserver -h 0.0.0.0 -p 3000 -m iagent.definitions
bff: python -m uvicorn src.iagent.gateway:app --host 0.0.0.0 --port ${PORT:-8000}
