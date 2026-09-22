"""
app/engine/preprice_histogram.py
과거 실제 사정률(예정가격/기초금액)의 히스토그램.

투찰가 계산에서 사용자가 사정률 c 를 직접 넣을 수 있다 (T-038). c 는 예측이
아니라 선택이고, 그 선택의 결과는 단 하나의 부등식으로 정해진다:

    투찰가 유효  ⟺  c ≥ 실제 사정률        (A값이 있어도 같다 — bidding.py 참조)

그래서 "이 c 를 넣으면 어떻게 되나" 는 과거 실제 사정률 분포 위에 c 를 긋는
것으로 답이 된다. 여기서는 그 분포를 bin 별 개수로만 만든다. 유효율·근접률은
프론트에서 c 를 움직일 때마다 이 개수로 계산한다.

bin 은 복수예비가격 생성범위(최대 ±3%)를 덮는 97~103%, 폭 0.05%p 다.
근접 판정 폭(0.10%p)이 bin 두 개에 정확히 맞는다.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from app.engine import contract_law

BIN_START = Decimal("0.970")
BIN_WIDTH = Decimal("0.0005")
N_BINS = 120
_BIN_END = BIN_START + BIN_WIDTH * N_BINS   # 1.030


@dataclass(frozen=True)
class PrepriceHistogram:
    law: str
    n: int
    bin_start: Decimal
    bin_width: Decimal
    counts: list[int]


def build_preprice_histogram(
    rows: Iterable[tuple[str | None, Decimal | None]],
    law: str,
) -> PrepriceHistogram:
    """(발주처명, 사정률) 행에서 계약법이 같은 공고만 골라 bin 별로 센다.

    law 가 UNKNOWN 이면 전체를 쓴다 — 모르면 넓게 잡는 쪽이 안전하다.
    범위 밖 값과 None 은 버린다. 규정상 나올 수 없는 값이라 데이터 오류다.
    """
    counts = [0] * N_BINS
    n = 0
    for client_name, rate in rows:
        if rate is None:
            continue
        if law != contract_law.UNKNOWN and contract_law.classify(client_name) != law:
            continue
        rate = Decimal(rate)
        if rate < BIN_START or rate > _BIN_END:
            continue
        idx = int((rate - BIN_START) / BIN_WIDTH)
        if idx == N_BINS:            # 정확히 상한(1.030)인 값은 마지막 bin
            idx = N_BINS - 1
        counts[idx] += 1
        n += 1
    return PrepriceHistogram(
        law=law, n=n, bin_start=BIN_START, bin_width=BIN_WIDTH, counts=counts,
    )
