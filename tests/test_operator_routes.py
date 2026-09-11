import pytest
from tests.helpers import make_user, auth_headers
from ui.models import Operator
from ui import db


VALID_STEAM_ID = '76561198000000001'
VALID_STEAM_ID_2 = '76561198000000002'


# --- GET /api/operators/ ---

def test_list_operators_authenticated(client, app):
    make_user(app, 'listuser1', 'password123')
    headers = auth_headers(app, 'listuser1')
    with app.app_context():
        db.session.add(Operator(name='Alice', steam_id64=VALID_STEAM_ID))
        db.session.commit()
    response = client.get('/api/operators/', headers=headers)
    assert response.status_code == 200
    data = response.get_json()['data']
    assert len(data) == 1
    assert data[0]['name'] == 'Alice'
    assert data[0]['steam_id64'] == VALID_STEAM_ID
    assert data[0]['default_level'] == 5


def test_list_operators_unauthenticated(client, app):
    response = client.get('/api/operators/')
    assert response.status_code == 401


def test_list_operators_ordered_by_name(client, app):
    make_user(app, 'admin1', 'admin1pass1')
    headers = auth_headers(app, 'admin1')
    with app.app_context():
        db.session.add(Operator(name='Zed', steam_id64=VALID_STEAM_ID))
        db.session.add(Operator(name='Alice', steam_id64=VALID_STEAM_ID_2))
        db.session.commit()
    response = client.get('/api/operators/', headers=headers)
    names = [op['name'] for op in response.get_json()['data']]
    assert names == sorted(names)


# --- POST /api/operators/ ---

def test_create_operator_success(client, app):
    make_user(app, 'creator', 'creatorpass')
    headers = auth_headers(app, 'creator')
    response = client.post('/api/operators/', headers=headers, json={
        'name': 'Bob',
        'steam_id64': VALID_STEAM_ID,
        'default_level': 3,
    })
    assert response.status_code == 201
    data = response.get_json()['data']
    assert data['name'] == 'Bob'
    assert data['steam_id64'] == VALID_STEAM_ID
    assert data['default_level'] == 3

    with app.app_context():
        operator = Operator.query.filter_by(steam_id64=VALID_STEAM_ID).first()
        assert operator is not None
        assert operator.name == 'Bob'


def test_create_operator_default_level_defaults_to_5(client, app):
    make_user(app, 'creator2', 'creator2pass')
    headers = auth_headers(app, 'creator2')
    response = client.post('/api/operators/', headers=headers, json={
        'name': 'Carol',
        'steam_id64': VALID_STEAM_ID,
    })
    assert response.status_code == 201
    assert response.get_json()['data']['default_level'] == 5


def test_create_operator_unauthenticated(client, app):
    response = client.post('/api/operators/', json={
        'name': 'Hacker',
        'steam_id64': VALID_STEAM_ID,
    })
    assert response.status_code == 401


def test_create_operator_missing_body(client, app):
    make_user(app, 'adminuser', 'adminpass12')
    headers = auth_headers(app, 'adminuser')
    response = client.post('/api/operators/', headers=headers,
                            data='not json', content_type='text/plain')
    assert response.status_code in (400, 415)


def test_create_operator_missing_name(client, app):
    make_user(app, 'admin2', 'admin2pass1')
    headers = auth_headers(app, 'admin2')
    response = client.post('/api/operators/', headers=headers, json={
        'steam_id64': VALID_STEAM_ID,
    })
    assert response.status_code == 400


def test_create_operator_invalid_steam_id(client, app):
    make_user(app, 'admin3', 'admin3pass1')
    headers = auth_headers(app, 'admin3')
    response = client.post('/api/operators/', headers=headers, json={
        'name': 'Dave',
        'steam_id64': 'not-a-steamid',
    })
    assert response.status_code == 400


