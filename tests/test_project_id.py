from datetime import date, datetime

from app.etl.project_id import (
    canonical_project_id,
    is_military_notice_no,
    lookup_pattern,
    split_project_id,
)


def test_military_number_gets_open_year():
    assert canonical_project_id("LPK0148-1", date(2026, 9, 8)) == "LPK0148-1@2026"
    assert canonical_project_id(" UMM0535-1 ", datetime(2026, 8, 26, 11, 0)) == "UMM0535-1@2026"


def test_g2b_numbers_untouched():
    for raw in ("R26BK01705597-000", "20241234791-00", "E012600944-1", "2026-14249"):
        assert canonical_project_id(raw, date(2026, 1, 1)) == raw


def test_without_year_returns_raw_not_invented():
    # 연도를 모르면 지어내지 않는다 — 충돌 가능성은 남지만 없는 값을 채우지 않는다
    assert canonical_project_id("LPK0148-1", None) == "LPK0148-1"


def test_already_canonical_is_idempotent():
    assert canonical_project_id("LPK0148-1@2025", date(2026, 1, 1)) == "LPK0148-1@2025"


def test_split_and_pattern():
    assert split_project_id("LPK0148-1@2026") == ("LPK0148-1", 2026)
    assert split_project_id("R26BK01705597-000") == ("R26BK01705597-000", None)
    assert lookup_pattern("LPK0148-1") == "LPK0148-1@%"
    assert lookup_pattern("R26BK01705597-000") is None
    assert is_military_notice_no("HDG0053-1") and not is_military_notice_no("HDG0053-1@2026")
