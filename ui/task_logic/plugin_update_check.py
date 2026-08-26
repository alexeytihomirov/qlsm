# ui/task_logic/plugin_update_check.py
#
# "Check for Updates" — replaces the old blind "Update Plugins" button.
# ql-assets/data/minqlx-plugins/ is the source of truth (see
# ui/plugin_manifest.py). Two independent diffs against it:
#
#  - host common pool (/home/ql/assets/common/minqlx-plugins/ on the VPS) —
#    the shared baseline every instance backfills from on restart.
#  - each instance's *selected* plugins (configs/{host}/{instance}/scripts/,
#    local to the qlsm controller) — these are excluded from the common-pool
#    backfill on purpose (an operator may have hand-edited one via the script
#    editor), so they only ever went stale silently. This is the category
#    that caused the match_restore.py incident: an instance-selected file
#    with a real upstream fix, and no path for that fix to ever reach it.
#
# system-hooks (ql-assets/data/system-hooks/) is NOT checked here: that sync
# task in sync_instance_configs_and_restart.yml runs unconditionally on every
# restart with no exclude list, so it self-heals and was never the bug.

import os

from ui.update_checks import hash_local_tree, parse_sha256sum_output, diff_trees, PLUGIN_EXTENSIONS
from ui.plugin_manifest import MINQLX_PLUGINS_POOL_DIR
from .ansible_runner import run_host_ansible_adhoc

COMMON_POOL_REMOTE_DIR = "/home/ql/assets/common/minqlx-plugins"


def _pool_dir():
    return os.path.abspath(MINQLX_PLUGINS_POOL_DIR)


def _instance_scripts_dir(host_name, instance_id):
    return os.path.abspath(os.path.join('configs', host_name, str(instance_id), 'scripts'))


def check_common_pool(host):
    """Diffs ql-assets pool vs the host's shared /home/ql/assets/common/minqlx-plugins/.
    Returns (changes, error). error is set (changes is None) if the host was unreachable."""
    source = hash_local_tree(_pool_dir(), extensions=PLUGIN_EXTENSIONS)
    success, stdout, stderr = run_host_ansible_adhoc(
        host,
        module_args=f"find {COMMON_POOL_REMOTE_DIR} -maxdepth 1 -type f "
                    f"\\( -name '*.py' -o -name '*.ql-plugin.json' \\) -exec sha256sum {{}} +",
    )
    if not success:
        return None, stderr or "Failed to read remote plugin pool state"

    target = parse_sha256sum_output(stdout, strip_prefix=COMMON_POOL_REMOTE_DIR + "/")
    return diff_trees(source, target), None


def check_instance_selected_plugins(host, instance):
    """Diffs ql-assets pool vs this instance's own selected-scripts snapshot
    (configs/{host}/{instance}/scripts/) — purely local, no SSH needed."""
    source = hash_local_tree(_pool_dir(), extensions=PLUGIN_EXTENSIONS)
    target = hash_local_tree(_instance_scripts_dir(host.name, instance.id), extensions=PLUGIN_EXTENSIONS)
    # Only meaningful for files the instance actually selected — an instance
    # not using a given plugin at all isn't "missing an update" for it.
    target_names = set(target)
    filtered_source = {name: h for name, h in source.items() if name in target_names}
    return diff_trees(filtered_source, target)


def check_host_updates(host):
    """Full check payload for a host + all its instances."""
    common_pool_changes, common_pool_error = check_common_pool(host)
    instances_payload = []
    for instance in host.instances:
        instances_payload.append({
            "id": instance.id,
            "name": instance.name,
            "port": instance.port,
            "status": instance.status.value,
            "selected_plugin_changes": check_instance_selected_plugins(host, instance),
        })
    return {
        "host_id": host.id,
        "common_pool_changes": common_pool_changes or [],
        "common_pool_error": common_pool_error,
        "instances": instances_payload,
    }
