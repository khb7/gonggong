"""
tests/test_a_value.py
A값 역산 · 실효 하한율 · A값 반영 투찰가 검증.

검증 데이터는 실제 Info21c `입찰리스트` 엑셀
(data/downloads/info21c_0002_20250501_20250515.xlsx, 2025-05-01~15)에서 가져왔다.
"""

from decimal import Decimal

import pytest

from app.engine.a_value import (
    bid_price_with_a_value,
    derive_a_value,
    effective_limit_rate,
    has_a_value_tag,
    resolve_legal_limit_rate,
    split_limit_rates,
)
from app.engine.calculator import calculate_single


# ── [A값] 태그 파싱 ────────────────────────────────────────────


@pytest.mark.parametrize("name", [
    "학생회관 승강기 설치 공사 [제한][A값][순]",
    "부천시 보훈회관 노후시설물 정비 및 교체공사 [관내][수의][기초][A값]",
    # 공고명이 잘려 닫는 괄호가 사라진 경우
    "남양읍 행정복지센터 건립사업(건축) [내역][공의][기초][A값",
])
def test_has_a_value_tag_true(name):
    assert has_a_value_tag(name) is True


@pytest.mark.parametrize("name", [
    "국립세종도서관 옥상 방수 및 누수 보수공사 (긴급) [급][수의][기초]",
    "25-81) 박격포 차양대 신축 시설공사 [공]",
    "",
    None,
])
def test_has_a_value_tag_false(name):
    assert has_a_value_tag(name) is False


# ── 법정 하한율 역추정 ─────────────────────────────────────────


def test_resolve_legal_rate_snaps_down():
    """실효 하한율 이하의 후보 중 가장 큰 값을 고른다."""
    assert resolve_legal_limit_rate(Decimal("0.88255")) == Decimal("0.87745")


def test_resolve_legal_rate_does_not_snap_to_service_rate():
    """공사 공고를 용역 하한율로 오분류하지 않는다.

    후보표를 공사+용역 합집합으로 쓰던 시절, 법정 0.89745 인 공사 공고에
    A값이 붙으면 실효율이 0.90 을 넘어 용역값 `0.90000` 에 걸렸다.
    그러면 A값이 21% 과소 산출된다. 공사 표에는 0.89745 위가 없어야 한다.
    """
    from app.engine.a_value import LEGAL_LIMIT_RATES_SERVICE

    eff = Decimal("0.90258")  # 법정 0.89745 + A값 5%
    assert resolve_legal_limit_rate(eff) == Decimal("0.89745")
    # 용역 표를 명시적으로 넘기면 용역값이 나온다 (분리가 실제로 동작하는지)
    assert resolve_legal_limit_rate(eff, rates=LEGAL_LIMIT_RATES_SERVICE) == Decimal("0.90000")


def test_resolve_legal_rate_exact_match():
    """A값이 없으면 실효 = 법정이므로 그대로 매칭된다."""
    assert resolve_legal_limit_rate(Decimal("0.87745")) == Decimal("0.87745")


def test_resolve_legal_rate_prefers_declared():
    """원본에 낙찰하한율 컬럼이 있으면 추정보다 우선한다."""
    got = resolve_legal_limit_rate(Decimal("0.88255"), declared=Decimal("0.86745"))
    assert got == Decimal("0.86745")


def test_resolve_legal_rate_rejects_impossible_declared():
    """법정 하한율이 실효 하한율보다 높은 건 모순 — 신뢰하지 않는다."""
    got = resolve_legal_limit_rate(Decimal("0.87745"), declared=Decimal("0.95"))
    assert got == Decimal("0.87745")


def test_resolve_legal_rate_below_all_candidates():
    assert resolve_legal_limit_rate(Decimal("0.5")) is None


# ── A값 역산 ───────────────────────────────────────────────────


def test_derive_a_value_real_case():
    """
    실측: 학생회관 승강기 설치 공사 [제한][A값][순]
        예정가격    328,577,900
        낙찰하한가  289,985,144
        법정 하한율 0.88
      ⇒ A = (289,985,144 − 328,577,900 × 0.88) / 0.12 = 6,971,600
    """
    a = derive_a_value(328_577_900, 289_985_144, Decimal("0.88"))
    assert a == pytest.approx(6_971_600, abs=10)


