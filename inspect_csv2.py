import pandas as pd
import io
import pprint

csv_path = 'md/UI-ADOFAA-003R.입찰공고 결과내역_3-25_12-25.csv'

try:
    with open(csv_path, 'r', encoding='utf-16le', errors='replace') as f:
        lines = f.readlines()
        
    start_idx = -1
    for i, line in enumerate(lines):
        if line.startswith('"입찰공고번호"'):
            start_idx = i
            break
            
    if start_idx != -1:
        data_str = "".join(lines[start_idx:])
        df = pd.read_csv(io.StringIO(data_str), sep="\t", dtype=str)
        with open("csv_info.txt", "w", encoding="utf-8") as out:
            out.write("--- COLUMNS ---\n")
            for c in df.columns:
                out.write(c + "\n")
            out.write("\n--- SAMPLE DATA (1 row) ---\n")
            out.write(pprint.pformat(df.head(1).to_dict('records')[0]))
    else:
        print("Header not found")
except Exception as e:
    import traceback
    traceback.print_exc()
