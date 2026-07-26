"""add firewall_pool_v2 to host

Revision ID: b7c1a9d2e4f0
Revises: ee8f7e103564
Create Date: 2026-07-25 10:12:44.318902

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c1a9d2e4f0'
down_revision = 'ee8f7e103564'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('host', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'firewall_pool_v2',
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ))


def downgrade():
    with op.batch_alter_table('host', schema=None) as batch_op:
        batch_op.drop_column('firewall_pool_v2')
