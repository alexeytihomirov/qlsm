from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required
from ui import db
from ui.models import ApiKey
from ui.vultr_settings import get_vultr_api_key, set_vultr_api_key
from ui.telemetry_relay_settings import (
    get_stats_hub_url,
    set_stats_hub_url,
    get_stats_hub_ingest_token,
    set_stats_hub_ingest_token,
)

settings_api_bp = Blueprint('settings_api_routes', __name__)


def require_api_key():
    """Validate Bearer token from Authorization header.

    Returns (True, None) on success or (False, response) on failure.
    """
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return False, (jsonify({'error': {'message': 'Missing or invalid Authorization header.'}}), 401)
    token = auth[len('Bearer '):]
    key = ApiKey.query.first()
    if not key or token != key.key:
        return False, (jsonify({'error': {'message': 'Invalid API key.'}}), 401)
    return True, None


# --- JWT-protected management routes ---

@settings_api_bp.route('/api-key', methods=['GET'])
@jwt_required()
def get_api_key():
    """Get the current active API key."""
    key = ApiKey.query.first()
    if not key:
        return jsonify({'data': None})
    return jsonify({'data': key.to_dict()})


@settings_api_bp.route('/api-key', methods=['POST'])
@jwt_required()
def regenerate_api_key():
    """Delete all existing keys and generate a new one."""
    ApiKey.query.delete()
    new_key = ApiKey.generate()
    db.session.add(new_key)
    db.session.commit()
    current_app.logger.info('External API key regenerated.')
    return jsonify({'data': new_key.to_dict(), 'message': 'New API key generated.'})


@settings_api_bp.route('/api-key', methods=['DELETE'])
@jwt_required()
def revoke_api_key():
    """Revoke (delete) the current API key."""
    deleted = ApiKey.query.delete()
    db.session.commit()
    if deleted:
        current_app.logger.info('External API key revoked.')
        return jsonify({'message': 'API key revoked.'})
    return jsonify({'error': {'message': 'No active API key to revoke.'}}), 404


@settings_api_bp.route('/vultr-key', methods=['GET'])
@jwt_required()
def get_vultr_key_setting():
    """Return the configured Vultr API key, or null if unset."""
    return jsonify({'data': {'key': get_vultr_api_key() or None}})


@settings_api_bp.route('/vultr-key', methods=['PUT'])
@jwt_required()
def update_vultr_key_setting():
    """Set (or clear, with an empty string) the Vultr API key."""
    data = request.get_json() or {}
    value = data.get('key', '')
    if not isinstance(value, str):
        return jsonify({'error': {'message': 'key must be a string.'}}), 400
    set_vultr_api_key(value)
    db.session.commit()
    current_app.logger.info('Vultr API key updated via Settings.')
    return jsonify({'data': {'key': get_vultr_api_key() or None}, 'message': 'Vultr API key updated.'})


@settings_api_bp.route('/stats-hub', methods=['GET'])
@jwt_required()
def get_stats_hub_setting():
    """Return the configured ql-stats-hub target (URL + ingest token), or null fields if unset.

    This is the STATS_HUB_INGEST_TOKEN from stats-hub's own .env - NOT its
    STATS_HUB_API_TOKEN (dashboard/read token). The wrong one causes a
    silent HTTP 401 on every telemetry POST.
    """
    return jsonify({'data': {
        'url': get_stats_hub_url() or None,
        'ingest_token': get_stats_hub_ingest_token() or None,
    }})


@settings_api_bp.route('/stats-hub', methods=['PUT'])
@jwt_required()
def update_stats_hub_setting():
    """Set (or clear, with an empty string) the ql-stats-hub URL/ingest token."""
    data = request.get_json() or {}
    url = data.get('url', '')
    token = data.get('ingest_token', '')
    if not isinstance(url, str) or not isinstance(token, str):
        return jsonify({'error': {'message': 'url and ingest_token must be strings.'}}), 400
    set_stats_hub_url(url)
    set_stats_hub_ingest_token(token)
    db.session.commit()
    current_app.logger.info('Stats-hub target updated via Settings.')
    return jsonify({'data': {
        'url': get_stats_hub_url() or None,
        'ingest_token': get_stats_hub_ingest_token() or None,
    }, 'message': 'Stats-hub target updated.'})

