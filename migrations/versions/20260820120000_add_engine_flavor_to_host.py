"""add engine_flavor/engine_source/engine_artifact_url to host

Revision ID: 20260820120000
Revises: 20260810000000
Create Date: 2026-08-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260820120000'
down_revision = '20260810000000'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('host', schema=None) as batch_op:
        batch_op.add_column(sa.Column('engine_flavor', sa.String(length=20), nullable=False, server_default='minqlx'))
        batch_op.add_column(sa.Column('engine_source', sa.String(length=20), nullable=False, server_default='build'))
        batch_op.add_column(sa.Column('engine_artifact_url', sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table('host', schema=None) as batch_op:
        batch_op.drop_column('engine_artifact_url')
        batch_op.drop_column('engine_source')
        batch_op.drop_column('engine_flavor')
