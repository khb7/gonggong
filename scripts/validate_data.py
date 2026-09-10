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

from sqlalchemy import text

from app.db.session import AsyncSessionLocal


class _Conn:
    """asyncpg 스타일 API 를 SQLAlchemy 세션 위에 얹은 얇은 어댑터.

    이 스크립트는 원래 asyncpg 로 Postgres 에 직접 붙었는데, 실제 DB 는
    `.env` 의 DATABASE_URL(sqlite+aiosqlite) 이라 **한 번도 실행된 적이 없다**.
    A값 미역산·하한율 오염·client_id 죽음이 전부 이 검증기를 통과한 것처럼
    보였던 이유다. 이제 앱과 같은 세션을 쓰므로 SQLite/Postgres 양쪽에서 돈다.
    """

    def __init__(self, session):
        self._s = session

    async def fetchval(self, sql, params: dict | None = None):
        row = (await self._s.execute(text(sql), params or {})).first()
        return row[0] if row else None

    async def fetchrow(self, sql, params: dict | None = None):
        return (await self._s.execute(text(sql), params or {})).mappings().first()

    async def fetch(self, sql, params: dict | None = None):
        return (await self._s.execute(text(sql), params or {})).mappings().all()

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

    # 법정 하한율 이산성.
    # 법정 하한율은 규정상 소수의 이산값만 갖는다. 고유값이 많다는 건
    # A값이 녹아든 '실효' 하한율이 법정 자리에 그대로 들어갔다는 뜻이다.
    # (실제로 이 상태가 방치돼 distinct 2,678 / 12,445 였다.)
    distinct_legal = await conn.fetchval(
        "SELECT COUNT(DISTINCT ROUND(legal_limit_rate, 5)) FROM bids_history "
        "WHERE legal_limit_rate IS NOT NULL"
    ) or 0
    print(f"[legal_limit_rate] 고유값 수: {distinct_legal}")
    if distinct_legal > 60:
        failures.append(
            f"법정 하한율 고유값 {distinct_legal}개 — A값 미분리 의심. "
            f"etl_csv.py --upsert 로 재적재 필요"
        )
    elif distinct_legal > 30:
        warnings.append(f"법정 하한율 고유값 {distinct_legal}개")

    # A값 정합성.
    # `[A값]` 태그가 붙었는데 a_value 가 0이면 역산이 돌지 않은 것이다.
    # 이 검사가 없어서 a_value 가 12,445건 전부 0인 채로 방치됐다.
    with_a = await conn.fetchval("SELECT COUNT(*) FROM bids_history WHERE a_value > 0") or 0
    tagged = await conn.fetchval("SELECT COUNT(*) FROM bids_history WHERE has_a_value = 1") or 0
    print(f"[a_value] A값 역산된 행: {with_a / total * 100:.1f}% ({with_a}/{total})")
    if tagged:
        missing = await conn.fetchval(
            "SELECT COUNT(*) FROM bids_history WHERE has_a_value = 1 AND COALESCE(a_value, 0) = 0"
        ) or 0
        miss_pct = missing / tagged * 100
        print(f"[a_value] A값 공고인데 역산 실패: {miss_pct:.1f}% ({missing}/{tagged})")
        if miss_pct >= 30:
            failures.append(f"A값 공고 중 역산 실패 {miss_pct:.1f}% — 역산 파이프라인 미동작")
        elif miss_pct >= 10:
            warnings.append(f"A값 공고 중 역산 실패 {miss_pct:.1f}%")

        ratio = await conn.fetchval(
            "SELECT AVG(a_value * 1.0 / base_price) FROM bids_history "
            "WHERE a_value > 0 AND base_price > 0"
        )
        if ratio:
            # 실측 기준: 자사 151건 5.23%, 시장 전체 3~4%대. 1% 미만이면 과소 산출이다
            # (후보표에 용역 하한율이 섞이면 이렇게 된다 — a_value.py 주석 참조).
            print(f"[a_value] 기초금액 대비 평균 비중: {float(ratio) * 100:.2f}%")
            if float(ratio) < 0.01:
                failures.append(
                    f"A값 비중 {float(ratio) * 100:.2f}% — 과소 산출. 하한율 후보표 오분류 의심"
                )

    # ── 3. region ──────────────────────────────────────────────────────────
    regions = await conn.fetch(
        "SELECT DISTINCT region FROM bids_history"
    )
    invalid_regions = [r["region"] for r in regions if not is_valid_region(r["region"])]
    if invalid_regions:
        # ANY($1::text[]) 는 Postgres 전용 → IN (:r0, :r1, ...) 으로 전개한다.
        keys = ", ".join(f":r{i}" for i in range(len(invalid_regions)))
        invalid_count = await conn.fetchval(
            f"SELECT COUNT(*) FROM bids_history WHERE region IN ({keys})",
            {f"r{i}": v for i, v in enumerate(invalid_regions)},
        ) or 0
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

    # ── 4. 사정률(preprice_rate) 범위 ─────────────────────────────────────
    #
    # ⚠ 예전에는 이 검사가 `adjustment_rate` 를 0.95~1.05 로 봤다. 그 컬럼이
    #   사정률이라고 잘못 알던 시절의 기준이다. 실제로 `adjustment_rate` 는
    #   **낙찰가/기초금액**(중앙 0.883)이라 항상 범위를 벗어나 95.7% FAIL 이 났다.
    #   진짜 사정률은 `preprice_rate`(예정가격/기초금액) 다.
    #
    # 사정률은 복수예비가격 제도가 만들어내므로 이론값이 정해져 있다:
    #   생성범위 ±2%(국가계약) → sd 0.513% / ±3%(지방계약) → sd 0.767%
    #   실측 범위는 대략 ±2.3% 안이다.   근거: 강민석·류문찬(2015) Table 3·4
    pp_total = await conn.fetchval(
        "SELECT COUNT(*) FROM bids_history WHERE preprice_rate IS NOT NULL"
    ) or 0
    if pp_total:
        oor = await conn.fetchval(
            "SELECT COUNT(*) FROM bids_history "
            "WHERE preprice_rate IS NOT NULL AND (preprice_rate < 0.96 OR preprice_rate > 1.04)"
        ) or 0
        oor_pct = oor / pp_total * 100
        print(f"[preprice_rate] 0.96~1.04 범위 외: {oor_pct:.1f}% ({oor}/{pp_total})")
        if oor_pct >= 5:
            failures.append(f"사정률 범위 이탈 {oor_pct:.1f}% — 예정가격/기초금액 매핑 오류 의심")
        elif oor_pct >= 1:
            warnings.append(f"사정률 범위 이탈 {oor_pct:.1f}%")

        stat = await conn.fetchrow(
            "SELECT AVG(preprice_rate) AS m, COUNT(*) AS c FROM bids_history "
            "WHERE preprice_rate IS NOT NULL AND preprice_rate BETWEEN 0.9 AND 1.1"
        )
        if stat and stat["c"]:
            mean = float(stat["m"])
            print(f"[preprice_rate] 평균: {mean:.5f}  (이론 0.999~1.000)")
            if not (0.99 <= mean <= 1.01):
                failures.append(f"사정률 평균 {mean:.5f} — 제도상 1.0 근처여야 한다")
    else:
        print("[preprice_rate] 값 없음 — etl_csv.py 재적재 필요")
        warnings.append("preprice_rate 미적재")

    # adjustment_rate(=낙찰가/기초금액) 는 ETL 이 0.70~1.00 으로 거른다. 그 범위 확인만.
    adj_oor = await conn.fetchval(
        "SELECT COUNT(*) FROM bids_history WHERE adjustment_rate <= 0.70 OR adjustment_rate >= 1.00"
    ) or 0
    if adj_oor:
        print(f"[adjustment_rate] ETL 허용범위(0.70~1.00) 밖: {adj_oor}건")
        warnings.append(f"adjustment_rate 범위 이탈 {adj_oor}건")

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
    # COUNT(*) FILTER 는 Postgres 전용이라 SUM(CASE ...) 로 바꿨다 (SQLite 호환).
    # 낙찰하한가가 없는 공고는 애초에 하한율을 대조할 수 없어 위반율이 23배 높다
    # (26.1% vs 1.1%). 엔진이 이미 집계에서 빼므로(`_verifiable_limits_filter`)
    # 두 모집단을 갈라서 보고한다 — 합쳐 세면 고칠 수 없는 229건이 매주 경고로
    # 떠서 정작 고쳐야 할 소수가 묻힌다.
    inv = await conn.fetchrow(
        """
        SELECT SUM(CASE WHEN w.bid_rate
                          < COALESCE(bh.legal_limit_rate, bh.lower_limit_rate) - 0.00002
                        THEN 1 ELSE 0 END) AS viol,
               COUNT(*) AS tot,
               SUM(CASE WHEN w.bid_rate
                          < COALESCE(bh.legal_limit_rate, bh.lower_limit_rate) - 0.00002
                        AND COALESCE(bh.lower_limit_price, 0) > 0
                        THEN 1 ELSE 0 END) AS viol_in_scope,
               SUM(CASE WHEN COALESCE(bh.lower_limit_price, 0) > 0
                        THEN 1 ELSE 0 END) AS tot_in_scope
        FROM bid_participants w
        JOIN bids_history bh ON w.project_id = bh.project_id
        WHERE w.is_winner
        """
    )
    if inv and inv["tot"]:
        in_scope = inv["tot_in_scope"] or 0
        viol_in = inv["viol_in_scope"] or 0
        excluded = inv["viol"] - viol_in
        viol_pct = viol_in / in_scope * 100 if in_scope else 0.0
        print(
            f"[불변식] 낙찰자 투찰율 < 법정 하한율 (집계 대상): "
            f"{viol_pct:.2f}% ({viol_in}/{in_scope})"
        )
        print(
            f"[불변식] 낙찰하한가 없어 집계에서 제외된 위반: {excluded}건 "
            f"— 대조 근거가 없어 고칠 수 없다"
        )
        if viol_pct >= 10:
            failures.append(
                f"낙찰자 불변식 위반 {viol_pct:.1f}% — 하한율 오염. "
                f"etl_participants.py --update-limits 로 원본 하한율 재적재 필요"
            )
        elif viol_in > 0:
            warnings.append(f"낙찰자 불변식 위반 {viol_in}건 (집계 대상 내)")
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
    # `::int` 는 Postgres 전용 캐스트 → CAST(... AS INTEGER)
    hist = await conn.fetch("""
        SELECT CAST(adjustment_rate * 100 AS INTEGER) as pct, COUNT(*) as cnt
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
    async with AsyncSessionLocal() as session:
        conn = _Conn(session)
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
        return 1 if failures else 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.exit(asyncio.run(main()))
