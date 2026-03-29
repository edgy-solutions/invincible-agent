import json
from enum import Enum
from typing import Dict, Any, Optional, Union, List
from fastapi import FastAPI, Request
from pydantic import BaseModel
import uvicorn

from baml_client import b

# Initialize runtime BAML configuration logic
try:
    from ..llm_utils import init_baml_client
    b = init_baml_client(b)
except ImportError:
    try:
        from llm_utils import init_baml_client
        b = init_baml_client(b)
    except ImportError:
        pass

app = FastAPI(title="Engine F - Presentation Agent")

class RenderRequest(BaseModel):
    raw_data: Union[Dict[str, Any], List[Dict[str, Any]], str]
    persona: str

@app.post("/render_ui")
async def render_ui(request: RenderRequest) -> Any:
    # 1. Stringify raw data safely
    if isinstance(request.raw_data, (dict, list)):
        str_raw_data = json.dumps(request.raw_data)
    else:
        str_raw_data = str(request.raw_data)
        
    # 2. Call BAML router (now returns DashboardUI with components array)
    baml_response = await b.DesignUI(str_raw_data, request.persona.upper())
    
    # 3. Return the model dump directly
    return baml_response.model_dump()

@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "engine": "F"}

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8087))
    uvicorn.run(app, host="0.0.0.0", port=port)
