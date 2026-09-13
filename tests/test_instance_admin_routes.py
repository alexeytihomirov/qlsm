from unittest.mock import patch

from ui import db
from ui.models import Host, QLInstance
from tests.helpers import auth_headers, make_user


def _seed():
    host = Host(name='host-a', ip_address='10.0.0.1', ssh_user='root',
                ssh_key_path='/keys/id', ssh_port=22, provider='vultr')
    db.session.add(host)
    db.session.flush()
    instance = QLInstance(name='inst-a', port=27960, hostname='hn', host_id=host.id)
    db.session.add(instance)
    db.session.commit()
    return instance


def test_returns_the_admins_read_from_redis(client, app):
    make_user(app, 'adminuser', 'password123')
    headers = auth_headers(app, 'adminuser')
    with app.app_context():
        instance_id = _seed().id
    admins = [{'steam_id64': '76561198087654321', 'level': 5}]
    with patch('ui.routes.instance_admin_routes.read_live_admins', return_value=(admins, None)):
        response = client.get(f'/api/instances/{instance_id}/admins', headers=headers)
    assert response.status_code == 200
    assert response.get_json()['data'] == {'admins': admins, 'error': None}


def test_unreachable_host_is_200_with_an_error_string(client, app):
    make_user(app, 'adminuser', 'password123')
    headers = auth_headers(app, 'adminuser')
    with app.app_context():
        instance_id = _seed().id
    with patch('ui.routes.instance_admin_routes.read_live_admins',
               return_value=(None, 'The server is unreachable, so admin levels could not be read.')):
        response = client.get(f'/api/instances/{instance_id}/admins', headers=headers)
    assert response.status_code == 200
    data = response.get_json()['data']
    assert data['admins'] is None
    assert 'unreachable' in data['error']


def test_unknown_instance_is_404(client, app):
    make_user(app, 'adminuser', 'password123')
    response = client.get('/api/instances/424242/admins', headers=auth_headers(app, 'adminuser'))
    assert response.status_code == 404


def test_requires_authentication(client, app):
    with app.app_context():
        instance_id = _seed().id
    assert client.get(f'/api/instances/{instance_id}/admins').status_code == 401
