import pandas as pd

from app.tools.anomaly_detection import (
    detect_all_anomalies,
    detect_budget_breaches,
    detect_iqr_anomalies,
    detect_rule_based,
    detect_zscore_anomalies,
)


def test_detect_zscore_anomalies():
    # Z-score requires a dataset with an extreme outlier
    # 9 normal values of 10.0 and 1 huge outlier of 1000.0
    df = pd.DataFrame({
        "Amount": [10.0] * 9 + [1000.0],
        "Type": ["Expense"] * 10
    })

    df_result = detect_zscore_anomalies(df, column="Amount", threshold=2.0)
    
    assert "Anomaly_ZScore" in df_result.columns
    # The last element should be flagged as an anomaly
    assert bool(df_result.iloc[-1]["Anomaly_ZScore"]) is True
    # The normal elements should not be flagged
    assert bool(df_result.iloc[0]["Anomaly_ZScore"]) is False


def test_detect_iqr_anomalies():
    # IQR flags values outside Q1 - 1.5*IQR and Q3 + 1.5*IQR
    # Let's create values where Q1=10, Q3=20 -> IQR=10 -> Upper bound = 35
    df = pd.DataFrame({
        "Amount": [10.0, 12.0, 15.0, 18.0, 20.0, 100.0],
        "Type": ["Expense"] * 6
    })

    df_result = detect_iqr_anomalies(df, column="Amount")

    assert "Anomaly_IQR" in df_result.columns
    # 100.0 is way above upper bound (35)
    assert bool(df_result.iloc[-1]["Anomaly_IQR"]) is True
    # 15.0 is normal
    assert bool(df_result.iloc[2]["Anomaly_IQR"]) is False


def test_detect_rule_based_duplicates():
    # Test duplicate detection
    dates = pd.to_datetime(["2026-05-23", "2026-05-23", "2026-05-24"])
    df = pd.DataFrame({
        "Date": dates,
        "Entity": ["Google Ads", "Google Ads", "GitHub"],
        "Amount": [1500.0, 1500.0, 250.0],
        "Type": ["Expense", "Expense", "Expense"]
    })

    df_result = detect_rule_based(df)
    
    assert "is_duplicate" in df_result.columns
    # The first two are identical duplicates on the same day
    assert bool(df_result.iloc[0]["is_duplicate"]) is True
    assert bool(df_result.iloc[1]["is_duplicate"]) is True
    # The third one is not a duplicate
    assert bool(df_result.iloc[2]["is_duplicate"]) is False


def test_detect_rule_based_large_amount():
    # Test large amount (>2x average of Type)
    df = pd.DataFrame({
        "Entity": ["Vendor"] * 5,
        "Amount": [10.0, 10.0, 10.0, 10.0, 100.0],  # average = 28, 2x average = 56
        "Type": ["Expense"] * 5,
        "Date": pd.to_datetime(["2026-05-23"] * 5)
    })

    df_result = detect_rule_based(df)
    
    assert "is_large_amount" in df_result.columns
    # 100 is > 56, so flagged
    assert bool(df_result.iloc[-1]["is_large_amount"]) is True
    # 10 is normal
    assert bool(df_result.iloc[0]["is_large_amount"]) is False


def test_detect_rule_based_mom_spikes():
    # Test MoM spikes (>2x previous month for same entity and type)
    dates = pd.to_datetime([
        "2026-04-10", "2026-04-20",  # April: total 300 for Vendor A
        "2026-05-10", "2026-05-15"   # May: total 1000 for Vendor A (>2x of April's 300)
    ])
    df = pd.DataFrame({
        "Date": dates,
        "Entity": ["Vendor A", "Vendor A", "Vendor A", "Vendor A"],
        "Amount": [150.0, 150.0, 500.0, 500.0],
        "Type": ["Expense"] * 4
    })

    df_result = detect_rule_based(df)
    
    assert "is_mom_anomaly" in df_result.columns
    # May records should be flagged as MoM spikes
    assert bool(df_result.iloc[2]["is_mom_anomaly"]) is True
    assert bool(df_result.iloc[3]["is_mom_anomaly"]) is True
    # April records should not be flagged (no previous month data to trigger >2x)
    assert bool(df_result.iloc[0]["is_mom_anomaly"]) is False


def test_detect_budget_breaches():
    df = pd.DataFrame({
        "Date": pd.to_datetime(["2026-05-10", "2026-05-12", "2026-05-15", "2026-05-20"]),
        "Category": ["Marketing", "Marketing", "Software", "Travel"],
        "Amount": [600.0, 500.0, 250.0, 100.0],  # Marketing total = 1100, Software = 250
        "Type": ["Expense", "Expense", "Expense", "Expense"]
    })

    # Limit for Marketing is 1000 (exceeded), limit for Software is 500 (not exceeded)
    budget_limits = {
        "Marketing": 1000.0,
        "Software": 500.0
    }

    df_result = detect_budget_breaches(df, budget_limits=budget_limits)

    assert "Is_Budget_Breach" in df_result.columns
    # Marketing rows should be marked as breach
    assert bool(df_result.iloc[0]["Is_Budget_Breach"]) is True
    assert bool(df_result.iloc[1]["Is_Budget_Breach"]) is True
    assert df_result.iloc[0]["Limit"] == 1000.0
    assert df_result.iloc[0]["Actual"] == 1100.0
    assert df_result.iloc[0]["Overspend"] == 100.0
    assert df_result.iloc[0]["Percent_Over"] == "10.0%"

    # Software and Travel should not be breach
    assert bool(df_result.iloc[2]["Is_Budget_Breach"]) is False
    assert bool(df_result.iloc[3]["Is_Budget_Breach"]) is False


def test_detect_all_anomalies_and_severity():
    # Let's verify master method that combines everything and assigns severity
    dates = pd.to_datetime(["2026-05-23"] * 6)
    df = pd.DataFrame({
        "Date": dates,
        "Category": ["Marketing", "Marketing", "Software", "Travel", "Software", "Software"],
        # Marketing total = 2200 (exceeds budget 2000)
        # We also have duplicates for Software (same Date, Entity, Amount, Type)
        # We also have an extreme amount outlier (10000.0) for Software
        "Entity": ["Google Ads", "Google Ads", "GitHub", "Uber", "GitHub", "GitHub"],
        "Amount": [1200.0, 1000.0, 250.0, 50.0, 250.0, 10000.0],
        "Type": ["Expense"] * 6
    })

    budget_limits = {
        "Marketing": 2000.0
    }

    df_result = detect_all_anomalies(df, budget_limits=budget_limits)

    assert "Is_Anomaly" in df_result.columns
    assert "Severity" in df_result.columns

    # 1. Marketing should have budget breach and High/Critical severity
    assert bool(df_result.iloc[0]["Is_Budget_Breach"]) is True
    assert df_result.iloc[0]["Severity"] in ["High", "Critical"]

    # 2. Software duplicates (GitHub 250) should be rule-flagged
    assert bool(df_result.iloc[2]["is_duplicate"]) is True
    assert bool(df_result.iloc[2]["Is_Anomaly"]) is True

    # 3. Extreme outlier (10000.0) should be IQR and Rule-Based flagged (High/Critical)
    assert bool(df_result.iloc[5]["Anomaly_IQR"]) is True
    assert bool(df_result.iloc[5]["Anomaly_RuleBased"]) is True
    assert df_result.iloc[5]["Severity"] in ["High", "Critical"]

    # 4. Uber (50.0) is normal and should be normal
    assert bool(df_result.iloc[3]["Is_Anomaly"]) is False
    assert df_result.iloc[3]["Severity"] == "Normal"
