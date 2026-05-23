import os
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from tools.data_ingestion import DataIngestion

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
    mock_data = "date,category,amount,entity\n23-05-2026,Marketing,1500.0,Google Ads"

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


@patch("gspread.authorize")
@patch("google_auth.get_google_credentials")
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
