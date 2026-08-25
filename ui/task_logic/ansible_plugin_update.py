# ui/task_logic/ansible_plugin_update.py
#
# Refreshes the host-baseline minqlx plugin pool (/home/ql/assets/common/
# minqlx-plugins/) from ql-assets/data/minqlx-plugins/ without running the
# full setup_host.yml (network/firewall/SSH/etc). Mirrors
# ansible_workshop_update.py's force_update_workshop_logic, minus the
# workshop-item-id specifics — see update_common_plugins.yml.

import logging
from rq import get_current_job
from flask import current_app

from ui.models import HostStatus, InstanceStatus
from ui.database import get_host, update_host, update_instance
from .ansible_runner import _run_host_ansible_playbook


log = logging.getLogger(__name__)


def update_common_plugins_logic(host_id, restart_instance_ids):
    host = get_host(host_id)
    if not host:
        current_app.logger.error(f"update_common_plugins_logic: Host {host_id} not found.")
        return False

    original_host_logs = host.logs or ""
    update_host(host.id, status=HostStatus.ACTIVE, logs=f"Updating common minqlx plugin pool...\n{original_host_logs}")

    try:
        current_app.logger.info(f"Executing common plugin pool update playbook for host: {host.name}")
        get_current_job()

        success, stdout, stderr = _run_host_ansible_playbook(
            host=host,
            playbook_name="update_common_plugins.yml",
        )

        if success:
            current_app.logger.info(f"Common plugin pool updated on {host.name}.")
            update_host(host.id, status=HostStatus.ACTIVE, logs=f"Common plugin pool updated.\n{original_host_logs}")

            from ui.tasks import restart_instance
            for instance in host.instances:
                if instance.status == InstanceStatus.STOPPED or instance.id not in restart_instance_ids:
                    continue

                update_instance(
                    instance.id,
                    status=InstanceStatus.RESTARTING,
                    logs=f"Common plugin pool updated. Queuing restart...\n{instance.logs or ''}"
                )
                restart_instance.queue(instance.id)
            return True
        else:
            current_app.logger.error(f"Failed to update common plugin pool on {host.name}: {stderr}")
            update_host(host.id, status=HostStatus.ERROR, logs=f"Common plugin pool update failed: {stderr}.\n{original_host_logs}")
            return False

    except Exception as e:
        current_app.logger.exception(f"Unexpected error in update_common_plugins_logic: {e}")
        job = get_current_job()
        job_str = job.id if job else "unknown_job"
        update_host(host.id, status=HostStatus.ERROR, logs=f"Unexpected Python error during plugin pool update (Job ID: {job_str}): {str(e)}\n{original_host_logs}")
        return False
