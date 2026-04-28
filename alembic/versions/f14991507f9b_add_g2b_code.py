"""add_g2b_code

Revision ID: f14991507f9b
Revises: e8a1c3f90b27
Create Date: 2026-04-04 16:01:16.942791

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f14991507f9b'
down_revision: Union[str, Sequence[str], None] = 'e8a1c3f90b27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # g2b_code 컬럼 추가
    op.add_column('bids_history', sa.Column('g2b_code', sa.String(length=50), nullable=True))

    # 기존 unique constraint 제거 후 unique index로 교체
    with op.batch_alter_table('bids_history') as batch_op:
        batch_op.drop_constraint('bids_history_project_id_key', type_='unique')

    op.drop_index(op.f('ix_bids_history_project_id'), table_name='bids_history')
    op.create_index(op.f('ix_bids_history_project_id'), 'bids_history', ['project_id'], unique=True)
    op.create_index(op.f('ix_bids_history_g2b_code'), 'bids_history', ['g2b_code'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_bids_history_g2b_code'), table_name='bids_history')
    op.drop_index(op.f('ix_bids_history_project_id'), table_name='bids_history')
    op.create_index(op.f('ix_bids_history_project_id'), 'bids_history', ['project_id'], unique=False)

    with op.batch_alter_table('bids_history') as batch_op:
        batch_op.create_unique_constraint('bids_history_project_id_key', ['project_id'])

    op.drop_column('bids_history', 'g2b_code')
