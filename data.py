import pandas as pd
data = pd.read_csv(r"C:\Users\KAPISH\Downloads\MOCK_DATA (2) (1).csv") # Ya (2) wali file
# Ab sirf yeh ek line kaafi hai
data['date'] = pd.to_datetime(data['date'], dayfirst=True, format='mixed', errors='coerce')
print(data.groupby(data['date'].dt.to_period('M'))[data.columns[3]].sum())