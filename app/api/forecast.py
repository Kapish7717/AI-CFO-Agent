import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import get_current_user_id
from app.db.database import get_user_transactions

router = APIRouter()

class ForecastRequest(BaseModel):
    months: int = 3

@router.post("/api/v1/forecast")
def forecast(payload: ForecastRequest, user_id: int = Depends(get_current_user_id)):
    rows = get_user_transactions(user_id)
    if not rows:
        raise HTTPException(status_code=400, detail="No transactions found for forecasting.")

    df = pd.DataFrame(rows)
    if df.empty:
        raise HTTPException(status_code=400, detail="No transactions available.")

    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
    df = df.sort_values('Date')

    if df['Date'].isna().all():
        raise HTTPException(status_code=400, detail="Unable to parse dates for forecasting.")

    monthly = df.groupby(df['Date'].dt.to_period('M')).agg(
        revenue=('Amount', lambda x: float(x[df.loc[x.index, 'Type'] == 'Revenue'].sum())),
        expenses=('Amount', lambda x: float(x[df.loc[x.index, 'Type'] == 'Expense'].sum()))
    ).reset_index()

    monthly['revenue'] = monthly['revenue'].fillna(0.0)
    monthly['expenses'] = monthly['expenses'].fillna(0.0)

    if len(monthly) < 2:
        raise HTTPException(status_code=400, detail="Need at least two months of data to forecast.")

    monthly['net'] = monthly['revenue'] - monthly['expenses']
    monthly['revenue_diff'] = monthly['revenue'].diff().fillna(0)
    monthly['expenses_diff'] = monthly['expenses'].diff().fillna(0)

    avg_rev_growth = float(monthly['revenue_diff'].mean())
    avg_exp_growth = float(monthly['expenses_diff'].mean())
    last_month = monthly.iloc[-1]

    forecasted = []
    last_revenue = float(last_month['revenue'])
    last_expenses = float(last_month['expenses'])

    for i in range(payload.months):
        last_revenue += avg_rev_growth
        last_expenses += avg_exp_growth
        forecasted.append({
            "month": f"+{i+1}",
            "projected_revenue": max(last_revenue, 0.0),
            "projected_expenses": max(last_expenses, 0.0),
            "projected_net": max(last_revenue - last_expenses, 0.0),
        })

    return {
        "success": True,
        "forecast": forecasted,
    }