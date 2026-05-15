import pandas as pd
import glob
import os

def find_latest_gradio_csv(prefix="MOCK_DATA"):
    temp_dir = os.path.join(os.environ.get('TEMP', ''), 'gradio')
    if not os.path.exists(temp_dir):
        return None
    
    files = []
    for root, dirs, filenames in os.walk(temp_dir):
        for f in filenames:
            if f.endswith(".csv") and prefix in f:
                path = os.path.join(root, f)
                files.append((path, os.path.getmtime(path)))
    
    if not files:
        return None
    
    # Sort by modification time
    files.sort(key=lambda x: x[1], reverse=True)
    return [f[0] for f in files[:5]] # Return top 5 latest

def inspect_raw_csvs():
    paths = find_latest_gradio_csv()
    if not paths:
        print("No Gradio CSVs found in TEMP.")
        return
    
    for p in paths:
        print(f"\n--- Inspecting {p} ---")
        try:
            df = pd.read_csv(p)
            print(f"Columns: {df.columns.tolist()}")
            print("First 3 rows:")
            print(df.head(3))
        except Exception as e:
            print(f"Error reading {p}: {e}")

if __name__ == "__main__":
    inspect_raw_csvs()