def test_derive_a_value_zero_when_no_a_value():
    """
    실측: 국립세종도서관 옥상 방수 (A값 태그 없음)
        예정가격 143,317,675 × 0.87745 = 125,754,094 = 낙찰하한가
      ⇒ A = 0
    """
    assert derive_a_value(143_317_675, 125_754_094, Decimal("0.87745")) == 0


def test_derive_a_value_ignores_rounding_noise():
    """원 단위 절사로 생기는 잔차는 0으로 떨어뜨린다."""
    assert derive_a_value(143_317_675, 125_754_095, Decimal("0.87745")) == 0


def test_derive_a_value_guards_bad_input():
    assert derive_a_value(0, 100, Decimal("0.88")) == 0
    assert derive_a_value(100, 0, Decimal("0.88")) == 0
    assert derive_a_value(100, 90, Decimal("1")) == 0


# ── 실효 하한율 ────────────────────────────────────────────────


def test_effective_limit_rate_matches_source_data():
    """역산한 A값으로 실효 하한율을 되돌리면 원래 비율이 나온다."""
    eff = effective_limit_rate(328_577_900, 6_971_600, Decimal("0.88"))
    assert float(eff) == pytest.approx(289_985_144 / 328_577_900, abs=1e-7)


def test_effective_equals_legal_when_no_a_value():
    assert effective_limit_rate(1_000_000_000, 0, Decimal("0.89745")) == Decimal("0.89745")


# ── split_limit_rates (ETL 진입점) ────────────────────────────


def test_split_limit_rates_with_a_value():
    legal, eff, a = split_limit_rates(328_577_900, 289_985_144, None)
    assert legal == Decimal("0.87745")
    assert float(eff) == pytest.approx(0.88255, abs=1e-5)
    # A = (낙찰하한가 − 예정가격 × r) / (1 − r)
    #   = (289,985,144 − 328,577,900 × 0.87745) / 0.12255 ≈ 13,663,530  (기초금액 대비 4.16%)
    assert a == pytest.approx(13_663_530, abs=10)


# ── 실측 정답지 회귀 ───────────────────────────────────────────


def test_construction_table_matches_declared_a_value():
    """A값이 원본에 명시된 실측 151건으로 역산기를 검증한다.

    `data/downloads/인포나의투찰성향*.xlsx` 는 A값을 컬럼으로 제공한다.
    그 A값을 정답으로 두고, 낙찰하한가·예정가격만으로 역산한 결과와 대조한다
    (시장 데이터에는 A값 컬럼이 없으므로 `declared` 없이 = 동일 조건).

    후보표를 공사+용역 합집합으로 쓰면 법정율 매칭이 30.5% 로 떨어지고
    A값이 실제의 78.8% 로 과소 산출된다. 공사 표에서는 둘 다 100% 다.
    """
    import glob
    import pandas as pd

    paths = sorted(glob.glob("data/downloads/인포나의투찰성향*.xlsx"))
    if not paths:
        pytest.skip("실측 파일 없음 — 로컬 데이터가 있을 때만 도는 회귀 테스트")

    df = pd.concat([pd.read_excel(p, header=1) for p in paths], ignore_index=True)

    def _num(col):
        return pd.to_numeric(
            df[col].astype(str).str.replace(",", "", regex=False).str.extract(r"(-?[\d.]+)")[0],
            errors="coerce",
        )

    a_true, est, low = _num("A값"), _num("예정가격"), _num("낙찰하한가")

    checked = matched = 0
    total_true = total_derived = 0
    for i in range(len(df)):
        if pd.isna(a_true[i]) or pd.isna(est[i]) or pd.isna(low[i]) or est[i] <= 0:
            continue
        checked += 1
        legal, _eff, a_derived = split_limit_rates(int(est[i]), int(low[i]), None)
        # 정답 법정율: A값을 알 때의 (낙찰하한가 − A) / (예정가격 − A)
        r_true = (Decimal(str(low[i])) - Decimal(str(a_true[i]))) / (
            Decimal(str(est[i])) - Decimal(str(a_true[i]))
        )
        if legal is not None and abs(float(legal) - float(r_true)) < 1e-5:
            matched += 1
        total_true += a_true[i]
        total_derived += a_derived

    assert checked >= 100, f"검증 표본이 너무 적다 ({checked}건)"
    assert matched == checked, f"법정율 오분류 {checked - matched}/{checked}건"
    assert total_derived == pytest.approx(total_true, rel=1e-4)