def test_create_operator_invalid_default_level(client, app):
    make_user(app, 'admin4', 'admin4pass1')
    headers = auth_headers(app, 'admin4')
    response = client.post('/api/operators/', headers=headers, json={
        'name': 'Eve',
        'steam_id64': VALID_STEAM_ID,
        'default_level': 9,
    })
    assert response.status_code == 400


def test_create_operator_duplicate_steam_id(client, app):
    make_user(app, 'admin5', 'admin5pass1')
    headers = auth_headers(app, 'admin5')
    with app.app_context():
        db.session.add(Operator(name='Existing', steam_id64=VALID_STEAM_ID))
        db.session.commit()
    response = client.post('/api/operators/', headers=headers, json={
        'name': 'Duplicate',
        'steam_id64': VALID_STEAM_ID,
    })
    assert response.status_code == 409


# --- PATCH /api/operators/<id> ---

def test_update_operator_success(client, app):
    make_user(app, 'admin6', 'admin6pass1')
    headers = auth_headers(app, 'admin6')
    with app.app_context():
        operator = Operator(name='Frank', steam_id64=VALID_STEAM_ID, default_level=5)
        db.session.add(operator)
        db.session.commit()
        operator_id = operator.id
    response = client.patch(f'/api/operators/{operator_id}', headers=headers, json={
        'name': 'Franklin',
        'default_level': 2,
    })
    assert response.status_code == 200
    data = response.get_json()['data']
    assert data['name'] == 'Franklin'
    assert data['default_level'] == 2
    assert data['steam_id64'] == VALID_STEAM_ID


def test_update_operator_not_found(client, app):
    make_user(app, 'admin7', 'admin7pass1')
    headers = auth_headers(app, 'admin7')
    response = client.patch('/api/operators/99999', headers=headers, json={'name': 'Ghost'})
    assert response.status_code == 404


def test_update_operator_unauthenticated(client, app):
    with app.app_context():
        operator = Operator(name='Grace', steam_id64=VALID_STEAM_ID)
        db.session.add(operator)
        db.session.commit()
        operator_id = operator.id
    response = client.patch(f'/api/operators/{operator_id}', json={'name': 'Hacked'})
    assert response.status_code == 401


def test_update_operator_duplicate_steam_id(client, app):
    make_user(app, 'admin8', 'admin8pass1')
    headers = auth_headers(app, 'admin8')
    with app.app_context():
        db.session.add(Operator(name='Holder', steam_id64=VALID_STEAM_ID))
        target = Operator(name='Target', steam_id64=VALID_STEAM_ID_2)
        db.session.add(target)
        db.session.commit()
        target_id = target.id
    response = client.patch(f'/api/operators/{target_id}', headers=headers, json={
        'steam_id64': VALID_STEAM_ID,
    })
    assert response.status_code == 409


# --- DELETE /api/operators/<id> ---

def test_delete_operator_success(client, app):
    make_user(app, 'admin9', 'admin9pass1')
    headers = auth_headers(app, 'admin9')
    with app.app_context():
        operator = Operator(name='Ivan', steam_id64=VALID_STEAM_ID)
        db.session.add(operator)
        db.session.commit()
        operator_id = operator.id
    response = client.delete(f'/api/operators/{operator_id}', headers=headers)
    assert response.status_code == 200

    with app.app_context():
        assert db.session.get(Operator, operator_id) is None


def test_delete_operator_unauthenticated(client, app):
    with app.app_context():
        operator = Operator(name='Jack', steam_id64=VALID_STEAM_ID)
        db.session.add(operator)
        db.session.commit()
        operator_id = operator.id
    response = client.delete(f'/api/operators/{operator_id}')
    assert response.status_code == 401


def test_delete_operator_not_found(client, app):
    make_user(app, 'admin10', 'admin10pass1')
    headers = auth_headers(app, 'admin10')
    response = client.delete('/api/operators/99999', headers=headers)
    assert response.status_code == 404
