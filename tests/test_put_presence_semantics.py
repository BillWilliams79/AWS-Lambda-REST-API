"""PUT distinguishes absent / NULL / empty-string (req #3172).

req #3172 was filed against a measured symptom: `update_requirement
{"affected_repos":""}` and `{"affected_repos":null}` both left the stored value
unchanged, indistinguishable from never sending the key at all. The requirement
framed the fix as belonging in `rest_put`/`rest_post` — "the gateway cannot
distinguish 'the caller did not mention this field' from 'the caller explicitly
sent empty/null'".

Re-measured here, directly against `lambda_handler` (bypassing every layer above
it — darwin-mcp's tool wrappers, the MCP transport), THIS layer already gets it
right: `rest_put.py` builds its SET clause from `body.keys()` — on BOTH of its
two independent code paths, the single-record `UPDATE ... SET col = %s` path
and the bulk `CASE id WHEN ... END` path for a multi-row PUT — so a key's mere
PRESENCE in a row's JSON body, whatever its value, puts it in that row's SET
clause. A row that never mentions the key is the only shape that leaves the
column alone, on either path. These tests pin that behaviour down as a
conformance guarantee so it cannot regress silently, across all three ownership
classes `auth_utils.py` defines (`memory/database.md` § Single DB Gateway Rule):

  * CREATOR_FK_TABLES — `requirements.affected_repos` (req #3172's own column)
  * PROFILE_TABLE      — `profiles.timezone`
  * JUNCTION_OWNERSHIP — `map_coordinates.altitude` (NULL/absent only — a
    DECIMAL column has no "empty string" state; an empty string sent to it
    either fails or coerces under this RDS instance's non-strict `sql_mode`,
    neither of which is the question this file asks)

The actual defect req #3172 reports lives one layer up: `darwin-mcp/server.py`'s
`update_requirement` tool used `affected_repos: str = ""` as BOTH the
"parameter omitted" default AND the value a caller sends to mean "write an
empty string" — collapsing the two by construction, no matter what
`rest_put.py` does with what it is handed. That tool now accepts the word
'empty' as a value distinguishable from omission (darwin-mcp/tests/
test_tool_layer.py::test_update_requirement_empty_writes_literal_empty_string).
This file's job is the other half: proving the layer BENEATH that fix already
carries a key's presence and value through faithfully, so nothing here needs
to change and nothing here should regress.
"""
import time
import uuid

import pytest

from conftest import extract_id


# ---------------------------------------------------------------------------
# Fixtures — dedicated identity, isolated from the shared test_data profile.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def owner_fk():
    return f"put-presence-{int(time.time())}-{uuid.uuid4().hex[:6]}"


def _invoker(sub):
    from handler import lambda_handler
    import json

    def _invoke(method, path, query=None, body=None):
        return lambda_handler({
            'httpMethod': method,
            'path': path,
            'queryStringParameters': query,
            'body': json.dumps(body) if body is not None else None,
            'requestContext': {'authorizer': {'claims': {'sub': sub}}},
        }, {})
    return _invoke


def _purge(conn, creator):
    import pymysql as _pymysql
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM map_coordinates WHERE map_run_fk IN "
                        "(SELECT id FROM map_runs WHERE creator_fk = %s)", (creator,))
            cur.execute("DELETE FROM map_runs WHERE creator_fk = %s", (creator,))
            cur.execute("DELETE FROM requirements WHERE creator_fk = %s", (creator,))
            cur.execute("DELETE FROM categories WHERE creator_fk = %s", (creator,))
            cur.execute("DELETE FROM projects WHERE creator_fk = %s", (creator,))
            cur.execute("DELETE FROM profiles WHERE id = %s", (creator,))
        conn.commit()
    except _pymysql.MySQLError:
        conn.rollback()


@pytest.fixture(scope="module")
def owner(owner_fk, db_connection):
    invoke = _invoker(owner_fk)
    invoke('POST', '/darwin_dev/profiles', body={
        'id': owner_fk, 'name': 'put-presence owner',
        'email': 'put-presence@test.invalid'})
    yield invoke
    _purge(db_connection, owner_fk)


@pytest.fixture(scope="module")
def category_id(owner):
    resp = owner('POST', '/darwin_dev/projects', body={'project_name': 'put-presence project'})
    assert resp['statusCode'] == 200, resp
    project_id = int(extract_id(resp))

    resp = owner('POST', '/darwin_dev/categories', body={
        'category_name': 'put-presence category', 'project_fk': project_id})
    assert resp['statusCode'] == 200, resp
    return int(extract_id(resp))