def test_split_limit_rates_without_lower_limit_price():
    """낙찰하한가가 없으면 A값을 알 수 없다 — 신고값을 양쪽에 그대로 둔다."""
    legal, eff, a = split_limit_rates(143_317_675, None, Decimal("0.87745"))
    assert legal == Decimal("0.87745")
    assert eff == Decimal("0.87745")
    assert a == 0


# ── 투찰가 공식 ────────────────────────────────────────────────


def test_bid_price_with_a_value_hits_the_floor():
    """
    A값을 반영하면 낙찰하한가에 정확히 붙는다.
    (offset=0, 예정가격/A값/하한율 모두 실측값)
    """
    price = bid_price_with_a_value(328_577_900, 6_971_600, Decimal("0.88"))
    assert price == pytest.approx(289_985_144, abs=2)


def test_ignoring_a_value_falls_below_the_floor():
    """A값을 빼먹으면 하한가 아래로 떨어져 부적격 탈락한다."""
    naive = bid_price_with_a_value(328_577_900, 0, Decimal("0.88"))
    assert naive < 289_985_144
    assert 289_985_144 - naive == pytest.approx(836_592, abs=10)


def test_calculate_single_backward_compatible():
    """a_value=0이면 기존 공식 base_price × predicted_rate × (LLR+offset)과 같다."""
    base_price = 1_000_000_000
    llr = Decimal("0.89745")
    predicted = Decimal("1.0")
    offset = Decimal("0.001")

    got = calculate_single(base_price, llr, predicted, offset)
    expected = int(Decimal(base_price) * predicted * (llr + offset))

    assert got["price_krw"] == expected
    assert got["a_value"] == 0


def test_calculate_single_with_a_value_is_higher():
    """A값이 있으면 같은 offset에서 투찰가가 더 높다."""
    base_price = 328_577_900
    llr = Decimal("0.88")

    without = calculate_single(base_price, llr, Decimal("1.0"), Decimal("0"), a_value=0)
    with_a = calculate_single(base_price, llr, Decimal("1.0"), Decimal("0"), a_value=6_971_600)

    assert with_a["price_krw"] > without["price_krw"]
    assert with_a["rate_pct"] > without["rate_pct"]
    assert with_a["a_value"] == 6_971_600


def test_calculate_single_rejects_a_value_above_expected_price():
    """A값이 예정가격을 넘는 이상값이면 무시하고 A값 없이 계산한다."""
    got = calculate_single(100_000_000, Decimal("0.88"), Decimal("1.0"), Decimal("0"),
                           a_value=200_000_000)
    assert got["a_value"] == 0
    assert got["price_krw"] == 88_000_000


# ── 분포상 내 위치 (A값 조정) ──────────────────────────────────────

from app.engine.distribution import calc_my_position


def _bins(*offsets: float) -> list[dict]:
    return [
        {"offset_pct": o, "count": 10, "win_count": 1, "historical_win_rate": 10.0}
        for o in offsets
    ]


def _price_at(base_price: int, llr: Decimal, offset_pct: float, a: int) -> int:
    """분포 축(조정 투찰율) 기준 offset을 실제 투찰금액으로 되돌린다."""
    rate = llr + Decimal(str(offset_pct)) / Decimal(100)
    return int((Decimal(base_price) - Decimal(a)) * rate + Decimal(a))


def test_my_position_a_value_zero_matches_legacy():
    """a_value=0이면 기존 계산과 동일하다."""
    base, llr = 100_000_000, Decimal("0.87745")
    price = _price_at(base, llr, -0.7, 0)
    bins = _bins(-0.8, -0.7, -0.5)

    assert calc_my_position(price, base, llr, bins, 0) == calc_my_position(
        price, base, llr, bins
    )


