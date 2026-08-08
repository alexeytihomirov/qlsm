"""DB-backed Vultr API key.

VULTR_API_KEY historically lived only in .env, which meant it never
traveled with a global backup/restore. This mirrors the ApiKey model's
precedent ("single-user app where the key is always viewable in the
Settings UI") by storing it in the existing generic AppSetting table
instead, while still falling back to os.environ so an existing install's
.env keeps working until the value is saved once through the UI.
"""
import os

from ui import db
from ui.models import AppSetting

VULTR_API_KEY_SETTING = 'vultr_api_key'


def get_vultr_api_key():
    """Return the configured Vultr API key (DB value wins over .env)."""
    row = AppSetting.query.get(VULTR_API_KEY_SETTING)
    if row and row.value.strip():
        return row.value.strip()
    return os.environ.get('VULTR_API_KEY', '').strip()


def set_vultr_api_key(value):
    """Create/update/clear the DB-backed Vultr API key. Does not commit."""
    value = (value or '').strip()
    row = AppSetting.query.get(VULTR_API_KEY_SETTING)
    if not value:
        if row:
            db.session.delete(row)
        return
    if row:
        row.value = value
    else:
        db.session.add(AppSetting(key=VULTR_API_KEY_SETTING, value=value))


def is_vultr_configured():
    return bool(get_vultr_api_key())
