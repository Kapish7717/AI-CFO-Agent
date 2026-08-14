from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.db.database import strip_transaction_record
from app.db.unified_store import strip_unified_transaction
from app.tools.data_ingestion import DataIngestion


def test_load_from_csv_normal(tmp_path):
    # Create a temporary normal CSV file
    csv_file = tmp_path / "normal_data.csv"
    data = "Date,Category,Amount,Entity\n23-05-2026,Marketing,1500.0,Google Ads\n24-05-2026,Software,250.0,GitHub"
    csv_file.write_text(data)

    ingestor = DataIngestion()
    df = ingestor.load_from_csv(str(csv_file))

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == ["Date", "Category", "Amount", "Entity"]
    assert df.iloc[0]["Category"] == "Marketing"
    assert float(df.iloc[0]["Amount"]) == 1500.0


def test_load_from_csv_with_title_row(tmp_path):
    # Create a temporary CSV file with a title row and an empty row to trigger heuristic (df.iloc[0].count() <= 1)
    csv_file = tmp_path / "title_data.csv"
    data = "My Financial Report,Unnamed: 1,Unnamed: 2,Unnamed: 3\n,,,\nDate,Category,Amount,Entity\n23-05-2026,Marketing,1500.0,Google Ads"
    csv_file.write_text(data)

    ingestor = DataIngestion()
    df = ingestor.load_from_csv(str(csv_file))

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert "Unnamed" in df.columns[0]


def test_load_from_csv_file_not_found():
    ingestor = DataIngestion()
    with pytest.raises(FileNotFoundError):
        ingestor.load_from_csv("non_existent_file.csv")


def test_load_from_excel_file_not_found():
    ingestor = DataIngestion()
    with pytest.raises(FileNotFoundError):
        ingestor.load_from_excel("non_existent_file.xlsx")


def test_load_from_excel_normal(tmp_path):
    # Create a temporary normal Excel file using pandas
    excel_file = tmp_path / "normal_data.xlsx"
    df_expected = pd.DataFrame({
        "Date": ["23-05-2026"],
        "Category": ["Marketing"],
        "Amount": [1500.0],
        "Entity": ["Google Ads"]
    })
    df_expected.to_excel(str(excel_file), index=False)

    ingestor = DataIngestion()
    df = ingestor.load_from_excel(str(excel_file))

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert df.iloc[0]["Category"] == "Marketing"


def test_load_from_google_sheets_csv_export(requests_mock=None):
    # Direct CSV export URL should bypass gspread OAuth and load via read_csv
    sheet_url = "https://docs.google.com/spreadsheets/d/12345/export?format=csv"

    # Patch pd.read_csv to return a mock DataFrame when called with the URL
    with patch("pandas.read_csv") as mock_read_csv:
        mock_read_csv.return_value = pd.DataFrame({
            "date": ["23-05-2026"],
            "category": ["Marketing"],
            "amount": [1500.0],
            "entity": ["Google Ads"]
        })
        
        ingestor = DataIngestion()
        df = ingestor.load_from_google_sheets(sheet_url)

        mock_read_csv.assert_called_once_with(sheet_url)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert df.iloc[0]["category"] == "Marketing"


def test_strip_transaction_record_normalizes_aliases():
    raw = {
        "date": "2026-05-23",
        "category": "Marketing",
        "amount": "1500.5",
        "entity": "Google Ads",
        "type": "Expense"
    }

    normalized = strip_transaction_record(raw)

    assert normalized["Date"] == pd.Timestamp("2026-05-23")
    assert normalized["Category"] == "Marketing"
    assert normalized["Amount"] == 1500.5
    assert normalized["Entity"] == "Google Ads"
    assert normalized["Type"] == "Expense"
    assert normalized["Severity"] == "Normal"
    assert normalized["Is_Budget_Breach"] is False
    assert normalized["Is_Mom_Anomaly"] is False
    assert normalized["Anomaly_Reason"] is None


def test_strip_unified_transaction_normalizes_stripe_payload():
    raw = {
        "id": "ch_123",
        "amount": 1500,
        "currency": "usd",
        "created": 1710000000,
        "status": "succeeded",
        "billing_details": {"name": "Acme Ltd"}
    }

    normalized = strip_unified_transaction(raw, source="stripe")

    assert normalized["external_id"] == "ch_123"
    assert normalized["source"] == "stripe"
    assert normalized["amount"] == 15.0
    assert normalized["currency"] == "USD"
    assert normalized["transaction_date"] == datetime.fromtimestamp(
        1710000000, tz=timezone.utc
    ).replace(tzinfo=None)
    assert normalized["status"] == "succeeded"
    assert normalized["counterparty"] == "Acme Ltd"
    assert normalized["transaction_type"] == "revenue"
    assert normalized["direction"] == "inflow"
    assert normalized["category"] == "revenue"


