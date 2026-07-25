"""REST contracts for the `agent_instructions` junction (req #3049).

This table has a composite PK and NO `id` column, which makes the generic
passthrough behave in two ways the Darwin UI must be written around. Both are
locked here because both are invisible until something depends on them:

1. **A SINGLE-OBJECT POST COMMITS THE ROW AND THEN RETURNS 500.** `rest_post.py`
   re-reads the new row with `SELECT ... WHERE id = <LAST_INSERT_ID()>`, which
   raises 1054 on a table with no `id` column — after the INSERT has already
   committed under autocommit. The caller sees a failure that actually succeeded.
   The test below asserts BOTH halves on purpose. Do not "fix" it into a silent
   regression: `test_swarm_starts.py` documents the same read-back assumption,
   and the fix belongs in `rest_post.py`, not here.

2. **An ARRAY body works.** `_rest_post_bulk` does no read-back, so it returns
   201 `{"inserted": N}`. That is the ONLY sound insert path for this table and
   the one `Darwin/src/Agents/actions/instructionsApi.js` uses for every link,
   including single links.

PUT is impossible (rest_put.py requires `id`), so a load-order change is a
DELETE + re-POST. `DELETE {agent_fk}` clearing one agent's whole list is the
primitive that makes the reorder normalize pass possible.
"""
import json

import pytest

from conftest import extract_id


def _err(response):
    return json.loads(response['body'])


def _links(db_connection, agent_fk):
    with db_connection.cursor() as cur:
        cur.execute('SELECT instruction_fk, sort_order FROM agent_instructions '
                    'WHERE agent_fk = %s ORDER BY sort_order', (agent_fk,))
        return cur.fetchall()


@pytest.fixture
def registry(invoke, creator_fk):
    """One agent plus two instructions, torn down after the test.

    Deleting the parents cascades any junction rows away, so the junction needs
    no explicit cleanup — which is itself the behaviour asserted at the end.
    """
    made = {'agents': [], 'instructions': []}

    def _agent(suffix):
        resp = invoke('POST', '/darwin_dev/agents', body={
            'name': f'pytest {creator_fk} {suffix}',
            'file_name': f'pytest-{creator_fk}-{suffix}.md',
            'overview': 'pytest fixture agent',
            'ai_model': 'opus[1m]',
            'effort': 'high',
            'creator_fk': creator_fk,
        })
        assert resp['statusCode'] == 200, resp['body']
        row_id = extract_id(resp)
        made['agents'].append(row_id)
        return int(row_id)

    def _instruction(suffix):
        resp = invoke('POST', '/darwin_dev/instructions', body={
            'name': f'pytest-{creator_fk}-{suffix}',
            'content': 'binding text',
            'creator_fk': creator_fk,
        })
        assert resp['statusCode'] == 200, resp['body']
        row_id = extract_id(resp)
        made['instructions'].append(row_id)
        return int(row_id)

    yield {'agent': _agent, 'instruction': _instruction}

    for row_id in made['agents']:
        invoke('DELETE', '/darwin_dev/agents', body={'id': row_id})
    for row_id in made['instructions']:
        invoke('DELETE', '/darwin_dev/instructions', body={'id': row_id})


