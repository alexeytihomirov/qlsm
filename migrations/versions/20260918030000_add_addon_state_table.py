"""add addon_state table

One row per (addon_id, scope, scope_id) holding the enable flag and the
addon's own settings blob.

Revision ID: 20260918030000
Revises: 20260915120000
Create Date: 2026-09-18 03:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260918030000'
down_revision = '20260915120000'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'addon_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('addon_id', sa.String(length=64), nullable=False),
        sa.Column('scope', sa.String(length=16), nullable=False),
        sa.Column('scope_id', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('settings_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('addon_id', 'scope', 'scope_id', name='uq_addon_state_scope'),
    )
    with op.batch_alter_table('addon_state', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_addon_state_addon_id'), ['addon_id'], unique=False)


def downgrade():
    with op.batch_alter_table('addon_state', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_addon_state_addon_id'))
    op.drop_table('addon_state')
