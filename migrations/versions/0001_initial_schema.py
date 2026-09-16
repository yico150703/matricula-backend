"""initial schema for university enrollment

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
