import pandas as pd
import io

try:
    with open("md/UI-ADOFAA-003R.입찰공고 결과내역.csv", "r", encoding="utf-16le", errors="replace") as f:
        lines = f.readlines()
        
    start_idx = -1
    for i, line in enumerate(lines):
        if line.startswith('"입찰공고번호"'):
            start_idx = i
            break
            
    if start_idx != -1:
        data_str = "".join(lines[start_idx:])
        df = pd.read_csv(io.StringIO(data_str), sep="\t", dtype=str)
        print("--- COLUMNS ---")
        for c in df.columns:
            print(c)
        print("--- SAMPLE DATA ---")
        print(df.head(2).to_dict('records'))
    else:
        print("Header not found")
except Exception as e:
    import traceback
    traceback.print_exc()
