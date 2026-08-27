"""
scripts/validate_data.py
ETL 적재 후 bids_history 데이터 품질 자동 검증.

사용법:
  python scripts/validate_data.py

판정:
  ✅ 백필 진행 가능   — 실패 항목 0개
  ⚠ 품질 주의        — 경고만 있는 경우
  ❌ 재수집 필요      — 실패 항목 1개 이상
"""

import asyncio
import io
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncpg

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres@localhost:5432/gonggong").replace(
    "postgresql+asyncpg://", "postgresql://"
)

# 지역명 화이트리스트 (단일 지역 또는 "전국,경기" 형식 조합)
REGION_WHITELIST = {
    "경기", "서울", "인천", "부산", "대구", "대전", "광주", "울산", "세종",
    "강원", "충남", "충북", "전남", "전북", "경남", "경북", "제주", "전국",
}


def is_valid_region(region: str) -> bool:
    """'전국,경기' 형식 포함 — 쉼표로 분리 후 각 파트가 화이트리스트에 있으면 유효."""
    parts = [p.strip() for p in region.split(",")]
    return all(p in REGION_WHITELIST for p in parts)


async def validate(conn) -> tuple[list[str], list[str], int]:
    """(warnings, failures, total) 반환."""
    warnings = []
    failures = []
    total = await conn.fetchval("SELECT COUNT(*) FROM bids_history")

    if total == 0:
        failures.append("bids_history가 비어있음 — ETL을 먼저 실행하세요")
        return warnings, failures, 0

    print(f"\n총 레코드: {total}건\n")

    # ── 1. participants ────────────────────────────────────────────────────
    zero_p = await conn.fetchval(
        "SELECT COUNT(*) FROM bids_history WHERE participants = 0"
    )
    zero_pct = zero_p / total * 100
    print(f"[participants] 0인 비율: {zero_pct:.1f}% ({zero_p}/{total})")
    if zero_pct >= 80:
        failures.append(f"participants=0 비율 {zero_pct:.1f}% — 상세 포맷 컬럼 누락 의심")
    elif zero_pct >= 30:
        warnings.append(f"participants=0 비율 {zero_pct:.1f}% — 일부 데이터 누락")

    # ── 2. lower_limit_rate ───────────────────────────────────────────────
    #
    # 예전에는 "0.87745 고정 비율"이 높으면 ETL fallback 상수가 채운 가짜 값이라
    # 판단했다. 그 fallback을 제거했으므로(etl_csv.py) 이제 0.87745가 많은 건
    # 2025-07-08 개정 이전 데이터라는 뜻이지 오류가 아니다.
    # 지금 봐야 할 신호는 "법정 하한율을 판별하지 못한 행"이다.
    no_legal = await conn.fetchval(
        "SELECT COUNT(*) FROM bids_history WHERE legal_limit_rate IS NULL"
    )
    no_legal_pct = no_legal / total * 100
    print(f"[legal_limit_rate] 판별 실패 비율: {no_legal_pct:.1f}% ({no_legal}/{total})")
    if no_legal_pct >= 30:
        failures.append(f"법정 하한율 미판별 {no_legal_pct:.1f}% — 원본 컬럼 누락 의심")
    elif no_legal_pct >= 5:
        warnings.append(f"법정 하한율 미판별 {no_legal_pct:.1f}%")

    # 개정 전후 하한율 혼재 현황 (정보성 — 실패 조건 아님)
    rate_mix = await conn.fetch(
        "SELECT legal_limit_rate AS r, COUNT(*) AS c FROM bids_history "
        "WHERE legal_limit_rate IS NOT NULL GROUP BY r ORDER BY c DESC LIMIT 5"
    )
    mix = ", ".join(f"{row['r']}:{row['c']}" for row in rate_mix)
    print(f"[legal_limit_rate] 상위 분포: {mix}")

    # A값 반영 현황 (정보성)
    with_a = await conn.fetchval("SELECT COUNT(*) FROM bids_history WHERE a_value > 0")
    print(f"[a_value] A값 역산된 행: {with_a / total * 100:.1f}% ({with_a}/{total})")

    # ── 3. region ──────────────────────────────────────────────────────────
    regions = await conn.fetch(
        "SELECT DISTINCT region FROM bids_history"
    )
    invalid_regions = [r["region"] for r in regions if not is_valid_region(r["region"])]
    if invalid_regions:
        invalid_count = await conn.fetchval(
            "SELECT COUNT(*) FROM bids_history WHERE region = ANY($1::text[])",
            invalid_regions,
        )
    else:
        invalid_count = 0
    invalid_pct = invalid_count / total * 100
    print(f"[region] 화이트리스트 외 값 비율: {invalid_pct:.1f}% ({invalid_count}/{total})")
    if invalid_regions:
        print(f"  의심 값 샘플: {invalid_regions[:5]}")
    if invalid_pct >= 50:
        failures.append(f"region 의심값 비율 {invalid_pct:.1f}% — 요약 포맷 의심")
    elif invalid_pct >= 20:
        warnings.append(f"region 의심값 비율 {invalid_pct:.1f}%")

    # ── 4. adjustment_rate 범위 ───────────────────────────────────────────
    out_of_range = await conn.fetchval(
        "SELECT COUNT(*) FROM bids_history WHERE adjustment_rate < 0.95 OR adjustment_rate > 1.05"
    )
    oor_pct = out_of_range / total * 100
    print(f"[adjustment_rate] 0.95~1.05 범위 외: {oor_pct:.1f}% ({out_of_range}/{total})")
    if oor_pct >= 5:
        failures.append(f"adjustment_rate 범위 이탈 {oor_pct:.1f}%")
    elif oor_pct >= 1:
        warnings.append(f"adjustment_rate 범위 이탈 {oor_pct:.1f}%")

    # ── 5. price_method 분포 (판정 없음, 정보 출력만) ─────────────────────
    pm_dist = await conn.fetch(
        "SELECT price_method, COUNT(*) as cnt FROM bids_history GROUP BY price_method ORDER BY cnt DESC"
    )
    print("[price_method] 분포:")
    for r in pm_dist:
        print(f"  {r['price_method']}: {r['cnt']}건 ({r['cnt']/total*100:.1f}%)")

    # ── 6. 낙찰자 불변식 ───────────────────────────────────────────────────
    # 낙찰자의 투찰율은 법정 낙찰하한율보다 낮을 수 없다 (하한 미달은 실격).
    # bid_rate(원본 `투찰율(%)`)는 이미 A값이 제거된 조정 투찰율이므로
    # 비교 기준선은 실효 하한율이 아니라 법정 하한율이다.
    # 근거: md/design/bid_rate_definitions.md
    inv = await conn.fetchrow(
        """
        SELECT COUNT(*) FILTER (
                   WHERE w.bid_rate < COALESCE(bh.legal_limit_rate, bh.lower_limit_rate) - 0.00002
               ) AS viol,
               COUNT(*) AS tot
        FROM bid_participants w
        JOIN bids_history bh ON w.project_id = bh.project_id
        WHERE w.is_winner
        """
    )
    if inv and inv["tot"]:
        viol_pct = inv["viol"] / inv["tot"] * 100
        print(
            f"[불변식] 낙찰자 투찰율 < 법정 하한율: "
            f"{viol_pct:.1f}% ({inv['viol']}/{inv['tot']})"
        )
        if viol_pct >= 10:
            failures.append(
                f"낙찰자 불변식 위반 {viol_pct:.1f}% — 하한율 오염. "
                f"etl_participants.py --update-limits 로 원본 하한율 재적재 필요"
            )
        elif inv["viol"] > 0:
            warnings.append(f"낙찰자 불변식 위반 {inv['viol']}건")
    else:
        print("[불변식] 참여자 데이터 없음 — 검사 건너뜀")

    return warnings, failures, total


