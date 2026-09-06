"""merge runtime heads, backfill Host.runtime from engine_flavor, drop engine_flavor/engine_source/engine_artifact_url

Merges the two alembic heads produced by the dngrtech/qlsm upstream merge:
20260818000001 (upstream's Host.runtime / ConfigPreset.runtime) and
20260823120000 (this fork's own history, which independently grew
Host.engine_flavor/engine_source/engine_artifact_url on the same base).

Host.engine_flavor == 'minqlxtended' has only ever meant one thing on this
fork: the qlhub-patched build (see ui/runtime.py's MINQLXTENDED_PATCHED and
ansible/playbooks/tasks/build_engine_hook.yml) -- there was never a plain,
unpatched minqlxtended option before this merge. So the backfill maps
engine_flavor 'minqlxtended' to runtime 'minqlxtended-patched', not to the
now-distinct vanilla 'minqlxtended' runtime, or the one host that already
runs the patched build (dev-inbox: host "germany") would read back as
requesting a rebuild of the vanilla, unpatched engine on its next
setup/rebuild run and silently lose the native item-events/demo-capture
patches.

Revision ID: 20260906120000
Revises: 20260818000001, 20260823120000
Create Date: 2026-09-06 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '20260906120000'
down_revision = ('20260818000001', '20260823120000')
branch_labels = None
depends_on = None


def upgrade():
    # host.runtime was added by 20260818000000 with server_default='minqlx',
    # which backfilled every pre-existing row -- including any row whose
    # engine_flavor says otherwise -- to 'minqlx'. Overwrite from
    # engine_flavor, which is this fork's authoritative record of what a host
    # actually runs.
    op.execute(sa.text(
        "UPDATE host SET runtime = "
        "CASE engine_flavor "
        "WHEN 'minqlxtended' THEN 'minqlxtended-patched' "
        "ELSE engine_flavor "
        "END"
    ))

    with op.batch_alter_table('host', schema=None) as batch_op:
        batch_op.drop_column('engine_artifact_url')
        batch_op.drop_column('engine_source')
        batch_op.drop_column('engine_flavor')


def downgrade():
    with op.batch_alter_table('host', schema=None) as batch_op:
        batch_op.add_column(sa.Column('engine_flavor', sa.String(length=20), nullable=False, server_default='minqlx'))
        batch_op.add_column(sa.Column('engine_source', sa.String(length=20), nullable=False, server_default='build'))
        batch_op.add_column(sa.Column('engine_artifact_url', sa.String(length=500), nullable=True))

    # Both minqlxtended runtimes collapse back to the one flavor this fork's
    # older schema ever had. engine_source/engine_artifact_url stay at their
    # server_default ('build'/NULL) -- nothing before this merge ever set
    # engine_source to 'artifact' (confirmed against the production DB before
    # this migration was written), so there is no data to recover there.
    op.execute(sa.text(
        "UPDATE host SET engine_flavor = "
        "CASE WHEN runtime IN ('minqlxtended', 'minqlxtended-patched') THEN 'minqlxtended' "
        "ELSE 'minqlx' "
        "END"
    ))
