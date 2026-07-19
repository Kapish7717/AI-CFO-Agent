import os
import json
import sys
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# We added the spreadsheets.readonly scope for gspread
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]

TOKEN_PATH = "token.json"
CREDENTIALS_PATH = "credentials.json"

def get_db_token(user_id: int):
    """Loads token from PostgreSQL database."""
    try:
        from db.database import get_user_google_token
        return get_user_google_token(user_id)
    except Exception as e:
        sys.stderr.write(f"[AUTH DB ERROR] Failed to fetch token for user {user_id}: {e}\n")
        return None

def save_db_token(user_id: int, token_json_str: str):
    """Saves token to PostgreSQL database."""
    try:
        from db.database import save_user_google_token
        save_user_google_token(user_id, token_json_str)
    except Exception as e:
        sys.stderr.write(f"[AUTH DB ERROR] Failed to save token for user {user_id}: {e}\n")

def is_authenticated(user_id: int = None):
    """Checks if valid credentials already exist."""
    # 1. Try DB if user_id is provided
    if user_id is not None:
        token_json = get_db_token(user_id)
        if token_json:
            try:
                creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
                if creds and creds.valid:
                    return True
                if creds and creds.expired and creds.refresh_token:
                    return True  # Can be refreshed
            except Exception:
                pass
        return False

    # 2. Fallback to local token.json
    if not os.path.exists(TOKEN_PATH):
        return False
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        if creds and creds.valid:
            return True
        if creds and creds.expired and creds.refresh_token:
            return True # It can be refreshed
        return False
    except Exception:
        return False

def get_credentials_dict():
    """Load credentials from file or environment variable."""
    if os.path.exists(CREDENTIALS_PATH):
        try:
            with open(CREDENTIALS_PATH, 'r') as f:
                return json.load(f)
        except Exception as e:
            sys.stderr.write(f"[AUTH ERROR] Failed to read {CREDENTIALS_PATH}: {e}\n")
    
    # Check for Hugging Face Secret / Environment Variable
    env_creds = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if env_creds:
        try:
            # Strip potential quotes from Docker/HF env injection
            cleaned_env = env_creds.strip().strip('"').strip("'")
            return json.loads(cleaned_env)
        except Exception as e:
            sys.stderr.write(f"[AUTH ERROR] Failed to parse GOOGLE_CREDENTIALS_JSON: {e}\n")
    
    return None

def get_google_credentials(user_id: int = None):
    """
    Main entry point for tools.
    Returns credentials if available, otherwise raises Exception with instructions.
    """
    creds = None
    
    # 1. Try to load credentials for user_id from DB
    if user_id is not None:
        token_json = get_db_token(user_id)
        if token_json:
            try:
                creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
            except Exception as e:
                sys.stderr.write(f"[AUTH] Error reading DB token for user {user_id}: {e}\n")
    
    # 2. Fallback to token.json if no DB token or no user_id
    if not creds and os.path.exists(TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        except Exception as e:
            sys.stderr.write(f"[AUTH] Error reading local {TOKEN_PATH}: {e}\n")

    # 3. Check if token is valid or needs refresh
    if creds and creds.valid:
        return creds
        
    if creds and creds.expired and creds.refresh_token:
        try:
            sys.stderr.write(f"[AUTH] Refreshing expired Google token for user {user_id}...\n")
            creds.refresh(Request())
            # Save refreshed token to DB or local file
            if user_id is not None:
                save_db_token(user_id, creds.to_json())
            else:
                with open(TOKEN_PATH, "w") as token:
                    token.write(creds.to_json())
            return creds
        except Exception as e:
            sys.stderr.write(f"[AUTH ERROR] Token refresh failed: {e}\n")

    # 4. If no token, we need to authenticate
    creds_dict = get_credentials_dict()
    if not creds_dict:
        raise Exception("MISSING_CREDENTIALS: 'credentials.json' is missing and GOOGLE_CREDENTIALS_JSON secret is not set. You must provide your Google Client Configuration.")

    # In a cloud environment (Hugging Face / Kubernetes), we can't open a browser.
    # We must provide a URL and ask the user for a code manually.
    is_cloud = os.environ.get("HF_TOKEN") or os.environ.get("SPACE_ID") or os.environ.get("KUBERNETES_SERVICE_HOST")
    
    if is_cloud:
        # Check if the user is calling this via the tool flow or UI
        sys.stderr.write("[AUTH] Cloud environment detected. Manual code entry required.\n")
        raise Exception("AUTH_REQUIRED: Please authenticate via the 'Google Login' tab in the UI or use the 'authenticate_google' tool.")

    # Local fallback: This will automatically open a browser tab on the user's machine.
    try:
        sys.stderr.write("[AUTH] Local environment detected. Opening browser for login...\n")
        flow = InstalledAppFlow.from_client_config(creds_dict, SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
        if user_id is not None:
            save_db_token(user_id, creds.to_json())
        else:
            with open(TOKEN_PATH, "w") as token:
                token.write(creds.to_json())
        return creds
    except Exception as e:
        sys.stderr.write(f"[AUTH ERROR] Local flow failed: {e}\n")
        # If local flow fails (e.g. no display), fallback to returning the URL instructions
        raise Exception(f"AUTH_REQUIRED: Local browser flow failed. {e}")

# Global storage for the auth flow to handle PKCE (code_verifier)
_active_flows = {}
_oauth_user_ids = {}

def get_auth_url(redirect_uri='http://localhost', user_id: int = 1):
    """Returns a URL the user can visit to authorize the app."""
    creds_dict = get_credentials_dict()
    if not creds_dict:
        return "Error: No credentials found. Set GOOGLE_CREDENTIALS_JSON or upload credentials.json."
    
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(
        creds_dict, 
        SCOPES, 
        redirect_uri=redirect_uri
    )
    auth_url, state = flow.authorization_url(prompt='consent', access_type='offline')
    
    # Store the flow so we can use its code_verifier later during exchange
    _active_flows[state] = flow
    _oauth_user_ids[state] = user_id
    return auth_url

def get_oauth_user_id(state: str = None):
    """Resolves the user_id associated with an OAuth state parameter."""
    if state and state in _oauth_user_ids:
        return _oauth_user_ids[state]
    if _oauth_user_ids:
        return list(_oauth_user_ids.values())[-1]
    return 1

def exchange_code_for_token(code, redirect_uri='http://localhost', user_id: int = None):
    """Exchanges an authorization code for a token and saves it."""
    creds_dict = get_credentials_dict()
    if not creds_dict:
        return "Error: No credentials found."
        
    try:
        from google_auth_oauthlib.flow import Flow
        
        # Try to retrieve the flow that started this request to get the code_verifier
        flow = None
        if _active_flows:
            # For simplicity in this single-user app, we take the most recent flow
            state, flow = list(_active_flows.items())[-1]
        
        if not flow:
            flow = Flow.from_client_config(
                creds_dict, 
                SCOPES, 
                redirect_uri=redirect_uri
            )
            
        flow.fetch_token(code=code)
        creds = flow.credentials
        
        if user_id is not None:
            save_db_token(user_id, creds.to_json())
        else:
            with open(TOKEN_PATH, "w") as token:
                token.write(creds.to_json())
                
        return "Success! Token created. You can now use Google tools."
    except Exception as e:
        return f"Error: {e}"

def get_gmail_service(user_id: int = None):
    return build("gmail", "v1", credentials=get_google_credentials(user_id=user_id))

def get_calendar_service(user_id: int = None):
    return build("calendar", "v3", credentials=get_google_credentials(user_id=user_id))
