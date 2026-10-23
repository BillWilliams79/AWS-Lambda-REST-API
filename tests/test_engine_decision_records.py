"""Engine 2 decision records round-trip through the gateway (req #3756, interface I2).

The acceptance test of the data contract: a decision record WRITTEN BY THE
SCENARIO MODEL (`tests/fixtures/engine_decision_record.json`, produced by
`scripts/swarm/engine2` for scenario `capacity-full-then-freeing` — the cycle
that admits two requirements) is POSTed through `lambda_handler`, read back,
and is IDENTICAL — and still hashes to its own id, so it still replays (R12).
Its stored inputs read back hashing to their keys.

The indexed columns (`pipeline_fk`, `machine_fk`) name rows this test owns;
the record JSON is the fixture untouched, so its own location (plan 900) is
fixture data. Keeping the two consistent is darwin-mcp's job
(`services/engine2.py::engine_record_row`), not the gateway's — the gateway's
job, proved here, is that what goes in comes out.

Requires `exports.sh` (a real darwin_dev connection).
"""
import hashlib
import json
import os
import time
import uuid

import pytest

from conftest import extract_id

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'engine_decision_record.json')


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def content_hash(obj):
    return 'sha256:' + hashlib.sha256(canonical(obj).encode('utf-8')).hexdigest()


def record_id(record):
    return content_hash({k: v for k, v in record.items() if k != 'id'})


@pytest.fixture(scope='module')
def fixture():
    with open(FIXTURE) as fh:
        return json.load(fh)


def _rows(response):
    assert response['statusCode'] == 200, response
    body = json.loads(response['body'])
    return json.loads(body) if isinstance(body, str) else body


@pytest.fixture(scope='module')
def scope(invoke, test_data, db_connection, creator_fk):
    tag = uuid.uuid4().hex[:6]
    resp = invoke('POST', '/darwin_dev/pipelines', body={'title': f'eng-rt-{tag}'})
    pipeline_id = extract_id(resp)
    resp = invoke('POST', '/darwin_dev/machines', body={
        'title': f'eng-rt-{tag}', 'hostname': f'eng-rt-{tag}-{int(time.time())}',
        'platform': 'darwin', 'arch': 'arm64'})
    machine_id = extract_id(resp)
    assert pipeline_id and machine_id
    yield {'pipeline': int(pipeline_id), 'machine': int(machine_id)}
    with db_connection.cursor() as cur:
        cur.execute('DELETE FROM engine_inputs WHERE creator_fk = %s', (creator_fk,))
        cur.execute('DELETE FROM pipelines WHERE id = %s', (pipeline_id,))
        cur.execute('DELETE FROM machines WHERE id = %s', (machine_id,))
    db_connection.commit()


def _record_body(record, scope):
    inputs = record['inputs']
    return {
        'record_hash': record['id'], 'prior_hash': record['prior_id'],
        'pipeline_fk': scope['pipeline'], 'machine_fk': scope['machine'],
        'claim_id': record['location']['claim_id'], 'seq': record['cycle']['seq'],
        'verdict': record['cycle']['verdict'],
        'admitted_count': sum(1 for q in record['queue'] if q['code'] == 'ADMITTED'),
        'queue_count': len(record['queue']), 'cut': record['cut'],
        'plan_payload_hash': inputs['plan_payload'], 'capacity_hash': inputs['capacity'],
        'claims_hash': inputs['claims'], 'clock_hash': inputs['clock'],
        'prior_record_hash': inputs['prior_record'],
        'record': canonical(record), 'record_bytes': len(canonical(record).encode()),
    }


def test_the_fixture_is_a_scenario_model_record(fixture):
    record = fixture['record']
    assert record['schema'] == 'engine2.decision_record/1'
    assert record_id(record) == record['id']
    assert any(q['code'] == 'ADMITTED' for q in record['queue'])


def test_a_scenario_record_round_trips_identical(invoke, scope, fixture):
    record = fixture['record']
    resp = invoke('POST', '/darwin_dev/engine_decision_records',
                  body=_record_body(record, scope))
    assert resp['statusCode'] == 200, resp
    row_id = extract_id(resp)

    rows = _rows(invoke('GET', '/darwin_dev/engine_decision_records', query={'id': row_id}))
    assert len(rows) == 1
    stored = rows[0]['record']
    assert stored == record
    assert record_id(stored) == record['id'] == rows[0]['record_hash']
    assert rows[0]['admitted_count'] == 2


