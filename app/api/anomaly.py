
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import get_current_user_id
from app.db.database import get_user_transactions, update_transaction_anomalies
from app.tools.anomaly_detection import detect_all_anomalies

router = APIRouter()

class AnomalyRequest(BaseModel):
    budget_limits: dict[str, float] | None = None

@router.post("/api/v1/anomaly")
def detect_anomaly(payload: AnomalyRequest, user_id: int = Depends(get_current_user_id)):
    rows = get_user_transactions(user_id)
    if not rows:
        raise HTTPException(status_code=400, detail="No transactions found for the user.")

    df = pd.DataFrame(rows)
    analyzed = detect_all_anomalies(df, budget_limits=payload.budget_limits)
    update_transaction_anomalies(user_id, analyzed.to_dict("records"))

    return {
        "success": True,
        "anomaly_count": int((analyzed['Is_Anomaly']).sum()) if 'Is_Anomaly' in analyzed else 0,
        "high_severity_count": int((analyzed['Severity'] == 'High').sum()) if 'Severity' in analyzed else 0,
    }