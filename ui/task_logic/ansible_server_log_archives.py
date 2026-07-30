"""Server-log archive listing and reading for QLDS instances.

Server logs are exported out of journald into rotating per-instance files by
the host-side qlsm-archive-serverlogs timer (see
ansible/playbooks/tasks/server_log_archiving.yml). This module lists those
archives and reads their contents.

Kept separate from ansible_instance_mgmt.py, which is already far past the
project's file-size guideline.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid

from ui import db
from ui.models import QLInstance
from ui.task_logic.ansible_instance_mgmt import _extract_ansible_debug_msg
from ui.task_logic.common import log

# Canonical archive names produced by logrotate with
# `dateext` + `dateformat -%Y%m%d-%H%M%S`. `delaycompress` leaves the newest
# archive uncompressed, so the .gz suffix is optional.
#
# Anchored with \A...\Z rather than ^...$: this value reaches a remote shell
# command, and $ matches just before a trailing newline even under
# .fullmatch(), so 'server.log\n' (and injected content after it) would
# otherwise slip through. \A...\Z has no such exception. Call sites must
# still use .fullmatch() — these anchors are defense-in-depth, not a
# substitute for it.
SERVER_LOG_FILENAME_RE = re.compile(r'\Aserver\.log(-\d{8}-\d{6}(\.gz)?)?\Z')

CURRENT_SERVER_LOG = 'server.log'

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


def _sort_archives(files):
    """server.log first, then archives newest-first.

    The YYYYMMDD-HHMMSS suffix sorts lexically in chronological order, so a
    reverse string sort on the suffix yields newest-first.
    """
    current = [f for f in files if f == CURRENT_SERVER_LOG]
    archives = sorted((f for f in files if f != CURRENT_SERVER_LOG), reverse=True)
    return current + archives


def list_instance_server_log_archives(instance_id):
    """List available server-log files for an instance.

    Returns a tuple: (success: bool, files: list[str], error_msg: str or None)
    """
    process = None

    try:
        instance, host, instance_error = _resolve_instance(instance_id)
        if instance_error:
            log.error(f"Cannot list server log archives for instance {instance_id}: {instance_error}")
            return False, [], instance_error

        playbook_path = os.path.abspath('ansible/playbooks/list_server_log_archives.yml')
        inventory_path = os.path.abspath('ansible/inventory/')

        extravars = {
            'port': instance.port,
            'ansible_ssh_user': host.ssh_user,
            'ansible_ssh_private_key_file': os.path.abspath(host.ssh_key_path),
        }

        cmd = ['ansible-playbook', playbook_path, '-i', inventory_path,
               '-l', host.name, '-e', json.dumps(extravars)]

        log.info(f"Listing server log archives for instance {instance_id} on host {host.name}...")

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=_ansible_env())
        stdout, stderr = process.communicate(timeout=ANSIBLE_TIMEOUT_SECONDS)
        rc = process.returncode

        if rc != 0:
            log.error(f"Ansible failed to list server log archives for instance {instance_id}. "
                      f"RC: {rc}. stderr: {stderr[-500:]}")
            return False, [], f"Failed to list server log archives (RC: {rc})."

        msg_content = _extract_ansible_debug_msg(stdout)
        if not msg_content:
            log.warning(f"No 'msg' found in ansible output for instance {instance_id}.")
            return True, [], None

        try:
            files = json.loads(msg_content)
        except json.JSONDecodeError as e:
            log.error(f"Failed to parse server log file list JSON for instance {instance_id}: {e}")
            return False, [], "Failed to parse server log file list."

        if not isinstance(files, list):
            log.warning(f"Parsed server log msg is not a list: {type(files)}")
            return True, [], None

        valid_files = [f for f in files
                       if isinstance(f, str) and SERVER_LOG_FILENAME_RE.fullmatch(f)]
        return True, _sort_archives(valid_files), None

    except subprocess.TimeoutExpired:
        if process is not None:
            process.kill()
            process.communicate()
        log.error(f"Timeout listing server log archives for instance {instance_id}")
        return False, [], "Timeout while listing server log archives from remote host."
    except Exception as e:
        log.exception(f"Exception listing server log archives for instance {instance_id}: {e}")
        return False, [], "Failed to list server log archives."


def fetch_instance_server_log(instance_id, filename=CURRENT_SERVER_LOG,
                              filter_mode='lines', lines=500):
    """Read a server-log file (current or archived) from the remote host.

    Content is transported via ansible.builtin.fetch into a local temp file
    rather than being scraped out of Ansible's console output, so multi-MB
    reads stay reliable.

    Returns a tuple: (success: bool, logs: str, error_msg: str or None)
    """
    if not SERVER_LOG_FILENAME_RE.fullmatch(filename or ''):
        return False, "", "Invalid server log filename."

    if filter_mode not in ('lines', 'all'):
        return False, "", "filter_mode must be 'lines' or 'all'"

    if filter_mode == 'lines':
        if not isinstance(lines, int):
            return False, "", "lines must be an integer"
        if lines < 10 or lines > 10000:
            return False, "", "lines must be between 10 and 10000"

    process = None
    local_dir = None

    try:
        instance, host, instance_error = _resolve_instance(instance_id)
        if instance_error:
            log.error(f"Cannot fetch server log for instance {instance_id}: {instance_error}")
            return False, "", instance_error

        local_dir = tempfile.mkdtemp(prefix='qlsm-serverlog-')
        local_dest = os.path.join(local_dir, 'server-log.txt')

        playbook_path = os.path.abspath('ansible/playbooks/fetch_server_log_archive.yml')
        inventory_path = os.path.abspath('ansible/inventory/')

        extravars = {
            'port': instance.port,
            'ansible_ssh_user': host.ssh_user,
            'ansible_ssh_private_key_file': os.path.abspath(host.ssh_key_path),
            'filter_mode': filter_mode,
            'lines': lines,
            'filename': filename,
            'fetch_token': uuid.uuid4().hex,
            'local_dest': local_dest,
        }

        cmd = ['ansible-playbook', playbook_path, '-i', inventory_path,
               '-l', host.name, '-e', json.dumps(extravars)]

        log.info(f"Fetching server log for instance {instance_id} on host {host.name} "
                 f"(file: {filename}, mode: {filter_mode}, lines: {lines})...")

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=_ansible_env())
        stdout, stderr = process.communicate(timeout=ANSIBLE_TIMEOUT_SECONDS)
        rc = process.returncode

        if rc != 0:
            log.error(f"Ansible failed to fetch server log for instance {instance_id}. "
                      f"RC: {rc}. stderr: {stderr[-500:]}")
            return False, "", f"Failed to fetch server logs (RC: {rc})."

        if not os.path.exists(local_dest):
            log.info(f"Server log file {filename} not present for instance {instance_id}")
            return True, "-- Server log file not found --", None

        with open(local_dest, 'r', errors='replace') as fh:
            logs = fh.read()

        if not logs.strip():
            logs = "-- No entries --"

        log.info(f"Fetched {len(logs)} bytes of server log for instance {instance_id}")
        return True, logs, None

    except subprocess.TimeoutExpired:
        if process is not None:
            process.kill()
            process.communicate()
        log.error(f"Timeout fetching server log for instance {instance_id}")
        return False, "", "Timeout while fetching server logs from remote host."
    except Exception as e:
        log.exception(f"Exception fetching server log for instance {instance_id}: {e}")
        return False, "", "Failed to fetch server logs."
    finally:
        if local_dir:
            shutil.rmtree(local_dir, ignore_errors=True)