def test_the_list_projection_leaves_the_record_out(invoke, scope, fixture):
    rows = _rows(invoke('GET', '/darwin_dev/engine_decision_records', query={
        'pipeline_fk': str(scope['pipeline']),
        'fields': 'id,record_hash,seq,verdict,admitted_count'}))
    assert rows and all('record' not in r for r in rows)


def test_the_inputs_round_trip_hashing_to_their_keys(invoke, scope, fixture):
    record = fixture['record']
    for name, digest in record['inputs'].items():
        if name == 'prior_record':
            continue                 # resolved from the records table by its id
        body = fixture['inputs'][digest]
        resp = invoke('POST', '/darwin_dev/engine_inputs', body={
            'content_hash': digest, 'input_kind': name, 'body': canonical(body),
            'body_bytes': len(canonical(body).encode())})
        assert resp['statusCode'] == 200, resp
        rows = _rows(invoke('GET', '/darwin_dev/engine_inputs', query={'content_hash': digest}))
        assert rows[0]['body'] == body
        assert content_hash(rows[0]['body']) == digest


def test_an_input_hash_is_stored_once(invoke, scope, fixture):
    digest = fixture['record']['inputs']['clock']
    body = fixture['inputs'][digest]
    resp = invoke('POST', '/darwin_dev/engine_inputs', body={
        'content_hash': digest, 'input_kind': 'clock', 'body': canonical(body)})
    assert resp['statusCode'] == 409, resp


def test_a_blank_verdict_is_refused(invoke, scope, fixture):
    body = _record_body(fixture['record'], scope)
    body['record_hash'] = 'sha256:' + 'b' * 64
    body['verdict'] = ''
    resp = invoke('POST', '/darwin_dev/engine_decision_records', body=body)
    assert resp['statusCode'] == 400, resp


def test_an_outcome_is_answered_and_read_back(invoke, scope, fixture, db_connection):
    rows = _rows(invoke('GET', '/darwin_dev/engine_decision_records', query={
        'record_hash': fixture['record']['id'], 'fields': 'id'}))
    record_fk = rows[0]['id']
    resp = invoke('POST', '/darwin_dev/projects', body={'project_name': 'eng-rt'})
    project = extract_id(resp)
    resp = invoke('POST', '/darwin_dev/categories', body={'category_name': 'eng-rt',
                                                          'project_fk': project})
    category = extract_id(resp)
    resp = invoke('POST', '/darwin_dev/requirements', body={'title': 'eng-rt',
                                                            'category_fk': category})
    requirement = extract_id(resp)
    try:
        resp = invoke('POST', '/darwin_dev/engine_outcomes', body={
            'record_fk': record_fk, 'requirement_fk': requirement})
        assert resp['statusCode'] == 200, resp
        outcome = extract_id(resp)
        resp = invoke('PUT', '/darwin_dev/engine_outcomes', body=[{
            'id': outcome, 'outcome_state': 'landed', 'session_ids': json.dumps([41, 42])}])
        assert resp['statusCode'] == 200, resp
        row = _rows(invoke('GET', '/darwin_dev/engine_outcomes', query={'id': outcome}))[0]
        assert row['outcome_state'] == 'landed'
        assert row['session_ids'] == [41, 42]
    finally:
        with db_connection.cursor() as cur:
            cur.execute('DELETE FROM requirements WHERE id = %s', (requirement,))
            cur.execute('DELETE FROM categories WHERE id = %s', (category,))
            cur.execute('DELETE FROM projects WHERE id = %s', (project,))
        db_connection.commit()


def test_another_user_cannot_read_the_record(scope, fixture, db_connection):
    from handler import lambda_handler
    stranger = f'eng-stranger-{uuid.uuid4().hex[:6]}'
    resp = lambda_handler({
        'httpMethod': 'GET', 'path': '/darwin_dev/engine_decision_records',
        'queryStringParameters': {'record_hash': fixture['record']['id']}, 'body': None,
        'requestContext': {'authorizer': {'claims': {'sub': stranger}}}}, {})
    assert resp['statusCode'] == 404, resp
