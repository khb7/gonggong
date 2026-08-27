"""
app/db/models.py
SQLAlchemy ORM 모델 정의

테이블:
  - bids_history      : 과거 입찰 결과 기록
  - client_statistics : 발주처별 사정률 통계 캐시
  - project_bucket    : 금액 구간 정의
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class BidsHistory(Base):
    """
    과거 입찰 결과 데이터.
    사정률(adjustment_rate) 분포 분석의 핵심 원천 데이터.
    """

    __tablename__ = "bids_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True, comment="나라장터 공고 번호")
    client_name: Mapped[str] = mapped_column(String(100), nullable=True, index=True, comment="발주처명")
    region: Mapped[str] = mapped_column(String(50), nullable=False, comment="지역")

    base_price: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="기초금액 (원)")
    lower_limit_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, comment="낙찰하한율 (예: 0.877450)"
    )
    adjustment_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, comment="실제 사정률 (개찰 후 공개값)"
    )
    winner_price: Mapped[int] = mapped_column(BigInteger, nullable=True, comment="낙찰가 (원)")
    participants: Mapped[int] = mapped_column(Integer, nullable=False, comment="참여 업체 수")
    bid_date: Mapped[date] = mapped_column(Date, nullable=True, index=True, comment="개찰 일자")

    # ── 2026-03-27 추가 ──────────────────────────────────────
    bid_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="기타", index=True,
        comment="입찰방식: 적격심사 / 최저가 / 협상 / 기타"
    )
    client_id: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True,
        comment="나라장터 발주청 코드 (없으면 NULL)"
    )
    price_method: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="기타",
        comment="예정가격 결정방식: 복수예비가격 / 고정예정가격 / 기타"
    )
    g2b_code: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True,
        comment="나라장터 공사 분류 코드 (g2b분류)"
    )

    # ── 2026-08-27 추가: A값 분리 ────────────────────────────
    #
    # lower_limit_rate 컬럼에는 두 가지 의미가 섞여 들어왔다.
    #   - 원본에 낙찰하한가가 있던 행 → A값이 녹아든 '실효' 하한율
    #   - 없던 행 / G2B 수집분        → A값이 빠진 '법정' 하한율
    # 아래 세 컬럼으로 의미를 분리한다. lower_limit_rate는 하위 호환용으로 유지.
    a_value: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0",
        comment="A값 = 투찰율 적용 제외 법정경비 합계 (원). 미상이면 0"
    )
    has_a_value: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="0", index=True,
        comment="A값 적용 공고 여부 (공고명 [A값] 태그 기준)"
    )
    legal_limit_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6), nullable=True,
        comment="법정 낙찰하한율 (A값 제외, 예: 0.877450)"
    )
    effective_limit_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 8), nullable=True,
        comment="실효 낙찰하한율 = 낙찰하한가 / 예정가격 (A값 포함)"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BidLicenseType(Base):
    """
    입찰 공고별 면허 업종 목록.

    bids_history의 project_type 단일 컬럼을 대체.
    하나의 공고는 여러 면허 업종을 동시에 요구할 수 있으며
    각 업종의 규모(대/소), 상호허용 여부, 주력 여부를 함께 저장한다.

    예) '건축,토건,실내건축[대](상호허용)' →
        {type_name: '건축',     size: None, is_mutual: False, is_primary: False}
        {type_name: '토건',     size: None, is_mutual: False, is_primary: False}
        {type_name: '실내건축', size: '대',  is_mutual: True,  is_primary: False}
    """

    __tablename__ = "bid_license_types"
    __table_args__ = (
        UniqueConstraint("project_id", "type_name", name="uq_bid_license_project_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="나라장터 공고 번호"
    )
    type_name: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True, comment="공종명 (예: 실내건축, 건축, 토건)"
    )
    size: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="면허 규모: 대 / 소 / None"
    )
    is_mutual: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="상호허용 여부"
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="주력 공종 여부 (주력: 태그)"
    )


class BidParticipants(Base):
    """
    입찰 공고별 전체 참여자 투찰 데이터.

    bids_history가 낙찰자(1위)의 사정률만 저장하는 반면,
    이 테이블은 모든 참여자의 투찰금액·투찰율을 저장한다.

    활용:
      - 경쟁 밀집 구간 파악 → 과밀 구간 회피 전략
      - 발주처·공종별 투찰 패턴 분포 분석
      - 끝자리 동적 블랙리스트 생성
      - 1~2위 마진 분석
    """

    __tablename__ = "bid_participants"
    __table_args__ = (
        UniqueConstraint("project_id", "rank", name="uq_bid_participants_project_rank"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="나라장터 공고 번호"
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, comment="개찰순위")
    bid_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="투찰금액 (원)")
    bid_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, comment="투찰율 = 투찰금액 / 예정가격"
    )
    base_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6), nullable=True, comment="기초대비율 = 투찰금액 / 기초금액"
    )
    vs_lower_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6), nullable=True, comment="예비가격대비율 (낙찰하한율 기준 차이, %p)"
    )
    is_winner: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="낙찰자 여부 (rank=1)"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BidPreliminaryPrice(Base):
    """
    복수예비가격 15개 데이터.

    개찰 후 공개되는 15개 예비가격과 추첨 선택 여부를 저장한다.
    2개가 추첨(is_selected=True)되어 평균 → 예정가격 결정.
    """

    __tablename__ = "bid_preliminary_prices"
    __table_args__ = (
        UniqueConstraint("project_id", "num", name="uq_bid_prelim_project_num"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="나라장터 공고 번호"
    )
    num: Mapped[int] = mapped_column(Integer, nullable=False, comment="예비가격 번호 (1~15)")
    price: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="예비가격 금액 (원)")
    base_pct: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, comment="기초금액 대비 편차 % (예: -1.9589)"
    )
    is_selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="추첨 선택 여부"
    )


class ClientStatistics(Base):
    """
    발주처별 사정률 통계 캐시.
    bids_history 에서 계산한 결과를 저장하여 빠른 조회를 지원한다.
    Fallback 우선순위 1순위.
    """

    __tablename__ = "client_statistics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    project_type: Mapped[str] = mapped_column(String(50), nullable=False)
    bucket_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="금액 구간 ID")

    median_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, comment="Trimmed Median 사정률")
    mad_rate: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, comment="MAD 값")
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, comment="사용된 데이터 수")

    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProjectBucket(Base):
    """
    금액 구간 정의.
    공종+금액 구간으로 데이터를 분리하기 위한 기준 테이블.
    초기 시드 데이터로 투입.
    """

    __tablename__ = "project_bucket"

    bucket_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    min_price: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="구간 최솟값 (원)")
    max_price: Mapped[int] = mapped_column(
        BigInteger, nullable=True, comment="구간 최댓값 (원, NULL=무제한)"
    )
    description: Mapped[str] = mapped_column(String(100), nullable=False)

    @staticmethod
    def get_bucket_id(base_price: int) -> int:
        """
        기초금액으로 bucket_id를 반환한다.
        (DB 조회 없이 빠른 인메모리 분류용)
        """
        if base_price < 100_000_000:       # 1억 미만
            return 1
        elif base_price < 500_000_000:     # 5억 미만
            return 2
        elif base_price < 2_000_000_000:   # 20억 미만
            return 3
        else:
            return 4