async def print_summary(conn):
    """추가 통계 출력."""
    print("\n─── 공종별 / 버킷별 분포 ───")
    pt = await conn.fetch(
        """
        SELECT l.type_name AS project_type, COUNT(*) AS cnt
        FROM bid_license_types l
        JOIN bids_history bh ON bh.project_id = l.project_id
        GROUP BY l.type_name ORDER BY cnt DESC
        """
    )
    for r in pt:
        print(f"  {r['project_type']}: {r['cnt']}건")

    bucket_dist = await conn.fetch("""
        SELECT
            CASE
                WHEN base_price < 100000000 THEN '버킷1(<1억)'
                WHEN base_price < 500000000 THEN '버킷2(1억~5억)'
                WHEN base_price < 2000000000 THEN '버킷3(5억~20억)'
                ELSE '버킷4(20억+)'
            END as bucket,
            COUNT(*) as cnt
        FROM bids_history GROUP BY 1 ORDER BY 1
    """)
    for r in bucket_dist:
        print(f"  {r['bucket']}: {r['cnt']}건")

    print("\n─── adjustment_rate 히스토그램 ───")
    hist = await conn.fetch("""
        SELECT floor(adjustment_rate * 100)::int as pct, COUNT(*) as cnt
        FROM bids_history
        GROUP BY 1 ORDER BY 1
    """)
    for r in hist:
        bar = "█" * min(r["cnt"] // 5, 40)
        print(f"  {r['pct']}%: {bar} ({r['cnt']}건)")

    print("\n─── 발주처별 건수 Top 10 + 예상 Fallback 레벨 ───")
    top_clients = await conn.fetch("""
        SELECT client_name, COUNT(*) as cnt
        FROM bids_history
        GROUP BY client_name
        ORDER BY cnt DESC
        LIMIT 10
    """)
    for r in top_clients:
        cnt = r["cnt"]
        level = "client (Lv1)" if cnt >= 20 else f"region/bucket 이하 ({cnt}건, 20건 미달)"
        print(f"  {r['client_name']}: {cnt}건 → 예상 {level}")


async def main():
    conn = await asyncpg.connect(DB_URL)
    try:
        print("=" * 50)
        print("  bids_history 데이터 품질 검증")
        print("=" * 50)

        warnings, failures, total = await validate(conn)

        if total > 0:
            await print_summary(conn)

        print("\n" + "=" * 50)
        if failures:
            print("❌ 재수집 필요")
            for f in failures:
                print(f"  FAIL: {f}")
        elif warnings:
            print("⚠ 진행 가능하나 데이터 품질 주의")
            for w in warnings:
                print(f"  WARN: {w}")
        else:
            print("✅ 백필 진행 가능")
        print("=" * 50)
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    asyncio.run(main())