def test_strip_unified_transaction_categorizes_payout_refund_as_expense():
    payout = strip_unified_transaction(
        {
            "id": "po_xyz",
            "object": "payout",
            "amount": 50000,
            "currency": "usd",
            "created": 1710000000,
            "status": "paid",
        },
        source="stripe",
    )
    assert payout["transaction_type"] == "expense"
    assert payout["direction"] == "outflow"
    assert payout["category"] == "expense"

    refund = strip_unified_transaction(
        {
            "id": "re_abc",
            "object": "refund",
            "amount": 2000,
            "currency": "usd",
            "created": 1710000000,
            "status": "succeeded",
        },
        source="stripe",
    )
    assert refund["transaction_type"] == "refund"
    assert refund["direction"] == "outflow"
    assert refund["status"] == "succeeded"

    failed_charge = strip_unified_transaction(
        {
            "id": "ch_fail",
            "object": "charge",
            "amount": 100,
            "currency": "usd",
            "created": 1710000000,
            "status": "failed",
        },
        source="stripe",
    )
    assert failed_charge["transaction_type"] == "expense"
    assert failed_charge["status"] == "failed"
    assert failed_charge["direction"] == "outflow"


def test_excel_row_maps_to_unified_schema():
    from app.db.unified_store import _excel_record

    expense = _excel_record(4, {
        "Date": "2026-05-01",
        "Type": "Expense",
        "Category": "Marketing",
        "Entity": "Ads Inc",
        "Amount": 500.0,
    })
    assert expense["source"] == "excel"
    assert expense["user_id"] == 4
    assert expense["transaction_type"] == "expense"
    assert expense["direction"] == "outflow"
    assert expense["amount"] == 500.0
    assert expense["category"] == "Marketing"
    assert expense["counterparty"] == "Ads Inc"

    revenue = _excel_record(4, {
        "Date": "2026-05-02",
        "Type": "Revenue",
        "Category": "Sales",
        "Entity": "ClientCo",
        "Amount": 9000.0,
    })
    assert revenue["transaction_type"] == "revenue"
    assert revenue["direction"] == "inflow"

    # Re-uploading the same row yields the same external_id (idempotent dedup).
    dup = _excel_record(4, {
        "Date": "2026-05-01",
        "Type": "Expense",
        "Category": "Marketing",
        "Entity": "Ads Inc",
        "Amount": 500.0,
    })
    assert dup["external_id"] == expense["external_id"]

    # DB-backed rows use lowercase keys; mapping + hash must be identical so the
    # same transaction never inserts twice across df and DB paths.
    lower = _excel_record(4, {
        "date": "2026-05-01",
        "type": "Expense",
        "category": "Marketing",
        "entity": "Ads Inc",
        "amount": 500.0,
    })
    assert lower["transaction_type"] == "expense"
    assert lower["category"] == "Marketing"
    assert lower["counterparty"] == "Ads Inc"
    assert lower["external_id"] == expense["external_id"]

    # A pandas Timestamp date must hash the same as its string form.
    ts = _excel_record(4, {
        "Date": pd.Timestamp("2026-05-01"),
        "Type": "Expense",
        "Category": "Marketing",
        "Entity": "Ads Inc",
        "Amount": 500.0,
    })
    assert ts["external_id"] == expense["external_id"]


@patch("gspread.authorize")
@patch("app.integrations.google_auth.get_google_credentials")
def test_load_from_google_sheets_gspread(mock_get_creds, mock_gspread_authorize):
    # Normal sheets URL uses gspread
    sheet_url = "https://docs.google.com/spreadsheets/d/12345/edit"
    
    mock_creds = MagicMock()
    mock_get_creds.return_value = mock_creds

    mock_client = MagicMock()
    mock_gspread_authorize.return_value = mock_client

    mock_spreadsheet = MagicMock()
    mock_client.open_by_url.return_value = mock_spreadsheet

    mock_worksheet = MagicMock()
    mock_spreadsheet.get_worksheet.return_value = mock_worksheet
    
    # gspread returns list of dicts
    mock_worksheet.get_all_records.return_value = [
        {"date": "23-05-2026", "category": "Marketing", "amount": 1500.0, "entity": "Google Ads"}
    ]

    ingestor = DataIngestion()
    df = ingestor.load_from_google_sheets(sheet_url)

    mock_get_creds.assert_called_once()
    mock_gspread_authorize.assert_called_once_with(mock_creds)
    mock_client.open_by_url.assert_called_once_with(sheet_url)
    mock_spreadsheet.get_worksheet.assert_called_once_with(0)
    mock_worksheet.get_all_records.assert_called_once()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert df.iloc[0]["category"] == "Marketing"
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
