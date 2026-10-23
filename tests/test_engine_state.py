"""Engine 2 desired/actual state and heartbeat through the gateway (req #3756, I3, I4).

What the gateway half of the contract must hold:

  * a new engine state is OFF and STOPPED until somebody flips it (R6);
  * the switch takes `on`/`off` and refuses a BLANK (`ENUM_COLUMNS`);
  * a heartbeat that changes `beats` gets a DB-clock `beat_at`, and a
    desired-state flip — written through the same gateway — never does, which is
    why the heartbeat is its own table (R4);
  * another user's machine cannot be named (`CREATOR_TABLE_REFERENCES`).

The 'missing' health state itself is computed by whoever reads the beat
(darwin-mcp `services/engine2.py::engine_health`, `tests/engine/
test_contract_heartbeat.py`); this file proves the stamp it is computed from.

Requires `exports.sh` (a real darwin_dev connection).
"""
import json
import time
import uuid

import pytest

from conftest import extract_id


def _rows(response):
    assert response['statusCode'] == 200, response
    body = json.loads(response['body'])
    return json.loads(body) if isinstance(body, str) else body


@pytest.fixture(scope='module')
def scope(invoke, test_data, db_connection):
    tag = uuid.uuid4().hex[:6]
    pipeline_id = extract_id(invoke('POST', '/darwin_dev/pipelines',
                                    body={'title': f'eng-st-{tag}'}))
    machine_id = extract_id(invoke('POST', '/darwin_dev/machines', body={
        'title': f'eng-st-{tag}', 'hostname': f'eng-st-{tag}-{int(time.time())}',
        'platform': 'darwin', 'arch': 'arm64'}))
    assert pipeline_id and machine_id
    yield {'pipeline': pipeline_id, 'machine': machine_id}
    with db_connection.cursor() as cur:
        cur.execute('DELETE FROM pipelines WHERE id = %s', (pipeline_id,))
        cur.execute('DELETE FROM machines WHERE id = %s', (machine_id,))
    db_connection.commit()


@pytest.fixture(scope='module')
def state(invoke, scope):
    resp = invoke('POST', '/darwin_dev/engine_states', body={
        'pipeline_fk': scope['pipeline'], 'machine_fk': scope['machine']})
    assert resp['statusCode'] == 200, resp
    return extract_id(resp)


def test_a_new_state_is_off_and_stopped(invoke, state):
    row = _rows(invoke('GET', '/darwin_dev/engine_states', query={'id': state}))[0]
    assert row['desired_state'] == 'off'
    assert row['actual_state'] == 'stopped'
    assert row['epic_fk'] is None


def test_a_second_whole_plan_state_on_one_machine_is_a_409(invoke, scope, state):
    resp = invoke('POST', '/darwin_dev/engine_states', body={
        'pipeline_fk': scope['pipeline'], 'machine_fk': scope['machine']})
    assert resp['statusCode'] == 409, resp


def test_the_switch_flips(invoke, state):
    resp = invoke('PUT', '/darwin_dev/engine_states', body=[{
        'id': state, 'desired_state': 'on', 'desired_reason': 'user'}])
    assert resp['statusCode'] == 200, resp
    row = _rows(invoke('GET', '/darwin_dev/engine_states', query={'id': state}))[0]
    assert row['desired_state'] == 'on'


@pytest.mark.parametrize('column', ['desired_state', 'actual_state'])
def test_a_blank_switch_is_refused(invoke, state, column):
    resp = invoke('PUT', '/darwin_dev/engine_states', body=[{'id': state, column: ''}])
    assert resp['statusCode'] == 400, resp


def test_a_beat_is_stamped_and_a_flip_is_not(invoke, state):
    resp = invoke('POST', '/darwin_dev/engine_heartbeats', body={
        'engine_state_fk': state, 'beats': 1,
        'health': json.dumps({'read_ok': False, 'degraded_count': 1})})
    assert resp['statusCode'] == 200, resp
    beat = extract_id(resp)
    row = _rows(invoke('GET', '/darwin_dev/engine_heartbeats', query={'id': beat}))[0]
    assert row['beat_at'] is None                   # never beat-UPDATED yet
    assert row['health'] == {'read_ok': False, 'degraded_count': 1}

    invoke('PUT', '/darwin_dev/engine_states', body=[{'id': state, 'desired_state': 'off'}])
    row = _rows(invoke('GET', '/darwin_dev/engine_heartbeats', query={'id': beat}))[0]
    assert row['beat_at'] is None                   # the flip stamped nothing

    resp = invoke('PUT', '/darwin_dev/engine_heartbeats', body=[{'id': beat, 'beats': 2}])
    assert resp['statusCode'] == 200, resp
    row = _rows(invoke('GET', '/darwin_dev/engine_heartbeats', query={'id': beat}))[0]
    assert row['beat_at'] is not None               # the beat did


def test_another_users_machine_cannot_be_named(scope):
    from handler import lambda_handler
    stranger = f'eng-stranger-{uuid.uuid4().hex[:6]}'

    def call(method, path, body):
        return lambda_handler({
            'httpMethod': method, 'path': path, 'queryStringParameters': None,
            'body': json.dumps(body),
            'requestContext': {'authorizer': {'claims': {'sub': stranger}}}}, {})

    call('POST', '/darwin_dev/profiles', {'id': stranger, 'name': 'stranger',
                                          'email': f'{stranger}@test.invalid'})
    try:
        own = extract_id(call('POST', '/darwin_dev/pipelines', {'title': 'stranger'}))
        resp = call('POST', '/darwin_dev/engine_states', {
            'pipeline_fk': own, 'machine_fk': scope['machine']})
        assert resp['statusCode'] == 403, resp
    finally:
        call('DELETE', '/darwin_dev/pipelines', {'title': 'stranger'})
        call('DELETE', '/darwin_dev/profiles', {'id': stranger})
