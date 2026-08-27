"""merge license_types and base_rate branches

Revision ID: a6e041fc9944
Revises: 37e6818cd693, 54acb1bf74ff
Create Date: 2026-08-27 14:20:31.932314

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a6e041fc9944'
down_revision: Union[str, Sequence[str], None] = ('37e6818cd693', '54acb1bf74ff')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
