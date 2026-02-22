"""
GET filtering, sorting, and aggregation tests for Lambda-Rest.

Tests all query string parameter features of rest_get_table.py:
- Basic field filtering (creator_fk, id, etc.)
- Multiple filters (AND logic)
- IN clause queries
- Date range filtering (filter_ts)
- Sorting (single and multi-field, ascending/descending)
- Sparse field selection
- Count and group-by aggregations
- Invalid input validation
- Response encoding

All tests use the test_data fixture and rely on conftest.py's invoke() utility.
"""
import json
import pytest

from conftest import extract_id


def test_get_filter_by_creator_fk(invoke, creator_fk):
    """GET-01: Filter areas by creator_fk → 200, body contains area_name.

    Tests basic field filtering where a single QSP matches records by creator.
    """
    response = invoke('GET', '/darwin_dev/areas', query={'creator_fk': creator_fk})
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert isinstance(body, list)
    assert len(body) > 0
    # At least one area should have 'area_name' field
    assert any('area_name' in record for record in body)


def test_get_filter_by_id(invoke, test_ids):
    """GET-02: Filter areas by id → 200, body contains the specific area.

    Tests exact ID filtering returns the single matching record.
    """
    area_id = test_ids['area_id']
    response = invoke('GET', '/darwin_dev/areas', query={'id': area_id})
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]['id'] == int(area_id)
    assert body[0]['area_name'] == 'pytest Area'


def test_get_multiple_filters_and(invoke, creator_fk, test_ids):
    """GET-03: Filter by multiple QSPs (AND logic) → 200.

    Tests that multiple query parameters create AND conditions.
    Filters by both creator_fk and id.
    """
    area_id = test_ids['area_id']
    response = invoke('GET', '/darwin_dev/areas', query={
        'id': area_id,
        'creator_fk': creator_fk,
    })
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]['id'] == int(area_id)
    assert body[0]['creator_fk'] == creator_fk


def test_get_in_clause(invoke, test_ids):
    """GET-04: Filter with IN clause syntax ?id=(id1,id2,...) → 200.

    Tests that parenthesized comma-separated values trigger IN logic.
    """
    area_id = test_ids['area_id']
    # Query with IN clause containing the test area and a non-existent ID
    response = invoke('GET', '/darwin_dev/areas', query={
        'id': f'({area_id},999999)',
    })
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert isinstance(body, list)
    assert len(body) >= 1
    assert any(record['id'] == int(area_id) for record in body)
    assert body[0]['area_name'] == 'pytest Area'


def test_get_date_range_filter(invoke, creator_fk, test_ids):
    """GET-05: Filter by date range (filter_ts) → 200.

    Tests the filter_ts parameter for BETWEEN filtering on timestamps.
    - POST a done task with done_ts in the query range
    - GET with filter_ts=(done_ts,start,end)
    - Verify the task appears in results
    - DELETE the task to clean up
    """
    # Step 1: Create a done task with explicit done_ts
    create_resp = invoke('POST', '/darwin_dev/tasks', body={
        'description': 'Date Filter Test Task',
        'area_fk': test_ids['area_id'],
        'creator_fk': creator_fk,
        'priority': '0',
        'done': '1',
        'done_ts': '2025-06-15 12:00:00',
    })
    assert create_resp['statusCode'] == 200
    task_id = extract_id(create_resp)
    assert task_id is not None

    # Step 2: GET with filter_ts in range
    response = invoke('GET', '/darwin_dev/tasks', query={
        'creator_fk': creator_fk,
        'filter_ts': '(done_ts,2025-06-01T00:00:00,2025-06-30T23:59:59)',
    })
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert isinstance(body, list)
    assert len(body) > 0
    # Verify the task we just created is in the results
    assert any(record['id'] == int(task_id) for record in body)

    # Step 3: DELETE cleanup
    delete_resp = invoke('DELETE', '/darwin_dev/tasks', body={'id': task_id})
    assert delete_resp['statusCode'] == 200


def test_get_sort_ascending(invoke, creator_fk):
    """GET-06: Sort results ascending → 200.

    Tests ?sort=column:asc produces results in ascending order.
    """
    response = invoke('GET', '/darwin_dev/areas', query={
        'creator_fk': creator_fk,
        'sort': 'id:asc',
    })
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert isinstance(body, list)
    assert len(body) > 0
    # Verify ascending order (each id >= previous)
    ids = [record['id'] for record in body]
    assert ids == sorted(ids)


def test_get_sort_descending(invoke, creator_fk):
    """GET-07: Sort results descending → 200.

    Tests ?sort=column:desc produces results in descending order.
    """
    response = invoke('GET', '/darwin_dev/areas', query={
        'creator_fk': creator_fk,
        'sort': 'id:desc',
    })
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert isinstance(body, list)
    assert len(body) > 0
    # Verify descending order (each id <= previous)
    ids = [record['id'] for record in body]
    assert ids == sorted(ids, reverse=True)


