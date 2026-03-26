import sys

try:
    with open("md/UI-ADOFAA-003R.입찰공고 결과내역.csv", "r", encoding="utf-16le", errors="replace") as f:
        lines = f.readlines()
        for i in range(50, 80):
            if i < len(lines):
                print(f"[{i}]: {repr(lines[i])}")
except Exception as e:
    import traceback
    traceback.print_exc()