class TestAgentInstructionsInsert:

    def test_array_body_post_returns_201_inserted(self, invoke, registry, db_connection):
        """THE load-bearing contract: array body → _rest_post_bulk → 201.

        Every link the UI writes goes through this path, single links included.
        """
        agent = registry['agent']('bulk')
        first = registry['instruction']('bulk-a')
        second = registry['instruction']('bulk-b')

        resp = invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent, 'instruction_fk': first, 'sort_order': 1},
            {'agent_fk': agent, 'instruction_fk': second, 'sort_order': 2},
        ])
        assert resp['statusCode'] == 201
        assert json.loads(resp['body'])['inserted'] == 2

        rows = _links(db_connection, agent)
        assert [(r['instruction_fk'], r['sort_order']) for r in rows] == \
            [(first, 1), (second, 2)]

    def test_single_object_post_returns_500_but_commits_the_row(
            self, invoke, registry, db_connection):
        """Known-bad, deliberately locked. See this module's docstring.

        The row IS created; only the read-back fails. A caller that retries on
        this "failure" gets a duplicate-key error on the second attempt, which is
        exactly why the UI never uses the single-object path.
        """
        agent = registry['agent']('single')
        instruction = registry['instruction']('single-a')

        resp = invoke('POST', '/darwin_dev/agent_instructions', body={
            'agent_fk': agent, 'instruction_fk': instruction, 'sort_order': 1,
        })
        assert resp['statusCode'] == 500
        assert '1054' in _err(resp)

        rows = _links(db_connection, agent)
        assert [r['instruction_fk'] for r in rows] == [instruction]

    def test_duplicate_link_is_500_with_1062(self, invoke, registry):
        agent = registry['agent']('dupe')
        instruction = registry['instruction']('dupe-a')
        body = [{'agent_fk': agent, 'instruction_fk': instruction, 'sort_order': 1}]

        assert invoke('POST', '/darwin_dev/agent_instructions',
                      body=body)['statusCode'] == 201
        resp = invoke('POST', '/darwin_dev/agent_instructions', body=body)
        assert resp['statusCode'] == 500
        message = _err(resp)
        assert '1062' in message
        assert 'agent_instructions.PRIMARY' in message

    def test_bad_foreign_key_is_500_with_1452(self, invoke, registry):
        instruction = registry['instruction']('badfk-a')
        resp = invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': 999999999, 'instruction_fk': instruction, 'sort_order': 1},
        ])
        assert resp['statusCode'] == 500
        assert '1452' in _err(resp)


class TestAgentInstructionsDelete:

    def test_composite_delete_then_404(self, invoke, registry):
        agent = registry['agent']('del')
        instruction = registry['instruction']('del-a')
        invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent, 'instruction_fk': instruction, 'sort_order': 1},
        ])

        key = {'agent_fk': agent, 'instruction_fk': instruction}
        assert invoke('DELETE', '/darwin_dev/agent_instructions',
                      body=key)['statusCode'] == 200
        # Re-deleting is a 404, which call_rest_api THROWS on — the UI's unlink
        # path swallows it because an absent link is the desired end state.
        assert invoke('DELETE', '/darwin_dev/agent_instructions',
                      body=key)['statusCode'] == 404

    def test_delete_by_agent_clears_that_agents_whole_list(
            self, invoke, registry, db_connection):
        """The reorder primitive: one call empties one agent's load order.

        Scoped to the agent — another agent's links must survive.
        """
        agent = registry['agent']('clear')
        other = registry['agent']('keeper')
        first = registry['instruction']('clear-a')
        second = registry['instruction']('clear-b')

        invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent, 'instruction_fk': first, 'sort_order': 1},
            {'agent_fk': agent, 'instruction_fk': second, 'sort_order': 2},
            {'agent_fk': other, 'instruction_fk': first, 'sort_order': 1},
        ])

        assert invoke('DELETE', '/darwin_dev/agent_instructions',
                      body={'agent_fk': agent})['statusCode'] == 200
        assert _links(db_connection, agent) == ()
        assert len(_links(db_connection, other)) == 1


class TestAgentInstructionsPut:

    def test_put_is_rejected_because_there_is_no_id(self, invoke, registry):
        """Documents WHY load order is a DELETE + re-POST rather than an update."""
        agent = registry['agent']('put')
        instruction = registry['instruction']('put-a')
        invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent, 'instruction_fk': instruction, 'sort_order': 1},
        ])

        resp = invoke('PUT', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent, 'instruction_fk': instruction, 'sort_order': 2},
        ])
        assert resp['statusCode'] == 400


class TestAgentInstructionsCascade:

    def test_deleting_the_instruction_cascades_its_links(
            self, invoke, creator_fk, registry, db_connection):
        """Why the UI shows the bound-agent list before a hard delete: the links
        vanish with no trace and each agent silently loses the duty at next boot."""
        agent = registry['agent']('cascade')
        resp = invoke('POST', '/darwin_dev/instructions', body={
            'name': f'pytest-{creator_fk}-cascade-victim',
            'content': 'about to be deleted',
            'creator_fk': creator_fk,
        })
        victim = int(extract_id(resp))
        invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent, 'instruction_fk': victim, 'sort_order': 1},
        ])
        assert len(_links(db_connection, agent)) == 1

        assert invoke('DELETE', '/darwin_dev/instructions',
                      body={'id': victim})['statusCode'] == 200
        assert _links(db_connection, agent) == ()
