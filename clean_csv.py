import sys
import pandas as pd
import io

try:
    with open("md/UI-ADOFAA-003R.입찰공고 결과내역.csv", "r", encoding="utf-16le", errors="replace") as f:
        lines = f.readlines()
        
    start_idx = -1
    for i, line in enumerate(lines):
        if "입찰공고번호" in line or "사정률" in line or "예가대비투찰률" in line:
            start_idx = i
            break
            
    if start_idx != -1:
        # Some rows might have trailing commas or weird newlines
        clean_lines = [line.strip("\n\r") for line in lines[start_idx:]]
        # Some files have weird page breaks or footer. Let's just find where it stops being tabular
        data_lines = []
        for line in clean_lines:
            if "출력일자" in line or "UI-ADOFAA-003R" in line or line.startswith("---"):
                break
            if line.strip():
                data_lines.append(line)
                
        with open("md/cleaned_result.csv", "w", encoding="utf-8") as out:
            for l in data_lines:
                out.write(l + "\n")
        
        print(f"Cleaned CSV written. Columns: {data_lines[0]}")
        
    else:
        print("Could not find header row.")

except Exception as e:
    import traceback
    traceback.print_exc()
