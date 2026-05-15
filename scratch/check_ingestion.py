import pandas as pd
import os


def load_from_google_sheets(self, sheet_url: str) -> pd.DataFrame:
        """
        Loads data from a Google Sheet using the gspread library and OAuth credentials.
        """
        import gspread
        import sys
        import os
        
        # Fast path: If it's a direct CSV export link, bypass OAuth and gspread
        if "export?format=csv" in sheet_url:
            import sys
            sys.stderr.write(f"Loading direct Google Sheets CSV export: {sheet_url}\n")
            df = pd.read_csv(sheet_url)
            sys.stderr.write(f"Successfully loaded {len(df)} rows directly via CSV export.\n")
            return df
            
        # Add parent directory to path to import google_auth
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from google_auth import get_google_credentials
        
        try:
            import sys
            sys.stderr.write("Authenticating with Google Sheets API...\n")
            creds = get_google_credentials()
            gc = gspread.authorize(creds)
            
            sys.stderr.write("Fetching real-time data using gspread...\n")
            sh = gc.open_by_url(sheet_url)
            worksheet = sh.get_worksheet(0) # Get the first sheet
            
            # get_all_records() returns a list of dictionaries
            data = worksheet.get_all_records()
            df = pd.DataFrame(data)
            
            sys.stderr.write(f"Successfully loaded {len(df)} rows securely via Google API.\n")
            return df
            
        except Exception as e:
            import sys
            sys.stderr.write(f"Error loading from Google Sheets via gspread: {repr(e)}\n")
            raise e


def main():
    df=load_from_google_sheets(self=None, sheet_url="https://docs.google.com/spreadsheets/d/1ctbJYuWtcmZb9c8JxUlZY7BiSbPlABgCwo6ZZt7sEGA/export?format=csv")
    print(df.head())
    
if __name__ == "__main__":
    main()