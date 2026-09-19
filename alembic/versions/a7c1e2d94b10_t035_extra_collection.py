"""T-035 추가 수집: 참여자 업체 식별자, 추정가격, 개찰 전 공고, 최종낙찰현황

Revision ID: a7c1e2d94b10
Revises: 5c939b062527
Create Date: 2026-09-19

⚠ SQLite 에서 alter_column 은 테이블 재작성이다. bid_participants 는 597만 행이라
   RAM 1GB 서버에서 위험하므로 **add_column 과 create_table 만** 쓴다.
   add_column 은 SQLite 에서 메타데이터 변경만이라 즉시 끝난다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c1e2d94b10'
down_revision: Union[str, Sequence[str], None] = '5c939b062527'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # bid_participants — 업체 식별자 3개
    op.add_column('bid_participants', sa.Column('company_id', sa.String(length=20), nullable=True, comment='사업자등록번호'))
    op.add_column('bid_participants', sa.Column('company_name', sa.String(length=200), nullable=True, comment='업체명'))
    op.add_column('bid_participants', sa.Column('ceo_name', sa.String(length=50), nullable=True, comment='대표자'))
    op.create_index(op.f('ix_bid_participants_company_id'), 'bid_participants', ['company_id'], unique=False)

    # bids_history — 추정가격
    op.add_column('bids_history', sa.Column('estimated_price', sa.BigInteger(), nullable=True, comment='추정가격 (원, 부가세 제외)'))

    # 개찰 전 공고
    op.create_table('bid_notices_open',
        sa.Column('project_id', sa.String(length=50), nullable=False, comment='나라장터 공고 번호'),
        sa.Column('info21c_bidid', sa.String(length=40), nullable=True, comment='info21c 내부 id'),
        sa.Column('notice_title', sa.String(length=300), nullable=True),
        sa.Column('client_name', sa.String(length=100), nullable=True, comment='발주기관'),
        sa.Column('demand_org', sa.String(length=100), nullable=True, comment='수요기관'),
        sa.Column('region', sa.String(length=50), nullable=True),
        sa.Column('license_text', sa.String(length=300), nullable=True, comment='업종 원문'),
        sa.Column('contract_method', sa.String(length=30), nullable=True, comment='계약방법 (수의/적격 …)'),
        sa.Column('price_method', sa.String(length=20), nullable=False, server_default='기타'),
        sa.Column('preprice_range_pct', sa.Integer(), nullable=True, comment='예가변동폭 ±N% (2=국가계약, 3=지방계약)'),
        sa.Column('legal_limit_rate', sa.Numeric(precision=12, scale=8), nullable=True, comment='법정 낙찰하한율'),
        sa.Column('a_value', sa.BigInteger(), nullable=False, server_default='0', comment='A값 (원)'),
        sa.Column('base_price', sa.BigInteger(), nullable=True, comment='기초금액 (원)'),
        sa.Column('estimated_price', sa.BigInteger(), nullable=True, comment='추정가격 (원)'),
        sa.Column('bid_close_at', sa.DateTime(), nullable=True, comment='투찰마감'),
        sa.Column('open_at', sa.DateTime(), nullable=True, comment='개찰일시'),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('project_id'),
    )
    op.create_index(op.f('ix_bid_notices_open_client_name'), 'bid_notices_open', ['client_name'], unique=False)
    op.create_index(op.f('ix_bid_notices_open_open_at'), 'bid_notices_open', ['open_at'], unique=False)

    # 최종낙찰현황
    op.create_table('bid_final_awards',
        sa.Column('project_id', sa.String(length=50), nullable=False, comment='나라장터 공고 번호'),
        sa.Column('info21c_bidid', sa.String(length=40), nullable=True),
        sa.Column('notice_title', sa.String(length=300), nullable=True),
        sa.Column('client_name', sa.String(length=100), nullable=True),
        sa.Column('open_date', sa.Date(), nullable=True),
        sa.Column('award_amount', sa.BigInteger(), nullable=True, comment='낙찰금액 (원)'),
        sa.Column('company_name', sa.String(length=200), nullable=True),
        sa.Column('ceo_name', sa.String(length=50), nullable=True),
        sa.Column('address', sa.String(length=300), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('project_id'),
    )
    op.create_index(op.f('ix_bid_final_awards_open_date'), 'bid_final_awards', ['open_date'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_bid_final_awards_open_date'), table_name='bid_final_awards')
    op.drop_table('bid_final_awards')
    op.drop_index(op.f('ix_bid_notices_open_open_at'), table_name='bid_notices_open')
    op.drop_index(op.f('ix_bid_notices_open_client_name'), table_name='bid_notices_open')
    op.drop_table('bid_notices_open')
    op.drop_column('bids_history', 'estimated_price')
    op.drop_index(op.f('ix_bid_participants_company_id'), table_name='bid_participants')
    op.drop_column('bid_participants', 'ceo_name')
    op.drop_column('bid_participants', 'company_name')
    op.drop_column('bid_participants', 'company_id')
