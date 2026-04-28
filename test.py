from cfo_tools import ingest_financial_data, detect_financial_anomalies, generate_cfo_pdf_report
import os

def run_tests():
    print("--- Test 1: Ingest Financial Data ---")
    expense_url = "https://docs.google.com/spreadsheets/d/19Cv2KbKm151bPkRrP-FpsfRAG74pntV-RZpuHskiKRU/edit?usp=sharing"
    revenue_url = "https://docs.google.com/spreadsheets/d/1T6bRfR-oSc20P_S8zHLgE-IBSN7TXr4o6CDF8ZL-w80/edit?usp=sharing"
    
    # Since these are LangChain @tool objects, we use .invoke()
    res1 = ingest_financial_data.invoke({
        "expense_path_or_url": expense_url,
        "revenue_path_or_url": revenue_url
    })
    print(res1)
    
    print("\n--- Test 2: Detect Financial Anomalies ---")
    res2 = detect_financial_anomalies.invoke({})
    print(res2)
    
    print("\n--- Test 3: Generate CFO PDF Report ---")
    res3 = generate_cfo_pdf_report.invoke({
        "output_filename": "test_business_cfo_report.pdf"
    })
    print(res3)
    
    if os.path.exists("test_business_cfo_report.pdf"):
        print("\n[SUCCESS]: PDF Report 'test_business_cfo_report.pdf' was successfully created!")
    else:
        print("\n[FAILURE]: PDF Report was not found.")

if __name__ == "__main__":
    run_tests()
