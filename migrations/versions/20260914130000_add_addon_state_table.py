"""add addon_state table

Phase 1 of the addon system (see
docs/superpowers/specs/2026-09-14-qlsm-addon-system-design.md in the monorepo).
One row per (addon_id, scope, scope_id) holding the enable flag and the
addon's own settings blob.

Revision ID: 20260914130000
Revises: 20260914120000
Create Date: 2026-09-14 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260914130000'
down_revision = '20260914120000'  # add_plugin_repository_table, landed the same day
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'addon_state' in inspector.get_table_names():
        return
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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'addon_state' not in inspector.get_table_names():
        return
    with op.batch_alter_table('addon_state', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_addon_state_addon_id'))
    op.drop_table('addon_state')
