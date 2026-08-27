"""
app/engine/contract_law.py
발주처 → 적용 계약법 판별과, 거기서 따라오는 사정률 산포.

복수예비가격 생성범위는 **규정으로 정해져 있다**:

    국가계약법 적용 → 기초금액 ±2% 범위에서 15개 생성
    지방계약법 적용 → 기초금액 ±3% 범위에서 15개 생성
                     (그중 4개 추첨 → 산술평균 = 예정가격)

따라서 사정률(예정가격/기초금액)의 산포는 추정 대상이 아니라 제도가 정한 값이다.
강민석·류문찬(2015) Table 3 의 이론 표준편차: ±2% → 0.513% / ±3% → 0.767%.

DB 12,010 공고 실측이 이를 재현한다:

    분류   공고     평균       sd%      MAD%     이론 sd
    국가   2,435   1.00057   0.549    0.3774   0.513 (±2%)
    지방   8,527   0.99874   0.744    0.5191   0.767 (±3%)
    대행     636   0.99940   0.708    0.4769   혼합
    불명     412   0.99922   0.601    0.3909   —

평균이 갈리는 것도 같은 논문이 예측한 그대로다 — 조달청·공공기관은 균등분할이라
평균이 기초금액과 같고(1.00057), 지자체는 비균등분할-A1 이라 99.9% 로 내려간다(0.99874).

⚠ 이 값들은 **중심값을 옮기는 데 쓰지 않는다.** 자사 투찰 151건 검정에서
   국가/지방으로 중심을 가르면 전역 고정보다 오히려 나빴다
   (하한가 ±0.10%p 근접 19건 → 16건). 시장 군별 평균이 자사가 실제로 만나는
   공고를 대표하지 못하기 때문이다. 근거: tasks.md T-020.
   산포는 그 편향의 영향을 받지 않으므로 이쪽만 쓴다.
"""

import re
from decimal import Decimal

NATIONAL = "national"
LOCAL = "local"
AGENCY = "agency"      # 지방조달청 — 지자체 조달 대행이라 국가/지방이 섞인다
UNKNOWN = "unknown"

# 판별 순서가 중요하다:
#   "조달청 인천지방조달청" 에는 '지방' 이, "육군" 은 `\S+군$` 에 걸린다.
_AGENCY_RE = re.compile(r"^조달청\s*\S*지방조달청")

_NATIONAL_RE = re.compile(
    # 군
    r"(국군|육군|해군|공군|해병|사단|군단|여단|사령부|근무지원단|제\d+부대"
    r"|방위사업청|국방|병무청"
    # 중앙행정기관·소속기관
    r"|국토교통부|국토관리청|국토관리사무소|환경청|보훈청|경찰청|소방청"
    # 중앙 공공기관 — '한국' 으로 시작하는 곳은 대부분 여기다
    r"|^한국|국가철도공단|중소기업은행|인천국제공항"
    # 교육·연구
    r"|국립|대학교|대학원|폴리텍"
    # 공단·원 계열 (지방시설관리공단은 아래 LOCAL 에서 먼저 걸린다)
    r"|공단|연구원|진흥원|관리단|평가원)"
)

_LOCAL_RE = re.compile(
    r"(교육청|교육지원청|특별시|광역시|자치도|도청|시청|군청|구청"
    r"|도시공사|도시관광공사|시설관리공단"
    # 지역명으로 시작하면 지방자치단체 또는 그 출자기관이다
    r"|^경기|^강원|^충청|^충북|^충남|^전라|^전북|^전남|^경상|^경북|^경남|^제주"
    r"|^서울|^부산|^대구|^인천|^광주|^대전|^울산|^세종"
    r"|\S+시$|\S+군$|\S+구$)"
)

# 사정률 표준편차 (소수). 위 실측표 기준.
# 불명은 전체 혼합값을 쓴다 — 모르면 넓게 잡는 쪽이 안전하다.
PREPRICE_SD: dict[str, Decimal] = {
    NATIONAL: Decimal("0.00549"),
    LOCAL: Decimal("0.00744"),
    AGENCY: Decimal("0.00708"),
    UNKNOWN: Decimal("0.00706"),
}

# 같은 표의 MAD. 중앙값 기준 절대편차라 극단값에 강건하다.
PREPRICE_MAD: dict[str, Decimal] = {
    NATIONAL: Decimal("0.003774"),
    LOCAL: Decimal("0.005191"),
    AGENCY: Decimal("0.004769"),
    UNKNOWN: Decimal("0.004856"),
}


def classify(client_name: str | None) -> str:
    """발주처명에서 적용 계약법을 판별한다.

    이름 규칙과 실측 sd 를 대조하면 40건 이상 발주처 76개 중 89.5% 가 일치한다.
    불일치는 거의 전부 지방조달청이었고, 그건 오분류가 아니라 실제로 혼합이라
    별도 범주(AGENCY)로 뒀다 — 지역별 sd 가 0.602(충북)~0.793(부산) 로 흩어진다.
    """
    if not client_name:
        return UNKNOWN
    name = str(client_name).strip()
    if not name or name == "None":
        return UNKNOWN

    if _AGENCY_RE.match(name):
        return AGENCY
    if name == "조달청":
        return NATIONAL
    if _NATIONAL_RE.search(name):
        return NATIONAL
    if _LOCAL_RE.search(name):
        return LOCAL
    return UNKNOWN


def preprice_sd(client_name: str | None) -> Decimal:
    """이 발주처 공고의 사정률 표준편차 (소수)."""
    return PREPRICE_SD[classify(client_name)]


def preprice_mad(client_name: str | None) -> Decimal:
    """이 발주처 공고의 사정률 MAD (소수)."""
    return PREPRICE_MAD[classify(client_name)]
