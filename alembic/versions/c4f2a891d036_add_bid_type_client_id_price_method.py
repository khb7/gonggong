"""add bid_type, client_id, price_method to bids_history

Revision ID: c4f2a891d036
Revises: a3f9e1c72b08
Create Date: 2026-03-27
"""

from alembic import op
import sqlalchemy as sa

revision = "c4f2a891d036"
down_revision = "a3f9e1c72b08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # bid_type: 입찰방식. 기존 데이터는 '기타'로 채움
    op.add_column(
        "bids_history",
        sa.Column(
            "bid_type",
            sa.String(20),
            nullable=False,
            server_default="기타",
            comment="입찰방식: 적격심사 / 최저가 / 협상 / 기타",
        ),
    )
    op.create_index("ix_bids_history_bid_type", "bids_history", ["bid_type"])

    # client_id: 나라장터 발주청 코드. 기존 데이터는 NULL
    op.add_column(
        "bids_history",
        sa.Column(
            "client_id",
            sa.String(20),
            nullable=True,
            comment="나라장터 발주청 코드",
        ),
    )
    op.create_index("ix_bids_history_client_id", "bids_history", ["client_id"])

    # price_method: 예정가격 결정방식. 기존 데이터는 '기타'로 채움
    op.add_column(
        "bids_history",
        sa.Column(
            "price_method",
            sa.String(30),
            nullable=False,
            server_default="기타",
            comment="예정가격 결정방식: 복수예비가격 / 고정예정가격 / 기타",
        ),
    )


def downgrade() -> None:
    op.drop_column("bids_history", "price_method")
    op.drop_index("ix_bids_history_client_id", "bids_history")
    op.drop_column("bids_history", "client_id")
    op.drop_index("ix_bids_history_bid_type", "bids_history")
    op.drop_column("bids_history", "bid_type")
