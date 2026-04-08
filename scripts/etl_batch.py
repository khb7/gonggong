"""
Info21c XLS 파일 일괄 DB 적재 스크립트.

사용법:
  python scripts/etl_batch.py                          # data/downloads/ 전체 처리
  python scripts/etl_batch.py --dir data/downloads     # 디렉토리 지정
  python scripts/etl_batch.py --pattern "*건축*"        # 특정 파일만
  python scripts/etl_batch.py --resume                 # 이미 처리된 파일 스킵 (로그 파일 기준)
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.etl_csv import extract_and_transform, load_to_db

LOG_FILE = Path("data/downloads/_etl_batch.log")


def load_done_files() -> set[str]:
    if not LOG_FILE.exists():
        return set()
    done = set()
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("OK:"):
            done.add(line[3:].strip())
    return done


def log_result(filename: str, status: str, inserted: int, skipped: int, elapsed: float):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        if status == "ok":
            f.write(f"OK:{filename}  [{ts}] 신규:{inserted} 스킵:{skipped} ({elapsed:.1f}s)\n")
        else:
            f.write(f"ERR:{filename}  [{ts}] {status}\n")


async def process_file(file: Path, upsert: bool) -> tuple[str, int, int]:
    df = extract_and_transform(file)
    inserted, skipped = await load_to_db(df, upsert=upsert)
    return "ok", inserted, skipped


async def main():
    parser = argparse.ArgumentParser(description="Info21c XLS 일괄 DB 적재")
    parser.add_argument("--dir", default="data/downloads", help="XLS 파일 디렉토리")
    parser.add_argument("--pattern", default="info21c_*.xls", help="파일 glob 패턴")
    parser.add_argument("--resume", action="store_true", help="이미 처리된 파일 스킵")
    parser.add_argument("--upsert", action="store_true", help="기존 레코드도 업데이트")
    args = parser.parse_args()

    download_dir = Path(args.dir)
    files = sorted(download_dir.glob(args.pattern))

    if not files:
        print(f"파일 없음: {download_dir}/{args.pattern}")
        sys.exit(1)

    done_files = load_done_files() if args.resume else set()

    total = len(files)
    to_process = [f for f in files if f.name not in done_files]

    print(f"총 {total}개 파일 / 처리 대상 {len(to_process)}개"
          + (f" ({total - len(to_process)}개 스킵)" if args.resume else ""))
    print(f"로그: {LOG_FILE}")
    print("=" * 60)

    total_inserted = 0
    total_skipped = 0
    errors = []

    for i, file in enumerate(to_process, 1):
        print(f"\n[{i}/{len(to_process)}] {file.name}")
        t0 = time.time()
        try:
            status, inserted, skipped = await process_file(file, upsert=args.upsert)
            elapsed = time.time() - t0
            total_inserted += inserted
            total_skipped += skipped
            log_result(file.name, status, inserted, skipped, elapsed)
            print(f"  → 완료: 신규 {inserted}건 / 스킵 {skipped}건 ({elapsed:.1f}s)")
        except Exception as e:
            elapsed = time.time() - t0
            msg = str(e)[:120]
            errors.append((file.name, msg))
            log_result(file.name, msg, 0, 0, elapsed)
            print(f"  → 오류: {msg}")

    print("\n" + "=" * 60)
    print(f"완료: 신규 {total_inserted}건 적재 / {total_skipped}건 스킵")
    if errors:
        print(f"\n실패 {len(errors)}개:")
        for name, msg in errors:
            print(f"  {name}: {msg}")
    else:
        print("오류 없음")


if __name__ == "__main__":
    asyncio.run(main())
