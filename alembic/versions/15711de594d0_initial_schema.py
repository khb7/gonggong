"""
alembic/versions/15711de594d0_initial_schema.py

초기 스키마 생성:
  - bids_history       : 과거 입찰 결과
  - client_statistics  : 발주처별 사정률 통계 캐시
  - project_bucket     : 금액 구간 정의 + 시드 데이터

Revision ID: 15711de594d0
Revises:
Create Date: 2026-03-11
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import NUMERIC

revision = "15711de594d0"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── project_bucket ──────────────────────────────────────
    op.create_table(
        "project_bucket",
        sa.Column("bucket_id", sa.Integer(), primary_key=True),
        sa.Column("min_price", sa.BigInteger(), nullable=False),
        sa.Column("max_price", sa.BigInteger(), nullable=True),
        sa.Column("description", sa.String(100), nullable=False),
    )

    # 시드 데이터 삽입
    op.execute("""
        INSERT INTO project_bucket (bucket_id, min_price, max_price, description)
        VALUES
            (1,          0,   100000000, '소형 (<1억) — 초정밀 소수점 경쟁'),
            (2,  100000000,   500000000, '표준 (1~5억)'),
            (3,  500000000,  2000000000, '중형 (5~20억)'),
            (4, 2000000000,        NULL, '대형 (20억+) — 보수적 투찰')
    """)

    # ── bids_history ─────────────────────────────────────────
    op.create_table(
        "bids_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(50), nullable=False),
        sa.Column("client_name", sa.String(100), nullable=False),
        sa.Column("region", sa.String(50), nullable=False),
        sa.Column("project_type", sa.String(50), nullable=False),
        sa.Column("base_price", sa.BigInteger(), nullable=False),
        sa.Column("lower_limit_rate", NUMERIC(10, 6), nullable=False),
        sa.Column("adjustment_rate", NUMERIC(10, 6), nullable=False),
        sa.Column("winner_price", sa.BigInteger(), nullable=True),
        sa.Column("participants", sa.Integer(), nullable=False),
        sa.Column("bid_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_bids_history_project_id", "bids_history", ["project_id"])
    op.create_index("ix_bids_history_client_name", "bids_history", ["client_name"])
    op.create_index("ix_bids_history_bid_date", "bids_history", ["bid_date"])

    # ── client_statistics ────────────────────────────────────
    op.create_table(
        "client_statistics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_name", sa.String(100), nullable=False),
        sa.Column("project_type", sa.String(50), nullable=False),
        sa.Column("bucket_id", sa.Integer(), nullable=False),
        sa.Column("median_rate", NUMERIC(10, 6), nullable=False),
        sa.Column("mad_rate", NUMERIC(10, 6), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_client_statistics_client_name", "client_statistics", ["client_name"])


def downgrade() -> None:
    op.drop_table("client_statistics")
    op.drop_index("ix_bids_history_bid_date", "bids_history")
    op.drop_index("ix_bids_history_client_name", "bids_history")
    op.drop_index("ix_bids_history_project_id", "bids_history")
    op.drop_table("bids_history")
    op.drop_table("project_bucket")
