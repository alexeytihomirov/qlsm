import re

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required
from ui import db
from ui.models import Operator

operator_api_bp = Blueprint('operator_api_routes', __name__)

STEAMID64_RE = re.compile(r'^7656119\d{10}$')


def _validate_name(name):
    if not isinstance(name, str):
        return None, 'Name is required.'
    name = name.strip()
    if not name:
        return None, 'Name is required.'
    if len(name) > 128:
        return None, 'Name must be at most 128 characters.'
    return name, None


def _validate_steam_id64(steam_id64):
    if not isinstance(steam_id64, str):
        return None, 'SteamID64 is required.'
    sid = steam_id64.strip()
    if not STEAMID64_RE.match(sid):
        return None, 'SteamID64 must be a 17-digit Steam64 ID starting with 7656119.'
    return sid, None


def _validate_default_level(value):
    if value is None or value == '':
        return 5, None
    try:
        level = int(value)
    except (TypeError, ValueError):
        return None, 'Default level must be an integer between 0 and 5.'
    if level < 0 or level > 5:
        return None, 'Default level must be between 0 and 5.'
    return level, None


@operator_api_bp.route('/', methods=['GET'])
@jwt_required()
def list_operators():
    """Get all operators."""
    operators = Operator.query.order_by(Operator.name).all()
    return jsonify({'data': [op.to_dict() for op in operators]}), 200


@operator_api_bp.route('/', methods=['POST'])
@jwt_required()
def create_operator():
    """Add a new operator to the directory."""
    data = request.get_json()
    if not data:
        return jsonify({'error': {'message': 'Request body must be JSON.'}}), 400

    name, name_error = _validate_name(data.get('name', ''))
    if name_error:
        return jsonify({'error': {'message': name_error}}), 400

    steam_id64, sid_error = _validate_steam_id64(data.get('steam_id64', ''))
    if sid_error:
        return jsonify({'error': {'message': sid_error}}), 400

    default_level, level_error = _validate_default_level(data.get('default_level'))
    if level_error:
        return jsonify({'error': {'message': level_error}}), 400

    if Operator.query.filter_by(steam_id64=steam_id64).first():
        return jsonify({'error': {'message': f"Operator with SteamID64 '{steam_id64}' already exists."}}), 409

    try:
        operator = Operator(name=name, steam_id64=steam_id64, default_level=default_level)
        db.session.add(operator)
        db.session.commit()
        current_app.logger.info(f"Operator '{name}' ({steam_id64}) created.")
        return jsonify({
            'data': operator.to_dict(),
            'message': f"Operator '{name}' added successfully."
        }), 201
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating operator '{name}': {e}")
        return jsonify({'error': {'message': 'Failed to create operator.'}}), 500


@operator_api_bp.route('/<int:operator_id>', methods=['PATCH'])
@jwt_required()
def update_operator(operator_id):
    """Update an existing operator's name, SteamID64, or default level."""
    operator = db.session.get(Operator, operator_id)
    if not operator:
        return jsonify({'error': {'message': 'Operator not found.'}}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': {'message': 'Request body must be JSON.'}}), 400

    if 'name' in data:
        name, name_error = _validate_name(data.get('name', ''))
        if name_error:
            return jsonify({'error': {'message': name_error}}), 400
        operator.name = name

    if 'steam_id64' in data:
        steam_id64, sid_error = _validate_steam_id64(data.get('steam_id64', ''))
        if sid_error:
            return jsonify({'error': {'message': sid_error}}), 400
        existing = Operator.query.filter_by(steam_id64=steam_id64).first()
        if existing and existing.id != operator_id:
            return jsonify({'error': {'message': f"Operator with SteamID64 '{steam_id64}' already exists."}}), 409
        operator.steam_id64 = steam_id64

    if 'default_level' in data:
        default_level, level_error = _validate_default_level(data.get('default_level'))
        if level_error:
            return jsonify({'error': {'message': level_error}}), 400
        operator.default_level = default_level

    try:
        db.session.commit()
        return jsonify({
            'data': operator.to_dict(),
            'message': f"Operator '{operator.name}' updated successfully."
        }), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating operator {operator_id}: {e}")
        return jsonify({'error': {'message': 'Failed to update operator.'}}), 500


@operator_api_bp.route('/<int:operator_id>', methods=['DELETE'])
@jwt_required()
def delete_operator(operator_id):
    """Remove an operator from the directory."""
    operator = db.session.get(Operator, operator_id)
    if not operator:
        return jsonify({'error': {'message': 'Operator not found.'}}), 404

    try:
        name = operator.name
        db.session.delete(operator)
        db.session.commit()
        current_app.logger.info(f"Operator '{name}' deleted.")
        return jsonify({'message': f"Operator '{name}' deleted successfully."}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting operator {operator_id}: {e}")
        return jsonify({'error': {'message': 'Failed to delete operator.'}}), 500
