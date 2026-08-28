"""Server-side demo listing for QLDS instances.

minqlxtended's native demo-match capture (see ql-assets/patches/minqlxtended/
minqlxtended-patches/demo_match.c) writes finished .dm_91 files under
fs_homepath/sv_demoDir, which for a qlsm-managed instance is
/home/ql/qlds-<port>/demos (sv_demoDir defaults to "demos" and is not
overridden anywhere in this repo). That per-POV .dm_91 output is the same
directory the plain sv_demoRecord path already writes flat, single-file
demos to, so both show up in the same listing here without any extra
plumbing. demo_native_manifest.py additionally packages each match's set of
per-POV .dm_91 files into one {match_id}_{map}.qlmatch zip (manifest.json +
demos/*.dm_91 + index/*.snaps.json) in that same directory - listed and
downloadable here too, since it is the one file an operator actually wants
for a match instead of picking through N separate per-POV files by hand.
This module lists those files so an operator can verify a manual
demo-recording test actually produced a file, without SSHing into the host
by hand.

Kept separate from ansible_instance_mgmt.py for the same reason as
ansible_server_log_archives.py: that file is already past the project's
file-size guideline.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

from ui import db
from ui.models import QLInstance
from ui.task_logic.ansible_instance_mgmt import _extract_ansible_debug_msg
from ui.task_logic.common import log

ANSIBLE_TIMEOUT_SECONDS = 60
FETCH_TIMEOUT_SECONDS = 180

# Matches demo_build_pov_name()'s output in demo_match.c (sanitised to
# [A-Za-z0-9_-] plus the literal ".dm_91" suffix) and
# build_match_package()'s "{match_id}_{map}.qlmatch" zip in
# demo_native_manifest.py. Anchored with \A/\Z (not ^/$) for the same reason
# SERVER_LOG_FILENAME_RE in ansible_server_log_archives.py is: this value
# reaches both a remote and a local filesystem path built by string
# concatenation, and $ still matches before a trailing newline under
# .fullmatch().
DEMO_FILENAME_RE = re.compile(r'\A[A-Za-z0-9._-]+\.(?:dm_91|qlmatch)\Z')

# Generous but bounded: a batch this large would already take minutes to
# fetch one-by-one over SSH, so this is a sanity cap, not a realistic usage
# ceiling.
MAX_DEMO_BATCH = 200


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
    """List server-side demo files (.dm_91 and .qlmatch) recorded for an instance.

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

        valid_demos = [d for d in demos if isinstance(d, dict) and isinstance(d.get('name'), str)
                       and DEMO_FILENAME_RE.fullmatch(d['name'])]
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


def fetch_instance_demos(instance_id, filenames):
    """Fetch one or more demo files from the remote host into memory.

    Returns a tuple: (success: bool, files: dict[str, bytes],
    missing: list[str], error_msg: str or None). `missing` holds requested
    filenames that no longer existed on the remote host by the time the
    fetch ran (e.g. cleaned up between listing and download) — not treated
    as a failure, since the files that WERE found are still worth returning.

    Filenames are validated against DEMO_FILENAME_RE before anything else,
    the same guard-before-ansible pattern as fetch_instance_server_log: this
    value reaches both a remote `src` path and a local `dest` path built by
    string concatenation in fetch_demos.yml.
    """
    if not isinstance(filenames, list) or not filenames:
        return False, {}, [], "filenames must be a non-empty list."
    if len(filenames) > MAX_DEMO_BATCH:
        return False, {}, [], f"Cannot fetch more than {MAX_DEMO_BATCH} demos at once."

    deduped = []
    for name in filenames:
        if not isinstance(name, str) or not DEMO_FILENAME_RE.fullmatch(name):
            return False, {}, [], f"Invalid demo filename: {name!r}"
        if name not in deduped:
            deduped.append(name)
    filenames = deduped

    process = None
    local_dir = None

    try:
        instance, host, instance_error = _resolve_instance(instance_id)
        if instance_error:
            log.error(f"Cannot fetch demos for instance {instance_id}: {instance_error}")
            return False, {}, [], instance_error

        local_dir = tempfile.mkdtemp(prefix='qlsm-demos-')

        playbook_path = os.path.abspath('ansible/playbooks/fetch_demos.yml')
        inventory_path = os.path.abspath('ansible/inventory/')

        extravars = {
            'port': instance.port,
            'ansible_ssh_user': host.ssh_user,
            'ansible_ssh_private_key_file': os.path.abspath(host.ssh_key_path),
            'filenames': filenames,
            'local_dir': local_dir,
        }

        cmd = ['ansible-playbook', playbook_path, '-i', inventory_path,
               '-l', host.name, '-e', json.dumps(extravars)]

        log.info(f"Fetching {len(filenames)} demo(s) for instance {instance_id} on host {host.name}...")

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=_ansible_env())
        stdout, stderr = process.communicate(timeout=FETCH_TIMEOUT_SECONDS)
        rc = process.returncode

        if rc != 0:
            log.error(f"Ansible failed to fetch demos for instance {instance_id}. "
                      f"RC: {rc}. stderr: {stderr[-500:]}")
            return False, {}, [], f"Failed to fetch demos (RC: {rc})."

        files = {}
        missing = []
        for name in filenames:
            local_path = os.path.join(local_dir, name)
            if os.path.isfile(local_path):
                with open(local_path, 'rb') as fh:
                    files[name] = fh.read()
            else:
                missing.append(name)

        log.info(f"Fetched {len(files)}/{len(filenames)} demo(s) for instance {instance_id}")
        return True, files, missing, None

    except subprocess.TimeoutExpired:
        if process is not None:
            process.kill()
            process.communicate()
        log.error(f"Timeout fetching demos for instance {instance_id}")
        return False, {}, [], "Timeout while fetching demos from remote host."
    except Exception as e:
        log.exception(f"Exception fetching demos for instance {instance_id}: {e}")
        return False, {}, [], "Failed to fetch demos."
    finally:
        if local_dir:
            shutil.rmtree(local_dir, ignore_errors=True)
