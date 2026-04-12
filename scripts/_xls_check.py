import xlrd, sys, io, contextlib
from pathlib import Path

files = sorted(Path('G:/내 드라이브/gonggong/participants').glob('*.xls'), key=lambda f: f.stat().st_size, reverse=True)

out = open('scripts/_xls_result.txt', 'w', encoding='utf-8')

ok_count = fail_count = 0
samples = []

with contextlib.redirect_stdout(io.StringIO()):  # xlrd 경고 삼키기
    for f in files:
        try:
            wb = xlrd.open_workbook(str(f))
            ws = wb.sheet_by_index(0)
            ok_count += 1
            if ws.nrows > 20 and len(samples) < 3:
                samples.append((f, ws))
        except:
            fail_count += 1

out.write(f'총 {len(files)}개 / 성공: {ok_count} / 실패: {fail_count}\n\n')

for f, ws in samples:
    out.write(f'=== {f.name} ({f.stat().st_size//1024}KB, {ws.nrows}행) ===\n')
    for i in range(ws.nrows):
        out.write(f'  행{i}: {ws.row_values(i)}\n')
    out.write('\n')

out.close()
print('완료: scripts/_xls_result.txt')
