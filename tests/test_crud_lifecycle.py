"""
CRUD lifecycle and integration tests for Lambda-Rest.

Tests complete Create-Read-Update-Delete cycles on areas and tasks,
cross-table foreign key integrity, bulk operations, and special character handling.

All tests use the test_data fixture (create profile → domain → area → task)
and rely on conftest.py's invoke() and extract_id() utilities for API calls.
"""
import json
import pytest

from conftest import extract_id


class TestCRUDLifecycle:
    """CRUD lifecycle tests on areas and tasks tables."""

    # -----------------------------------------------------------------------
    # CRUD-01: Areas CRUD lifecycle
    # -----------------------------------------------------------------------

    def test_crud_lifecycle_areas(self, invoke, creator_fk, test_ids):
        """CRUD-01: POST create area → PUT update → GET verify → DELETE → GET 404.

        Exercises the complete CRUD cycle on the areas table:
        - POST new area
        - PUT to update area_name
        - GET to verify the update
        - DELETE the area
        - GET to verify 404 (not found)
        """
        # Step 1: POST create new area
        create_resp = invoke('POST', '/darwin_dev/areas', body={
            'area_name': 'CRUD Test Area',
            'creator_fk': creator_fk,
            'domain_fk': test_ids['domain_id'],
            'closed': '0',
            'sort_order': '99',
        })
        assert create_resp['statusCode'] == 200
        area_id = extract_id(create_resp)
        assert area_id is not None

        # Step 2: PUT update area_name
        update_resp = invoke('PUT', '/darwin_dev/areas', body=[
            {'id': area_id, 'area_name': 'Updated Area Name'}
        ])
        assert update_resp['statusCode'] == 200

        # Step 3: GET verify update was applied
        get_resp = invoke('GET', '/darwin_dev/areas', query={'id': area_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert isinstance(body, list)
        assert len(body) > 0
        assert body[0]['area_name'] == 'Updated Area Name'

        # Step 4: DELETE the area
        delete_resp = invoke('DELETE', '/darwin_dev/areas', body={'id': area_id})
        assert delete_resp['statusCode'] == 200

        # Step 5: GET verify 404 (area no longer exists)
        get_404_resp = invoke('GET', '/darwin_dev/areas', query={'id': area_id})
        assert get_404_resp['statusCode'] == 404

    # -----------------------------------------------------------------------
    # CRUD-02: Tasks CRUD lifecycle
    # -----------------------------------------------------------------------

    def test_crud_lifecycle_tasks(self, invoke, creator_fk, test_ids):
        """CRUD-02: POST create task → PUT update → GET verify → DELETE → GET 404.

        Exercises the complete CRUD cycle on the tasks table:
        - POST new task with description and priority
        - PUT to update both description and priority
        - GET to verify the updates
        - DELETE the task
        - GET to verify 404
        """
        # Step 1: POST create new task
        create_resp = invoke('POST', '/darwin_dev/tasks', body={
            'description': 'CRUD Test Task',
            'area_fk': test_ids['area_id'],
            'creator_fk': creator_fk,
            'priority': '0',
            'done': '0',
        })
        assert create_resp['statusCode'] == 200
        task_id = extract_id(create_resp)
        assert task_id is not None

        # Step 2: PUT update description and priority
        update_resp = invoke('PUT', '/darwin_dev/tasks', body=[
            {
                'id': task_id,
                'description': 'Updated Task Description',
                'priority': '1',
            }
        ])
        assert update_resp['statusCode'] == 200

        # Step 3: GET verify updates were applied
        get_resp = invoke('GET', '/darwin_dev/tasks', query={'id': task_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert isinstance(body, list)
        assert len(body) > 0
        assert body[0]['description'] == 'Updated Task Description'
        assert body[0]['priority'] == 1

        # Step 4: DELETE the task
        delete_resp = invoke('DELETE', '/darwin_dev/tasks', body={'id': task_id})
        assert delete_resp['statusCode'] == 200

        # Step 5: GET verify 404
        get_404_resp = invoke('GET', '/darwin_dev/tasks', query={'id': task_id})
        assert get_404_resp['statusCode'] == 404

    # -----------------------------------------------------------------------
    # CRUD-03: Cross-table FK integrity and cascade delete
    # -----------------------------------------------------------------------

    def test_cross_table_fk_integrity(self, invoke, creator_fk):
        """CRUD-03: Create domain→area→task hierarchy, verify, cascade delete.

        Tests foreign key integrity across the hierarchy:
        - POST domain (creator_fk)
        - POST area (domain_fk references new domain)
        - POST task (area_fk references new area)
        - GET verify task exists
        - DELETE domain (should cascade)
        - GET task verify 404 (cascaded delete)
        """
        # Step 1: Create domain
        domain_resp = invoke('POST', '/darwin_dev/domains', body={
            'domain_name': 'FK Test Domain',
            'creator_fk': creator_fk,
            'closed': '0',
        })
        assert domain_resp['statusCode'] == 200
        domain_id = extract_id(domain_resp)
        assert domain_id is not None

        # Step 2: Create area under that domain
        area_resp = invoke('POST', '/darwin_dev/areas', body={
            'area_name': 'FK Test Area',
            'creator_fk': creator_fk,
            'domain_fk': domain_id,
            'closed': '0',
            'sort_order': '1',
        })
        assert area_resp['statusCode'] == 200
        area_id = extract_id(area_resp)
        assert area_id is not None

        # Step 3: Create task under that area
        task_resp = invoke('POST', '/darwin_dev/tasks', body={
            'description': 'FK Test Task',
            'area_fk': area_id,
            'creator_fk': creator_fk,
            'priority': '0',
            'done': '0',
        })
        assert task_resp['statusCode'] == 200
        task_id = extract_id(task_resp)
        assert task_id is not None

        # Step 4: GET verify task exists
        get_resp = invoke('GET', '/darwin_dev/tasks', query={'id': task_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert len(body) > 0

        # Step 5: DELETE domain (cascades to area and task)
        delete_resp = invoke('DELETE', '/darwin_dev/domains', body={'id': domain_id})
        assert delete_resp['statusCode'] == 200

        # Step 6: GET task verify 404 (cascaded delete)
        get_404_resp = invoke('GET', '/darwin_dev/tasks', query={'id': task_id})
        assert get_404_resp['statusCode'] == 404

    # -----------------------------------------------------------------------
    # CRUD-04: Bulk task operations
    # -----------------------------------------------------------------------

    def test_bulk_task_operations(self, invoke, creator_fk, test_ids):
        """CRUD-04: Create 3 tasks, bulk PUT update, verify via IN clause, delete.

        Tests bulk operations:
        - POST 3 separate tasks
        - PUT all 3 with priority='1' in single array body
        - GET with IN clause query to retrieve all 3
        - DELETE each task individually
        """
        # Step 1: Create 3 tasks
        task_ids = []
        for i in range(3):
            create_resp = invoke('POST', '/darwin_dev/tasks', body={
                'description': f'Bulk Test Task {i+1}',
                'area_fk': test_ids['area_id'],
                'creator_fk': creator_fk,
                'priority': '0',
                'done': '0',
            })
            assert create_resp['statusCode'] == 200
            task_id = extract_id(create_resp)
            assert task_id is not None
            task_ids.append(task_id)

        # Step 2: Bulk PUT update all 3 tasks with priority=1
        bulk_body = [
            {'id': task_ids[0], 'priority': '1'},
            {'id': task_ids[1], 'priority': '1'},
            {'id': task_ids[2], 'priority': '1'},
        ]
        update_resp = invoke('PUT', '/darwin_dev/tasks', body=bulk_body)
        assert update_resp['statusCode'] == 200

        # Step 3: GET with IN clause to verify all 3 have priority=1
        # IN clause format: query string "({id1},{id2},{id3})"
        in_clause = f"({','.join(task_ids)})"
        get_resp = invoke('GET', '/darwin_dev/tasks', query={'id': in_clause})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert len(body) == 3
        for task in body:
            assert task['priority'] == 1

        # Step 4: Delete each task
        for task_id in task_ids:
            delete_resp = invoke('DELETE', '/darwin_dev/tasks', body={'id': task_id})
            assert delete_resp['statusCode'] == 200

        # Verify all deleted
        for task_id in task_ids:
            get_resp = invoke('GET', '/darwin_dev/tasks', query={'id': task_id})
            assert get_resp['statusCode'] == 404

    # -----------------------------------------------------------------------
    # CRUD-05: Special character CRUD lifecycle
    # -----------------------------------------------------------------------

    def test_special_char_lifecycle(self, invoke, creator_fk, test_ids):
        """CRUD-05: CRUD with apostrophes, quotes, and special chars.

        Tests that special characters round-trip correctly:
        - POST area with: O'Brien's "Test" Area\\Path
        - PUT update to: It's a test; DROP areas;--
        - GET verify special chars preserved exactly
        - DELETE cleanup
        """
        # Step 1: POST area with special characters
        special_name_1 = "O'Brien's \"Test\" Area\\Path"
        create_resp = invoke('POST', '/darwin_dev/areas', body={
            'area_name': special_name_1,
            'creator_fk': creator_fk,
            'domain_fk': test_ids['domain_id'],
            'closed': '0',
            'sort_order': '50',
        })
        assert create_resp['statusCode'] == 200
        area_id = extract_id(create_resp)
        assert area_id is not None

        # Step 2: GET and verify special chars preserved
        get_resp = invoke('GET', '/darwin_dev/areas', query={'id': area_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert body[0]['area_name'] == special_name_1

        # Step 3: PUT with SQL injection attempt string
        special_name_2 = "It's a test; DROP areas;--"
        update_resp = invoke('PUT', '/darwin_dev/areas', body=[
            {'id': area_id, 'area_name': special_name_2}
        ])
        assert update_resp['statusCode'] == 200

        # Step 4: GET and verify injection attempt was treated as literal string
        get_resp = invoke('GET', '/darwin_dev/areas', query={'id': area_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert body[0]['area_name'] == special_name_2

        # Step 5: DELETE cleanup
        delete_resp = invoke('DELETE', '/darwin_dev/areas', body={'id': area_id})
        assert delete_resp['statusCode'] == 200

        # Step 6: Verify deleted
        get_404_resp = invoke('GET', '/darwin_dev/areas', query={'id': area_id})
        assert get_404_resp['statusCode'] == 404

    # -----------------------------------------------------------------------
    # CRUD-06: Task priority and done flag updates
    # -----------------------------------------------------------------------

    def test_task_priority_and_done_updates(self, invoke, creator_fk, test_ids):
        """CRUD-06: Update task priority and done flags in separate PUT calls.

        Tests flag field updates:
        - POST task with priority=0, done=0
        - PUT to set priority=1, done=0
        - GET verify priority changed
        - PUT to set priority=0, done=1
        - GET verify done changed
        - DELETE cleanup
        """
        # Step 1: Create task
        create_resp = invoke('POST', '/darwin_dev/tasks', body={
            'description': 'Flag Test Task',
            'area_fk': test_ids['area_id'],
            'creator_fk': creator_fk,
            'priority': '0',
            'done': '0',
        })
        assert create_resp['statusCode'] == 200
        task_id = extract_id(create_resp)
        assert task_id is not None

        # Step 2: PUT priority to 1
        update_resp = invoke('PUT', '/darwin_dev/tasks', body=[
            {'id': task_id, 'priority': '1', 'done': '0'}
        ])
        assert update_resp['statusCode'] == 200

        # Step 3: GET verify priority
        get_resp = invoke('GET', '/darwin_dev/tasks', query={'id': task_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert body[0]['priority'] == 1
        assert body[0]['done'] == 0

        # Step 4: PUT done to 1
        update_resp = invoke('PUT', '/darwin_dev/tasks', body=[
            {'id': task_id, 'priority': '0', 'done': '1'}
        ])
        assert update_resp['statusCode'] == 200

        # Step 5: GET verify done
        get_resp = invoke('GET', '/darwin_dev/tasks', query={'id': task_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert body[0]['priority'] == 0
        assert body[0]['done'] == 1

        # Step 6: DELETE cleanup
        delete_resp = invoke('DELETE', '/darwin_dev/tasks', body={'id': task_id})
        assert delete_resp['statusCode'] == 200

    # -----------------------------------------------------------------------
    # CRUD-07: Sort order field on areas
    # -----------------------------------------------------------------------

    def test_area_sort_order_update(self, invoke, creator_fk, test_ids):
        """CRUD-07: Create area, update sort_order via PUT, verify via GET.

        Tests the sort_order field on areas:
        - POST area with sort_order=10
        - PUT update sort_order=25
        - GET verify sort_order changed
        - DELETE cleanup
        """
        # Step 1: Create area with sort_order
        create_resp = invoke('POST', '/darwin_dev/areas', body={
            'area_name': 'Sort Test Area',
            'creator_fk': creator_fk,
            'domain_fk': test_ids['domain_id'],
            'closed': '0',
            'sort_order': '10',
        })
        assert create_resp['statusCode'] == 200
        area_id = extract_id(create_resp)
        assert area_id is not None

        # Step 2: GET verify initial sort_order
        get_resp = invoke('GET', '/darwin_dev/areas', query={'id': area_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert body[0]['sort_order'] == 10

        # Step 3: PUT update sort_order
        update_resp = invoke('PUT', '/darwin_dev/areas', body=[
            {'id': area_id, 'sort_order': '25'}
        ])
        assert update_resp['statusCode'] == 200

        # Step 4: GET verify updated sort_order
        get_resp = invoke('GET', '/darwin_dev/areas', query={'id': area_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert body[0]['sort_order'] == 25

        # Step 5: DELETE cleanup
        delete_resp = invoke('DELETE', '/darwin_dev/areas', body={'id': area_id})
        assert delete_resp['statusCode'] == 200

    # -----------------------------------------------------------------------
    # CRUD-08: Task sort order field
    # -----------------------------------------------------------------------

    def test_task_sort_order_update(self, invoke, creator_fk, test_ids):
        """CRUD-08: Create task, update sort_order via PUT, verify via GET.

        Tests the sort_order field on tasks:
        - POST task with sort_order=null (or numeric)
        - PUT update sort_order=42
        - GET verify sort_order changed
        - DELETE cleanup
        """
        # Step 1: Create task
        create_resp = invoke('POST', '/darwin_dev/tasks', body={
            'description': 'Task Sort Order Test',
            'area_fk': test_ids['area_id'],
            'creator_fk': creator_fk,
            'priority': '0',
            'done': '0',
        })
        assert create_resp['statusCode'] == 200
        task_id = extract_id(create_resp)
        assert task_id is not None

        # Step 2: PUT update sort_order to 42
        update_resp = invoke('PUT', '/darwin_dev/tasks', body=[
            {'id': task_id, 'sort_order': '42'}
        ])
        assert update_resp['statusCode'] == 200

        # Step 3: GET verify sort_order
        get_resp = invoke('GET', '/darwin_dev/tasks', query={'id': task_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert body[0]['sort_order'] == 42

        # Step 4: DELETE cleanup
        delete_resp = invoke('DELETE', '/darwin_dev/tasks', body={'id': task_id})
        assert delete_resp['statusCode'] == 200

    # -----------------------------------------------------------------------
    # CRUD-09: Close (soft delete) and reopen area
    # -----------------------------------------------------------------------

    def test_area_soft_delete_and_reopen(self, invoke, creator_fk, test_ids):
        """CRUD-09: Close (soft delete) area via closed=1, reopen via closed=0.

        Tests soft delete using the closed flag:
        - POST area with closed=0
        - PUT update closed=1
        - PUT update closed=0 to reopen
        - GET verify closed status
        - DELETE hard delete
        """
        # Step 1: Create area
        create_resp = invoke('POST', '/darwin_dev/areas', body={
            'area_name': 'Close Test Area',
            'creator_fk': creator_fk,
            'domain_fk': test_ids['domain_id'],
            'closed': '0',
            'sort_order': '1',
        })
        assert create_resp['statusCode'] == 200
        area_id = extract_id(create_resp)
        assert area_id is not None

        # Step 2: PUT to close (soft delete)
        update_resp = invoke('PUT', '/darwin_dev/areas', body=[
            {'id': area_id, 'closed': '1'}
        ])
        assert update_resp['statusCode'] == 200

        # Step 3: GET verify closed
        get_resp = invoke('GET', '/darwin_dev/areas', query={'id': area_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert body[0]['closed'] == 1

        # Step 4: PUT to reopen
        update_resp = invoke('PUT', '/darwin_dev/areas', body=[
            {'id': area_id, 'closed': '0'}
        ])
        assert update_resp['statusCode'] == 200

        # Step 5: GET verify reopened
        get_resp = invoke('GET', '/darwin_dev/areas', query={'id': area_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert body[0]['closed'] == 0

        # Step 6: DELETE hard delete
        delete_resp = invoke('DELETE', '/darwin_dev/areas', body={'id': area_id})
        assert delete_resp['statusCode'] == 200