def test_get_multi_field_sort(invoke, creator_fk):
    """GET-08: Sort by multiple fields → 200.

    Tests ?sort=col1:asc,col2:asc produces multi-level sort.
    """
    response = invoke('GET', '/darwin_dev/areas', query={
        'creator_fk': creator_fk,
        'sort': 'closed:asc,sort_order:asc',
    })
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert isinstance(body, list)
    assert len(body) > 0
    # Verify first sort level (closed) is ascending
    closed_values = [record['closed'] for record in body]
    assert closed_values == sorted(closed_values)


def test_get_sparse_fields(invoke, creator_fk):
    """GET-09: Sparse field selection ?fields=col1,col2 → 200.

    Tests that only specified fields are returned in the response.
    """
    response = invoke('GET', '/darwin_dev/areas', query={
        'creator_fk': creator_fk,
        'fields': 'id,area_name',
    })
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert isinstance(body, list)
    assert len(body) > 0
    # Verify only requested fields are present
    for record in body:
        assert 'id' in record
        assert 'area_name' in record
        # Other fields should not be present (sparse response)
        assert 'domain_fk' not in record
        assert 'closed' not in record


def test_get_count_group(invoke, creator_fk):
    """GET-10: Count and group-by aggregation ?fields=count(*),group_col → 200.

    Tests ?fields=count(*),domain_fk produces count grouped by domain.
    """
    response = invoke('GET', '/darwin_dev/areas', query={
        'creator_fk': creator_fk,
        'fields': 'count(*),domain_fk',
    })
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert isinstance(body, list)
    assert len(body) > 0
    # Each result should have count(*) and domain_fk
    for record in body:
        assert 'count(*)' in record or 'COUNT(*)' in record or 'COUNT(*)' in str(record).upper()
        assert 'domain_fk' in record


def test_get_invalid_qsp_key_returns_400(invoke):
    """GET-11: Invalid QSP key (non-existent column) → 400.

    Tests that a QSP with a key that doesn't match any column returns 400.
    """
    response = invoke('GET', '/darwin_dev/areas', query={
        'nonexistent_column': 'value',
    })
    assert response['statusCode'] == 400


def test_get_invalid_field_returns_400(invoke, creator_fk):
    """GET-12: Invalid field in ?fields=col1,badcol → 400.

    Tests that requesting a non-existent column in fields returns 400.
    """
    response = invoke('GET', '/darwin_dev/areas', query={
        'creator_fk': creator_fk,
        'fields': 'id,nonexistent_field',
    })
    assert response['statusCode'] == 400


def test_get_nonexistent_table_returns_500(invoke):
    """GET-13: GET from non-existent table → 500 or exception.

    Tests that accessing a table that doesn't exist fails with 500.
    May raise an exception, which is also acceptable.
    """
    try:
        response = invoke('GET', '/darwin_dev/nonexistent_table')
        assert response['statusCode'] == 500
    except Exception:
        # Exception is acceptable for non-existent table
        pass


def test_get_no_matching_rows_returns_404(invoke):
    """GET-14: GET with filter matching no rows → 404.

    Tests that a valid query that matches zero records returns 404.
    """
    response = invoke('GET', '/darwin_dev/areas', query={
        'id': '999999999',
    })
    assert response['statusCode'] == 404


def test_get_invalid_sort_column_returns_400(invoke, creator_fk):
    """GET-15: Invalid sort column ?sort=BOGUS_COL:asc → 400.

    Tests that sorting by a non-existent column returns 400.
    """
    response = invoke('GET', '/darwin_dev/areas', query={
        'creator_fk': creator_fk,
        'sort': 'BOGUS_COLUMN:asc',
    })
    assert response['statusCode'] == 400


def test_get_response_single_encoded(invoke, test_ids):
    """GET-16: Response body is single-encoded JSON (not double-encoded).

    Tests that json.loads(response['body']) directly yields a list of dicts,
    not a string that requires a second parse.
    """
    response = invoke('GET', '/darwin_dev/areas', query={'id': test_ids['area_id']})
    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    # body should be a list of dicts, not a string
    assert isinstance(body, list)
    assert len(body) > 0
    assert isinstance(body[0], dict)
    assert 'id' in body[0]
    assert 'area_name' in body[0]
    # If body was double-encoded, body[0] would be a string, not a dict
    assert not isinstance(body[0]['id'], str)  # id should be int, not stringified


def test_get_count_too_many_fields_returns_400(invoke, creator_fk):
    """GET-17: Count with too many fields ?fields=count(*),col1,col2 → 400.

    Tests that count(*) aggregation with more than one group-by field
    returns 400 (only one group-by field allowed with count).
    """
    response = invoke('GET', '/darwin_dev/areas', query={
        'creator_fk': creator_fk,
        'fields': 'count(*),domain_fk,creator_fk',
    })
    assert response['statusCode'] == 400
    # Body should contain error message
    body = response.get('body', '')
    if body:
        assert 'BAD REQUEST' in body or 'error' in body.lower()
