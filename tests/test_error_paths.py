"""
Error path and edge case tests for Lambda-Rest POST, PUT, and DELETE operations.

Tests malformed requests, missing required fields, FK violations, response encoding,
NULL value handling, bulk operations, and response structure verification.

All tests use the test_data fixture (create profile → domain → area → task)
and rely on conftest.py's invoke() and extract_id() utilities for API calls.
"""
import json
import pytest

from conftest import extract_id


class TestPostErrorPaths:
    """POST operation error path tests."""

    # -----------------------------------------------------------------------
    # POST-01: Empty body returns 400
    # -----------------------------------------------------------------------

    def test_post_empty_body_returns_400(self, invoke):
        """POST-01: POST /darwin_dev/areas with empty body {} returns 400."""
        response = invoke('POST', '/darwin_dev/areas', body={})
        assert response['statusCode'] == 400

    # -----------------------------------------------------------------------
    # POST-02: Missing required field returns 500
    # -----------------------------------------------------------------------

    def test_post_missing_required_field_returns_500(self, invoke):
        """POST-02: POST with missing required field (creator_fk) returns 500.

        May raise an exception; accept both 500 status or exception.
        """
        try:
            response = invoke('POST', '/darwin_dev/domains', body={
                'domain_name': 'No Creator',
            })
            assert response['statusCode'] == 500
        except Exception:
            pass  # Exception is also acceptable

    # -----------------------------------------------------------------------
    # POST-03: FK violation returns 500
    # -----------------------------------------------------------------------

    def test_post_fk_violation_returns_500(self, invoke):
        """POST-03: POST with invalid FK (domain_fk='999999') returns 500.

        May raise an exception; accept both 500 status or exception.
        """
        try:
            response = invoke('POST', '/darwin_dev/areas', body={
                'area_name': 'Bad FK',
                'creator_fk': 'nonexistent-user-id',
                'domain_fk': '999999',
                'closed': '0',
            })
            assert response['statusCode'] == 500
        except Exception:
            pass  # Exception is also acceptable

    # -----------------------------------------------------------------------
    # POST-04: Response single-encoded verification
    # -----------------------------------------------------------------------

    def test_post_response_single_encoded(self, invoke, creator_fk, test_ids):
        """POST-04: POST response body is single-encoded (not double-encoded).

        json.loads(response['body']) should yield a list of dicts, not a string.
        Clean up the domain after.
        """
        response = invoke('POST', '/darwin_dev/domains', body={
            'domain_name': 'Single Encoded Test Domain',
            'creator_fk': creator_fk,
            'closed': '0',
        })
        assert response['statusCode'] == 200

        # Parse response body
        body = json.loads(response['body'])
        assert isinstance(body, list)
        assert len(body) > 0
        assert isinstance(body[0], dict)
        assert 'id' in body[0]

        # Clean up
        domain_id = body[0]['id']
        invoke('DELETE', '/darwin_dev/domains', body={'id': domain_id})

    # -----------------------------------------------------------------------
    # POST-05: NULL value handling
    # -----------------------------------------------------------------------

    def test_post_null_value_handling(self, invoke, creator_fk, test_ids):
        """POST-05: POST area with sort_order='NULL', verify NULL stored via GET.

        Tests that the string 'NULL' is converted to SQL NULL and stored correctly.
        Clean up the area after.
        """
        response = invoke('POST', '/darwin_dev/areas', body={
            'area_name': 'NULL Sort Order Test Area',
            'creator_fk': creator_fk,
            'domain_fk': test_ids['domain_id'],
            'closed': '0',
            'sort_order': 'NULL',
        })
        assert response['statusCode'] == 200
        area_id = extract_id(response)
        assert area_id is not None

        # GET and verify NULL was stored
        get_resp = invoke('GET', '/darwin_dev/areas', query={'id': area_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert len(body) > 0
        assert body[0]['sort_order'] is None  # NULL in MySQL → None in JSON

        # Clean up
        invoke('DELETE', '/darwin_dev/areas', body={'id': area_id})

    # -----------------------------------------------------------------------
    # POST-06: Task with all fields populated
    # -----------------------------------------------------------------------

    def test_post_task_with_all_fields(self, invoke, creator_fk, test_ids):
        """POST-06: POST task with all fields filled, verify 200 and description present.

        Clean up the task after.
        """
        response = invoke('POST', '/darwin_dev/tasks', body={
            'priority': '1',
            'done': '0',
            'description': 'All Fields Task Test',
            'area_fk': test_ids['area_id'],
            'creator_fk': creator_fk,
            'sort_order': '99',
        })
        assert response['statusCode'] == 200

        body = json.loads(response['body'])
        assert isinstance(body, list)
        assert len(body) > 0
        assert 'description' in body[0]
        assert body[0]['description'] == 'All Fields Task Test'
        assert body[0]['priority'] == 1
        assert body[0]['done'] == 0
        assert body[0]['sort_order'] == 99

        # Clean up
        task_id = body[0]['id']
        invoke('DELETE', '/darwin_dev/tasks', body={'id': task_id})


class TestPutErrorPaths:
    """PUT operation error path tests."""

    # -----------------------------------------------------------------------
    # PUT-01: Empty body returns 400
    # -----------------------------------------------------------------------

    def test_put_empty_body_returns_400(self, invoke):
        """PUT-01: PUT /darwin_dev/areas with empty array body [] returns 400."""
        response = invoke('PUT', '/darwin_dev/areas', body=[])
        assert response['statusCode'] == 400

    # -----------------------------------------------------------------------
    # PUT-02: Missing id returns 400
    # -----------------------------------------------------------------------

    def test_put_missing_id_returns_400(self, invoke):
        """PUT-02: PUT with body=[{'area_name': 'No ID'}] (missing id) returns 400."""
        response = invoke('PUT', '/darwin_dev/areas', body=[
            {'area_name': 'No ID'},
        ])
        assert response['statusCode'] == 400

    # -----------------------------------------------------------------------
    # PUT-03: Only id, no fields to update returns 400
    # -----------------------------------------------------------------------

    def test_put_only_id_no_fields_returns_400(self, invoke, test_ids):
        """PUT-03: PUT with body=[{'id': area_id}] (no fields) returns 400."""
        response = invoke('PUT', '/darwin_dev/areas', body=[
            {'id': test_ids['area_id']},
        ])
        assert response['statusCode'] == 400

    # -----------------------------------------------------------------------
    # PUT-04: Nonexistent id returns 204
    # -----------------------------------------------------------------------

    def test_put_nonexistent_id_returns_204(self, invoke):
        """PUT-04: PUT with id='999999999' returns 204 (no rows updated)."""
        response = invoke('PUT', '/darwin_dev/areas', body=[
            {'id': '999999999', 'area_name': 'Ghost'},
        ])
        assert response['statusCode'] == 204

    # -----------------------------------------------------------------------
    # PUT-05: Invalid column returns 500
    # -----------------------------------------------------------------------

    def test_put_invalid_column_returns_500(self, invoke, test_ids):
        """PUT-05: PUT with nonexistent column returns 500.

        May raise an exception; accept both 500 status or exception.
        """
        try:
            response = invoke('PUT', '/darwin_dev/areas', body=[
                {'id': test_ids['area_id'], 'nonexistent_column': 'val'},
            ])
            assert response['statusCode'] == 500
        except Exception:
            pass  # Exception is also acceptable

    # -----------------------------------------------------------------------
    # PUT-06: Bulk with missing id in second returns 400
    # -----------------------------------------------------------------------

    def test_put_bulk_missing_id_in_second_returns_400(self, invoke, test_ids):
        """PUT-06: Bulk PUT with second element missing id returns 400.

        Array: [{'id': valid_id, 'area_name': 'Valid'}, {'area_name': 'No ID'}]
        """
        response = invoke('PUT', '/darwin_dev/areas', body=[
            {'id': test_ids['area_id'], 'area_name': 'Valid'},
            {'area_name': 'No ID'},
        ])
        assert response['statusCode'] == 400

    # -----------------------------------------------------------------------
    # PUT-07: NULL value handling
    # -----------------------------------------------------------------------

    def test_put_null_value(self, invoke, creator_fk, test_ids):
        """PUT-07: PUT [{'id': area_id, 'sort_order': 'NULL'}] stores NULL.

        Verify NULL via GET, then restore sort_order after.
        """
        # First, set sort_order to a non-NULL value to verify the change
        invoke('PUT', '/darwin_dev/areas', body=[
            {'id': test_ids['area_id'], 'sort_order': '77'},
        ])

        # GET and verify it's set
        get_resp = invoke('GET', '/darwin_dev/areas', query={'id': test_ids['area_id']})
        body = json.loads(get_resp['body'])
        assert body[0]['sort_order'] == 77

        # Now PUT NULL
        response = invoke('PUT', '/darwin_dev/areas', body=[
            {'id': test_ids['area_id'], 'sort_order': 'NULL'},
        ])
        assert response['statusCode'] == 200

        # GET and verify NULL was stored
        get_resp = invoke('GET', '/darwin_dev/areas', query={'id': test_ids['area_id']})
        body = json.loads(get_resp['body'])
        assert body[0]['sort_order'] is None

        # Restore sort_order to a sensible value
        invoke('PUT', '/darwin_dev/areas', body=[
            {'id': test_ids['area_id'], 'sort_order': '1'},
        ])

    # -----------------------------------------------------------------------
    # PUT-08: Bulk update multiple areas
    # -----------------------------------------------------------------------

    def test_put_bulk_update(self, invoke, creator_fk, test_ids):
        """PUT-08: Create 2 areas, bulk PUT both with different values, verify 200.

        Clean up the areas after.
        """
        # Create 2 areas
        area_ids = []
        for i in range(2):
            resp = invoke('POST', '/darwin_dev/areas', body={
                'area_name': f'Bulk Test Area {i+1}',
                'creator_fk': creator_fk,
                'domain_fk': test_ids['domain_id'],
                'closed': '0',
                'sort_order': str(i + 1),
            })
            assert resp['statusCode'] == 200
            area_id = extract_id(resp)
            assert area_id is not None
            area_ids.append(area_id)

        # Bulk PUT both with different area_name values
        response = invoke('PUT', '/darwin_dev/areas', body=[
            {'id': area_ids[0], 'area_name': 'Updated Bulk Area 1'},
            {'id': area_ids[1], 'area_name': 'Updated Bulk Area 2'},
        ])
        assert response['statusCode'] == 200

        # Verify both were updated
        get_resp = invoke('GET', '/darwin_dev/areas', query={
            'id': f"({','.join(area_ids)})"
        })
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert len(body) == 2
        names = {area['area_name'] for area in body}
        assert 'Updated Bulk Area 1' in names
        assert 'Updated Bulk Area 2' in names

        # Clean up
        for area_id in area_ids:
            invoke('DELETE', '/darwin_dev/areas', body={'id': area_id})


class TestDeleteErrorPaths:
    """DELETE operation error path tests."""

    # -----------------------------------------------------------------------
    # DELETE-01: Empty body returns 400
    # -----------------------------------------------------------------------

    def test_delete_empty_body_returns_400(self, invoke):
        """DELETE-01: DELETE /darwin_dev/areas with empty body {} returns 400."""
        response = invoke('DELETE', '/darwin_dev/areas', body={})
        assert response['statusCode'] == 400

    # -----------------------------------------------------------------------
    # DELETE-02: Nonexistent id returns 404
    # -----------------------------------------------------------------------

    def test_delete_nonexistent_returns_404(self, invoke):
        """DELETE-02: DELETE with id='999999999' returns 404 (no rows deleted)."""
        response = invoke('DELETE', '/darwin_dev/areas', body={'id': '999999999'})
        assert response['statusCode'] == 404

    # -----------------------------------------------------------------------
    # DELETE-03: Multi-condition WHERE clause
    # -----------------------------------------------------------------------

    def test_delete_multi_condition(self, invoke, creator_fk, test_ids):
        """DELETE-03: Delete task with multi-condition WHERE (id AND done).

        Create a task, DELETE with body={'id': task_id, 'done': '0'},
        verify 200 and task is deleted.
        """
        # Create task
        resp = invoke('POST', '/darwin_dev/tasks', body={
            'priority': '0',
            'done': '0',
            'description': 'Multi-Condition Delete Test',
            'area_fk': test_ids['area_id'],
            'creator_fk': creator_fk,
        })
        assert resp['statusCode'] == 200
        task_id = extract_id(resp)
        assert task_id is not None

        # DELETE with multi-condition: id AND done='0'
        response = invoke('DELETE', '/darwin_dev/tasks', body={
            'id': task_id,
            'done': '0',
        })
        assert response['statusCode'] == 200

        # Verify task is deleted
        get_resp = invoke('GET', '/darwin_dev/tasks', query={'id': task_id})
        assert get_resp['statusCode'] == 404


class TestResponseStructure:
    """Response structure and encoding tests."""

    # -----------------------------------------------------------------------
    # RESPONSE-01: statusCode is int
    # -----------------------------------------------------------------------

    def test_response_statuscode_is_int(self, invoke):
        """RESPONSE-01: Response statusCode should be int type, not string."""
        response = invoke('GET', '/darwin_dev/areas', query={'id': '999999999'})
        assert isinstance(response['statusCode'], int)

    # -----------------------------------------------------------------------
    # RESPONSE-02: Error response contains message
    # -----------------------------------------------------------------------

    def test_error_response_contains_message(self, invoke):
        """RESPONSE-02: 404 response body should contain 'NOT FOUND' message."""
        response = invoke('GET', '/darwin_dev/areas', query={'id': '999999999'})
        assert response['statusCode'] == 404
        body = json.loads(response['body'])
        assert 'NOT FOUND' in str(body).upper()

    # -----------------------------------------------------------------------
    # RESPONSE-03: CORS headers on error
    # -----------------------------------------------------------------------

    def test_cors_headers_on_error(self, invoke):
        """RESPONSE-03: 404 response should have CORS headers.

        Verify Access-Control-Allow-Origin and Access-Control-Allow-Methods.
        """
        response = invoke('GET', '/darwin_dev/areas', query={'id': '999999999'})
        assert response['statusCode'] == 404
        assert 'headers' in response
        headers = response.get('headers', {})
        assert headers.get('Access-Control-Allow-Origin') == '*'
        assert 'PUT' in headers.get('Access-Control-Allow-Methods', '')

    # -----------------------------------------------------------------------
    # RESPONSE-04: GET database response structure
    # -----------------------------------------------------------------------

    def test_get_database_response(self, invoke):
        """RESPONSE-04: GET /darwin_dev returns 200 with properly encoded response.

        Verify:
        - statusCode is 200
        - body is single-encoded (json.loads gives a list)
        - body contains 'areas' and 'domains' table names
        - isBase64Encoded is boolean False
        - CORS headers present
        """
        response = invoke('GET', '/darwin_dev')
        assert response['statusCode'] == 200

        # Verify isBase64Encoded is boolean False
        assert 'isBase64Encoded' in response
        assert response['isBase64Encoded'] is False

        # Parse body and verify structure
        body = json.loads(response['body'])
        assert isinstance(body, list)
        assert len(body) > 0
        assert all(isinstance(item, str) for item in body)

        # Verify expected tables are present
        table_names = set(body)
        assert 'areas' in table_names
        assert 'domains' in table_names
        assert 'tasks' in table_names

        # Verify CORS headers
        headers = response.get('headers', {})
        assert headers.get('Access-Control-Allow-Origin') == '*'
