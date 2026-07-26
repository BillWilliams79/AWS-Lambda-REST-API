"""REST contracts for the `agent_instructions` junction (req #3049, #3057).

This table has a composite PK and NO `id` column. Both insert paths are locked
here because neither is visible from the table definition alone:

1. **A SINGLE-OBJECT POST RETURNS 201 WITH NO BODY.** `rest_post.py` reads the
   new row back with `SELECT ... WHERE id = <LAST_INSERT_ID()>`, which no
   `id`-less table can answer. Req #3057 made it consult the `DESC` column list
   it already has and skip the read-back instead — before that it raised 1054
   and returned 500 for a row that had already committed under autocommit, so
   every caller saw a successful write as a failure. The 201 asserted below is
   the whole fix: assert the status AND the committed row, because a regression
   here is silent in either direction.

2. **An ARRAY body returns 201 `{"inserted": N}`.** `_rest_post_bulk` never
   read back, so this path was always sound. It is one round trip for N links,
   which is why `Darwin/src/Agents/actions/instructionsApi.js` keeps using it
   for every link, single links included.

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

    def test_single_object_post_returns_201_and_commits_the_row(
            self, invoke, registry, db_connection):
        """req #3057. See this module's docstring.

        Both halves matter. The status must be 201 — a 500 here is the old bug,
        which made callers treat a committed row as a failed write and retry
        into a duplicate-key error. The body must stay empty — there is no
        `id` to read the row back by, so the gateway has nothing honest to
        return and callers re-read by composite key.
        """
        agent = registry['agent']('single')
        instruction = registry['instruction']('single-a')

        resp = invoke('POST', '/darwin_dev/agent_instructions', body={
            'agent_fk': agent, 'instruction_fk': instruction, 'sort_order': 1,
        })
        assert resp['statusCode'] == 201, resp['body']
        assert json.loads(resp['body']) == ''

        rows = _links(db_connection, agent)
        assert [(r['instruction_fk'], r['sort_order']) for r in rows] == \
            [(instruction, 1)]

    def test_single_object_post_duplicate_is_still_500_with_1062(
            self, invoke, registry):
        """The 201 is scoped to the read-back, not to INSERT errors.

        `rest_post.py` returns early on an INSERT failure, so skipping the
        read-back cannot swallow one. If this ever returns 201 the guard has
        been moved above the INSERT's error handling and every junction write
        has become unverifiable.
        """
        agent = registry['agent']('single-dupe')
        instruction = registry['instruction']('single-dupe-a')
        body = {'agent_fk': agent, 'instruction_fk': instruction, 'sort_order': 1}

        assert invoke('POST', '/darwin_dev/agent_instructions',
                      body=dict(body))['statusCode'] == 201
        resp = invoke('POST', '/darwin_dev/agent_instructions', body=dict(body))
        assert resp['statusCode'] == 500
        assert '1062' in _err(resp)

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
