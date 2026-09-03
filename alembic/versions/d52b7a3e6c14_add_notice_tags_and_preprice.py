"""add_notice_tags_and_preprice

원본 xlsx 가 갖고 있는데 ETL 이 버리던 값들을 담을 자리를 만든다.

  - bids_history.notice_title        공고명 원문 (태그의 출처)
  - bids_history.preprice_rate       진짜 사정률 = 예정가격 / 기초금액
  - bids_history.est_price           예정가격 원값
  - bids_history.lower_limit_price   낙찰하한가 원값 (A값 역산에 필요)
  (has_a_value 는 d5c7b39a4e10 이 만든다 — 그쪽 정의가 non-null + index 라 더 낫다)
  - bid_tags                         공고명 대괄호 태그 1:N (bid_license_types 와 같은 패턴)

bid_participants.base_rate / vs_lower_limit 는 54acb1bf74ff 에서 이미 추가돼 있다.
값이 비어 있을 뿐이라 스키마 변경 없이 UPDATE 로 채운다.

Revision ID: d52b7a3e6c14
Revises: 8d3110058ed9
Create Date: 2026-08-26 17:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd52b7a3e6c14'
down_revision: Union[str, Sequence[str], None] = '8d3110058ed9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── bids_history ────────────────────────────────────────────────────────
    # 전부 nullable. 재적재 전 기존 행은 NULL 로 남아 '미판정'과 False 가 구분된다.
    op.add_column('bids_history', sa.Column('notice_title', sa.String(length=300), nullable=True))
    op.add_column('bids_history', sa.Column('preprice_rate', sa.Numeric(10, 6), nullable=True))
    op.add_column('bids_history', sa.Column('est_price', sa.BigInteger(), nullable=True))
    op.add_column('bids_history', sa.Column('lower_limit_price', sa.BigInteger(), nullable=True))

    # ── bid_tags ────────────────────────────────────────────────────────────
    op.create_table(
        'bid_tags',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.String(length=50), nullable=False),
        sa.Column('tag', sa.String(length=20), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'tag', name='uq_bid_tags_project_tag'),
    )
    op.create_index(op.f('ix_bid_tags_project_id'), 'bid_tags', ['project_id'], unique=False)
    op.create_index(op.f('ix_bid_tags_tag'), 'bid_tags', ['tag'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_bid_tags_tag'), table_name='bid_tags')
    op.drop_index(op.f('ix_bid_tags_project_id'), table_name='bid_tags')
    op.drop_table('bid_tags')

    op.drop_column('bids_history', 'lower_limit_price')
    op.drop_column('bids_history', 'est_price')
    op.drop_column('bids_history', 'preprice_rate')
    op.drop_column('bids_history', 'notice_title')
