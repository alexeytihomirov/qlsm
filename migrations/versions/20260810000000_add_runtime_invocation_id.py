"""add runtime invocation id to qlinstance

Revision ID: 20260810000000
Revises: 755d969fcce8
Create Date: 2026-08-10
"""
from alembic import op
import sqlalchemy as sa


revision = "20260810000000"
down_revision = "755d969fcce8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ql_instance", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("runtime_invocation_id", sa.String(length=64), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("ql_instance", schema=None) as batch_op:
        batch_op.drop_column("runtime_invocation_id")
