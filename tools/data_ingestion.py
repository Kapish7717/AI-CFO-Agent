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
            df = pd.read_csv(file_path)
            print(f"Successfully loaded {len(df)} rows from {file_path}")
            return df
        except Exception as e:
            print(f"Error loading CSV: {e}")
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
            print(f"Successfully loaded {len(df)} rows from {file_path}")
            return df
        except Exception as e:
            print(f"Error loading Excel file: {e}")
            raise e

    def load_from_google_sheets(self, sheet_url: str) -> pd.DataFrame:
        """
        Loads data from a public Google Sheet using its URL.
        
        Note: For private sheets, a library like `gspread` and service account 
        credentials would be required. This method relies on the sheet being 
        publicly viewable and uses pandas to read the export URL.
        
        Args:
            sheet_url (str): The URL of the Google Sheet.
            
        Returns:
            pd.DataFrame: A pandas DataFrame containing the loaded data.
        """
        try:
            # Convert the regular Google Sheets URL to an export CSV URL
            if "edit#gid=" in sheet_url:
                csv_url = sheet_url.replace("edit#gid=", "export?format=csv&gid=")
            elif "edit?usp=sharing" in sheet_url:
                 csv_url = sheet_url.replace("edit?usp=sharing", "export?format=csv")
            elif "edit" in sheet_url:
                csv_url = sheet_url.replace("edit", "export?format=csv")
            else:
                 csv_url = sheet_url # Assume it's already an export link or handled by pandas
            
            df = pd.read_csv(csv_url)
            print(f"Successfully loaded {len(df)} rows from Google Sheets")
            return df
        except Exception as e:
            print(f"Error loading from Google Sheets: {e}")
            print("Note: Ensure the Google Sheet is set to 'Anyone with the link can view' for this simple method.")
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
