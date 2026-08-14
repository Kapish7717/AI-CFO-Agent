import html
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.core.security import (
    create_access_token,
    get_current_user_id,
    verify_password,
)
from app.db.database import (
    create_user,
    delete_user_google_token,
    get_user_by_email,
    get_user_by_id,
)
from app.integrations.google_auth import (
    exchange_code_for_token,
    get_auth_url,
    get_oauth_user_id,
    is_authenticated,
)

logger = logging.getLogger("backend.api.auth")
router = APIRouter()

class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "Finance Head"

class LoginRequest(BaseModel):
    email: str
    password: str

class AuthExchangeRequest(BaseModel):
    code: str

def get_effective_redirect_uri(request: Request) -> str:
    base_url = str(request.base_url).rstrip('/')
    x_forwarded_proto = request.headers.get("x-forwarded-proto")
    if x_forwarded_proto == "https" and base_url.startswith("http://"):
        base_url = base_url.replace("http://", "https://", 1)
    elif "hf.space" in base_url and base_url.startswith("http://"):
        base_url = base_url.replace("http://", "https://", 1)
    return f"{base_url}/auth/callback"

@router.post("/api/auth/register")
def register_user(req: RegisterRequest):
    email = req.email.strip().lower()
    logger.info(f"Registration request received for email: {email}")
    if not email or "@" not in email:
        raise HTTPException(status_code=422, detail="A valid email is required.")
    if len(req.password) < 8:
        raise HTTPException(
            status_code=422, detail="Password must be at least 8 characters long."
        )
    if get_user_by_email(email):
        logger.warning(f"Registration failed: User with email {email} already exists.")
        raise HTTPException(status_code=409, detail="User with this email already exists.")
    try:
        user_id = create_user(email, req.password, req.full_name, req.role)
        logger.info(f"User registration successful. Created User ID: {user_id}")
        token = create_access_token(user_id, email, req.role, req.full_name)
        return {"success": True, "user_id": user_id, "token": token}
    except Exception as e:
        logger.error(f"Error during registration for email {email}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Registration failed. Please try again.") from e

@router.post("/api/auth/login")
def login_user(req: LoginRequest):
    email_clean = req.email.strip().lower()
    logger.info(f"Login attempt for email: {email_clean}")
    try:
        user = get_user_by_email(req.email)
        if not user:
            logger.warning(f"Login failed: No user found with email {email_clean}")
            raise HTTPException(status_code=400, detail="Invalid email or password.")
        if not verify_password(req.password, user["password_hash"]):
            logger.warning(f"Login failed: Invalid password for email {email_clean}")
            raise HTTPException(status_code=400, detail="Invalid email or password.")

        token = create_access_token(
            user["id"], user["email"], user["role"], user.get("full_name") or ""
        )
        logger.info(f"Login successful for email: {email_clean} (User ID: {user['id']})")
        return {
            "success": True,
            "token": token,
            "user": {
                "id": user["id"],
                "email": user["email"],
                "full_name": user["full_name"],
                "role": user["role"],
                "avatar_url": user["avatar_url"]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during login for email {email_clean}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Login failed. Please try again.") from e

@router.get("/api/auth/me")
def get_me(user_id: int = Depends(get_current_user_id)):
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
        "avatar_url": user["avatar_url"]
    }

@router.post("/api/auth/google/disconnect")
def disconnect_google(user_id: int = Depends(get_current_user_id)):
    try:
        delete_user_google_token(user_id)
        return {"success": True}
    except Exception as e:
        logger.error(f"Google disconnect failed for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Could not disconnect Google.") from e

@router.get("/auth/url")
async def get_google_auth_url(request: Request, user_id: int = Depends(get_current_user_id)):
    redirect_uri = get_effective_redirect_uri(request)
    return {"url": get_auth_url(redirect_uri=redirect_uri, user_id=user_id)}

@router.post("/auth/exchange")
async def exchange_google_code(request: AuthExchangeRequest, server_req: Request, user_id: int = Depends(get_current_user_id)):
    redirect_uri = get_effective_redirect_uri(server_req)
    result = exchange_code_for_token(request.code, redirect_uri=redirect_uri, user_id=user_id)
    return {"message": result}

@router.get("/auth/callback")
async def auth_callback(request: Request, code: str, state: str = None):
    redirect_uri = get_effective_redirect_uri(request)
    user_id = get_oauth_user_id(state)
    result = exchange_code_for_token(code, redirect_uri=redirect_uri, user_id=user_id, state=state)

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
                <p>{html.escape(result)}</p>
                <div class="close-hint">Please try starting the authentication process again.</div>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html_content, status_code=400)

@router.get("/auth/status")
def get_auth_status(user_id: int = Depends(get_current_user_id)):
    return {"authenticated": is_authenticated(user_id=user_id)}
