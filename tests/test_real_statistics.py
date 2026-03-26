import os
import sys
import pandas as pd
import io
from decimal import Decimal, InvalidOperation

# Add the project root to sys.path so app modules can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.engine.statistics import trimmed_median, mad, confidence_range

def parse_price(val):
    if pd.isna(val):
        return None
    try:
        # Remove commas and convert to str
        cleaned = str(val).replace(',', '')
        return Decimal(cleaned)
    except InvalidOperation:
        return None

def main():
    csv_path = "md/UI-ADOFAA-003R.입찰공고 결과내역.csv"
    print(f"Reading data from {csv_path}...")
    
    try:
        with open(csv_path, "r", encoding="utf-16le", errors="replace") as f:
            lines = f.readlines()
            
        start_idx = -1
        for i, line in enumerate(lines):
            if line.startswith('"입찰공고번호"'):
                start_idx = i
                break
                
        if start_idx == -1:
            print("Could not find data headers.")
            return
            
        data_str = "".join(lines[start_idx:])
        df = pd.read_csv(io.StringIO(data_str), sep="\t", dtype=str)
        print(f"Loaded {len(df)} rows of data.")
        
        # We need to extract one Adjustment Rate (사정률) per Bid Notice (입찰공고번호)
        # Drop duplicates based on bid notice number
        unique_bids = df.drop_duplicates(subset=["입찰공고번호"])
        print(f"Found {len(unique_bids)} unique bids.")
        
        rates = []
        for idx, row in unique_bids.iterrows():
            calc_base = parse_price(row.get("기초금액"))
            calc_exp = parse_price(row.get("예정가격"))
            
            if calc_base and calc_exp and calc_base > 0:
                # 사정률 = (예정가격 / 기초금액) * 100
                rate = (calc_exp / calc_base) * Decimal("100")
                # Usually 사정률 is around 97 ~ 103 range
                if Decimal("90") <= rate <= Decimal("110"):
                    rates.append(rate)
                    
        output = []
        output.append(f"Calculated valid adjustment rates for {len(rates)} bids.")
        
        if not rates:
            output.append("No valid rates to compute statistics.")
            with open("tests/test_results.txt", "w", encoding="utf-8") as f:
                f.write("\n".join(output))
            print("Done")
            return
            
        output.append("-" * 50)
        output.append("Running app.engine.statistics functions...")
        output.append("-" * 50)
        
        # 1. Trimmed Median
        t_median = trimmed_median(rates, trim_pct=0.05)
        output.append(f"Trimmed Median (5%): {t_median:.6f}%")
        
        # 2. MAD
        mad_val = mad(rates)
        output.append(f"MAD (Median Absolute Deviation): {mad_val:.6f}%")
        
        # 3. Confidence Range
        lower, upper = confidence_range(t_median, mad_val)
        output.append(f"Confidence Range (Median ± MAD): [{lower:.6f}%, {upper:.6f}%]")
        
        output.append("\nTest completed successfully!")
        
        with open("tests/test_results.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(output))
        
        print("Test completed. See tests/test_results.txt")
        
    except Exception as e:
        print("An error occurred during testing:")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