def _fresh_requirement(owner, req_id):
    """A second, independent GET — never trust the PUT's own (empty) response body."""
    resp = owner('GET', '/darwin_dev/requirements', query={'id': req_id})
    assert resp['statusCode'] == 200, resp
    import json
    return json.loads(resp['body'])[0]


def _fresh_profile(owner, profile_id):
    resp = owner('GET', '/darwin_dev/profiles', query={'id': profile_id})
    assert resp['statusCode'] == 200, resp
    import json
    return json.loads(resp['body'])[0]


def _fresh_coordinate(owner, coord_id):
    resp = owner('GET', '/darwin_dev/map_coordinates', query={'id': coord_id})
    assert resp['statusCode'] == 200, resp
    import json
    return json.loads(resp['body'])[0]


# ---------------------------------------------------------------------------
# CREATOR_FK_TABLES — requirements.affected_repos
# ---------------------------------------------------------------------------

def test_creator_fk_table_absent_key_leaves_value_unchanged(owner, category_id):
    resp = owner('POST', '/darwin_dev/requirements', body={
        'title': 'put-presence req', 'category_fk': category_id,
        'affected_repos': 'Darwin'})
    assert resp['statusCode'] == 200, resp
    req_id = extract_id(resp)

    # PUT that never mentions affected_repos at all.
    put_resp = owner('PUT', '/darwin_dev/requirements',
                     body=[{'id': req_id, 'title': 'put-presence req renamed'}])
    assert put_resp['statusCode'] == 200, put_resp

    row = _fresh_requirement(owner, req_id)
    assert row['title'] == 'put-presence req renamed'
    assert row['affected_repos'] == 'Darwin', (
        "a PUT that never named affected_repos must leave it untouched")


def test_creator_fk_table_present_null_clears_the_column(owner, category_id):
    resp = owner('POST', '/darwin_dev/requirements', body={
        'title': 'put-presence req null', 'category_fk': category_id,
        'affected_repos': 'Darwin'})
    req_id = extract_id(resp)

    put_resp = owner('PUT', '/darwin_dev/requirements',
                     body=[{'id': req_id, 'affected_repos': None}])
    assert put_resp['statusCode'] == 200, put_resp

    row = _fresh_requirement(owner, req_id)
    assert row['affected_repos'] is None, (
        "a PUT body naming affected_repos with a JSON null must write SQL NULL")


def test_creator_fk_table_present_empty_string_writes_empty_string(owner, category_id):
    resp = owner('POST', '/darwin_dev/requirements', body={
        'title': 'put-presence req empty', 'category_fk': category_id,
        'affected_repos': 'Darwin'})
    req_id = extract_id(resp)

    put_resp = owner('PUT', '/darwin_dev/requirements',
                     body=[{'id': req_id, 'affected_repos': ''}])
    assert put_resp['statusCode'] == 200, put_resp

    row = _fresh_requirement(owner, req_id)
    assert row['affected_repos'] == '', (
        "a PUT body naming affected_repos with an explicit \"\" must write a "
        "literal empty string, distinct from NULL")
    assert row['affected_repos'] is not None


def test_creator_fk_table_bulk_put_case_syntax_has_the_same_presence_semantics(
        owner, category_id):
    """`rest_put.py` has TWO SET-clause builders — a single-record `UPDATE ...
    SET col = %s` path and a bulk `CASE id WHEN ... END` path for a multi-row
    PUT (live traffic: PriorityCard.jsx's hand-sort save). They are separate
    code, so the single-record tests above prove nothing about this one.
    """
    resp_a = owner('POST', '/darwin_dev/requirements', body={
        'title': 'put-presence bulk a', 'category_fk': category_id,
        'affected_repos': 'Darwin'})
    req_a = extract_id(resp_a)
    resp_b = owner('POST', '/darwin_dev/requirements', body={
        'title': 'put-presence bulk b', 'category_fk': category_id,
        'affected_repos': 'Darwin'})
    req_b = extract_id(resp_b)

    # Bulk PUT: row A explicitly clears affected_repos to NULL, row B never
    # mentions the column at all.
    put_resp = owner('PUT', '/darwin_dev/requirements', body=[
        {'id': req_a, 'affected_repos': None},
        {'id': req_b, 'title': 'put-presence bulk b renamed'},
    ])
    assert put_resp['statusCode'] == 200, put_resp

    row_a = _fresh_requirement(owner, req_a)
    row_b = _fresh_requirement(owner, req_b)
    assert row_a['affected_repos'] is None, (
        "bulk CASE-syntax PUT must write NULL for a key present with a JSON null")
    assert row_b['affected_repos'] == 'Darwin', (
        "bulk CASE-syntax PUT must leave a column alone for a row that never "
        "named it, even though a SIBLING row in the same statement did")
    assert row_b['title'] == 'put-presence bulk b renamed'


