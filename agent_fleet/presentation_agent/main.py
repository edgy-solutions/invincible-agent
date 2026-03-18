import json
from enum import Enum
from typing import Dict, Any, Optional, Union
from fastapi import FastAPI, Request
from pydantic import BaseModel
import uvicorn

from baml_client import b
from baml_client.types import PersonaTarget, SemanticUIContainer

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
    
    # 4. Extract and stringify the payload safely using Python
    payload = baml_response.model_dump()
    
    # Safely stringify the entities and relationships so the React frontend 
    # can JSON.parse() them without escaping errors. 
    # Since BAML 0.219 uses strings, we try to load them first to avoid double-escaping.
    def safe_json_dump(val):
        if not val: return "[]"
        if isinstance(val, str):
            try:
                # If it's already valid JSON, don't double dump
                parsed = json.loads(val)
                return json.dumps(parsed)
            except:
                return json.dumps(val)
        return json.dumps(val)

    payload["entities"] = safe_json_dump(payload.get("entities"))
    payload["relationships"] = safe_json_dump(payload.get("relationships"))
    
    return payload

@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "engine": "F"}

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8087))
    uvicorn.run(app, host="0.0.0.0", port=port)
