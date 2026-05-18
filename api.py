from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
import json
import asyncio
from agent import graph
from google_auth import get_auth_url, exchange_code_for_token

app = FastAPI(title="AI CFO Agent API")

class ChatRequest(BaseModel):
    prompt: str

class AuthExchangeRequest(BaseModel):
    code: str

@app.get("/auth/url")
async def get_google_auth_url():
    return {"url": get_auth_url()}

@app.post("/auth/exchange")
async def exchange_google_code(request: AuthExchangeRequest):
    result = exchange_code_for_token(request.code)
    return {"message": result}

@app.post("/stream")
async def stream_chat(request: ChatRequest):
    """
    Endpoint that accepts a prompt and streams back the LangGraph execution steps.
    """
    async def event_generator():
        print(f"\n[API] Received request: {request.prompt[:100]}...")
        initial_state = {"messages": [("user", request.prompt)]}
        try:
            # Use astream for async graph execution
            async for s in graph.astream(initial_state, stream_mode="updates"):
                step_name = list(s.keys())[0]
                
                final_message = ""
                if "messages" in s[step_name] and s[step_name]["messages"]:
                    final_message = s[step_name]["messages"][-1].content
                    
                data = {
                    "step": step_name,
                    "message": final_message
                }
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            print(f"[API] Request cancelled by client: {request.prompt[:50]}...")
            raise
        except Exception as e:
            print(f"[API ERROR] {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/health")
def health_check():
    return {"status": "ok"}
