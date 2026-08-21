"""add operator table

Revision ID: 20260821010000
Revises: 20260820120000
Create Date: 2026-08-21 01:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260821010000'
down_revision = '20260820120000'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('operator',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('steam_id64', sa.String(length=20), nullable=False),
    sa.Column('default_level', sa.Integer(), nullable=False, server_default='5'),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('steam_id64')
    )


def downgrade():
    op.drop_table('operator')
