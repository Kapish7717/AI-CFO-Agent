import pandas as pd
import os

class DataIngestion:
    """
    Handles ingestion of financial data from various sources like CSV and Google Sheets.
    """
    
    def __init__(self):
        pass

    def load_from_csv(self, file_path: str) -> pd.DataFrame:
        """
        Loads financial data from a local CSV file.
        
        Args:
            file_path (str): The path to the CSV file.
            
        Returns:
            pd.DataFrame: A pandas DataFrame containing the loaded data.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"CSV file not found at {file_path}")
        
        try:
            # First, try reading normally
            df = pd.read_csv(file_path)
            
            # HEURISTIC: If the first row has many NaNs or just one non-null value, 
            # it might be a title row.
            if df.columns.str.contains('Unnamed').any() and df.iloc[0].count() <= 1:
                import sys
                sys.stderr.write(f"Detected potential title row in {file_path}. Skipping first row...\n")
                df = pd.read_csv(file_path, skiprows=1)
                
            import sys
            sys.stderr.write(f"Successfully loaded {len(df)} rows from {file_path}\n")
            return df
        except Exception as e:
            import sys
            sys.stderr.write(f"Error loading CSV: {e}\n")
            raise e

    def load_from_excel(self, file_path: str) -> pd.DataFrame:
        """
        Loads financial data from a local Excel file.
        
        Args:
            file_path (str): The path to the Excel file.
            
        Returns:
            pd.DataFrame: A pandas DataFrame containing the loaded data.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Excel file not found at {file_path}")
        
        try:
            df = pd.read_excel(file_path)
            import sys
            sys.stderr.write(f"Successfully loaded {len(df)} rows from {file_path}\n")
            return df
        except Exception as e:
            import sys
            sys.stderr.write(f"Error loading Excel file: {e}\n")
            raise e

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
            df['date'] = pd.to_datetime(df['date'], dayfirst=True, format='mixed', errors='coerce')
                
            sys.stderr.write(f"Successfully loaded {len(df)} rows securely via Google API.\n")
            return df
            
        except Exception as e:
            import sys
            import traceback
            sys.stderr.write(f"Error loading from Google Sheets via gspread: {repr(e)}\n")
            sys.stderr.write(f"TRACEBACK: {traceback.format_exc()}\n")
            raise e

# Example usage
# if __name__ == "__main__":
#     ingestor = DataIngestion()
#     df_exp = ingestor.load_from_google_sheets("https://docs.google.com/spreadsheets/d/19Cv2KbKm151bPkRrP-FpsfRAG74pntV-RZpuHskiKRU/edit?usp=sharing")
#     df_rev = ingestor.load_from_google_sheets("https://docs.google.com/spreadsheets/d/1T6bRfR-oSc20P_S8zHLgE-IBSN7TXr4o6CDF8ZL-w80/edit?usp=sharing")
#     print("Expenses Data:")
#     print(df_exp.head())
#     print("\nRevenue Data:")
#     print(df_rev.head())
#     print("Data Ingestion module ready.")
    
    # Example for CSV (uncomment and provide a valid path to test)
    # df_csv = ingestor.load_from_csv("path/to/your/financial_data.csv")
    # print(df_csv.head())
    
    # Example for Public Google Sheet (uncomment and provide a valid public sheet URL)
    # public_sheet_url = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit#gid=0"
    # df_sheets = ingestor.load_from_google_sheets(public_sheet_url)
    # print(df_sheets.head())
