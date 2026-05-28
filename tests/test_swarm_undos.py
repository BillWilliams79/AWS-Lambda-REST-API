"""CRUD lifecycle for swarm_undos (req #2719).

Verifies the generic Lambda-Rest passthrough handles the new table without
any per-table code change. Mirrors test_swarm_starts.py.

The `reason` column is NOT NULL — every POST must supply it. session_fk and
the snapshot columns are nullable; the skill captures them from the manifest
at undo time, but legacy invocations may pass NULL.
"""
import json

from conftest import extract_id


class TestSwarmUndosCRUD:
    """CRUD lifecycle for swarm_undos (req #2719)."""

    def test_swarm_undos_crud_lifecycle(self, invoke, creator_fk):
        """POST create swarm_undo → PUT update → GET verify → DELETE → GET 404."""
        # Step 1: POST a swarm_undo record. session_fk/swarm_start_fk_at_undo
        # are left NULL — they are best-effort snapshots and the test
        # exercises the generic passthrough on the table's mandatory columns.
        create_resp = invoke('POST', '/darwin_dev/swarm_undos', body={
            'reason': 'Wrong approach — restarting with deployed coordination',
            'task_name': 'test-swarm-undos-crud',
            'branch': 'feature/0-test-swarm-undos-crud',
            'coordination_type': 'implemented',
            'creator_fk': creator_fk,
        })
        assert create_resp['statusCode'] == 200
        swarm_undo_id = extract_id(create_resp)
        assert swarm_undo_id is not None

        # Step 2: PUT update — change reason and coordination_type
        update_resp = invoke('PUT', '/darwin_dev/swarm_undos', body=[
            {'id': swarm_undo_id,
             'reason': 'Out of scope — splitting into smaller reqs',
             'coordination_type': 'planned'}
        ])
        assert update_resp['statusCode'] in (200, 204)

        # Step 3: GET verify
        get_resp = invoke('GET', '/darwin_dev/swarm_undos', query={'id': swarm_undo_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert isinstance(body, list)
        assert len(body) > 0
        assert body[0]['reason'] == 'Out of scope — splitting into smaller reqs'
        assert body[0]['coordination_type'] == 'planned'
        assert body[0]['task_name'] == 'test-swarm-undos-crud'

        # Step 4: DELETE
        delete_resp = invoke('DELETE', '/darwin_dev/swarm_undos',
                             body={'id': swarm_undo_id})
        assert delete_resp['statusCode'] == 200

        # Step 5: GET 404
        get_404 = invoke('GET', '/darwin_dev/swarm_undos',
                         query={'id': swarm_undo_id})
        assert get_404['statusCode'] == 404
