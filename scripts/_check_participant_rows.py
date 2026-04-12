"""
"공고명" 레이아웃에서 행15 이후 참여업체 데이터 구조 확인.
"""
import xlrd, contextlib, io
from pathlib import Path

files = sorted(Path('G:/내 드라이브/gonggong/participants').glob('*.xls'),
               key=lambda f: f.stat().st_size, reverse=True)

with contextlib.redirect_stdout(io.StringIO()):
    for f in files:
        try:
            wb = xlrd.open_workbook(str(f), ignore_workbook_corruption=True)
            ws = wb.sheet_by_index(0)
            if ws.cell_value(0, 0) == '공고명' and ws.nrows > 20:
                break
        except:
            pass

print(f'파일: {f.name}')
print(f'총 {ws.nrows}행 {ws.ncols}열\n')

print('=== 헤더 섹션 (행0~14) ===')
for i in range(min(15, ws.nrows)):
    row = ws.row_values(i)
    # 빈 값 제거해서 보기 좋게
    compact = [(j, v) for j, v in enumerate(row) if v != '']
    print(f'행{i:2d}: {compact}')

print(f'\n=== 참여업체 섹션 (행15~24) ===')
for i in range(15, min(25, ws.nrows)):
    print(f'행{i:2d}: {ws.row_values(i)}')

print(f'\n=== 마지막 5행 ===')
for i in range(ws.nrows - 5, ws.nrows):
    print(f'행{i:2d}: {ws.row_values(i)}')

# 추가: 몇몇 파일의 기초금액/사정률 추출 테스트
print('\n=== 추출 테스트 (파일 5개) ===')
count = 0
with contextlib.redirect_stdout(io.StringIO()):
    for f2 in files:
        try:
            wb2 = xlrd.open_workbook(str(f2), ignore_workbook_corruption=True)
            ws2 = wb2.sheet_by_index(0)
            if ws2.cell_value(0, 0) != '공고명':
                continue

            공고번호 = ws2.cell_value(2, 2)
            발주기관 = ws2.cell_value(2, 8)
            개찰일시 = ws2.cell_value(3, 2)
            기초금액_raw = ws2.cell_value(3, 8)
            낙찰하한율_raw = ws2.cell_value(4, 8)
            예가기초_raw = ws2.cell_value(5, 8)
            투찰기초_raw = ws2.cell_value(6, 8)
            참여수 = ws2.nrows - 15  # 추정

            count += 1
            print(f'[{count}] {f2.name[:40]}')
            print(f'    공고번호={공고번호}, 발주기관={발주기관}')
            print(f'    개찰={개찰일시}, 기초={기초금액_raw}')
            print(f'    낙찰하한율={낙찰하한율_raw}, 예가/기초={예가기초_raw}, 투찰/기초={투찰기초_raw}')
            print(f'    참여업체(추정)={참여수}개')
            if count >= 5:
                break
        except:
            pass
