"""add_bid_license_types

Revision ID: b7e2d4f8a1c3
Revises: f14991507f9b
Create Date: 2026-04-28

bids_history.project_type (단일 문자열) →
bid_license_types 테이블 (공고별 면허 업종 목록, 다대다)

각 공종 토큰의 규모(대/소), 상호허용 여부, 주력 여부를 컬럼으로 분리.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7e2d4f8a1c3'
down_revision: Union[str, Sequence[str], None] = 'f14991507f9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. bid_license_types 테이블 생성
    op.create_table(
        'bid_license_types',
        sa.Column('id',         sa.Integer(),     autoincrement=True, nullable=False),
        sa.Column('project_id', sa.String(50),    nullable=False),
        sa.Column('type_name',  sa.String(100),   nullable=False),
        sa.Column('size',       sa.String(10),    nullable=True),
        sa.Column('is_mutual',  sa.Boolean(),     nullable=False, server_default='false'),
        sa.Column('is_primary', sa.Boolean(),     nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'type_name', name='uq_bid_license_project_type'),
    )
    op.create_index('ix_bid_license_types_project_id', 'bid_license_types', ['project_id'])
    op.create_index('ix_bid_license_types_type_name',  'bid_license_types', ['type_name'])

    # 2. 기존 bids_history.project_type 데이터 → bid_license_types 이관
    #    (is_primary=true, is_mutual=false, size=null)
    op.execute("""
        INSERT OR IGNORE INTO bid_license_types (project_id, type_name, size, is_mutual, is_primary)
        SELECT project_id, project_type, NULL, 0, 1
        FROM bids_history
        WHERE project_type IS NOT NULL AND project_type <> ''
    """)

    # 3. project_type 컬럼 삭제 (SQLite는 batch 모드 필요)
    with op.batch_alter_table('bids_history') as batch_op:
        batch_op.drop_column('project_type')


def downgrade() -> None:
    # project_type 컬럼 복원
    op.add_column('bids_history',
        sa.Column('project_type', sa.String(50), nullable=True))

    # bid_license_types 에서 is_primary=true 첫 번째 값으로 복원
    op.execute("""
        UPDATE bids_history h
        SET project_type = (
            SELECT type_name
            FROM bid_license_types l
            WHERE l.project_id = h.project_id
              AND l.is_primary = true
            ORDER BY l.id
            LIMIT 1
        )
    """)
    op.execute("UPDATE bids_history SET project_type = '기타' WHERE project_type IS NULL")
    op.alter_column('bids_history', 'project_type', nullable=False)

    # bid_license_types 테이블 제거
    op.drop_index('ix_bid_license_types_type_name',  'bid_license_types')
    op.drop_index('ix_bid_license_types_project_id', 'bid_license_types')
    op.drop_table('bid_license_types')
