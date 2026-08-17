import logging
import re
import secrets
import string

from ui import db
from ui.constants import BASE_GAME_PORT, ZMQ_RCON_BASE_PORT, ZMQ_STATS_BASE_PORT

log = logging.getLogger(__name__)


def generate_zmq_rcon_password(length=14):
    """Generate a secure random password for ZMQ RCON.

    Uses letters, digits, and safe punctuation (avoiding shell-problematic chars).
    """
    # Avoid: # (comment), ! (shell history), * (glob), % (format), & (background)
    # These get mangled by shell, Ansible, or Quake arg parsing even when quoted
    safe_punctuation = '-_='
    alphabet = string.ascii_letters + string.digits + safe_punctuation
    return ''.join(secrets.choice(alphabet) for _ in range(length))


ZMQ_PASSWORD_MIN_LENGTH = 8
ZMQ_PASSWORD_MAX_LENGTH = 64
# Mirrors the generator's alphabet above. Anything wider risks being mangled by
# the shell, Ansible extra-vars, or Quake arg parsing on the way to ExecStart.
ZMQ_PASSWORD_PATTERN = re.compile(r'^[A-Za-z0-9\-_=]+$')
ZMQ_PASSWORD_ALLOWED_DESCRIPTION = 'letters, digits, and - _ ='


def validate_zmq_password(raw, label):
    """Validate a user-supplied ZMQ password.

    Returns (value, error). A missing or blank value returns (None, None),
    meaning "generate one at deploy time" -- the behavior of every instance
    created before this field existed.
    """
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        return None, f"{label} must be a string."
    value = raw.strip()
    if not value:
        return None, None
    if len(value) < ZMQ_PASSWORD_MIN_LENGTH or len(value) > ZMQ_PASSWORD_MAX_LENGTH:
        return None, (
            f"{label} must be between {ZMQ_PASSWORD_MIN_LENGTH} and "
            f"{ZMQ_PASSWORD_MAX_LENGTH} characters."
        )
    if not ZMQ_PASSWORD_PATTERN.match(value):
        return None, f"{label} may only contain {ZMQ_PASSWORD_ALLOWED_DESCRIPTION}."
    return value, None


def ensure_zmq_rcon_setup(instance):
    """
    Ensure ZMQ RCON settings (port and password) are set for the instance.
    Port is calculated deterministically: 28888 + (game_port - 27960).
    If password is missing, generate it.
    """
    changed = False

    # Calculate deterministic ZMQ port
    # Base: 28888, Offset: game_port - 27960
    # e.g., 27960 -> 28888, 27961 -> 28889
    target_zmq_port = ZMQ_RCON_BASE_PORT + (instance.port - BASE_GAME_PORT)

    # Calculate deterministic ZMQ Stats port (User requested stats support)
    # Base: 29999, Offset: game_port - 27960
    target_zmq_stats_port = ZMQ_STATS_BASE_PORT + (instance.port - BASE_GAME_PORT)

    if instance.zmq_rcon_port != target_zmq_port:
        log.info(f"Updating ZMQ RCON port for instance {instance.id} from {instance.zmq_rcon_port} to {target_zmq_port}")
        instance.zmq_rcon_port = target_zmq_port
        changed = True

    if instance.zmq_stats_port != target_zmq_stats_port:
        log.info(f"Updating ZMQ Stats port for instance {instance.id} from {instance.zmq_stats_port} to {target_zmq_stats_port}")
        instance.zmq_stats_port = target_zmq_stats_port
        changed = True

    # Generate zmq_rcon_password if not already set
    if not instance.zmq_rcon_password:
        instance.zmq_rcon_password = generate_zmq_rcon_password()
        changed = True

    # Generate zmq_stats_password if not already set
    if not instance.zmq_stats_password:
        instance.zmq_stats_password = generate_zmq_rcon_password()
        changed = True

    if changed:
        log.info(f"Instance {instance.id} ZMQ RCON settings updated. Port: {instance.zmq_rcon_port}")

    return instance.zmq_rcon_port, instance.zmq_rcon_password
