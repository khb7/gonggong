"""merge base_rate branch

Revision ID: 8d3110058ed9
Revises: 37e6818cd693, 54acb1bf74ff
Create Date: 2026-08-26 16:48:30.500459

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d3110058ed9'
down_revision: Union[str, Sequence[str], None] = ('37e6818cd693', '54acb1bf74ff')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
