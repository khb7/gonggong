"""add project_id unique constraint

Revision ID: a3f9e1c72b08
Revises: 15711de594d0
Create Date: 2026-03-14
"""

from alembic import op

revision = "a3f9e1c72b08"
down_revision = "15711de594d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "bids_history_project_id_key",
        "bids_history",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "bids_history_project_id_key",
        "bids_history",
        type_="unique",
    )
