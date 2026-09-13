"""Read one instance's admin list straight from its minqlx Redis database."""

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

from ui import db
from ui.models import QLInstance
from ui.task_logic.permission_read import read_live_admins

instance_admin_api_bp = Blueprint('instance_admin_api_routes', __name__)


@instance_admin_api_bp.route('/<int:instance_id>/admins', methods=['GET'])
@jwt_required()
def get_instance_admins(instance_id):
    instance = db.session.get(QLInstance, instance_id)
    if instance is None:
        return jsonify({"error": {"message": f"Instance {instance_id} not found."}}), 404

    admins, error = read_live_admins(instance)
    return jsonify({"data": {"admins": admins, "error": error}}), 200
