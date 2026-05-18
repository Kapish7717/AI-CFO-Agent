import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.style.use('bmh')
import numpy as np
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from langchain_groq import ChatGroq
import os
import json
import sys

GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")


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
        
        raw_key = os.environ.get("GROQ_API_KEY", "")
        api_key = raw_key.strip().strip('"').strip("'")

        if not api_key:
            sys.stderr.write("[REPORT GEN WARNING] No valid GROQ_API_KEY found. Skipping narrative.\n")
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

        system_prompt = "You are an expert AI Business CFO (Chief Financial Officer). Your task is to provide a highly professional CFO: Executive report narrative."

        user_prompt = f"""
Analyze the following financial data.

DATA:
- Total Revenue: ${total_rev:,.2f}
- Total Expenses: ${total_spend:,.2f}
- Burn Rate: ${burn_rate:,.2f}
- Net Profit: ${profit:,.2f}
- Top Expense Category: {top_exp_cat}
- Top Revenue Source: {top_rev_cat}
- Anomalies Detected: {anomaly_count}
- Month-wise Expenses: {monthly_exp_str}
- Month-wise Revenue: {monthly_rev_str}
- BUDGET BREACHES: {breach_summary}

{"USER SPECIFIC REQUEST: " + self.custom_instructions if self.custom_instructions else ""}

FORMAT REQUIREMENTS:
Return exactly 6 sections separated by exactly "|||". Do not use markdown headers or bold text. Write plain text paragraphs.

Section 1: Executive Summary (2-3 sentences on overall financial health).
|||
Section 2: Revenue Insights (2 sentences on revenue performance).
|||
Section 3: Expense Insights (2 sentences on spending performance).
|||
Section 4: Anomaly Explanation (2 sentences on the significance of the {anomaly_count} anomalies).
|||
Section 5: Conclusion & Recommendations (3 actionable CFO recommendations).
|||
Section 6: Custom Request Response (Directly address the USER SPECIFIC REQUEST above. If no request, just say "No custom request.")
"""
        try:
            # FORCE DISABLE TRACING for this internal tool call.
            # Stalling occurs because LangSmith's background threads can deadlock 
            # or fail to initialize correctly when called from within an MCP tool subprocess.
            original_tracing = os.environ.get("LANGCHAIN_TRACING_V2")
            os.environ["LANGCHAIN_TRACING_V2"] = "false"
            
            sys.stderr.write(f"[REPORT GEN] Calling Groq LLM ({GROQ_MODEL}) [Tracing: FORCED OFF]...\n")
            client = ChatGroq(
                model=GROQ_MODEL,
                temperature=0.3,
                groq_api_key=api_key,
                request_timeout=60.0
            )
            
            # Use invoke with empty callbacks as a double-safety
            response = client.invoke(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                config={"callbacks": []}
            )
            
            # Restore original tracing if it was set
            if original_tracing is not None:
                os.environ["LANGCHAIN_TRACING_V2"] = original_tracing
            else:
                del os.environ["LANGCHAIN_TRACING_V2"]
                
            content = response.content
            sys.stderr.write("[REPORT GEN] LLM narrative received.\n")
            parts = content.split("|||")

            return {
                "exec": parts[0].strip() if len(parts) > 0 else "Error.",
                "rev":  parts[1].strip() if len(parts) > 1 else "",
                "exp":  parts[2].strip() if len(parts) > 2 else "",
                "anom": parts[3].strip() if len(parts) > 3 else "",
                "rec":  parts[4].strip() if len(parts) > 4 else "",
                "custom": parts[5].strip() if len(parts) > 5 else ""
            }
        except Exception as e:
            sys.stderr.write(f"[REPORT GEN ERROR] Narrative generation failed: {e}\n")
            return {
                "exec": "Executive summary is currently unavailable due to a connection issue.",
                "rev": "Revenue streams are being processed.",
                "exp": "Expense categories are being analyzed.",
                "anom": "Anomalies have been flagged for manual review.",
                "rec": "Please review the raw data for specific recommendations.",
                "custom": "N/A"
            }

    def generate_charts(self):
        sys.stderr.write("[REPORT GEN] Starting chart generation...\n")
        charts = {}

        # --- REVENUE CHARTS ---
        if not self.revenue.empty:
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
            exp_trend = self.expenses.set_index('Date').resample('ME')['Amount'].sum() if not self.expenses.empty else pd.Series(dtype=float)
            rev_trend = self.revenue.set_index('Date').resample('ME')['Amount'].sum() if not self.revenue.empty else pd.Series(dtype=float)

            trend_df = pd.DataFrame({'Revenue': rev_trend, 'Expense': exp_trend}).fillna(0)
            
            # Remove months with absolutely no activity to prevent huge gaps in charts
            trend_df = trend_df[(trend_df['Revenue'] != 0) | (trend_df['Expense'] != 0)]

            if not trend_df.empty:
                plt.figure(figsize=(8, 4))
                ax = trend_df[['Revenue', 'Expense']].plot(kind='line', marker='o', color=['#2ecc71', '#e74c3c'], linewidth=2)
                plt.title('Revenue vs Expense Comparison', fontsize=12)
                plt.ylabel('Amount ($)')
                plt.xlabel('Month')
                plt.grid(True, linestyle='--', alpha=0.7)
                
                # Format X-axis labels nicely
                nice_labels = [d.strftime('%b %Y') for d in trend_df.index]
                plt.xticks(trend_df.index, nice_labels, rotation=45)
                
                plt.tight_layout()
                charts['comp_trend'] = 'comp_trend.png'
                handles, labels = ax.get_legend_handles_labels()
                if labels:
                    ax.legend(handles, labels)
                plt.savefig(charts['comp_trend'], dpi=150)
                plt.close()

                plt.figure(figsize=(8, 4))
                trend_df['Profit'] = trend_df['Revenue'] - trend_df['Expense']
                colors_bar = ['#2ecc71' if x >= 0 else '#e74c3c' for x in trend_df['Profit']]
                
                # Use range-based index for bar plot to prevent temporal spacing issues
                plt.bar(range(len(trend_df)), trend_df['Profit'], color=colors_bar)
                plt.title('Monthly Net Profit Margin', fontsize=12)
                plt.ylabel('Amount ($)')
                plt.xlabel('Month')
                nice_labels = [d.strftime('%b %Y') for d in trend_df.index]
                plt.xticks(range(len(nice_labels)), nice_labels, rotation=45)
                plt.grid(axis='y', linestyle='--', alpha=0.7)
                plt.tight_layout()
                charts['profit_bar'] = 'profit_bar.png'
                plt.savefig(charts['profit_bar'], dpi=150)
                plt.close()

        sys.stderr.write(f"[REPORT GEN] Generated {len(charts)} charts.\n")
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

        t = Table(data, colWidths=[1.6 * inch] * 4)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#ecf0f1')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2c3e50')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.white),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
            ('TOPPADDING', (0, 0), (-1, -1), 15),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
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
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(bg_color)),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f9f9f9')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7'))
        ]))
        return t

    def build_budget_summary_table(self):
        if not self.budget_breaches:
            return None

        table_data = [['Category', 'Limit', 'Actual', 'Overspend', '% Over']]
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e67e22')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#fef5e7'))
        ]

        for b in self.budget_breaches:
            # FIX BUG 3: safe .get() with fallbacks on all breach dict keys
            table_data.append([
                str(b.get('Category', 'Unknown')),
                f"${b.get('Limit', 0):,.2f}",
                f"${b.get('Actual', 0):,.2f}",
                f"${b.get('Overspend', 0):,.2f}",
                str(b.get('Percent_Over', 'N/A'))
            ])

        t = Table(table_data, colWidths=[140, 90, 90, 90, 70])
        t.setStyle(TableStyle(style_cmds))
        return t

    def build_anomaly_table(self):
        if self.anomalies.empty:
            return Paragraph("No anomalies detected in this period.", self.styles['Normal'])

        # FIX BUG 2: original code used row.get() on a pandas Series which raises
        # AttributeError when the column doesn't exist. Use 'in row.index' guard instead.
        def get_reason(row):
            r = []
            if 'Anomaly_ZScore' in row.index and row['Anomaly_ZScore']:
                r.append("Z-Score")
            if 'Anomaly_IQR' in row.index and row['Anomaly_IQR']:
                r.append("IQR")
            if 'Anomaly_RuleBased' in row.index and row['Anomaly_RuleBased']:
                r.append("Rule-Based")
            return " + ".join(r) if r else "Unknown"

        self.anomalies = self.anomalies.copy()
        self.anomalies['Reason'] = self.anomalies.apply(get_reason, axis=1)

        severity_order = {'Critical': 0, 'High': 1, 'Medium': 2, 'Normal': 3}
        sorted_anomalies = self.anomalies.sort_values(
            by=['Severity'],
            key=lambda x: x.map(lambda v: severity_order.get(v, 99))
        ).head(15)

        table_data = [['Date', 'Type', 'Entity', 'Amount', 'Severity', 'Reason']]
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8e44ad')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7'))
        ]

        for i, (_, row) in enumerate(sorted_anomalies.iterrows()):
            date_str = str(row['Date'].date()) if pd.notna(row['Date']) else "N/A"
            table_data.append([
                date_str,
                str(row.get('Type', '')),
                Paragraph(str(row.get('Entity', ''))[:30], self.styles['TableText']),
                f"${row['Amount']:,.2f}",
                str(row.get('Severity', '')),
                Paragraph(str(row['Reason']), self.styles['TableText'])
            ])
            row_idx = i + 1
            severity = row.get('Severity', '')
            if severity == 'Critical':
                style_cmds.append(('BACKGROUND', (0, row_idx), (-1, row_idx), colors.HexColor('#ffcccc')))
            elif severity == 'High':
                style_cmds.append(('BACKGROUND', (0, row_idx), (-1, row_idx), colors.HexColor('#ffe6cc')))

        t = Table(table_data, colWidths=[65, 55, 90, 75, 60, 175])
        t.setStyle(TableStyle(style_cmds))
        return t

    def build_monthly_revenue_table(self):
        """Builds a table showing total revenue for each month."""
        if self.revenue.empty:
            return None

        # Group by Month-Year
        df_monthly = self.revenue.copy()
        df_monthly['Month'] = df_monthly['Date'].dt.strftime('%b %Y')
        # Ensure we keep the temporal order
        df_monthly['Month_Sort'] = df_monthly['Date'].dt.to_period('M')
        
        table_data = [["Month", "Total Revenue", "Transaction Count", "Avg Transaction"]]
        
        grouped = df_monthly.groupby(['Month_Sort', 'Month'])['Amount'].agg(['sum', 'count', 'mean']).reset_index()
        grouped.sort_values('Month_Sort', inplace=True)
        
        for _, row in grouped.iterrows():
            table_data.append([
                row['Month'],
                f"${row['sum']:,.2f}",
                str(row['count']),
                f"${row['mean']:,.2f}"
            ])
            
        t = Table(table_data, colWidths=[120, 120, 120, 120])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2e7d32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ]))
        return t

    def generate_pdf(self):
        doc = SimpleDocTemplate(
            self.output_path, pagesize=letter,
            rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36
        )
        sys.stderr.write("[REPORT GEN] Starting PDF generation pipeline...\n")
        narrative = self.generate_llm_narrative()
        charts = self.generate_charts()
        sys.stderr.write("[REPORT GEN] Components ready. Building elements...\n")

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
            img1 = Image(charts['rev_bar'], width=3.5 * inch, height=1.75 * inch)
            img2 = Image(charts['rev_trend'], width=3.5 * inch, height=1.75 * inch)
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
            img1 = Image(charts['exp_bar'], width=3.5 * inch, height=1.75 * inch)
            img2 = Image(charts['exp_trend'], width=3.5 * inch, height=1.75 * inch)
            self.elements.append(Table([[img1, img2]]))

        self.elements.append(Spacer(1, 15))
        self.elements.append(self.build_summary_table('Expense'))
        self.elements.append(Spacer(1, 20))

        # --- 4. PROFITABILITY & COMPARISON ---
        self.elements.append(Paragraph("3. Profitability & Comparative Analysis", self.styles['SectionHeader']))
        if 'comp_trend' in charts and 'profit_bar' in charts:
            self.elements.append(Image(charts['comp_trend'], width=7 * inch, height=3.5 * inch))
            self.elements.append(Spacer(1, 10))
            self.elements.append(Image(charts['profit_bar'], width=7 * inch, height=3.5 * inch))

        self.elements.append(PageBreak())

        # --- 5. ANOMALY DETECTION ---
        self.elements.append(Paragraph("4. Financial Anomalies", self.styles['SectionHeader']))

        if self.budget_breaches:
            self.elements.append(Paragraph("Budget Breach Summary", self.styles['Heading2']))
            self.elements.append(Paragraph(
                "The following categories have exceeded their allocated budget limits.",
                self.styles['Normal']
            ))
            self.elements.append(Spacer(1, 10))
            breach_table = self.build_budget_summary_table()
            if breach_table:
                self.elements.append(breach_table)
            self.elements.append(Spacer(1, 20))

        if narrative["anom"]:
            self.elements.append(Paragraph("Anomaly Explanation", self.styles['Heading2']))
            self.elements.append(Paragraph(narrative["anom"].replace("\n", "<br/>"), self.styles['Normal']))
            self.elements.append(Spacer(1, 10))

        self.elements.append(Paragraph(
            f"{len(self.anomalies)} total anomalies flagged for review.",
            self.styles['AnomalyBanner']
        ))
        self.elements.append(Spacer(1, 15))
        self.elements.append(self.build_anomaly_table())
        self.elements.append(Spacer(1, 20))

        # --- 6. DETAILED MONTHLY REVENUE (Automatic Appendix) ---
        if not self.revenue.empty:
            self.elements.append(PageBreak())
            self.elements.append(Paragraph("Appendix: Month-Wise Revenue Breakdown", self.styles['SectionHeader']))
            self.elements.append(Paragraph(
                "The following table provides a detailed monthly breakdown of gross revenue performance for the period.",
                self.styles['Normal']
            ))
            self.elements.append(Spacer(1, 15))
            rev_table = self.build_monthly_revenue_table()
            if rev_table:
                self.elements.append(rev_table)
            self.elements.append(Spacer(1, 20))

        # --- 6. CONCLUSION & RECOMMENDATIONS ---
        self.elements.append(Paragraph("5. Conclusion & Recommendations", self.styles['SectionHeader']))
        self.elements.append(Paragraph(narrative["rec"].replace("\n", "<br/>"), self.styles['Normal']))

        if narrative.get("custom") and "No custom request" not in narrative["custom"]:
            self.elements.append(Spacer(1, 15))
            self.elements.append(Paragraph("6. Custom Insights", self.styles['SectionHeader']))
            self.elements.append(Paragraph(narrative["custom"].replace("\n", "<br/>"), self.styles['Normal']))

        # Build PDF
        try:
            sys.stderr.write(f"[REPORT GEN] Building PDF with {len(self.elements)} elements...\n")
            doc.build(self.elements)
            sys.stderr.write(f"[REPORT GEN] Executive Report successfully generated at: {self.output_path}\n")
        except Exception as e:
            sys.stderr.write(f"[REPORT GEN ERROR] Failed to build PDF: {e}\n")
            raise e

        # Cleanup temp chart files
        for chart_path in charts.values():
            if os.path.exists(chart_path):
                try:
                    os.remove(chart_path)
                except Exception:
                    pass


if __name__ == "__main__":
    pass