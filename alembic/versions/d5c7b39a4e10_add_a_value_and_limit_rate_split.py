"""add_a_value_and_limit_rate_split

A값(법정경비) 컬럼과 법정/실효 낙찰하한율 분리 컬럼을 추가한다.

기존 lower_limit_rate 에는 두 가지 의미가 섞여 있었다:
  - 원본에 낙찰하한가가 있던 행 → A값이 녹아든 '실효' 하한율
  - 없던 행 / G2B 수집분        → A값이 빠진 '법정' 하한율

Ref: md/reference/공공입찰_제도_가이드.md - 6. A값

Revision ID: d5c7b39a4e10
Revises: a6e041fc9944
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd5c7b39a4e10'
down_revision: Union[str, Sequence[str], None] = 'a6e041fc9944'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'bids_history',
        sa.Column('a_value', sa.BigInteger(), nullable=False, server_default='0'),
    )
    op.add_column(
        'bids_history',
        sa.Column('has_a_value', sa.Boolean(), nullable=False, server_default='0'),
    )
    op.add_column(
        'bids_history',
        sa.Column('legal_limit_rate', sa.Numeric(10, 6), nullable=True),
    )
    op.add_column(
        'bids_history',
        sa.Column('effective_limit_rate', sa.Numeric(12, 8), nullable=True),
    )
    op.create_index(
        op.f('ix_bids_history_has_a_value'), 'bids_history', ['has_a_value'], unique=False
    )

    # 기존 행 백필: 두 컬럼 모두 lower_limit_rate로 채운다.
    # 이 시점에는 A값을 알 수 없으므로 법정=실효로 두고,
    # ETL 재적재 시 실제 값으로 덮어쓴다.
    op.execute(
        "UPDATE bids_history "
        "SET legal_limit_rate = lower_limit_rate, "
        "    effective_limit_rate = lower_limit_rate "
        "WHERE legal_limit_rate IS NULL"
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_bids_history_has_a_value'), table_name='bids_history')
    op.drop_column('bids_history', 'effective_limit_rate')
    op.drop_column('bids_history', 'legal_limit_rate')
    op.drop_column('bids_history', 'has_a_value')
    op.drop_column('bids_history', 'a_value')
