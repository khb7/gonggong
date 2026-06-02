"""
app/db/normalize.py
bids_history 저장 전 텍스트 값을 정규화하는 유틸리티.

모든 ETL·수집 경로에서 이 모듈을 통해 정규화하여
쿼리 시 문자열 불일치 문제를 방지한다.
"""

# ── 공종 정규화 ────────────────────────────────────────────────

_PROJECT_TYPE_MAP: dict[str, str] = {
    # G2B API 반환값
    "건축공사업": "실내건축",
    "조경식재공사업": "조경",
    "조경공사업": "조경",
    # CSV ETL 값 (이미 정규화된 경우 그대로)
    "실내건축": "실내건축",
    "조경": "조경",
    # 코드값
    "0002": "실내건축",
    "0023": "조경",
}

VALID_PROJECT_TYPES = {"실내건축", "조경"}


def normalize_project_type(raw: str | None) -> str | None:
    """
    공종명을 정규화하여 반환한다.
    알 수 없는 값은 None 반환 → 수집 대상 제외.
    """
    if not raw:
        return None
    raw = raw.strip()
    # 직접 매핑 우선
    if raw in _PROJECT_TYPE_MAP:
        return _PROJECT_TYPE_MAP[raw]
    # 부분 문자열 매칭
    if "건축" in raw and "조경" not in raw:
        return "실내건축"
    if "조경" in raw:
        return "조경"
    return None


# ── 지역 정규화 ────────────────────────────────────────────────

_REGION_MAP: dict[str, str] = {
    # 특별시·광역시·특별자치시
    "서울특별시": "서울", "서울시": "서울", "서울": "서울",
    "부산광역시": "부산", "부산시": "부산", "부산": "부산",
    "대구광역시": "대구", "대구시": "대구", "대구": "대구",
    "인천광역시": "인천", "인천시": "인천", "인천": "인천",
    "광주광역시": "광주", "광주시": "광주", "광주": "광주",
    "대전광역시": "대전", "대전시": "대전", "대전": "대전",
    "울산광역시": "울산", "울산시": "울산", "울산": "울산",
    "세종특별자치시": "세종", "세종시": "세종", "세종": "세종",
    # 도
    "경기도": "경기", "경기": "경기",
    "강원도": "강원", "강원특별자치도": "강원", "강원": "강원",
    "충청북도": "충북", "충북": "충북",
    "충청남도": "충남", "충남": "충남",
    "전라북도": "전북", "전북특별자치도": "전북", "전북": "전북",
    "전라남도": "전남", "전남": "전남",
    "경상북도": "경북", "경북": "경북",
    "경상남도": "경남", "경남": "경남",
    "제주특별자치도": "제주", "제주도": "제주", "제주": "제주",
}

# 나라장터 지역코드 접미사 제거용 (예: "경기[41000]")
import re
_REGION_CODE_RE = re.compile(r"\[.*?\]")


# ── 면허업종 파싱 ────────────────────────────────────────────────

_SIZE_RE = re.compile(r"\[([대소])\]")          # [대] / [소]
_FIRST_BRACKET_RE = re.compile(r"[\[(]")        # 첫 번째 [ 또는 (


def parse_license_types(raw: str | None) -> list[dict]:
    """
    Info21c 면허업종제한목록 원문을 구조화된 리스트로 파싱한다.

    '건축,토건,실내건축[대](상호허용)' →
    [
        {"type_name": "건축",     "size": None, "is_mutual": False, "is_primary": False},
        {"type_name": "토건",     "size": None, "is_mutual": False, "is_primary": False},
        {"type_name": "실내건축", "size": "대",  "is_mutual": True,  "is_primary": False},
    ]

    규칙:
      - 쉼표(,) 구분자로 분리
      - [대] / [소]: size 필드
      - (상호허용): is_mutual = True
      - (주력:...): is_primary = True
      - type_name: 첫 번째 [ 또는 ( 이전 텍스트
    """
    if not raw:
        return []

    results: list[dict] = []
    seen: set[str] = set()

    for token in str(raw).split(","):
        token = token.strip()
        if not token:
            continue

        size_m = _SIZE_RE.search(token)
        size = size_m.group(1) if size_m else None
        is_mutual = "(상호허용)" in token
        is_primary = "(주력:" in token

        bracket_m = _FIRST_BRACKET_RE.search(token)
        type_name = token[: bracket_m.start()].strip() if bracket_m else token.strip()

        if not type_name or type_name in seen:
            continue
        seen.add(type_name)

        results.append({
            "type_name":  type_name,
            "size":       size,
            "is_mutual":  is_mutual,
            "is_primary": is_primary,
        })

    return results


def normalize_region(raw: str | None) -> str:
    """
    지역명을 시/도 단위 2글자로 정규화한다.
    인식 불가 시 'unknown' 반환.
    """
    if not raw:
        return "unknown"
    raw = _REGION_CODE_RE.sub("", raw).strip()

    # 직접 매핑 우선
    if raw in _REGION_MAP:
        return _REGION_MAP[raw]

    # 앞 단어 기반 매칭 (예: "경기도 수원시" → "경기")
    for key, val in _REGION_MAP.items():
        if raw.startswith(key):
            return val

    # 2글자 접두어로 재시도
    prefix = raw[:2]
    for key, val in _REGION_MAP.items():
        if key.startswith(prefix):
            return val

    return "unknown"


# ── 입찰방식 정규화 ────────────────────────────────────────────

_BID_TYPE_MAP: dict[str, str] = {
    "적격심사": "적격심사",
    "적격": "적격심사",
    "최저가낙찰": "최저가",
    "최저가": "최저가",
    "협상에의한계약": "협상",
    "협상에 의한 계약": "협상",
    "협상": "협상",
}

VALID_BID_TYPES = {"적격심사", "최저가", "협상", "기타"}


def normalize_bid_type(raw: str | None) -> str:
    """
    입찰방식을 정규화한다. 알 수 없는 값은 '기타' 반환.
    """
    if not raw:
        return "기타"
    raw = raw.strip()
    if raw in _BID_TYPE_MAP:
        return _BID_TYPE_MAP[raw]
    for key, val in _BID_TYPE_MAP.items():
        if key in raw:
            return val
    return "기타"


# ── 예정가격 결정방식 정규화 ──────────────────────────────────

_PRICE_METHOD_MAP: dict[str, str] = {
    "복수예비가격": "복수예비가격",
    "복수예비": "복수예비가격",
    "고정예정가격": "고정예정가격",
    "고정": "고정예정가격",
    "기초금액의일정비율": "고정예정가격",
}

VALID_PRICE_METHODS = {"복수예비가격", "고정예정가격", "기타"}


def normalize_price_method(raw: str | None) -> str:
    """
    예정가격 결정방식을 정규화한다. 알 수 없는 값은 '기타' 반환.
    """
    if not raw:
        return "기타"
    raw = raw.strip()
    if raw in _PRICE_METHOD_MAP:
        return _PRICE_METHOD_MAP[raw]
    for key, val in _PRICE_METHOD_MAP.items():
        if key in raw:
            return val
    return "기타"
