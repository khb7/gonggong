import xlrd, sys, io, contextlib
from pathlib import Path

files = sorted(Path('G:/내 드라이브/gonggong/participants').glob('*.xls'))

# 기존 방식 실패 파일 목록 수집
fail_files = []
with contextlib.redirect_stdout(io.StringIO()):
    for f in files:
        try:
            xlrd.open_workbook(str(f))
        except:
            fail_files.append(f)

print(f'기존 방식 실패: {len(fail_files)}개')

# ignore_workbook_corruption=True 로 재시도
recovered = []
still_fail = []
with contextlib.redirect_stdout(io.StringIO()):
    for f in fail_files:
        try:
            wb = xlrd.open_workbook(str(f), ignore_workbook_corruption=True)
            ws = wb.sheet_by_index(0)
            recovered.append((f, ws.nrows))
        except Exception as e:
            still_fail.append((f, str(e)[:80]))

print(f'ignore_workbook_corruption=True 로 복구: {len(recovered)}개')
print(f'여전히 실패: {len(still_fail)}개')

# 복구된 파일 샘플
print('\n=== 복구된 파일 샘플 (첫 3개) ===')
for f, nrows in recovered[:3]:
    with contextlib.redirect_stdout(io.StringIO()):
        wb = xlrd.open_workbook(str(f), ignore_workbook_corruption=True)
    ws = wb.sheet_by_index(0)
    print(f'\n{f.name} ({nrows}행)')
    for i in range(min(5, ws.nrows)):
        print(f'  행{i}:', ws.row_values(i))

# 여전히 실패하는 파일 에러 패턴
print('\n=== 여전히 실패하는 에러 패턴 ===')
err_types = {}
for f, err in still_fail:
    key = err[:50]
    err_types[key] = err_types.get(key, 0) + 1
for err, cnt in sorted(err_types.items(), key=lambda x: -x[1])[:5]:
    print(f'  [{cnt}개] {err}')
