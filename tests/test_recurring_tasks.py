"""
CRUD lifecycle tests for the recurring_tasks table.

Tests complete Create-Read-Update-Delete cycles covering all fields:
recurrence, anchor_date, active, accumulate, priority, insert_position.
"""
import json
import pytest

from conftest import extract_id


class TestRecurringTasksCRUD:
    """CRUD lifecycle tests for recurring_tasks table."""

    # -----------------------------------------------------------------------
    # RT-01: Full CRUD lifecycle
    # -----------------------------------------------------------------------

    def test_recurring_task_crud_lifecycle(self, invoke, creator_fk, test_ids):
        """RT-01: POST → GET → PUT → GET verify → DELETE → GET 404."""

        # Step 1: POST create a weekly recurring task
        create_resp = invoke('POST', '/darwin_dev/recurring_tasks', body={
            'description': 'Take out recycling',
            'area_fk': test_ids['area_id'],
            'recurrence': 'weekly',
            'anchor_date': '2025-01-06',
            'active': '1',
            'accumulate': '1',
            'priority': '0',
            'insert_position': 'bottom',
        })
        assert create_resp['statusCode'] == 200
        rt_id = extract_id(create_resp)
        assert rt_id is not None

        # Verify returned body has correct fields
        body = json.loads(create_resp['body'])
        assert body[0]['description'] == 'Take out recycling'
        assert body[0]['recurrence'] == 'weekly'
        assert body[0]['active'] == 1

        # Step 2: GET verify persisted
        get_resp = invoke('GET', '/darwin_dev/recurring_tasks', query={'id': rt_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert len(body) == 1
        assert body[0]['description'] == 'Take out recycling'
        assert body[0]['recurrence'] == 'weekly'
        assert body[0]['anchor_date'] == '2025-01-06'

        # Step 3: PUT update description and toggle active off
        update_resp = invoke('PUT', '/darwin_dev/recurring_tasks', body=[
            {'id': rt_id, 'description': 'Take out recycling (updated)', 'active': '0'}
        ])
        assert update_resp['statusCode'] == 200

        # Step 4: GET verify update
        get_resp = invoke('GET', '/darwin_dev/recurring_tasks', query={'id': rt_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert body[0]['description'] == 'Take out recycling (updated)'
        assert body[0]['active'] == 0

        # Step 5: DELETE
        delete_resp = invoke('DELETE', '/darwin_dev/recurring_tasks', body={'id': rt_id})
        assert delete_resp['statusCode'] == 200

        # Step 6: GET verify 404
        get_404 = invoke('GET', '/darwin_dev/recurring_tasks', query={'id': rt_id})
        assert get_404['statusCode'] == 404

    # -----------------------------------------------------------------------
    # RT-02: All recurrence types and anchor_date values
    # -----------------------------------------------------------------------

    def test_recurring_task_recurrence_types(self, invoke, creator_fk, test_ids):
        """RT-02: POST one task per recurrence type, verify anchor_date stored correctly."""

        cases = [
            ('daily',   None,         'Water plants'),
            ('weekly',  '2025-01-08', 'Wednesday standup'),
            ('monthly', '2025-01-15', 'Pay bills'),
            ('annual',  '2025-06-01', 'Annual review'),
        ]
        created_ids = []

        for recurrence, anchor, description in cases:
            body = {
                'description': description,
                'area_fk': test_ids['area_id'],
                'recurrence': recurrence,
                'active': '1',
                'accumulate': '1',
                'priority': '0',
                'insert_position': 'bottom',
            }
            if anchor:
                body['anchor_date'] = anchor

            resp = invoke('POST', '/darwin_dev/recurring_tasks', body=body)
            assert resp['statusCode'] == 200, f"POST failed for recurrence={recurrence}"
            rt_id = extract_id(resp)
            assert rt_id is not None
            created_ids.append((rt_id, recurrence, anchor))

        # Verify each
        for rt_id, recurrence, anchor in created_ids:
            get_resp = invoke('GET', '/darwin_dev/recurring_tasks', query={'id': rt_id})
            assert get_resp['statusCode'] == 200
            body = json.loads(get_resp['body'])
            assert body[0]['recurrence'] == recurrence
            if anchor:
                assert body[0]['anchor_date'] == anchor

        # Cleanup
        for rt_id, _, _ in created_ids:
            invoke('DELETE', '/darwin_dev/recurring_tasks', body={'id': rt_id})

    # -----------------------------------------------------------------------
    # RT-03: Toggle active and accumulate flags
    # -----------------------------------------------------------------------

    def test_recurring_task_flag_toggles(self, invoke, creator_fk, test_ids):
        """RT-03: Toggle active and accumulate flags via PUT, verify via GET."""

        create_resp = invoke('POST', '/darwin_dev/recurring_tasks', body={
            'description': 'Flag toggle test',
            'area_fk': test_ids['area_id'],
            'recurrence': 'daily',
            'active': '1',
            'accumulate': '1',
            'priority': '0',
            'insert_position': 'bottom',
        })
        assert create_resp['statusCode'] == 200
        rt_id = extract_id(create_resp)

        # Toggle active off, accumulate off
        invoke('PUT', '/darwin_dev/recurring_tasks', body=[
            {'id': rt_id, 'active': '0', 'accumulate': '0'}
        ])
        get_resp = invoke('GET', '/darwin_dev/recurring_tasks', query={'id': rt_id})
        body = json.loads(get_resp['body'])
        assert body[0]['active'] == 0
        assert body[0]['accumulate'] == 0

        # Toggle back on
        invoke('PUT', '/darwin_dev/recurring_tasks', body=[
            {'id': rt_id, 'active': '1', 'accumulate': '1'}
        ])
        get_resp = invoke('GET', '/darwin_dev/recurring_tasks', query={'id': rt_id})
        body = json.loads(get_resp['body'])
        assert body[0]['active'] == 1
        assert body[0]['accumulate'] == 1

        invoke('DELETE', '/darwin_dev/recurring_tasks', body={'id': rt_id})

    # -----------------------------------------------------------------------
    # RT-04: Filter by area_fk
    # -----------------------------------------------------------------------

    def test_recurring_task_filter_by_area(self, invoke, creator_fk, test_ids):
        """RT-04: Create 2 tasks for same area, GET filtered by area_fk returns both."""

        ids = []
        for i in range(2):
            resp = invoke('POST', '/darwin_dev/recurring_tasks', body={
                'description': f'Area filter test {i+1}',
                'area_fk': test_ids['area_id'],
                'recurrence': 'daily',
                'active': '1',
                'accumulate': '1',
                'priority': '0',
                'insert_position': 'bottom',
            })
            assert resp['statusCode'] == 200
            ids.append(extract_id(resp))

        # GET filtered by area_fk
        get_resp = invoke('GET', '/darwin_dev/recurring_tasks',
                          query={'area_fk': test_ids['area_id']})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        returned_ids = {str(row['id']) for row in body}
        assert ids[0] in returned_ids
        assert ids[1] in returned_ids

        for rt_id in ids:
            invoke('DELETE', '/darwin_dev/recurring_tasks', body={'id': rt_id})

    # -----------------------------------------------------------------------
    # RT-05: creator_fk isolation
    # -----------------------------------------------------------------------

    def test_recurring_task_creator_isolation(self, invoke, creator_fk, test_ids):
        """RT-05: Tasks created by one user are not visible to another."""

        # Create task as session creator_fk
        resp = invoke('POST', '/darwin_dev/recurring_tasks', body={
            'description': 'Isolation test task',
            'area_fk': test_ids['area_id'],
            'recurrence': 'daily',
            'active': '1',
            'accumulate': '1',
            'priority': '0',
            'insert_position': 'bottom',
        })
        assert resp['statusCode'] == 200
        rt_id = extract_id(resp)

        # GET as a different user — should not see it
        other_user = f"other-{creator_fk}"
        get_resp = invoke('GET', '/darwin_dev/recurring_tasks',
                          query={'id': rt_id}, authenticated_user=other_user)
        assert get_resp['statusCode'] == 404

        invoke('DELETE', '/darwin_dev/recurring_tasks', body={'id': rt_id})
