"""merge a_value and notice_tags branches

로컬(d52b7a3e6c14: 공고명 태그·사정률·원값)과 서버(d5c7b39a4e10: A값·하한율 분리)가
같은 지점에서 갈라져 각자 진행됐다. 스키마는 겹치지 않는다 —
has_a_value 만 양쪽이 만들려 해서 d52b7a3e6c14 쪽에서 뺐다(d5c7 정의가 non-null + index).

Revision ID: f0a2c5d81b44
Revises: d52b7a3e6c14, d5c7b39a4e10
Create Date: 2026-08-27 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0a2c5d81b44'
down_revision: Union[str, Sequence[str], None] = ('d52b7a3e6c14', 'd5c7b39a4e10')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
