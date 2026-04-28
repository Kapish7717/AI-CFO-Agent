import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import os
from dotenv import load_dotenv
load_dotenv()
try:
    from groq import Groq
except ImportError:
    Groq = None

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")


class ReportGenerator:
    """
    Generates a comprehensive Business CFO PDF report summarizing financial spending, 
    revenue, profit, anomalies, and month-over-month comparisons.
    """
    def __init__(self, df: pd.DataFrame, output_path: str = "business_cfo_report.pdf"):
        self.df = df.copy()
        self.output_path = output_path
        self.styles = getSampleStyleSheet()
        self.elements = []
        
        # Custom styles
        self.styles.add(ParagraphStyle(name='SectionHeader', parent=self.styles['Heading1'], fontSize=18, textColor=colors.HexColor('#2980b9'), spaceBefore=20, spaceAfter=15))
        self.styles.add(ParagraphStyle(name='BannerTitle', parent=self.styles['Heading1'], fontSize=26, textColor=colors.HexColor('#2c3e50'), alignment=1, spaceAfter=25))
        self.styles.add(ParagraphStyle(name='AnomalyBanner', parent=self.styles['Heading2'], textColor=colors.HexColor('#c0392b')))
        
        if 'Type' not in self.df.columns:
            self.df['Type'] = 'Expense' # Fallback
            
        self.expenses = self.df[self.df['Type'] == 'Expense'].copy()
        self.revenue = self.df[self.df['Type'] == 'Revenue'].copy()

        if 'Severity' in self.df.columns:
            self.anomalies = self.df[self.df['Severity'] != 'Normal'].copy()
        else:
            self.anomalies = pd.DataFrame()
            
    def generate_llm_narrative(self) -> dict:
        if not Groq or not GROQ_API_KEY:
            return {
                "exec": "LLM narrative generation skipped. Please set GROQ_API_KEY.",
                "rev": "N/A", "exp": "N/A", "anom": "N/A", "rec": "N/A"
            }
            
        total_spend = self.expenses['Amount'].sum() if not self.expenses.empty else 0
        total_rev = self.revenue['Amount'].sum() if not self.revenue.empty else 0
        profit = total_rev - total_spend
        anomaly_count = len(self.anomalies)
        
        top_exp_cat = self.expenses.groupby('Category')['Amount'].sum().idxmax() if not self.expenses.empty else "None"
        top_rev_cat = self.revenue.groupby('Category')['Amount'].sum().idxmax() if not self.revenue.empty else "None"

        system_prompt = "You are an expert AI Business CFO (Chief Financial Officer). Your task is to provide a highly professional CFO: Executive report narrative."
        
        user_prompt = f"""
Analyze the following financial data.

DATA:
- Total Revenue: ${total_rev:,.2f}
- Total Expenses: ${total_spend:,.2f}
- Net Profit: ${profit:,.2f}
- Top Expense Category: {top_exp_cat}
- Top Revenue Source: {top_rev_cat}
- Anomalies Detected: {anomaly_count}

FORMAT REQUIREMENTS:
Return exactly 5 sections separated by exactly "|||". Do not use markdown headers or bold text. Write plain text paragraphs.
Section 1: Executive Summary (2-3 sentences on overall financial health).
|||
Section 2: Revenue Insights (2 sentences on revenue performance).
|||
Section 3: Expense Insights (2 sentences on spending performance).
|||
Section 4: Anomaly Explanation (2 sentences on the significance of the {anomaly_count} anomalies).
|||
Section 5: Conclusion & Recommendations (3 actionable CFO recommendations).
"""
        try:
            client = Groq(api_key=GROQ_API_KEY)
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                model="llama-3.3-70b-versatile",
                temperature=0.3,
                max_tokens=800
            )
            content = response.choices[0].message.content
            parts = content.split("|||")
            return {
                "exec": parts[0].strip() if len(parts) > 0 else "Error.",
                "rev": parts[1].strip() if len(parts) > 1 else "",
                "exp": parts[2].strip() if len(parts) > 2 else "",
                "anom": parts[3].strip() if len(parts) > 3 else "",
                "rec": parts[4].strip() if len(parts) > 4 else ""
            }
        except Exception as e:
            return {"exec": f"Error: {e}", "rev": "", "exp": "", "anom": "", "rec": ""}

    def generate_charts(self):
        charts = {}
        plt.style.use('bmh')

        # --- REVENUE CHARTS ---
        if not self.revenue.empty:
            # Rev Bar
            plt.figure(figsize=(7, 3.5))
            rev_cat = self.revenue.groupby('Category')['Amount'].sum().sort_values(ascending=False).head(5)
            rev_cat.plot(kind='bar', color='#2ecc71')
            plt.title('Top Revenue Streams', fontsize=12)
            plt.ylabel('Amount ($)')
            plt.xticks(rotation=0)
            plt.tight_layout()
            charts['rev_bar'] = 'rev_bar.png'
            plt.savefig(charts['rev_bar'], dpi=150)
            plt.close()

            # Rev Trend
            if not self.revenue['Date'].isna().all():
                plt.figure(figsize=(7, 3.5))
                rev_trend = self.revenue.set_index('Date').resample('ME')['Amount'].sum()
                rev_trend.plot(kind='line', marker='o', color='#27ae60', linewidth=2)
                plt.title('Monthly Revenue Trend', fontsize=12)
                plt.ylabel('Amount ($)')
                plt.xlabel('Month')
                plt.tight_layout()
                charts['rev_trend'] = 'rev_trend.png'
                plt.savefig(charts['rev_trend'], dpi=150)
                plt.close()

        # --- EXPENSE CHARTS ---
        if not self.expenses.empty:
            # Exp Bar
            plt.figure(figsize=(7, 3.5))
            exp_cat = self.expenses.groupby('Category')['Amount'].sum().sort_values(ascending=False).head(5)
            exp_cat.plot(kind='bar', color='#e74c3c')
            plt.title('Top Expense Categories', fontsize=12)
            plt.ylabel('Amount ($)')
            plt.xticks(rotation=0)
            plt.tight_layout()
            charts['exp_bar'] = 'exp_bar.png'
            plt.savefig(charts['exp_bar'], dpi=150)
            plt.close()

            # Exp Trend
            if not self.expenses['Date'].isna().all():
                plt.figure(figsize=(7, 3.5))
                exp_trend = self.expenses.set_index('Date').resample('ME')['Amount'].sum()
                exp_trend.plot(kind='line', marker='o', color='#c0392b', linewidth=2)
                plt.title('Monthly Expense Trend', fontsize=12)
                plt.ylabel('Amount ($)')
                plt.xlabel('Month')
                plt.tight_layout()
                charts['exp_trend'] = 'exp_trend.png'
                plt.savefig(charts['exp_trend'], dpi=150)
                plt.close()

        # --- COMPARISON CHARTS ---
        if not self.df.empty and not self.df['Date'].isna().all():
            plt.figure(figsize=(8, 4))
            exp_trend = self.expenses.set_index('Date').resample('ME')['Amount'].sum() if not self.expenses.empty else pd.Series(dtype=float)
            rev_trend = self.revenue.set_index('Date').resample('ME')['Amount'].sum() if not self.revenue.empty else pd.Series(dtype=float)
            
            trend_df = pd.DataFrame({'Revenue': rev_trend, 'Expense': exp_trend}).fillna(0)
            if not trend_df.empty:
                # Line
                ax = trend_df.plot(kind='line', marker='o', color=['#2ecc71', '#e74c3c'], linewidth=2)
                plt.title('Revenue vs Expense Comparison', fontsize=12)
                plt.ylabel('Amount ($)')
                plt.xlabel('Month')
                plt.grid(True, linestyle='--', alpha=0.7)
                plt.tight_layout()
                charts['comp_trend'] = 'comp_trend.png'
                handles, labels = ax.get_legend_handles_labels()
                if labels: ax.legend(handles, labels)
                plt.savefig(charts['comp_trend'], dpi=150)
                plt.close()

                # Profit Bar
                plt.figure(figsize=(8, 4))
                trend_df['Profit'] = trend_df['Revenue'] - trend_df['Expense']
                colors_bar = ['#2ecc71' if x >= 0 else '#e74c3c' for x in trend_df['Profit']]
                trend_df['Profit'].plot(kind='bar', color=colors_bar)
                plt.title('Monthly Net Profit Margin', fontsize=12)
                plt.ylabel('Amount ($)')
                plt.xlabel('Month')
                
                # Make x-axis labels nicer
                nice_labels = [d.strftime('%b %Y') for d in trend_df.index]
                plt.xticks(range(len(nice_labels)), nice_labels, rotation=45)
                
                plt.tight_layout()
                charts['profit_bar'] = 'profit_bar.png'
                plt.savefig(charts['profit_bar'], dpi=150)
                plt.close()

        return charts

    def build_kpi_cards(self):
        total_spend = self.expenses['Amount'].sum() if not self.expenses.empty else 0
        total_rev = self.revenue['Amount'].sum() if not self.revenue.empty else 0
        profit = total_rev - total_spend
        
        if not self.expenses.empty and not self.expenses['Date'].isna().all():
            monthly_exp = self.expenses.set_index('Date').resample('ME')['Amount'].sum()
            burn_rate = monthly_exp.mean() if not monthly_exp.empty else 0
        else:
            burn_rate = total_spend
        
        data = [[
            f"Gross Revenue\n${total_rev:,.2f}", 
            f"Total Expenses\n${total_spend:,.2f}", 
            f"Net Profit\n${profit:,.2f}", 
            f"Avg Burn Rate\n${burn_rate:,.2f}/mo"
        ]]
        
        t = Table(data, colWidths=[1.6*inch]*4)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#ecf0f1')),
            ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor('#2c3e50')),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
            ('FONTSIZE', (0,0), (-1,-1), 11),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.white),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#bdc3c7')),
            ('TOPPADDING', (0,0), (-1,-1), 15),
            ('BOTTOMPADDING', (0,0), (-1,-1), 15),
        ]))
        return t

    def build_summary_table(self, df_type):
        df_subset = self.revenue if df_type == 'Revenue' else self.expenses
        if df_subset.empty:
            return Paragraph(f"No {df_type} data available.", self.styles['Normal'])

        summary = df_subset.groupby('Category')['Amount'].agg(['sum', 'count', 'mean']).reset_index()
        summary = summary.sort_values('sum', ascending=False).head(5)
        
        table_data = [['Category', 'Total Amount', 'Count', 'Avg Amount']]
        for _, row in summary.iterrows():
            table_data.append([
                str(row['Category'])[:20],
                f"${row['sum']:,.2f}",
                str(int(row['count'])),
                f"${row['mean']:,.2f}"
            ])

        t = Table(table_data, colWidths=[140, 100, 60, 100])
        bg_color = '#27ae60' if df_type == 'Revenue' else '#c0392b'
        
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor(bg_color)),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
            ('ALIGN', (0,0), (0,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,0), 6),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f9f9f9')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#bdc3c7'))
        ]))
        return t

    def build_anomaly_table(self):
        if self.anomalies.empty:
            return Paragraph("No anomalies detected in this period.", self.styles['Normal'])

        def get_reason(row):
            r = []
            if row.get('Anomaly_ZScore', False): r.append("Z-Score")
            if row.get('Anomaly_IQR', False): r.append("IQR")
            if row.get('Anomaly_RuleBased', False): r.append("Rule-Based")
            return " + ".join(r) if r else "Unknown"

        self.anomalies['Reason'] = self.anomalies.apply(get_reason, axis=1)
        severity_order = {'Critical': 0, 'High': 1, 'Medium': 2, 'Normal': 3}
        sorted_anomalies = self.anomalies.sort_values(by=['Severity'], key=lambda x: x.map(severity_order)).head(15)

        table_data = [['Date', 'Type', 'Entity', 'Amount', 'Severity', 'Reason']]
        style_cmds = [
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#8e44ad')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,0), 6),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#bdc3c7'))
        ]

        for i, (_, row) in enumerate(sorted_anomalies.iterrows()):
            date_str = str(row['Date'].date()) if pd.notna(row['Date']) else ""
            table_data.append([
                date_str, 
                str(row.get('Type', '')),
                str(row.get('Entity', ''))[:15], 
                f"${row['Amount']:,.2f}", 
                str(row.get('Severity', '')), 
                str(row['Reason'])
            ])
            row_idx = i + 1
            if row['Severity'] == 'Critical':
                style_cmds.append(('BACKGROUND', (0, row_idx), (-1, row_idx), colors.HexColor('#ffcccc')))
            elif row['Severity'] == 'High':
                style_cmds.append(('BACKGROUND', (0, row_idx), (-1, row_idx), colors.HexColor('#ffe6cc')))

        t = Table(table_data, colWidths=[70, 60, 100, 70, 60, 110])
        t.setStyle(TableStyle(style_cmds))
        return t

    def generate_pdf(self):
        doc = SimpleDocTemplate(self.output_path, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
        narrative = self.generate_llm_narrative()
        charts = self.generate_charts()
        
        # --- 1. EXECUTIVE SUMMARY ---
        self.elements.append(Paragraph("BUSINESS CFO: EXECUTIVE REPORT", self.styles['BannerTitle']))
        self.elements.append(self.build_kpi_cards())
        self.elements.append(Spacer(1, 20))
        
        self.elements.append(Paragraph("Executive Summary", self.styles['Heading2']))
        self.elements.append(Paragraph(narrative["exec"].replace("\n", "<br/>"), self.styles['Normal']))
        self.elements.append(Spacer(1, 20))

        # --- 2. REVENUE ANALYSIS ---
        self.elements.append(Paragraph("1. Revenue Analysis", self.styles['SectionHeader']))
        if narrative["rev"]:
            self.elements.append(Paragraph(narrative["rev"].replace("\n", "<br/>"), self.styles['Normal']))
            self.elements.append(Spacer(1, 10))
            
        if 'rev_bar' in charts and 'rev_trend' in charts:
            img1 = Image(charts['rev_bar'], width=3.5*inch, height=1.75*inch)
            img2 = Image(charts['rev_trend'], width=3.5*inch, height=1.75*inch)
            self.elements.append(Table([[img1, img2]]))
            
        self.elements.append(Spacer(1, 15))
        self.elements.append(self.build_summary_table('Revenue'))
        
        self.elements.append(PageBreak())

        # --- 3. EXPENSE ANALYSIS ---
        self.elements.append(Paragraph("2. Expense Analysis", self.styles['SectionHeader']))
        if narrative["exp"]:
            self.elements.append(Paragraph(narrative["exp"].replace("\n", "<br/>"), self.styles['Normal']))
            self.elements.append(Spacer(1, 10))
            
        if 'exp_bar' in charts and 'exp_trend' in charts:
            img1 = Image(charts['exp_bar'], width=3.5*inch, height=1.75*inch)
            img2 = Image(charts['exp_trend'], width=3.5*inch, height=1.75*inch)
            self.elements.append(Table([[img1, img2]]))
            
        self.elements.append(Spacer(1, 15))
        self.elements.append(self.build_summary_table('Expense'))
        
        self.elements.append(Spacer(1, 20))

        # --- 4. PROFITABILITY & COMPARISON ---
        self.elements.append(Paragraph("3. Profitability & Comparative Analysis", self.styles['SectionHeader']))
        if 'comp_trend' in charts and 'profit_bar' in charts:
            self.elements.append(Image(charts['comp_trend'], width=7*inch, height=3.5*inch))
            self.elements.append(Spacer(1, 10))
            self.elements.append(Image(charts['profit_bar'], width=7*inch, height=3.5*inch))
            
        self.elements.append(PageBreak())

        # --- 5. ANOMALY DETECTION ---
        self.elements.append(Paragraph("4. Financial Anomalies", self.styles['SectionHeader']))
        self.elements.append(Paragraph(f"⚠️ {len(self.anomalies)} anomalies flagged for review.", self.styles['AnomalyBanner']))
        if narrative["anom"]:
            self.elements.append(Spacer(1, 5))
            self.elements.append(Paragraph(narrative["anom"].replace("\n", "<br/>"), self.styles['Normal']))
            
        self.elements.append(Spacer(1, 15))
        self.elements.append(self.build_anomaly_table())
        
        self.elements.append(Spacer(1, 25))

        # --- 6. CONCLUSION & RECOMMENDATIONS ---
        self.elements.append(Paragraph("5. Conclusion & Recommendations", self.styles['SectionHeader']))
        self.elements.append(Paragraph(narrative["rec"].replace("\n", "<br/>"), self.styles['Normal']))

        doc.build(self.elements)
        print(f"Executive Report successfully generated at: {self.output_path}")

        for chart_path in charts.values():
            if os.path.exists(chart_path):
                try: os.remove(chart_path)
                except: pass

if __name__ == "__main__":
    pass
