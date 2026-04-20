"""add base_rate vs_lower_limit to bid_participants

Revision ID: 54acb1bf74ff
Revises: f14991507f9b
Create Date: 2026-04-16 11:40:30.615325

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '54acb1bf74ff'
down_revision: Union[str, Sequence[str], None] = 'f14991507f9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bid_participants", sa.Column("base_rate", sa.Numeric(10, 6), nullable=True, comment="기초대비율 = 투찰금액 / 기초금액"))
    op.add_column("bid_participants", sa.Column("vs_lower_limit", sa.Numeric(10, 6), nullable=True, comment="예비가격대비율 (낙찰하한율 기준 차이, %p)"))


def downgrade() -> None:
    op.drop_column("bid_participants", "vs_lower_limit")
    op.drop_column("bid_participants", "base_rate")
