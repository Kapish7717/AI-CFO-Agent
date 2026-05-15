import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# We added the spreadsheets.readonly scope for gspread
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]

from googleapiclient.discovery import build

def get_google_credentials():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                # If refresh fails, fall back to new login
                os.remove("token.json")
                return get_google_credentials()
        else:
            if not os.path.exists("credentials.json"):
                raise FileNotFoundError("credentials.json is missing! Please download OAuth Client ID from Google Cloud Console.")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
            
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())
            
    return creds

def get_gmail_service():
    return build("gmail", "v1", credentials=get_google_credentials())

def get_calendar_service():
    return build("calendar", "v3", credentials=get_google_credentials())
