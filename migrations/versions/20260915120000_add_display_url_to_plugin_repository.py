"""add display_url to plugin_repository

Revision ID: 20260915120000
Revises: 20260914120000
Create Date: 2026-09-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260915120000'
down_revision = '20260914120000'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('plugin_repository', schema=None) as batch_op:
        batch_op.add_column(sa.Column('display_url', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('plugin_repository', schema=None) as batch_op:
        batch_op.drop_column('display_url')
