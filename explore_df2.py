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
        with open("md/parsed_metadata.txt", "w", encoding="utf-8") as out:
            out.write("--- COLUMNS ---\n")
            for c in df.columns:
                out.write(c + "\n")
            out.write("\n--- SAMPLE ROW ---\n")
            import json
            out.write(json.dumps(df.iloc[0].to_dict(), ensure_ascii=False, indent=2))
        print("Done")
    else:
        print("Header not found")
except Exception as e:
    import traceback
    traceback.print_exc()
