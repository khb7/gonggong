"""add bid_participants table

Revision ID: e8a1c3f90b27
Revises: c4f2a891d036
Create Date: 2026-03-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import NUMERIC

revision = "e8a1c3f90b27"
down_revision = "c4f2a891d036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bid_participants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(50), nullable=False, comment="나라장터 공고 번호"),
        sa.Column("rank", sa.Integer(), nullable=False, comment="개찰순위"),
        sa.Column("bid_amount", sa.BigInteger(), nullable=False, comment="투찰금액 (원)"),
        sa.Column("bid_rate", NUMERIC(10, 6), nullable=False, comment="투찰율 = 투찰금액 / 예정가격"),
        sa.Column("is_winner", sa.Boolean(), nullable=False, server_default="false", comment="낙찰자 여부"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "rank", name="uq_bid_participants_project_rank"),
    )
    op.create_index("ix_bid_participants_project_id", "bid_participants", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_bid_participants_project_id", "bid_participants")
    op.drop_table("bid_participants")
