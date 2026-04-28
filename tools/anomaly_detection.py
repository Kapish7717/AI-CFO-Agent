import pandas as pd
import numpy as np

def detect_zscore_anomalies(df: pd.DataFrame, column: str = 'Amount', threshold: float = 3.0) -> pd.DataFrame:
    """
    Detects anomalies using the Z-score method.
    Returns the dataframe with an added 'Anomaly_ZScore' boolean column.
    """
    df = df.copy()
    
    # Calculate z-score separately for Expense and Revenue to not skew each other
    if 'Type' in df.columns:
        df['Z_Score'] = df.groupby('Type')[column].transform(lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0)
    else:
        mean = df[column].mean()
        std = df[column].std()
        df['Z_Score'] = (df[column] - mean) / std if std > 0 else 0
        
    df['Anomaly_ZScore'] = df['Z_Score'].abs() > threshold
    return df

def detect_iqr_anomalies(df: pd.DataFrame, column: str = 'Amount') -> pd.DataFrame:
    """
    Detects anomalies using the Interquartile Range (IQR) method.
    Returns the dataframe with an added 'Anomaly_IQR' boolean column.
    """
    df = df.copy()
    
    def calc_iqr_anomaly(group):
        Q1 = group.quantile(0.25)
        Q3 = group.quantile(0.75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        return (group < lower_bound) | (group > upper_bound)
        
    if 'Type' in df.columns:
        df['Anomaly_IQR'] = df.groupby('Type')[column].transform(calc_iqr_anomaly)
    else:
        df['Anomaly_IQR'] = calc_iqr_anomaly(df[column])
        
    return df

def detect_rule_based(df: pd.DataFrame, amount_col: str = 'Amount', entity_col: str = 'Entity', date_col: str = 'Date', type_col: str = 'Type') -> pd.DataFrame:
    """
    Detects anomalies using Business CFO rules:
    - Amounts > 2x average for that Type (Expense or Revenue)
    - Duplicates (same date, entity, amount, type)
    - Month-over-Month (MoM) entity spikes (> 2x previous month)
    """
    df = df.copy()

    # 1. Duplicates (same date, entity, amount, type)
    if not df[date_col].isna().all():
        df['date_only'] = df[date_col].dt.date
        subset_cols = ['date_only', entity_col, amount_col]
        if type_col in df.columns: subset_cols.append(type_col)
        df['is_duplicate'] = df.duplicated(subset=subset_cols, keep=False)
    else:
        subset_cols = [entity_col, amount_col]
        if type_col in df.columns: subset_cols.append(type_col)
        df['is_duplicate'] = df.duplicated(subset=subset_cols, keep=False)

    # 2. Amounts > 2x Average (Grouped by Type)
    df['is_large_amount'] = False
    if type_col in df.columns:
        for t in df[type_col].unique():
            mask = df[type_col] == t
            avg_amt = df.loc[mask, amount_col].mean()
            df.loc[mask, 'is_large_amount'] = df.loc[mask, amount_col] > (2 * avg_amt)
    else:
        avg_amt = df[amount_col].mean()
        df['is_large_amount'] = df[amount_col] > (2 * avg_amt)

    # 3. Month-over-Month (MoM) Entity Spikes (> 2x previous month)
    if not df[date_col].isna().all() and entity_col in df.columns:
        df['YearMonth'] = df[date_col].dt.to_period('M')
        
        group_cols = ['YearMonth', entity_col]
        if type_col in df.columns: group_cols.append(type_col)
            
        monthly_totals = df.groupby(group_cols)[amount_col].sum().reset_index()
        monthly_totals.rename(columns={amount_col: 'Monthly_Total'}, inplace=True)
        monthly_totals['Prev_YearMonth'] = monthly_totals['YearMonth'] - 1
        
        merge_on = ['Prev_YearMonth', entity_col]
        right_on = ['YearMonth', entity_col]
        if type_col in df.columns:
            merge_on.append(type_col)
            right_on.append(type_col)
            
        mom_df = pd.merge(monthly_totals, monthly_totals[right_on + ['Monthly_Total']],
                          left_on=merge_on, right_on=right_on, how='left', suffixes=('', '_prev'))
        
        # Anomaly if > 2x previous month
        mom_df['is_mom_anomaly'] = (mom_df['Monthly_Total_prev'].notna()) & (mom_df['Monthly_Total_prev'] > 0) & (mom_df['Monthly_Total'] > 2 * mom_df['Monthly_Total_prev'])
        
        join_cols = ['YearMonth', entity_col]
        if type_col in df.columns: join_cols.append(type_col)
            
        df = pd.merge(df, mom_df[join_cols + ['is_mom_anomaly']], on=join_cols, how='left')
        df['is_mom_anomaly'] = df['is_mom_anomaly'].fillna(False)
    else:
        df['is_mom_anomaly'] = False

    # Combine rules into the final 'Anomaly_RuleBased' column
    df['Anomaly_RuleBased'] = df['is_duplicate'] | df['is_large_amount'] | df['is_mom_anomaly']
    
    # Clean up temporary columns
    cols_to_drop = ['date_only', 'YearMonth']
    df.drop(columns=[col for col in cols_to_drop if col in df.columns], inplace=True)
    
    return df

def detect_all_anomalies(df: pd.DataFrame, amount_col: str = 'Amount') -> pd.DataFrame:
    """
    Applies multiple anomaly detection methods, combines the results using logical OR,
    and calculates a severity score based on how many methods flagged the transaction.
    """
    df = detect_zscore_anomalies(df, column=amount_col)
    df = detect_iqr_anomalies(df, column=amount_col)
    df = detect_rule_based(df, amount_col=amount_col)
    
    df['Is_Anomaly'] = df['Anomaly_ZScore'] | df['Anomaly_IQR'] | df['Anomaly_RuleBased']
    
    flags_count = df['Anomaly_ZScore'].astype(int) + df['Anomaly_IQR'].astype(int) + df['Anomaly_RuleBased'].astype(int)
    
    conditions = [
        (flags_count == 3),
        (flags_count == 2),
        (flags_count == 1)
    ]
    choices = ['Critical', 'High', 'Medium']
    
    df['Severity'] = np.select(conditions, choices, default='Normal')
    
    return df

if __name__ == "__main__":
    pass
