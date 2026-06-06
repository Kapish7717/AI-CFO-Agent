from fastapi import FastAPI, Request
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, HTMLResponse
import json
import asyncio
from agent import graph
from google_auth import get_auth_url, exchange_code_for_token, is_authenticated

app = FastAPI(title="AI CFO Agent API")

class ChatRequest(BaseModel):
    prompt: str

class AuthExchangeRequest(BaseModel):
    code: str

@app.get("/auth/url")
async def get_google_auth_url(request: Request):
    base_url = str(request.base_url).rstrip('/')
    redirect_uri = f"{base_url}/auth/callback"
    return {"url": get_auth_url(redirect_uri=redirect_uri)}

@app.post("/auth/exchange")
async def exchange_google_code(request: AuthExchangeRequest, server_req: Request):
    base_url = str(server_req.base_url).rstrip('/')
    redirect_uri = f"{base_url}/auth/callback"
    result = exchange_code_for_token(request.code, redirect_uri=redirect_uri)
    return {"message": result}

@app.get("/auth/callback")
async def auth_callback(request: Request, code: str, state: str = None):
    base_url = str(request.base_url).rstrip('/')
    redirect_uri = f"{base_url}/auth/callback"
    result = exchange_code_for_token(code, redirect_uri=redirect_uri)
    
    if "Success" in result:
        html_content = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Authentication Success</title>
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
            <style>
                body {
                    font-family: 'Inter', -apple-system, sans-serif;
                    background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    color: #f8fafc;
                }
                .container {
                    background: rgba(255, 255, 255, 0.05);
                    backdrop-filter: blur(10px);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    padding: 3rem;
                    border-radius: 24px;
                    text-align: center;
                    max-width: 450px;
                    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
                    animation: fadeIn 0.8s ease-out;
                }
                @keyframes fadeIn {
                    from { opacity: 0; transform: translateY(20px); }
                    to { opacity: 1; transform: translateY(0); }
                }
                .icon-wrapper {
                    width: 80px;
                    height: 80px;
                    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
                    border-radius: 50%;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    margin: 0 auto 2rem;
                    box-shadow: 0 8px 16px rgba(16, 185, 129, 0.3);
                }
                .icon {
                    font-size: 2.5rem;
                    color: white;
                    font-weight: bold;
                }
                h1 {
                    font-size: 1.8rem;
                    font-weight: 800;
                    margin: 0 0 1rem;
                    background: linear-gradient(to right, #38bdf8, #818cf8);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                }
                p {
                    color: #94a3b8;
                    font-size: 1rem;
                    line-height: 1.6;
                    margin: 0 0 2rem;
                }
                .close-hint {
                    font-size: 0.85rem;
                    color: #64748b;
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="icon-wrapper">
                    <span class="icon">✓</span>
                </div>
                <h1>Authentication Successful</h1>
                <p>Your Google account has been successfully linked. You can close this window and return to the AI CFO dashboard.</p>
                <div class="close-hint">You can safely close this browser tab now.</div>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content, status_code=200)
    else:
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Authentication Failed</title>
            <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
            <style>
                body {{
                    font-family: 'Inter', -apple-system, sans-serif;
                    background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    color: #f8fafc;
                }}
                .container {{
                    background: rgba(255, 255, 255, 0.05);
                    backdrop-filter: blur(10px);
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    padding: 3rem;
                    border-radius: 24px;
                    text-align: center;
                    max-width: 450px;
                    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
                    animation: fadeIn 0.8s ease-out;
                }}
                @keyframes fadeIn {{
                    from {{ opacity: 0; transform: translateY(20px); }}
                    to {{ opacity: 1; transform: translateY(0); }}
                }}
                .icon-wrapper {{
                    width: 80px;
                    height: 80px;
                    background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%);
                    border-radius: 50%;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    margin: 0 auto 2rem;
                    box-shadow: 0 8px 16px rgba(239, 68, 68, 0.3);
                }}
                .icon {{
                    font-size: 2.5rem;
                    color: white;
                    font-weight: bold;
                }}
                h1 {{
                    font-size: 1.8rem;
                    font-weight: 800;
                    margin: 0 0 1rem;
                    background: linear-gradient(to right, #fca5a5, #f87171);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                }}
                p {{
                    color: #94a3b8;
                    font-size: 1rem;
                    line-height: 1.6;
                    margin: 0 0 2rem;
                }}
                .close-hint {{
                    font-size: 0.85rem;
                    color: #64748b;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="icon-wrapper">
                    <span class="icon">✗</span>
                </div>
                <h1>Authentication Failed</h1>
                <p>{result}</p>
                <div class="close-hint">Please try starting the authentication process again.</div>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content, status_code=400)

@app.get("/auth/status")
def get_auth_status():
    return {"authenticated": is_authenticated()}

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
