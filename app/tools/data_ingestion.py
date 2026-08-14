import os
import re
import sys
from datetime import date

import pandas as pd


class DataIngestion:
    """
    Handles ingestion of financial data from various sources like CSV, Excel,
    Google Sheets, and bank statement PDFs.
    """
    
    def __init__(self):
        pass

    # Date/amount regexes shared by the PDF parser
    DATE_RE = re.compile(r'\b(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})\b')
    AMOUNT_RE = re.compile(r'-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?')

    def load_from_pdf(self, file_path: str) -> pd.DataFrame:
        """
        Loads financial transaction data from a bank/credit-card statement PDF.

        Strategy:
          1. Try pdfplumber table extraction (best for structured statements).
          2. Fall back to line-by-line text parsing for unstructured layouts.

        Returns a DataFrame with Date, Entity (description), Amount, and
        Category columns. Amounts are signed (negative = outflow).
        """
        is_url = str(file_path).startswith("http")
        if not is_url and not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found at {file_path}")

        import pdfplumber

        records = []
        sys.stderr.write(f"Parsing PDF statement: {file_path}\n")

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                try:
                    tables = page.extract_tables()
                except Exception as e:
                    sys.stderr.write(f"PDF table extraction failed on a page: {e}\n")
                    tables = None

                if tables:
                    for table in tables:
                        for row in table:
                            cells = [str(c).replace("\n", " ").strip() if c else "" for c in row]
                            parsed = self._parse_table_row(cells)
                            if parsed:
                                records.append(parsed)
                else:
                    text = page.extract_text() or ""
                    for line in text.split("\n"):
                        parsed = self._parse_text_line(line)
                        if parsed:
                            records.append(parsed)

        if not records:
            raise ValueError(
                "No transactions could be parsed from the PDF. "
                "Make sure it is a bank statement with Date/Amount columns."
            )

        df = pd.DataFrame(records)
        sys.stderr.write(f"Successfully parsed {len(df)} transactions from PDF.\n")
        return df

    def _parse_table_row(self, cells) -> dict | None:
        """Parses a row extracted from a structured table."""
        text = " ".join(c for c in cells if c)
        if not text:
            return None

        date_match = self.DATE_RE.search(text)
        if not date_match:
            return None

        # In a structured row, the last numeric-looking cell is the amount.
        amounts = []
        for c in cells:
            cleaned = c.replace(",", "").replace("$", "").replace(" ", "")
            try:
                amounts.append(float(cleaned))
            except ValueError:
                continue

        if not amounts:
            return None

        amount = amounts[-1]
        # Description = non-numeric cells except the date cell.
        description = " ".join(
            c for c in cells
            if c and not self._is_number(c) and not self.DATE_RE.search(c)
        ).strip() or "Unknown"

        return {
            "Date": self._to_date_object(date_match.group(1)),
            "Entity": description,
            "Amount": float(amount),
            "Category": "Unknown",
            "Type": "Expense",
        }

    def _parse_text_line(self, line: str) -> dict | None:
        """
        Parses a plain statement line. Amounts are right-aligned, so the
        amount token is the last whitespace-delimited field that looks like a
        number (e.g. '12,500.00', '-3,200.00', '450.75').
        """
        line = line.strip()
        if not line:
            return None

        date_match = self.DATE_RE.search(line)
        if not date_match:
            return None

        tokens = line.split()
        amount_token = None
        # Find the LAST token that parses as a plain amount (no trailing sign chars).
        for tok in reversed(tokens):
            cleaned = tok.replace(",", "").replace("$", "").replace("+", "")
            try:
                val = float(cleaned)
                amount_token = val
                break
            except ValueError:
                continue

        if amount_token is None:
            return None

        # Description = everything between the date and the amount token.
        date_end = date_match.end()
        desc_text = line[date_end:]
        # Remove the trailing amount token from the description.
        for tok in reversed(tokens):
            if tok in desc_text and desc_text.rstrip().endswith(tok):
                desc_text = desc_text[: desc_text.rstrip().rfind(tok)].strip()
                break
        description = re.sub(r'\s+', " ", desc_text).strip(" |-") or "Unknown"

        return {
            "Date": self._to_date_object(date_match.group(1)),
            "Entity": description,
            "Amount": float(amount_token),
            "Category": "Unknown",
            "Type": "Expense",
        }

    def _is_number(self, val: str) -> bool:
        try:
            float(val.replace(",", "").replace("$", "").replace(" ", ""))
            return True
        except ValueError:
            return False

    def _to_date_object(self, date_str: str) -> date | None:
        """Converts a DD/MM/YYYY (or DD-MM-YYYY) date string to a date object."""
        parts = re.split(r'[/\-. ]', date_str.strip())
        if len(parts) != 3:
            return None
        day, month, year = parts
        if len(year) == 2:
            year = "20" + year
        try:
            return date(int(year), int(month), int(day))
        except ValueError:
            return None

    def load_from_csv(self, file_path: str) -> pd.DataFrame:
        """
        Loads financial data from a local CSV file or HTTP URL.
        
        Args:
            file_path (str): The path or URL to the CSV file.
            
        Returns:
            pd.DataFrame: A pandas DataFrame containing the loaded data.
        """
        is_url = str(file_path).startswith("http")
        if not is_url and not os.path.exists(file_path):
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
        Loads financial data from a local Excel file or HTTP URL.
        
        Args:
            file_path (str): The path or URL to the Excel file.
            
        Returns:
            pd.DataFrame: A pandas DataFrame containing the loaded data.
        """
        is_url = str(file_path).startswith("http")
        if not is_url and not os.path.exists(file_path):
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
        import sys

        import gspread
        
        # Fast path: If it's a direct CSV export link, bypass OAuth and gspread
        if "export?format=csv" in sheet_url:
            import sys
            sys.stderr.write(f"Loading direct Google Sheets CSV export: {sheet_url}\n")
            df = pd.read_csv(sheet_url)
            sys.stderr.write(f"Successfully loaded {len(df)} rows directly via CSV export.\n")
            return df
            
        from app.integrations.google_auth import get_google_credentials
        
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
