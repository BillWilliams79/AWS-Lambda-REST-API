"""A pipeline's status and its derived timestamps, end to end against darwin_dev
(req #3965), through the real `lambda_handler` — the path the browser's editors
write on.
"""
import json
import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from test_pipeline2_compose import _invoker, _purge, extract_id   # noqa: E402


@pytest.fixture(scope="module")
def owner_fk():
    return f"lifecycle-owner-{int(time.time())}-{uuid.uuid4().hex[:6]}"


@pytest.fixture(scope="module")
def owner(owner_fk, db_connection):
    invoke = _invoker(owner_fk)
    invoke('POST', '/darwin_dev/profiles', body={
        'id': owner_fk, 'name': 'lifecycle owner', 'email': 'lifecycle@test.invalid'})
    yield invoke
    _purge(db_connection, owner_fk)


def _row(owner, pipeline_id):
    resp = owner('GET', '/darwin_dev/pipelines', query={
        'id': str(pipeline_id), 'fields': 'id,pipeline_status,started_at,completed_at'})
    assert resp['statusCode'] == 200, resp
    body = json.loads(resp['body'])            # GET is double-encoded (Known Bugs)
    return (json.loads(body) if isinstance(body, str) else body)[0]


def _put(owner, row):
    return owner('PUT', '/darwin_dev/pipelines', body=[row])


def test_a_new_pipeline_is_born_authoring_with_no_stamps(owner):
    resp = owner('POST', '/darwin_dev/pipelines', body={'title': 'born'})
    row = _row(owner, int(extract_id(resp)))
    assert row['pipeline_status'] == 'authoring'
    assert row['started_at'] is None and row['completed_at'] is None


# COVERS: SCH-050
def test_the_lifecycle_round_trip(owner):
    pid = int(extract_id(owner('POST', '/darwin_dev/pipelines', body={'title': 'trip'})))

    assert _put(owner, {'id': pid, 'pipeline_status': 'orchestrating'})['statusCode'] in (200, 204)
    running = _row(owner, pid)
    assert running['started_at'] is not None and running['completed_at'] is None

    # Stopping keeps the start; finishing stamps the end and keeps it.
    _put(owner, {'id': pid, 'pipeline_status': 'orchestration_ready'})
    assert _row(owner, pid)['started_at'] == running['started_at']
    _put(owner, {'id': pid, 'pipeline_status': 'met'})
    done = _row(owner, pid)
    assert done['completed_at'] is not None
    _put(owner, {'id': pid, 'pipeline_status': 'wontfix'})
    assert _row(owner, pid)['completed_at'] == done['completed_at']

    # Re-opening clears the end; orchestrating again does not move the start.
    _put(owner, {'id': pid, 'pipeline_status': 'orchestrating'})
    again = _row(owner, pid)
    assert again['completed_at'] is None
    assert again['started_at'] == running['started_at']


@pytest.mark.parametrize('value', ['draft', 'active', 'paused', 'completed'])
def test_a_retired_value_is_refused(owner, value):
    pid = int(extract_id(owner('POST', '/darwin_dev/pipelines', body={'title': 'old'})))
    assert _put(owner, {'id': pid, 'pipeline_status': value})['statusCode'] == 400
    assert owner('POST', '/darwin_dev/pipelines',
                 body={'title': 'old', 'pipeline_status': value})['statusCode'] == 400
    assert _row(owner, pid)['pipeline_status'] == 'authoring'


def test_a_locked_plan_still_takes_its_status(owner):
    pid = int(extract_id(owner('POST', '/darwin_dev/pipelines', body={'title': 'relic'})))
    _put(owner, {'id': pid, 'locked': 1})
    try:
        assert _put(owner, {'id': pid, 'pipeline_status': 'deferred'})['statusCode'] in (200, 204)
        row = _row(owner, pid)
        assert row['pipeline_status'] == 'deferred' and row['completed_at'] is not None
    finally:
        _put(owner, {'id': pid, 'locked': 0})
