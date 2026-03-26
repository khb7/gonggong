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

from sqlalchemy import BigInteger, Date, DateTime, Float, Integer, Numeric, String, func
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
    project_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="공종 (실내건축/조경 등)")

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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
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
