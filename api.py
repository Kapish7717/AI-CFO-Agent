from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
import json
import asyncio
import os
import shutil
import pandas as pd
import sys
import logging
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from agent import graph
from google_auth import get_auth_url, exchange_code_for_token, is_authenticated, get_oauth_user_id

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("cfo_backend.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("cfo_backend_api")
logger.info("FastAPI Server logging initialized.")

app = FastAPI(title="AI CFO Agent API")

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize DB on startup
@app.on_event("startup")
def startup_event():
    from db.database import init_db
    try:
        logger.info("Initializing database on startup...")
        init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization failed during startup: {e}", exc_info=True)
        sys.stderr.write(f"[DB STARTUP ERROR] {e}\n")

# Pydantic Schemas
class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "Finance Head"

class LoginRequest(BaseModel):
    email: str
    password: str

class UserSettingsUpdate(BaseModel):
    budget_marketing: float = None
    budget_operations: float = None
    budget_travel: float = None
    expense_file_path: str = None
    expense_file_name: str = None
    expense_url: str = None
    revenue_file_path: str = None
    revenue_file_name: str = None
    revenue_url: str = None
    selected_month: str = None

class ChatRequest(BaseModel):
    prompt: str
    user_id: int = 1

class AuthExchangeRequest(BaseModel):
    code: str
    user_id: int = 1

# Auth endpoints
@app.post("/api/auth/register")
def register_user(req: RegisterRequest):
    from db.database import get_user_by_email, create_user
    logger.info(f"Registration request received for email: {req.email.strip().lower()}")
    if get_user_by_email(req.email):
        logger.warning(f"Registration failed: User with email {req.email} already exists.")
        raise HTTPException(status_code=400, detail="User with this email already exists.")
    try:
        user_id = create_user(req.email, req.password, req.full_name, req.role)
        logger.info(f"User registration successful. Created User ID: {user_id}")
        return {"success": True, "user_id": user_id}
    except Exception as e:
        logger.error(f"Error during registration for email {req.email}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/auth/login")
def login_user(req: LoginRequest):
    from db.database import get_user_by_email, verify_password
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
        
        logger.info(f"Login successful for email: {email_clean} (User ID: {user['id']})")
        return {
            "success": True,
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
        raise HTTPException(status_code=500, detail=f"Database or server error: {e}")

@app.get("/api/auth/me")
def get_me(user_id: int = 1):
    from db.database import get_user_by_id
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

@app.post("/api/auth/google/disconnect")
def disconnect_google(user_id: int = 1):
    from db.database import delete_user_google_token
    try:
        delete_user_google_token(user_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# User settings endpoints
@app.get("/api/user-settings")
def get_settings(user_id: int = 1):
    from db.database import get_user_settings
    settings = get_user_settings(user_id)
    # Convert Decimal/Numeric to float for JSON response
    return {
        "budget_marketing": float(settings["budget_marketing"]) if settings["budget_marketing"] else 5000.0,
        "budget_operations": float(settings["budget_operations"]) if settings["budget_operations"] else 8000.0,
        "budget_travel": float(settings["budget_travel"]) if settings["budget_travel"] else 2000.0,
        "expense_file_path": settings["expense_file_path"],
        "expense_file_name": settings["expense_file_name"],
        "expense_url": settings["expense_url"],
        "revenue_file_path": settings["revenue_file_path"],
        "revenue_file_name": settings["revenue_file_name"],
        "revenue_url": settings["revenue_url"],
        "selected_month": settings["selected_month"]
    }

@app.post("/api/user-settings")
def update_settings(updates: UserSettingsUpdate, user_id: int = 1):
    from db.database import update_user_settings
    try:
        update_user_settings(user_id, updates.dict(exclude_unset=True))
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Chat history endpoints
@app.get("/api/chat/history")
def get_chat_history(user_id: int = 1):
    from db.database import get_user_chat_history
    history = get_user_chat_history(user_id)
    if not history:
        return [
            {
                "sender": "agent",
                "text": "Hi! 👋 I've initialized your workspace.\nHow can I help you today?",
                "timestamp": "00:00:00"
            }
        ]
    return history

def get_user_state_paths(user_id: int):
    """Utility to get file paths segmented by user_id."""
    os.makedirs("uploads", exist_ok=True)
    if user_id is not None:
        state_file = f"uploads/financial_state_{user_id}.pkl"
        report_file = f"uploads/executive_cfo_report_{user_id}.pdf"
        breaches_file = f"uploads/budget_breaches_{user_id}.json"
    else:
        state_file = "current_financial_state.pkl"
        report_file = "executive_cfo_report.pdf"
        breaches_file = "budget_breaches.json"
    return state_file, report_file, breaches_file

# Stream endpoint
@app.post("/stream")
async def stream_chat(request: ChatRequest):
    async def event_generator():
        print(f"\n[API] Received request for User {request.user_id}: {request.prompt[:100]}...")
        # Save user message to database
        try:
            from db.database import save_user_chat_message
            save_user_chat_message(request.user_id, "user", request.prompt)
        except Exception as dbe:
            sys.stderr.write(f"[DB ERROR] Failed to save user msg: {dbe}\n")

        # Prep prompt with USER_ID context so agent passes it to tools
        full_prompt = f"USER_ID: {request.user_id}\n\n{request.prompt}"
        initial_state = {"messages": [("user", full_prompt)]}
        try:
            bot_response = ""
            async for s in graph.astream(initial_state, stream_mode="updates"):
                step_name = list(s.keys())[0]
                
                final_message = ""
                if "messages" in s[step_name] and s[step_name]["messages"]:
                    final_message = s[step_name]["messages"][-1].content
                    
                if step_name == "agent" and final_message:
                    bot_response = final_message
                    
                data = {
                    "step": step_name,
                    "message": final_message
                }
                yield f"data: {json.dumps(data)}\n\n"

            # Save agent response to database
            if bot_response:
                try:
                    from db.database import save_user_chat_message
                    save_user_chat_message(request.user_id, "agent", bot_response)
                except Exception as dbe:
                    sys.stderr.write(f"[DB ERROR] Failed to save bot response: {dbe}\n")

        except asyncio.CancelledError:
            print(f"[API] Request cancelled by client: {request.prompt[:50]}...")
            raise
        except Exception as e:
            print(f"[API ERROR] {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Integrations / Google OAuth
def get_effective_redirect_uri(request: Request) -> str:
    base_url = str(request.base_url).rstrip('/')
    # Check header or hostname for Hugging Face SSL proxy
    x_forwarded_proto = request.headers.get("x-forwarded-proto")
    if x_forwarded_proto == "https" and base_url.startswith("http://"):
        base_url = base_url.replace("http://", "https://", 1)
    elif "hf.space" in base_url and base_url.startswith("http://"):
        base_url = base_url.replace("http://", "https://", 1)
    return f"{base_url}/auth/callback"

@app.get("/auth/url")
async def get_google_auth_url(request: Request, user_id: int = 1):
    redirect_uri = get_effective_redirect_uri(request)
    return {"url": get_auth_url(redirect_uri=redirect_uri, user_id=user_id)}

@app.post("/auth/exchange")
async def exchange_google_code(request: AuthExchangeRequest, server_req: Request):
    redirect_uri = get_effective_redirect_uri(server_req)
    result = exchange_code_for_token(request.code, redirect_uri=redirect_uri, user_id=request.user_id)
    return {"message": result}

@app.get("/auth/callback")
async def auth_callback(request: Request, code: str, state: str = None):
    redirect_uri = get_effective_redirect_uri(request)
    user_id = get_oauth_user_id(state)
    result = exchange_code_for_token(code, redirect_uri=redirect_uri, user_id=user_id)

    
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
def get_auth_status(user_id: int = 1):
    return {"authenticated": is_authenticated(user_id=user_id)}

@app.get("/health")
def health_check():
    return {"status": "ok"}

# File uploads
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), user_id: int = 1, file_type: str = None):
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        # Prefix the filename with the user's ID to keep it isolated
        safe_name = f"{user_id}_{file.filename}"
        
        from db.storage import upload_to_storage, get_storage_client
        if get_storage_client():
            # Write to a temporary path, upload to Supabase, then clean up
            temp_path = os.path.join(UPLOAD_DIR, f"temp_{safe_name}")
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            cloud_path = f"uploads/{safe_name}"
            clean_path = upload_to_storage(temp_path, cloud_path)
            
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
        else:
            file_path = os.path.join(UPLOAD_DIR, safe_name)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            clean_path = os.path.abspath(file_path).replace("\\", "/")

        # Persist uploaded file paths to user settings
        if file_type in ("expense", "revenue"):
            from db.database import update_user_settings
            if file_type == "expense":
                update_user_settings(user_id, {
                    "expense_file_path": clean_path,
                    "expense_file_name": file.filename,
                })
            else:
                update_user_settings(user_id, {
                    "revenue_file_path": clean_path,
                    "revenue_file_name": file.filename,
                })

        return {"file_path": clean_path, "filename": file.filename}
    except Exception as e:
        return {"error": f"Failed to upload file: {str(e)}"}

def format_short_currency(val):
    sign = "-" if val < 0 else ""
    abs_val = abs(val)
    if abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:.2f}M"
    elif abs_val >= 1_000:
        return f"{sign}${abs_val / 1_000:.0f}K"
    else:
        return f"{sign}${abs_val:.2f}"

def get_selected_month_data_raw(df, month_str):
    df_m = df[df['MonthYear'] == month_str]
    if df_m.empty:
        return None
    exp = float(df_m[df_m['Type'] == 'Expense']['Amount'].sum())
    rev = float(df_m[df_m['Type'] == 'Revenue']['Amount'].sum())
    return {
        "exp": exp,
        "rev": rev,
        "prof": rev - exp,
        "margin": ((rev - exp) / rev * 100) if rev > 0 else 0.0
    }

@app.get("/api/dashboard/overview")
def get_dashboard_overview(month: str = None, user_id: int = 1):
    state_file, report_file, breaches_file = get_user_state_paths(user_id)
    
    # Try downloading budget breaches from Supabase Storage
    from db.storage import download_from_storage
    download_from_storage(f"breaches/budget_breaches_{user_id}.json", breaches_file)
    
    # Check settings for budget limits
    from db.database import get_user_settings, get_user_transactions
    settings = get_user_settings(user_id)
    
    # Query transactions from database
    rows = get_user_transactions(user_id)
    
    if not rows:
        return {
            "total_revenue": "$0.00",
            "total_expenses": "$0.00",
            "net_profit": "$0.00",
            "cash_balance": "$0.00",
            "revenue_trend": {"text": "0% vs last month", "color": "green", "is_positive": True},
            "expense_trend": {"text": "0% vs last month", "color": "red", "is_positive": True},
            "profit_trend": {"text": "0% vs last month", "color": "green", "is_positive": True},
            "cash_trend": {"text": "0% vs last month", "color": "green", "is_positive": True},
            "profit_margin": 0,
            "profit_margin_trend": {"text": "0% vs last month", "color": "green", "is_positive": True},
            "categories": [],
            "cash_inflow": "$0.00",
            "cash_outflow": "$0.00",
            "net_cash_flow": "$0.00",
            "recent_insights": [],
            "trend_data": [],
            "available_months": [],
            "selected_month": "",
            "date_range_label": "N/A",
            "last_sync": "Never",
            # Add database settings values
            "budget_marketing": float(settings["budget_marketing"]) if settings["budget_marketing"] else 5000.0,
            "budget_operations": float(settings["budget_operations"]) if settings["budget_operations"] else 8000.0,
            "budget_travel": float(settings["budget_travel"]) if settings["budget_travel"] else 2000.0,
        }
        
    try:
        df = pd.DataFrame(rows)
        df = df.sort_values('Date')
        
        df['MonthYear'] = df['Date'].dt.strftime('%b %Y')
        months = df['Date'].dt.strftime('%b %Y').dropna().unique().tolist()
        min_dates = df.groupby('MonthYear')['Date'].min()
        months = sorted(months, key=lambda m: min_dates.get(m, df['Date'].min()))
        
        if not month or month not in months:
            selected_month = months[-1] if months else ""
        else:
            selected_month = month
            
        if not selected_month:
            return {}

        df_month = df[df['MonthYear'] == selected_month].copy()
        
        exp_month = df_month[df_month['Type'] == 'Expense']
        rev_month = df_month[df_month['Type'] == 'Revenue']
        
        tot_exp = float(exp_month['Amount'].sum()) if not exp_month.empty else 0.0
        tot_rev = float(rev_month['Amount'].sum()) if not rev_month.empty else 0.0
        net_prof = float(tot_rev - tot_exp)
        
        cash_bal = float(net_prof + 1750000.0)
        margin = float((net_prof / tot_rev * 100) if tot_rev > 0 else 0.0)
        
        try:
            month_idx = months.index(selected_month)
            if month_idx > 0:
                prev_month = months[month_idx - 1]
                prev_d = get_selected_month_data_raw(df, prev_month)
                if prev_d:
                    rev_change = float(((tot_rev - prev_d['rev']) / prev_d['rev'] * 100) if prev_d['rev'] > 0 else 0.0)
                    exp_change = float(((tot_exp - prev_d['exp']) / prev_d['exp'] * 100) if prev_d['exp'] > 0 else 0.0)
                    prof_change = float(((net_prof - prev_d['prof']) / prev_d['prof'] * 100) if prev_d['prof'] > 0 else 0.0)
                    prev_cash = float(prev_d['prof'] + 1750000.0)
                    cash_change = float(((cash_bal - prev_cash) / prev_cash * 100) if prev_cash > 0 else 0.0)
                    margin_change = float(margin - prev_d['margin'])
                else:
                    rev_change = exp_change = prof_change = cash_change = margin_change = 0.0
            else:
                rev_change = exp_change = prof_change = cash_change = margin_change = 0.0
        except Exception:
            rev_change = exp_change = prof_change = cash_change = margin_change = 0.0
            
        def get_trend_str(diff):
            sign = "+" if diff >= 0 else "-"
            color = "green" if diff >= 0 else "red"
            return {
                "text": f"{sign}{abs(diff):.1f}% vs last month",
                "color": color,
                "is_positive": diff >= 0
            }
            
        def get_margin_trend_str(diff):
            sign = "+" if diff >= 0 else "-"
            color = "green" if diff >= 0 else "red"
            return {
                "text": f"{sign}{abs(diff):.1f}% vs last month",
                "color": color,
                "is_positive": diff >= 0
            }

        cat_breakdown = []
        if not exp_month.empty:
            cat_sum = exp_month.groupby('Category')['Amount'].sum().sort_values(ascending=False)
            total_cat_spend = float(cat_sum.sum())
            for cat, amt in cat_sum.items():
                pct = float((amt / total_cat_spend * 100) if total_cat_spend > 0 else 0.0)
                cat_breakdown.append({
                    "category": str(cat),
                    "amount": float(amt),
                    "amount_formatted": format_short_currency(amt),
                    "percent": round(pct, 1)
                })
        
        if len(cat_breakdown) > 5:
            top_cats = cat_breakdown[:4]
            other_amt = float(sum(c['amount'] for c in cat_breakdown[4:]))
            other_pct = float(sum(c['percent'] for c in cat_breakdown[4:]))
            top_cats.append({
                "category": "Others",
                "amount": other_amt,
                "amount_formatted": format_short_currency(other_amt),
                "percent": round(other_pct, 1)
            })
            cat_breakdown = top_cats

        trend_data = []
        if not df_month.empty and 'Date' in df_month.columns:
            daily = df_month.groupby(df_month['Date'].dt.date).agg(
                expenses=('Amount', lambda x: float(x[df_month.loc[x.index, 'Type'] == 'Expense'].sum())),
                revenue=('Amount', lambda x: float(x[df_month.loc[x.index, 'Type'] == 'Revenue'].sum()))
            ).sort_index()
            
            daily_list = list(daily.iterrows())
            n_days = len(daily_list)
            step = max(1, n_days // 5)
            sampled_indices = list(range(0, n_days, step))
            if (n_days - 1) not in sampled_indices:
                sampled_indices.append(n_days - 1)
            
            running_exp = 0.0
            running_rev = 0.0
            for idx, (date_obj, row) in enumerate(daily.iterrows()):
                running_exp += float(row['expenses'])
                running_rev += float(row['revenue'])
                if idx in sampled_indices:
                    date_str = date_obj.strftime('%b %d')
                    trend_data.append({
                        "date": date_str,
                        "revenue": float(running_rev),
                        "expenses": float(running_exp),
                        "net_profit": float(running_rev - running_exp)
                    })

        anomalies_count = len(df_month[df_month['Severity'] != 'Normal']) if 'Severity' in df_month.columns else 0
        insights = []
        
        if os.path.exists(breaches_file):
            try:
                with open(breaches_file, "r") as f:
                    breaches = json.load(f)
                for b in breaches:
                    try:
                        b_month_str = pd.to_datetime(b['Date']).strftime("%b %Y")
                    except:
                        b_month_str = "Unknown Date"
                    if b_month_str == selected_month:
                        insights.append(
                            f"⚠️ Budget Breach ({b_month_str}): {b['Category']} spent {format_short_currency(b['Actual'])} "
                            f"(Limit: {format_short_currency(b['Limit'])}) | Over by {format_short_currency(b['Overspend'])}."
                        )
            except Exception:
                pass

        if 'rev_change' in locals() and rev_change != 0:
            insights.append(f"Revenue has {'increased' if rev_change >= 0 else 'decreased'} by {abs(rev_change):.1f}% compared to last month.")
        else:
            insights.append(f"Revenue stands at {format_short_currency(tot_rev)} for the month.")
            
        if not exp_month.empty and 'exp_change' in locals() and exp_change != 0:
            insights.append(f"Operating expenses are {'up' if exp_change >= 0 else 'down'} by {abs(exp_change):.1f}% MoM.")
            
        insights.append(f"Your cash position is {'healthy' if net_prof >= 0 else 'under pressure'} with a net gain of {format_short_currency(net_prof)}.")
        if anomalies_count > 0:
            insights.append(f"Warning: {anomalies_count} financial anomalies flagged in this period.")

        last_sync = "Never"
        pdf_path = report_file
        # Try downloading report PDF from Supabase Storage to check its modification time
        download_from_storage(f"reports/executive_cfo_report_{user_id}.pdf", pdf_path)
        if os.path.exists(pdf_path):
            import time
            mod_time = os.path.getmtime(pdf_path)
            last_sync = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mod_time))
        elif df is not None and not df.empty:
            import time
            last_sync = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))

        try:
            min_d = df_month['Date'].min()
            max_d = df_month['Date'].max()
            date_range_str = f"{min_d.strftime('%b %d')} - {max_d.strftime('%b %d, %Y')}"
        except:
            date_range_str = selected_month
            
        return {
            "total_revenue": format_short_currency(tot_rev),
            "total_expenses": format_short_currency(tot_exp),
            "net_profit": format_short_currency(net_prof),
            "cash_balance": format_short_currency(cash_bal),
            "revenue_trend": get_trend_str(rev_change),
            "expense_trend": get_trend_str(exp_change),
            "profit_trend": get_trend_str(prof_change),
            "cash_trend": get_trend_str(cash_change),
            "profit_margin": float(round(margin, 1)),
            "profit_margin_trend": get_margin_trend_str(margin_change),
            "categories": cat_breakdown,
            "cash_inflow": format_short_currency(tot_rev),
            "cash_outflow": format_short_currency(tot_exp),
            "net_cash_flow": format_short_currency(net_prof),
            "recent_insights": insights,
            "trend_data": trend_data,
            "available_months": months[::-1],
            "selected_month": selected_month,
            "date_range_label": date_range_str,
            "last_sync": last_sync,
            # Pass configurations
            "budget_marketing": float(settings["budget_marketing"]) if settings["budget_marketing"] else 5000.0,
            "budget_operations": float(settings["budget_operations"]) if settings["budget_operations"] else 8000.0,
            "budget_travel": float(settings["budget_travel"]) if settings["budget_travel"] else 2000.0
        }
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }

@app.get("/api/download-report")
def download_report(user_id: int = 1):
    _, report_file, _ = get_user_state_paths(user_id)
    
    # Try downloading PDF report from Supabase Storage
    from db.storage import download_from_storage
    download_from_storage(f"reports/executive_cfo_report_{user_id}.pdf", report_file)
    
    if os.path.exists(report_file):
        return FileResponse(report_file, media_type="application/pdf", filename=os.path.basename(report_file))
    return {"error": "Report not found. Please run anomaly detection and generate the report first."}

# Serve React static files
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
frontend_dir = os.path.join(PROJECT_ROOT, "frontend", "dist")

@app.get("/arjun_profile.png")
async def serve_profile_image():
    profile_path = os.path.join(PROJECT_ROOT, "arjun_profile.png")
    if os.path.exists(profile_path):
        return FileResponse(profile_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Profile image not found")

if os.path.exists(frontend_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="assets")
    
    @app.get("/{fallback_path:path}")
    async def serve_frontend(fallback_path: str):
        local_file = os.path.join(frontend_dir, fallback_path)
        if fallback_path and os.path.exists(local_file) and os.path.isfile(local_file):
            return FileResponse(local_file)
        
        index_file = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return HTMLResponse(content="<h3>React Frontend Not Built Yet</h3><p>Please run npm run build inside the frontend folder.</p>", status_code=404)
