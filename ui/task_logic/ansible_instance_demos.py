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
for a match instead of picking through N separate per-POV files by hand. The
qlmatch-packer additionally drops a {match_id}_{map}.replay.json.gz merged
replay sidecar next to each pack (see ql-assets/data/qlmatch-packer/pack.mjs)
- also listed and downloadable here, since it's the input the dashboard's
demo/replay view and !restorecp qlmatch both read.
This module lists those files so an operator can verify a manual
demo-recording test actually produced a file, without SSHing into the host
by hand.

Listing and fetching both talk directly to the host over SFTP (paramiko),
the same key-authenticated, no-persisted-host-key management channel as
service_runtime.py's runtime probe and rcon_transport.py's live rcon - not
ansible-playbook: these are simple stat/read operations with no templating
or privilege escalation to justify Ansible's overhead, so a plain SFTP
listdir + open is both faster and simpler to reason about than shelling out
to ansible-playbook for a two-line remote operation.

Kept separate from ansible_instance_mgmt.py for the same reason as
ansible_server_log_archives.py: that file is already past the project's
file-size guideline.
"""
import json
import os
import re
import stat as stat_module
import zipfile

import paramiko

from ui import db
from ui.models import QLInstance
from ui.rcon_transport import rcon_target_for_host
from ui.task_logic.common import log

SSH_CONNECT_TIMEOUT_SECONDS = 10
# Covers a whole batch fetch, not just one file - mirrors the old Ansible
# fetch module's FETCH_TIMEOUT_SECONDS budget.
SSH_IO_TIMEOUT_SECONDS = 180

# Matches demo_build_pov_name()'s output in demo_match.c (sanitised to
# [A-Za-z0-9_-] plus the literal ".dm_91" suffix), the .qlmatch packages
# (external qlmatch-packer's templated names and the in-process fallback's
# "{match_id}_{map}.qlmatch" - both sanitise to the same charset), the
# packer's per-match "{match_id}.packer.log", and the packer's merged-replay
# sidecar "{match_id}_{map}.replay.json.gz". Anchored with \A/\Z (not ^/$)
# for the same reason SERVER_LOG_FILENAME_RE in
# ansible_server_log_archives.py is: this value reaches both a remote and a
# local filesystem path built by string concatenation, and $ still matches
# before a trailing newline under .fullmatch().
DEMO_FILENAME_RE = re.compile(r'\A[A-Za-z0-9._-]+\.(?:dm_91|qlmatch|packer\.log|replay\.json\.gz)\Z')

# Mirrors restore/qlmatch.py's SIDECAR_EXT / sidecar_path_for(): the
# packer always names a pack's replay sidecar "{match_id}_{map}.replay.json.gz",
# regardless of what qlx_qlmatchNameTemplate made the .qlmatch's own filename
# look like (see qlmatch-to-replay.mjs / pack.mjs) - so a .qlmatch and its
# sidecar can NOT be paired by string-editing the .qlmatch filename; the
# match_id/map have to come from the pack's own manifest.json.
SIDECAR_EXT = '.replay.json.gz'

# Generous but bounded: a batch this large would already take minutes to
# fetch one-by-one over SFTP, so this is a sanity cap, not a realistic usage
# ceiling.
MAX_DEMO_BATCH = 200


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


def _demo_dir(instance):
    return f"/home/ql/qlds-{instance.port}/demos"


def _open_sftp(host):
    """Open a key-authenticated SFTP session to a managed host.

    Same target resolution and no-persisted-host-key trust model as the
    other direct-SSH management paths in this codebase (service_runtime.py's
    runtime probe, rcon_transport.py's live rcon) - this is a QLSM-internal
    channel to hosts QLSM itself provisioned, not a user-facing endpoint.
    Caller is responsible for closing the returned client (which also closes
    the sftp session).
    """
    target = rcon_target_for_host(host)
    if not target:
        raise OSError("Could not resolve an SSH target for this host.")

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=target,
            port=host.ssh_port,
            username=host.ssh_user,
            key_filename=os.path.abspath(host.ssh_key_path),
            timeout=SSH_CONNECT_TIMEOUT_SECONDS,
            banner_timeout=SSH_CONNECT_TIMEOUT_SECONDS,
            auth_timeout=SSH_CONNECT_TIMEOUT_SECONDS,
            allow_agent=False,
            look_for_keys=False,
        )
        sftp = client.open_sftp()
        sftp.get_channel().settimeout(SSH_IO_TIMEOUT_SECONDS)
    except Exception:
        client.close()
        raise
    return client, sftp


def list_instance_demos(instance_id):
    """List server-side demo files (.dm_91, .qlmatch, .packer.log,
    .replay.json.gz) recorded for an instance.

    Returns a tuple: (success: bool, demos: list[dict], error_msg: str or None)
    where each dict is {"name": str, "size": int, "mtime": float}, newest
    first.
    """
    client = None
    try:
        instance, host, instance_error = _resolve_instance(instance_id)
        if instance_error:
            log.error(f"Cannot list demos for instance {instance_id}: {instance_error}")
            return False, [], instance_error

        demo_dir = _demo_dir(instance)
        log.info(f"Listing demos for instance {instance_id} on host {host.name}...")

        client, sftp = _open_sftp(host)
        try:
            entries = sftp.listdir_attr(demo_dir)
        except FileNotFoundError:
            entries = []

        demos = [
            {'name': entry.filename, 'size': entry.st_size, 'mtime': entry.st_mtime}
            for entry in entries
            if entry.st_mode is not None and stat_module.S_ISREG(entry.st_mode)
            and DEMO_FILENAME_RE.fullmatch(entry.filename)
        ]
        demos.sort(key=lambda d: d.get('mtime') or 0, reverse=True)
        return True, demos, None

    except (paramiko.AuthenticationException, paramiko.SSHException, OSError) as exc:
        log.error(f"SSH failure listing demos for instance {instance_id}: {exc}")
        return False, [], "Failed to list demos from remote host."
    except Exception as e:
        log.exception(f"Exception listing demos for instance {instance_id}: {e}")
        return False, [], "Failed to list demos."
    finally:
        if client is not None:
            client.close()


def fetch_instance_demos(instance_id, filenames):
    """Fetch one or more demo files from the remote host into memory.

    Returns a tuple: (success: bool, files: dict[str, bytes],
    missing: list[str], error_msg: str or None). `missing` holds requested
    filenames that no longer existed on the remote host by the time the
    fetch ran (e.g. cleaned up between listing and download) — not treated
    as a failure, since the files that WERE found are still worth returning.

    Filenames are validated against DEMO_FILENAME_RE before anything else,
    the same guard-before-transport pattern as fetch_instance_server_log:
    this value reaches a remote path built by string concatenation.
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

    client = None
    try:
        instance, host, instance_error = _resolve_instance(instance_id)
        if instance_error:
            log.error(f"Cannot fetch demos for instance {instance_id}: {instance_error}")
            return False, {}, [], instance_error

        demo_dir = _demo_dir(instance)
        log.info(f"Fetching {len(filenames)} demo(s) for instance {instance_id} on host {host.name}...")

        client, sftp = _open_sftp(host)

        files = {}
        missing = []
        for name in filenames:
            try:
                with sftp.open(f"{demo_dir}/{name}", 'rb') as fh:
                    files[name] = fh.read()
            except FileNotFoundError:
                missing.append(name)

        log.info(f"Fetched {len(files)}/{len(filenames)} demo(s) for instance {instance_id}")
        return True, files, missing, None

    except (paramiko.AuthenticationException, paramiko.SSHException, OSError) as exc:
        log.error(f"SSH failure fetching demos for instance {instance_id}: {exc}")
        return False, {}, [], "Failed to fetch demos from remote host."
    except Exception as e:
        log.exception(f"Exception fetching demos for instance {instance_id}: {e}")
        return False, {}, [], "Failed to fetch demos."
    finally:
        if client is not None:
            client.close()


def qlmatch_sidecar_name(match_id, map_name):
    """The replay sidecar filename for a given manifest match_id/map.

    Same formula as restore/qlmatch.py's sidecar_path_for(), minus the
    directory component (callers here only need to check/download by name).
    """
    return f"{match_id}_{map_name}{SIDECAR_EXT}"


def read_qlmatch_manifest(instance_id, filename):
    """Read {match_id, map} out of a .qlmatch pack's manifest.json.

    Opens the remote pack through a seekable SFTP file handle and hands it
    straight to zipfile, so only the central directory and the small
    manifest.json member are fetched - not the multi-MB demos/*.dm_91
    payload the rest of the zip carries. Mirrors the manifest read
    restore/qlmatch.py's _pack_summary() already does locally on the game
    server; needed here because a pack's own filename does not reliably
    encode match_id/map (qlx_qlmatchNameTemplate can template it to anything).

    Returns a tuple: (success: bool, manifest: dict or None, error_msg: str
    or None) where manifest is {"match_id": str, "map": str}.
    """
    if not isinstance(filename, str) or not filename.endswith('.qlmatch') \
            or not DEMO_FILENAME_RE.fullmatch(filename):
        return False, None, f"Invalid qlmatch filename: {filename!r}"

    client = None
    try:
        instance, host, instance_error = _resolve_instance(instance_id)
        if instance_error:
            log.error(f"Cannot read qlmatch manifest for instance {instance_id}: {instance_error}")
            return False, None, instance_error

        demo_dir = _demo_dir(instance)
        client, sftp = _open_sftp(host)

        try:
            with sftp.open(f"{demo_dir}/{filename}", 'rb') as fh:
                with zipfile.ZipFile(fh) as zf:
                    raw = zf.read('manifest.json')
        except FileNotFoundError:
            return False, None, "Qlmatch file not found on the remote host."
        except (KeyError, zipfile.BadZipFile) as exc:
            return False, None, f"Could not read manifest.json from pack: {exc}"

        try:
            manifest = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as exc:
            return False, None, f"Malformed manifest.json: {exc}"

        if not isinstance(manifest, dict):
            return False, None, "Malformed manifest.json: not an object."

        match_id = str(manifest.get('match_id') or '')
        map_name = str(manifest.get('map') or '')
        if not match_id or not map_name:
            return False, None, "manifest.json missing match_id or map."

        return True, {'match_id': match_id, 'map': map_name}, None

    except (paramiko.AuthenticationException, paramiko.SSHException, OSError) as exc:
        log.error(f"SSH failure reading qlmatch manifest for instance {instance_id}: {exc}")
        return False, None, "Failed to read qlmatch manifest from remote host."
    except Exception as e:
        log.exception(f"Exception reading qlmatch manifest for instance {instance_id}: {e}")
        return False, None, "Failed to read qlmatch manifest."
    finally:
        if client is not None:
            client.close()