def test_my_position_uses_adjusted_bid_rate():
    """
    분포 x축은 조정 투찰율 (투찰금액−A)/(예정가격−A) 기준이다.
    A값을 넘기면 같은 offset으로 돌아와야 한다.
    """
    base, llr, a = 100_000_000, Decimal("0.87745"), 5_000_000
    price = _price_at(base, llr, -0.7, a)

    pos = calc_my_position(price, base, llr, _bins(-0.8, -0.7, -0.5), a)
    assert pos is not None
    assert pos["offset_pct"] == pytest.approx(-0.7)


def test_my_position_without_a_value_shifts_right():
    """A값 공고인데 A값을 빼먹으면 위치가 오른쪽으로 밀린다."""
    base, llr, a = 100_000_000, Decimal("0.87745"), 5_000_000
    price = _price_at(base, llr, -0.7, a)
    bins = _bins(-2.0, -0.7, 0.0, 2.0)

    correct = calc_my_position(price, base, llr, bins, a)
    forgotten = calc_my_position(price, base, llr, bins, 0)

    assert correct is not None and correct["offset_pct"] == pytest.approx(-0.7)
    # 매칭 bin이 없으면 None — 그것 자체가 "축을 벗어났다"는 신호다
    if forgotten is not None:
        assert forgotten["offset_pct"] > correct["offset_pct"]


def test_my_position_estimated_price_round_trips():
    """estimated_price는 입력 투찰가를 되돌려준다 (bin 반올림 오차 범위)."""
    base, llr, a = 100_000_000, Decimal("0.87745"), 5_000_000
    price = _price_at(base, llr, -0.7, a)

    pos = calc_my_position(price, base, llr, _bins(-0.7), a)
    assert pos is not None
    assert pos["estimated_price"] == pytest.approx(price, abs=100)


def test_my_position_ignores_a_value_above_base_price():
    base, llr = 100_000_000, Decimal("0.87745")
    price = _price_at(base, llr, -0.7, 0)

    pos = calc_my_position(price, base, llr, _bins(-0.7), base * 2)
    assert pos is not None
    assert pos["offset_pct"] == pytest.approx(-0.7)


# ── 투찰 유효 조건 (부호 규약) ─────────────────────────────────


def test_bid_is_valid_only_when_assumed_rate_exceeds_actual():
    """내가 건 사정률이 실제보다 **높아야** 유효하다.

    투찰가 ≥ 실제 낙찰하한가 이어야 하는데, 양쪽 모두
    `(기초금액 × 사정률 − A) × r + A` 꼴이므로 부등식이 사정률 비교로 줄어든다:

        (기초×c − A)·r + A  ≥  (기초×실제 − A)·r + A   ⟺   c ≥ 실제

    이 부호를 뒤집으면 "낮게 걸수록 유효" 라는 정반대 결론이 나온다.
    실제로 한 번 뒤집어 계산해 최적 사정률을 100.05 로 잘못 잡았다
    (정정값 100.15). 자사 투찰 151건에서 151/151 로 확인된 규약이다.
    """
    base, a, r = 800_000_000, 30_000_000, Decimal("0.87745")

    def floor_at(rate: Decimal) -> int:
        expected = int(Decimal(base) * rate)
        return bid_price_with_a_value(expected, a, r)

    actual = floor_at(Decimal("1.0010"))          # 실제 사정률 100.10%

    # 높게 걸면 유효 (내 투찰가가 실제 하한가 이상)
    assert floor_at(Decimal("1.0015")) >= actual
    # 낮게 걸면 무효
    assert floor_at(Decimal("1.0005")) < actual
    # 정확히 맞히면 경계에서 유효
    assert floor_at(Decimal("1.0010")) >= actual


def test_fixed_preprice_rate_sits_above_market_median():
    """고정 사정률은 실제 사정률 중앙값보다 위여야 한다.

    아래로 두면 절반 넘게 하한 미달로 실격한다 — 실측 무효율 67% 가 그 상태였다.
    """
    from app.api.v1.bidding import FIXED_PREPRICE_RATE

    # 자사 투찰 151건의 실제 사정률 중앙값 100.1059%
    assert FIXED_PREPRICE_RATE > Decimal("1.001059")
    # 그렇다고 너무 높으면 유효하기만 하고 낙찰선에서 멀어진다 (c=100.5 → 근접 6건)
    assert FIXED_PREPRICE_RATE < Decimal("1.003")
