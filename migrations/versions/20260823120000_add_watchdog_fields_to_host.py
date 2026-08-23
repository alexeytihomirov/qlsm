"""add watchdog_enabled/watchdog_config to Host

Revision ID: 20260823120000
Revises: 20260821010000
Create Date: 2026-08-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260823120000'
down_revision = '20260821010000'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('host', schema=None) as batch_op:
        batch_op.add_column(sa.Column('watchdog_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('watchdog_config', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('host', schema=None) as batch_op:
        batch_op.drop_column('watchdog_config')
        batch_op.drop_column('watchdog_enabled')
