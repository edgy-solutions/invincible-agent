import json
from enum import Enum
from typing import Dict, Any, Optional, Union
from fastapi import FastAPI, Request
from pydantic import BaseModel
import uvicorn

from baml_client import b
from baml_client.types import PersonaTarget, PresentationInstruction

app = FastAPI(title="Engine F - Presentation Agent")

class RenderRequest(BaseModel):
    raw_data: Union[Dict[str, Any], str]
    persona: str

@app.post("/render_ui")
async def render_ui(request: RenderRequest) -> Dict[str, Any]:
    # 1. Parse string to enum
    persona_str = request.persona.upper()
    try:
        persona_target = PersonaTarget(persona_str)
    except ValueError:
        persona_target = PersonaTarget.MECHANIC

    # 2. Stringify raw data safely
    if isinstance(request.raw_data, dict):
        str_raw_data = json.dumps(request.raw_data)
    else:
        str_raw_data = str(request.raw_data)
        
    # 3. Call BAML router
    baml_response = await b.DesignUI(str_raw_data, persona_target)
    
    # 4. Return component instruction
    return baml_response.model_dump()

@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "engine": "F"}

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8087))
    uvicorn.run(app, host="0.0.0.0", port=port)
