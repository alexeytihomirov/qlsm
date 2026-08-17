import pytest
from types import SimpleNamespace

from ui.task_logic.zmq_utils import (
    ZMQ_PASSWORD_MAX_LENGTH,
    ZMQ_PASSWORD_MIN_LENGTH,
    ensure_zmq_rcon_setup,
    generate_zmq_rcon_password,
    validate_zmq_password,
)


def test_generated_password_passes_its_own_validator():
    """The generator and the validator must never drift apart."""
    for _ in range(50):
        value, error = validate_zmq_password(generate_zmq_rcon_password(), 'Test Password')
        assert error is None
        assert value is not None


def test_none_is_accepted_and_means_auto_generate():
    assert validate_zmq_password(None, 'Test Password') == (None, None)


def test_blank_string_is_accepted_and_means_auto_generate():
    assert validate_zmq_password('   ', 'Test Password') == (None, None)


def test_valid_password_is_returned_stripped():
    value, error = validate_zmq_password('  Kp3-xR_9vT=2wQ  ', 'Test Password')
    assert error is None
    assert value == 'Kp3-xR_9vT=2wQ'


def test_non_string_is_rejected():
    value, error = validate_zmq_password(12345678, 'Test Password')
    assert value is None
    assert error == 'Test Password must be a string.'


@pytest.mark.parametrize('raw', ['short12', 'a' * (ZMQ_PASSWORD_MAX_LENGTH + 1)])
def test_out_of_range_length_is_rejected(raw):
    value, error = validate_zmq_password(raw, 'Test Password')
    assert value is None
    assert str(ZMQ_PASSWORD_MIN_LENGTH) in error and str(ZMQ_PASSWORD_MAX_LENGTH) in error


@pytest.mark.parametrize('raw', [
    'p@ssw0rdxx',
    'has spaces!',
    'quote"pass1',
    'dollar$sign1',
    'back`tick1',
    'semi;colon1',
    'hash#pass01',
])
def test_disallowed_characters_are_rejected(raw):
    """These characters get mangled by shell, Ansible, or Quake arg parsing."""
    value, error = validate_zmq_password(raw, 'Test Password')
    assert value is None
    assert 'may only contain' in error


def test_boundary_lengths_are_accepted():
    assert validate_zmq_password('a' * ZMQ_PASSWORD_MIN_LENGTH, 'P')[1] is None
    assert validate_zmq_password('a' * ZMQ_PASSWORD_MAX_LENGTH, 'P')[1] is None


def _fake_instance(**overrides):
    values = {
        'id': 1,
        'port': 27960,
        'zmq_rcon_port': None,
        'zmq_stats_port': None,
        'zmq_rcon_password': None,
        'zmq_stats_password': None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_ensure_zmq_rcon_setup_generates_missing_passwords():
    instance = _fake_instance()

    ensure_zmq_rcon_setup(instance)

    assert instance.zmq_rcon_password
    assert instance.zmq_stats_password


def test_ensure_zmq_rcon_setup_preserves_preset_passwords():
    """A manually supplied password must survive deploy untouched."""
    instance = _fake_instance(
        zmq_rcon_password='manual-rcon-01',
        zmq_stats_password='manual-stats-1',
    )

    ensure_zmq_rcon_setup(instance)

    assert instance.zmq_rcon_password == 'manual-rcon-01'
    assert instance.zmq_stats_password == 'manual-stats-1'
    assert instance.zmq_rcon_port == 28888
    assert instance.zmq_stats_port == 29999
