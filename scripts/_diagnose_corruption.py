import xlrd, sys, io, contextlib
from pathlib import Path

files = sorted(Path('G:/내 드라이브/gonggong/participants').glob('*.xls'), key=lambda f: f.stat().st_size)

ok_files = []
fail_files = []

with contextlib.redirect_stdout(io.StringIO()):
    for f in files:
        try:
            wb = xlrd.open_workbook(str(f))
            ok_files.append(f)
        except:
            fail_files.append(f)

out = open('scripts/_diagnose_result.txt', 'w', encoding='utf-8')

out.write(f'=== 파일 통계 ===\n')
out.write(f'총: {len(files)}개 / 정상: {len(ok_files)}개 / 손상: {len(fail_files)}개\n\n')

# 손상 파일 크기 분포
fail_sizes = [f.stat().st_size for f in fail_files]
ok_sizes = [f.stat().st_size for f in ok_files]
out.write(f'=== 파일 크기 분포 ===\n')
out.write(f'손상: min={min(fail_sizes)}, max={max(fail_sizes)}, 평균={sum(fail_sizes)//len(fail_sizes)}\n')
out.write(f'정상: min={min(ok_sizes)}, max={max(ok_sizes)}, 평균={sum(ok_sizes)//len(ok_sizes)}\n\n')

# 손상 파일 크기별 분류
size_buckets = {}
for f in fail_files:
    sz = f.stat().st_size
    size_buckets[sz] = size_buckets.get(sz, 0) + 1

out.write(f'=== 손상 파일 크기별 빈도 (상위 20) ===\n')
for sz, cnt in sorted(size_buckets.items(), key=lambda x: -x[1])[:20]:
    out.write(f'  {sz}bytes ({sz//1024}KB): {cnt}개\n')

out.write('\n')

# 손상 파일 헤더 확인 (크기별 대표 1개씩)
checked_sizes = set()
out.write(f'=== 손상 파일 헤더 (첫 200bytes) ===\n')
for f in fail_files:
    sz = f.stat().st_size
    if sz in checked_sizes:
        continue
    checked_sizes.add(sz)
    with open(f, 'rb') as fp:
        header = fp.read(200)
    try:
        text = header.decode('cp949', errors='replace')
    except:
        text = repr(header[:50])
    out.write(f'\n[{sz}bytes] {f.name}\n')
    out.write(f'  hex: {header[:16].hex()}\n')
    out.write(f'  text: {repr(text[:100])}\n')
    if len(checked_sizes) >= 5:
        break

# 정상 파일 헤더 확인
out.write(f'\n=== 정상 파일 헤더 (첫 200bytes) ===\n')
for f in ok_files[:3]:
    sz = f.stat().st_size
    with open(f, 'rb') as fp:
        header = fp.read(16)
    out.write(f'\n[{sz}bytes] {f.name}\n')
    out.write(f'  hex: {header.hex()}\n')

out.close()
print('완료: scripts/_diagnose_result.txt')