# ---------------------------------------------------------------------------
# PROFILE_TABLE — profiles.timezone
# ---------------------------------------------------------------------------

def test_profile_table_absent_key_leaves_value_unchanged(owner, owner_fk):
    resp = owner('PUT', '/darwin_dev/profiles',
                 body=[{'id': owner_fk, 'timezone': 'America/Los_Angeles'}])
    assert resp['statusCode'] == 200, resp

    put_resp = owner('PUT', '/darwin_dev/profiles',
                     body=[{'id': owner_fk, 'name': 'put-presence owner renamed'}])
    assert put_resp['statusCode'] == 200, put_resp

    row = _fresh_profile(owner, owner_fk)
    assert row['name'] == 'put-presence owner renamed'
    assert row['timezone'] == 'America/Los_Angeles'


def test_profile_table_present_null_and_empty_are_distinct(owner, owner_fk):
    owner('PUT', '/darwin_dev/profiles',
         body=[{'id': owner_fk, 'timezone': 'America/Los_Angeles'}])

    put_resp = owner('PUT', '/darwin_dev/profiles', body=[{'id': owner_fk, 'timezone': None}])
    assert put_resp['statusCode'] == 200, put_resp
    assert _fresh_profile(owner, owner_fk)['timezone'] is None

    owner('PUT', '/darwin_dev/profiles',
         body=[{'id': owner_fk, 'timezone': 'America/Los_Angeles'}])
    put_resp = owner('PUT', '/darwin_dev/profiles', body=[{'id': owner_fk, 'timezone': ''}])
    assert put_resp['statusCode'] == 200, put_resp
    row = _fresh_profile(owner, owner_fk)
    assert row['timezone'] == ''
    assert row['timezone'] is not None


# ---------------------------------------------------------------------------
# JUNCTION_OWNERSHIP — map_coordinates.altitude (no creator_fk of its own;
# scoped through map_runs, req #3122). NULL/absent only — see module docstring
# for why "empty string" is not a state this column has.
# ---------------------------------------------------------------------------

@pytest.fixture
def map_run_id(owner):
    resp = owner('POST', '/darwin_dev/map_runs', body={
        'run_id': int(time.time() * 1000) % 2_000_000_000,
        'activity_id': 1, 'activity_name': 'Ride',
        'start_time': '2026-08-14 12:00:00',
        'run_time_sec': 3600, 'distance_mi': '10.0',
    })
    assert resp['statusCode'] == 200, resp
    return int(extract_id(resp))


def test_junction_ownership_table_absent_key_leaves_value_unchanged(owner, map_run_id):
    resp = owner('POST', '/darwin_dev/map_coordinates', body={
        'map_run_fk': map_run_id, 'seq': 1,
        'latitude': '37.0', 'longitude': '-122.0', 'altitude': '100.5'})
    assert resp['statusCode'] == 200, resp
    coord_id = extract_id(resp)

    put_resp = owner('PUT', '/darwin_dev/map_coordinates',
                     body=[{'id': coord_id, 'seq': 2}])
    assert put_resp['statusCode'] == 200, put_resp

    row = _fresh_coordinate(owner, coord_id)
    assert row['seq'] == 2
    assert float(row['altitude']) == 100.5, (
        "a PUT that never named altitude must leave it untouched")


def test_junction_ownership_table_present_null_clears_the_column(owner, map_run_id):
    resp = owner('POST', '/darwin_dev/map_coordinates', body={
        'map_run_fk': map_run_id, 'seq': 3,
        'latitude': '37.0', 'longitude': '-122.0', 'altitude': '100.5'})
    coord_id = extract_id(resp)

    put_resp = owner('PUT', '/darwin_dev/map_coordinates',
                     body=[{'id': coord_id, 'altitude': None}])
    assert put_resp['statusCode'] == 200, put_resp

    row = _fresh_coordinate(owner, coord_id)
    assert row['altitude'] is None, (
        "a PUT body naming altitude with a JSON null must write SQL NULL, even "
        "on a table scoped through its parent rather than its own creator_fk")
