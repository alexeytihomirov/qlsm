"""Server-side demo listing for QLDS instances.

minqlxtended's native demo-match capture (see ql-assets/patches/minqlxtended/
minqlxtended-patches/demo_match.c) writes finished .dm_91 files under
fs_homepath/sv_demoDir, which for a qlsm-managed instance is
/home/ql/qlds-<port>/demos (sv_demoDir defaults to "demos" and is not
overridden anywhere in this repo). This module lists those files so an
operator can verify a manual demo-recording test actually produced a file,
without SSHing into the host by hand.

Kept separate from ansible_instance_mgmt.py for the same reason as
ansible_server_log_archives.py: that file is already past the project's
file-size guideline.
"""
import json
import os
import subprocess

from ui import db
from ui.models import QLInstance
from ui.task_logic.ansible_instance_mgmt import _extract_ansible_debug_msg
from ui.task_logic.common import log

ANSIBLE_TIMEOUT_SECONDS = 60


def _ansible_env():
    env = os.environ.copy()
    env['ANSIBLE_PIPELINING'] = 'True'
    env['ANSIBLE_REMOTE_TMP'] = '/tmp'
    env['ANSIBLE_BECOME_FLAGS'] = '-H -S -n'
    env['ANSIBLE_ALLOW_WORLD_READABLE_TMPFILES'] = 'True'
    env['ANSIBLE_NOCOLOR'] = 'True'
    return env


def _resolve_instance(instance_id):
    """Return (instance, host, error_msg)."""
    instance = db.session.get(QLInstance, instance_id)
    if not instance:
        return None, None, f"Instance {instance_id} not found."

    host = instance.host
    if not host:
        return instance, None, "Associated host not found."

    if not isinstance(instance.port, int) or instance.port <= 0:
        return instance, host, "Instance port is invalid."

    if not host.ip_address or not host.ssh_key_path or not host.ssh_user:
        return instance, host, "Host details missing (IP, SSH key, or user)."

    return instance, host, None


def list_instance_demos(instance_id):
    """List server-side demo files (.dm_91) recorded for an instance.

    Returns a tuple: (success: bool, demos: list[dict], error_msg: str or None)
    where each dict is {"name": str, "size": int, "mtime": float}, newest
    first.
    """
    process = None

    try:
        instance, host, instance_error = _resolve_instance(instance_id)
        if instance_error:
            log.error(f"Cannot list demos for instance {instance_id}: {instance_error}")
            return False, [], instance_error

        playbook_path = os.path.abspath('ansible/playbooks/list_demos.yml')
        inventory_path = os.path.abspath('ansible/inventory/')

        extravars = {
            'port': instance.port,
            'ansible_ssh_user': host.ssh_user,
            'ansible_ssh_private_key_file': os.path.abspath(host.ssh_key_path),
        }

        cmd = ['ansible-playbook', playbook_path, '-i', inventory_path,
               '-l', host.name, '-e', json.dumps(extravars)]

        log.info(f"Listing demos for instance {instance_id} on host {host.name}...")

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=_ansible_env())
        stdout, stderr = process.communicate(timeout=ANSIBLE_TIMEOUT_SECONDS)
        rc = process.returncode

        if rc != 0:
            log.error(f"Ansible failed to list demos for instance {instance_id}. "
                      f"RC: {rc}. stderr: {stderr[-500:]}")
            return False, [], f"Failed to list demos (RC: {rc})."

        msg_content = _extract_ansible_debug_msg(stdout)
        if not msg_content:
            log.warning(f"No 'msg' found in ansible output for instance {instance_id}.")
            return True, [], None

        try:
            demos = json.loads(msg_content)
        except json.JSONDecodeError as e:
            log.error(f"Failed to parse demo file list JSON for instance {instance_id}: {e}")
            return False, [], "Failed to parse demo file list."

        if not isinstance(demos, list):
            log.warning(f"Parsed demos msg is not a list: {type(demos)}")
            return True, [], None

        valid_demos = [d for d in demos if isinstance(d, dict) and isinstance(d.get('name'), str)]
        valid_demos.sort(key=lambda d: d.get('mtime') or 0, reverse=True)
        return True, valid_demos, None

    except subprocess.TimeoutExpired:
        if process is not None:
            process.kill()
            process.communicate()
        log.error(f"Timeout listing demos for instance {instance_id}")
        return False, [], "Timeout while listing demos from remote host."
    except Exception as e:
        log.exception(f"Exception listing demos for instance {instance_id}: {e}")
        return False, [], "Failed to list demos."
