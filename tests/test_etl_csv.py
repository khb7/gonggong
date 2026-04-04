"""
scripts/etl_csv.py 신규 컬럼 처리 테스트.
DB 연결 없이 extract_and_transform() 만 검증한다.
"""
import io
import sys
import os
import pytest
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from pathlib import Path
from scripts.etl_csv import extract_and_transform, normalize_price_method


# ── 헬퍼 ────────────────────────────────────────────────────────────────────

def make_csv(rows: list[dict]) -> Path:
    """임시 CSV 파일 생성 후 Path 반환."""
    import tempfile
    df = pd.DataFrame(rows)
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w",
                                     encoding="utf-8-sig")
    df.to_csv(tmp.name, index=False)
    return Path(tmp.name)


BASE_ROW = {
    "입찰공고번호": "TEST-001",
    "개찰순위": "1",
    "면허업종제한목록": "실내건축공사업[0002]",
    "낙찰하한율": "87.745",
    "기초금액": "100000000",
    "예산가격": "100000000",   # adjustment_rate = 1.0
    "투찰금액": "87745000",
    "입찰참여자수": "42",
    "투찰일자": "2025-01-15",
    "낙찰방법": "적격심사",
    "수요기관": "테스트기관",
    "수요기관지역": "경기",
    "수요기관사업자등록번호": "123-45-67890",
}


# ── price_method 정규화 ──────────────────────────────────────────────────────

def test_normalize_price_method_복수예비가격():
    assert normalize_price_method("복수예비가격") == "복수예비가격"

def test_normalize_price_method_고정예정가격():
    assert normalize_price_method("고정예정가격") == "고정예정가격"

def test_normalize_price_method_unknown():
    assert normalize_price_method("기타방식") == "기타"

def test_normalize_price_method_empty():
    assert normalize_price_method("") == "기타"


# ── price_method 컬럼 매핑 ───────────────────────────────────────────────────

def test_price_method_mapped_when_column_exists():
    row = {**BASE_ROW, "예정가격결정방식": "복수예비가격"}
    path = make_csv([row])
    df = extract_and_transform(path)
    assert len(df) == 1
    assert df.iloc[0]["price_method"] == "복수예비가격"


def test_price_method_default_when_column_missing():
    path = make_csv([BASE_ROW])
    df = extract_and_transform(path)
    assert len(df) == 1
    assert df.iloc[0]["price_method"] == "기타"


# ── 1순위사정율 처리 ─────────────────────────────────────────────────────────

def test_adjustment_rate_from_1순위사정율_when_column_exists():
    """1순위사정율 컬럼이 있으면 직접 사용한다 (퍼센트 → 소수 변환)."""
    row = {**BASE_ROW, "1순위사정율": "99.5"}  # 퍼센트 단위
    path = make_csv([row])
    df = extract_and_transform(path)
    assert len(df) == 1
    assert abs(float(df.iloc[0]["adjustment_rate"]) - 0.995) < 0.0001


def test_adjustment_rate_computed_when_column_missing():
    """1순위사정율 컬럼이 없으면 예산가격/기초금액으로 계산한다."""
    path = make_csv([BASE_ROW])
    df = extract_and_transform(path)
    assert len(df) == 1
    # 예산가격=기초금액=100000000 → adjustment_rate = 1.0
    assert abs(float(df.iloc[0]["adjustment_rate"]) - 1.0) < 0.0001


# ── g2b_code 처리 ────────────────────────────────────────────────────────────

def test_g2b_code_stored_when_column_exists():
    row = {**BASE_ROW, "g2b분류": "C081"}
    path = make_csv([row])
    df = extract_and_transform(path)
    assert len(df) == 1
    assert df.iloc[0]["g2b_code"] == "C081"


def test_g2b_code_none_when_column_missing():
    path = make_csv([BASE_ROW])
    df = extract_and_transform(path)
    assert len(df) == 1
    assert df.iloc[0]["g2b_code"] is None


# ── 기존 기능 회귀 테스트 ────────────────────────────────────────────────────

def test_participants_stored_correctly():
    path = make_csv([BASE_ROW])
    df = extract_and_transform(path)
    assert df.iloc[0]["participants"] == 42


def test_lower_limit_rate_converted_from_percent():
    """낙찰하한율 87.745 → 0.87745 변환 확인."""
    path = make_csv([BASE_ROW])
    df = extract_and_transform(path)
    assert abs(float(df.iloc[0]["lower_limit_rate"]) - 0.87745) < 0.000001


def test_region_stored_correctly():
    path = make_csv([BASE_ROW])
    df = extract_and_transform(path)
    assert df.iloc[0]["region"] == "경기"
