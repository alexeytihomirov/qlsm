"""add redis_db to qlinstance

Revision ID: 755d969fcce8
Revises: b7c1a9d2e4f0
Create Date: 2026-08-06 09:25:28.709548

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '755d969fcce8'
down_revision = 'b7c1a9d2e4f0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ql_instance', schema=None) as batch_op:
        batch_op.add_column(sa.Column('redis_db', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('ql_instance', schema=None) as batch_op:
        batch_op.drop_column('redis_db')
