import json
import logging
import os
import time

import pandas as pd
from fastapi import APIRouter, Depends

from app.agents.mcp_server import get_user_state_paths
from app.core.config import get_settings
from app.core.security import get_current_user_id
from app.db.database import get_user_settings, get_user_transactions
from app.db.storage import download_from_storage

router = APIRouter()
logger = logging.getLogger("backend.api.dashboard")

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

@router.get("/api/dashboard/overview")
def get_dashboard_overview(month: str = None, user_id: int = Depends(get_current_user_id)):
    state_file, report_file, breaches_file = get_user_state_paths(user_id)
    cash_base = get_settings().CASH_BASE_AMOUNT
    
    # Try downloading budget breaches from Supabase Storage
    try:
        download_from_storage(f"breaches/budget_breaches_{user_id}.json", breaches_file)
    except Exception:
        pass
    
    # Check settings for budget limits
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
        
        cash_bal = float(net_prof + cash_base)
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
                    prev_cash = float(prev_d['prof'] + cash_base)
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
        
        if len(cat_breakdown) > 10:
            top_cats = cat_breakdown[:9]
            other_amt = float(sum(c['amount'] for c in cat_breakdown[9:]))
            other_pct = float(sum(c['percent'] for c in cat_breakdown[9:]))
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
                with open(breaches_file) as f:
                    breaches = json.load(f)
                for b in breaches:
                    try:
                        b_month_str = pd.to_datetime(b['Date']).strftime("%b %Y")
                    except Exception:
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
        try:
            download_from_storage(f"reports/executive_cfo_report_{user_id}.pdf", pdf_path)
        except Exception:
            pass
        if os.path.exists(pdf_path):
            mod_time = os.path.getmtime(pdf_path)
            last_sync = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mod_time))
        elif df is not None and not df.empty:
            last_sync = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))

        try:
            min_d = df_month['Date'].min()
            max_d = df_month['Date'].max()
            date_range_str = f"{min_d.strftime('%b %d')} - {max_d.strftime('%b %d, %Y')}"
        except Exception:
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
            "budget_marketing": float(settings.get("budget_marketing")) if settings and settings.get("budget_marketing") is not None else 5000.0,
            "budget_operations": float(settings.get("budget_operations")) if settings and settings.get("budget_operations") is not None else 8000.0,
            "budget_travel": float(settings.get("budget_travel")) if settings and settings.get("budget_travel") is not None else 2000.0
        }
    except Exception as e:
        logger.warning("Dashboard overview failed for user %s: %s", user_id, e, exc_info=True)
        return {"error": str(e)}
