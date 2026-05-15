import pandas as pd
import os
import sys
import json
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from reportlab.lib.units import inch
from dotenv import load_dotenv

load_dotenv()

class ReportGenerator:
    """
    Generates a comprehensive Business CFO PDF report summarizing financial spending,
    revenue, profit, anomalies, and month-over-month comparisons.
    """
    def __init__(self, df: pd.DataFrame, output_path: str = "business_cfo_report.pdf", custom_instructions: str = ""):
        self.df = df.copy()
        self.output_path = output_path
        self.custom_instructions = custom_instructions
        self.styles = getSampleStyleSheet()
        self.elements = []

        # Custom styles
        self.styles.add(ParagraphStyle(name='SectionHeader', parent=self.styles['Heading1'], fontSize=18, textColor=colors.HexColor('#2980b9'), spaceBefore=20, spaceAfter=15))
        self.styles.add(ParagraphStyle(name='BannerTitle', parent=self.styles['Heading1'], fontSize=26, textColor=colors.HexColor('#2c3e50'), alignment=1, spaceAfter=25))
        self.styles.add(ParagraphStyle(name='AnomalyBanner', parent=self.styles['Heading2'], textColor=colors.HexColor('#c0392b')))
        self.styles.add(ParagraphStyle(name='TableText', parent=self.styles['Normal'], fontSize=9, leading=11))

        if 'Type' not in self.df.columns:
            self.df['Type'] = 'Expense'

        self.expenses = self.df[self.df['Type'] == 'Expense'].copy()
        self.revenue = self.df[self.df['Type'] == 'Revenue'].copy()

        if 'Severity' in self.df.columns:
            self.anomalies = self.df[self.df['Severity'] != 'Normal'].copy()
        else:
            self.anomalies = pd.DataFrame()

        # Load Budget Breaches
        self.budget_breaches = []
        BREACH_FILE = "budget_breaches.json"
        if os.path.exists(BREACH_FILE):
            try:
                with open(BREACH_FILE, "r") as f:
                    self.budget_breaches = json.load(f)
            except Exception:
                pass

    def generate_llm_narrative(self) -> dict:
        sys.stderr.write("[REPORT GEN] Starting LLM narrative generation...\n")
        if not os.environ.get("GROQ_API_KEY"):
            sys.stderr.write("[REPORT GEN WARNING] No GROQ_API_KEY found. Skipping narrative.\n")
            return {
                "exec": "LLM narrative generation skipped. GROQ_API_KEY missing.",
                "rev": "N/A", "exp": "N/A", "anom": "N/A", "rec": "N/A", "custom": "N/A"
            }

        total_spend = self.expenses['Amount'].sum() if not self.expenses.empty else 0
        total_rev = self.revenue['Amount'].sum() if not self.revenue.empty else 0
        burn_rate = total_spend - total_rev
        profit = total_rev - total_spend
        anomaly_count = len(self.anomalies)

        top_exp_cat = self.expenses.groupby('Category')['Amount'].sum().idxmax() if not self.expenses.empty else "None"
        top_rev_cat = self.revenue.groupby('Category')['Amount'].sum().idxmax() if not self.revenue.empty else "None"

        monthly_exp_str = "None"
        monthly_rev_str = "None"
        if not self.expenses.empty and not self.expenses['Date'].isna().all():
            m_exp = self.expenses.groupby(self.expenses['Date'].dt.to_period('M'))['Amount'].sum()
            monthly_exp_str = ", ".join([f"{d.strftime('%b %Y')}: ${v:,.2f}" for d, v in m_exp.items()])
        if not self.revenue.empty and not self.revenue['Date'].isna().all():
            m_rev = self.revenue.groupby(self.revenue['Date'].dt.to_period('M'))['Amount'].sum()
            monthly_rev_str = ", ".join([f"{d.strftime('%b %Y')}: ${v:,.2f}" for d, v in m_rev.items()])

        # FIX BUG 3: safe .get() access on budget breach dicts
        breach_summary = ", ".join([
            f"{b.get('Category', '?')} (+{b.get('Percent_Over', 'N/A')})"
            for b in self.budget_breaches
        ]) if self.budget_breaches else "None"
        
        print("\n--- TEST NARRATIVE CONTEXT ---")
        print(f"Total Rev: {total_rev}")
        print(f"Total Exp: {total_spend}")
        print(f"Monthly Rev: {monthly_rev_str}")
        return {"exec": "Testing mode active."}

def test_standalone():
    # Check if a CSV was passed as an argument
    if len(sys.argv) > 1 and sys.argv[1].endswith('.csv'):
        print(f"Loading data from CSV: {sys.argv[1]}")
        df = pd.read_csv(sys.argv[1])
        # Add basic columns if missing for testing
        if 'Type' not in df.columns:
            df['Type'] = 'Revenue' if 'revenue' in str(sys.argv[1]).lower() else 'Expense'
        if 'Amount' not in df.columns:
            # Map common names
            if 'revenue' in df.columns: df.rename(columns={'revenue': 'Amount'}, inplace=True)
            elif 'amount' in df.columns: df.rename(columns={'amount': 'Amount'}, inplace=True)
        if 'Date' not in df.columns:
            if 'date' in df.columns: df.rename(columns={'date': 'Date'}, inplace=True)
        
        # Ensure Date is datetime
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'])
    else:
        STATE_FILE = "current_financial_state.pkl"
        if os.path.exists(STATE_FILE):
            print(f"Loading data from existing state: {STATE_FILE}")
            df = pd.read_pickle(STATE_FILE)
        else:
            print("No state found. Using dummy data.")
            df = pd.DataFrame({
                'Date': pd.to_datetime(['2025-01-01', '2025-02-01']),
                'Amount': [5000, 7000],
                'Category': ['Sales', 'Sales'],
                'Type': ['Revenue', 'Revenue']
            })
    
    rg = ReportGenerator(df)
    rg.generate_llm_narrative()
    print("\nStandalone test completed successfully.")

if __name__ == "__main__":
    test_standalone()
