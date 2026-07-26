"""CRUD lifecycle for swarm_starts (req #2422).

Verifies the generic Lambda-Rest passthrough handles the new table without
any per-table code change. Mirrors test_crud_lifecycle.py.

The junction table swarm_start_sessions is canonically written via the MCP
tool `link_swarm_start_session`, not via REST — its cascade behavior is
covered by DarwinSQL/tests/test_cascades.py. (Generic POST to junction
tables fails the read-back because rest_post.py assumes an `id` column.)
"""
import json
import pytest

from conftest import extract_id


class TestSwarmStartsCRUD:
    """CRUD lifecycle for swarm_starts (req #2422)."""

    def test_swarm_starts_crud_lifecycle(self, invoke, creator_fk):
        """POST create swarm_start → PUT update → GET verify → DELETE → GET 404."""
        # Step 1: POST a swarm_start record.
        # Every key below must be a real swarm_starts column — the passthrough
        # builds the INSERT column list straight from the body, so a phantom key
        # is a MySQL 1054, not a skipped field. (req #3061: this fixture carried
        # `category_filter` and `item_count`, neither of which was ever created.)
        #
        # ai_model/effort are deliberately NOT their DDL defaults ('opus'/'high'):
        # posting the default would make the read-back below pass even if the
        # field never reached the INSERT at all.
        create_resp = invoke('POST', '/darwin_dev/swarm_starts', body={
            'arguments': 'swarm 1 2 3',
            'autonomy_filter': 'implemented',
            'auto_start': '0',
            'session_count': '3',
            'ai_model': 'sonnet',
            'effort': 'xhigh',
            'creator_fk': creator_fk,
        })
        assert create_resp['statusCode'] == 200
        swarm_start_id = extract_id(create_resp)
        assert swarm_start_id is not None

        # Step 2: PUT update — bump session_count, flip auto_start
        update_resp = invoke('PUT', '/darwin_dev/swarm_starts', body=[
            {'id': swarm_start_id, 'session_count': '5', 'auto_start': '1'}
        ])
        assert update_resp['statusCode'] in (200, 204)

        # Step 3: GET verify
        get_resp = invoke('GET', '/darwin_dev/swarm_starts', query={'id': swarm_start_id})
        assert get_resp['statusCode'] == 200
        body = json.loads(get_resp['body'])
        assert isinstance(body, list)
        assert len(body) > 0
        assert body[0]['session_count'] == 5
        assert body[0]['auto_start'] == 1
        assert body[0]['arguments'] == 'swarm 1 2 3'
        assert body[0]['autonomy_filter'] == 'implemented'
        assert body[0]['ai_model'] == 'sonnet'
        assert body[0]['effort'] == 'xhigh'

        # Step 4: DELETE
        delete_resp = invoke('DELETE', '/darwin_dev/swarm_starts', body={'id': swarm_start_id})
        assert delete_resp['statusCode'] == 200

        # Step 5: GET 404
        get_404 = invoke('GET', '/darwin_dev/swarm_starts', query={'id': swarm_start_id})
        assert get_404['statusCode'] == 404
