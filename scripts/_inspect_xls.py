import xlrd, warnings, sys
warnings.filterwarnings('ignore')
xlrd.open_workbook.__globals__['PRINT_QNAMES'] = False

from pathlib import Path

# xlrd 내부 경고 출력 억제
import logging
logging.disable(logging.CRITICAL)

files = sorted(Path('G:/내 드라이브/gonggong/participants').glob('*.xls'))

ok = []
fail_count = 0
small_count = 0

old_stderr = sys.stderr
sys.stderr = open('nul', 'w')
for f in files:
    try:
        wb = xlrd.open_workbook(str(f))
        ws = wb.sheet_by_index(0)
        if ws.nrows > 15:
            ok.append((f, ws, wb))
        else:
            small_count += 1
    except Exception:
        fail_count += 1
sys.stderr.close()
sys.stderr = old_stderr

ok_sorted = sorted(ok, key=lambda x: x[1].nrows, reverse=True)
print(f'정상(>15행): {len(ok)}개, 소형: {small_count}개, 실패: {fail_count}개')
print()

# 가장 큰 파일 구조 출력
f, ws, wb = ok_sorted[0]
print(f'=== 최대 파일: {f.name} ({ws.nrows}행) ===')
for i in range(ws.nrows):
    print(f'  행{i}:', ws.row_values(i))

print()

# 두 번째로 큰 파일
f2, ws2, wb2 = ok_sorted[1]
print(f'=== 2위 파일: {f2.name} ({ws2.nrows}행) ===')
for i in range(ws2.nrows):
    print(f'  행{i}:', ws2.row_values(i))
