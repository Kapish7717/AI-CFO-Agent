import pandas as pd
import os

STATE_FILE = "current_financial_state.pkl"

def inspect_data():
    if not os.path.exists(STATE_FILE):
        print("No state file found.")
        return
        
    df = pd.read_pickle(STATE_FILE)
    print("--- DATA INSPECTION ---")
    print(f"Total rows: {len(df)}")
    print(f"Columns: {df.columns.tolist()}")
    print("\nValue counts for 'Type':")
    print(df['Type'].value_counts())
    
    print("\nDate Column Check (Revenue):")
    rev_df = df[df['Type'] == 'Revenue']
    print(f"Revenue NaT count: {rev_df['Date'].isna().sum()} out of {len(rev_df)}")
    print(rev_df['Date'].head(20))
    
    print("\nDate Column Check (Expense):")
    exp_df = df[df['Type'] == 'Expense']
    print(f"Expense NaT count: {exp_df['Date'].isna().sum()} out of {len(exp_df)}")
    print(exp_df['Date'].head(5))

if __name__ == "__main__":
    inspect_data()
