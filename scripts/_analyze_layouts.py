"""
539개 participant XLS 파일의 레이아웃 패턴 분석.
ignore_workbook_corruption=True 로 전부 읽음.
"""
import xlrd, sys, io, contextlib
from pathlib import Path
from collections import Counter

files = sorted(Path('G:/내 드라이브/gonggong/participants').glob('*.xls'))

layouts = []   # (파일, 행0_col0, 행1_col0, 행2_col0, nrows, ncols)
fail = []

with contextlib.redirect_stdout(io.StringIO()):
    for f in files:
        try:
            wb = xlrd.open_workbook(str(f), ignore_workbook_corruption=True)
            ws = wb.sheet_by_index(0)
            r = [ws.cell_value(i, 0) if ws.nrows > i else '' for i in range(4)]
            layouts.append((f, r[0], r[1], r[2], r[3], ws.nrows, ws.ncols))
        except Exception as e:
            fail.append((f, str(e)[:80]))

print(f'성공: {len(layouts)}개 / 실패: {len(fail)}개\n')

# 행0 기준 레이아웃 분류
from collections import defaultdict
groups = defaultdict(list)
for item in layouts:
    groups[item[1]].append(item)

print('=== 레이아웃 종류 (행0 기준) ===')
for key, items in sorted(groups.items(), key=lambda x: -len(x[1])):
    print(f'\n[{len(items)}개] 행0="{key}"')
    sample = items[0]
    f, r0, r1, r2, r3, nrows, ncols = sample
    print(f'  행1="{r1}", 행2="{r2}", 행3="{r3}"')
    print(f'  {nrows}행 {ncols}열 | 샘플: {f.name}')
    # 해당 그룹 전체 행/열 분포
    row_counts = Counter(x[5] for x in items)
    print(f'  행수 분포: {dict(sorted(row_counts.items())[:10])}')

if fail:
    print(f'\n=== 여전히 실패: {len(fail)}개 ===')
    for f, e in fail[:5]:
        print(f'  {f.name}: {e}')

# 레이아웃별 상세 샘플 출력 (결과 파일로)
out = open('scripts/_layout_samples.txt', 'w', encoding='utf-8')
for key, items in sorted(groups.items(), key=lambda x: -len(x[1])):
    out.write(f'\n{"="*60}\n')
    out.write(f'레이아웃: 행0="{key}" ({len(items)}개)\n')
    # 행수가 가장 많은 샘플
    sample = max(items, key=lambda x: x[5])
    f, *_, nrows, ncols = sample
    out.write(f'샘플: {f.name} ({nrows}행 {ncols}열)\n\n')
    with contextlib.redirect_stdout(io.StringIO()):
        wb = xlrd.open_workbook(str(f), ignore_workbook_corruption=True)
    ws = wb.sheet_by_index(0)
    for i in range(min(15, ws.nrows)):
        out.write(f'  행{i}: {ws.row_values(i)}\n')
out.close()
print('\n상세 샘플 → scripts/_layout_samples.txt')
