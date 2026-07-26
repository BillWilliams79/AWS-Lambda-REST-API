"""REST contracts for the `agent_instructions` junction (req #3049, #3057, #3059).

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

3. **A rejected INSERT is a 409 CONFLICT, on either path** (req #3059). The
   composite PK makes 1062 the everyday failure here, and a bad `agent_fk` makes
   1452 the other. Both now carry `{errno, constraint, table}` instead of a
   pymysql string the UI had to regex. Note how this composes with (1): #3057
   made the READ-BACK stop reporting failure, #3059 made the WRITE report its
   failure precisely — the 201 covers only what happens after the row commits,
   so it cannot swallow a rejected INSERT.

PUT is impossible (rest_put.py requires `id`), so a load-order change is a
DELETE + re-POST. `DELETE {agent_fk}` clearing one agent's whole list is the
primitive that makes the reorder normalize pass possible.
"""
import json

import pytest

from conftest import extract_id


def _err(response):
    """A dict for 409 CONFLICT (req #3059), a bare string for any other error."""
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

    def test_single_object_post_duplicate_is_a_409_not_a_201(
            self, invoke, registry):
        """The 201 is scoped to the read-back, not to INSERT errors.

        `rest_post.py` returns early on an INSERT failure, so skipping the
        read-back cannot swallow one. If this ever returns 201 the guard has
        been moved above the INSERT's error handling and every junction write
        has become unverifiable.

        req #3059 changed the failure status from 500 to 409 — the assertion
        that matters is unchanged in spirit: a rejected INSERT must still be
        reported as a failure, and it must still name 1062.
        """
        agent = registry['agent']('single-dupe')
        instruction = registry['instruction']('single-dupe-a')
        body = {'agent_fk': agent, 'instruction_fk': instruction, 'sort_order': 1}

        assert invoke('POST', '/darwin_dev/agent_instructions',
                      body=dict(body))['statusCode'] == 201
        resp = invoke('POST', '/darwin_dev/agent_instructions', body=dict(body))
        assert resp['statusCode'] == 409
        payload = _err(resp)
        assert payload['errno'] == 1062
        assert payload['table'] == 'agent_instructions'

    def test_duplicate_link_is_409_conflict(self, invoke, registry):
        """req #3059: the bulk INSERT path reports a composite-PK collision.

        `constraint` is 'PRIMARY' — which every table has — so it only identifies
        anything paired with `table`. That is exactly how the UI reads it, and
        why `table` is sourced from the handler rather than parsed out of the
        driver's `'agent_instructions.PRIMARY'`.
        """
        agent = registry['agent']('dupe')
        instruction = registry['instruction']('dupe-a')
        body = [{'agent_fk': agent, 'instruction_fk': instruction, 'sort_order': 1}]

        assert invoke('POST', '/darwin_dev/agent_instructions',
                      body=body)['statusCode'] == 201
        resp = invoke('POST', '/darwin_dev/agent_instructions', body=body)
        assert resp['statusCode'] == 409
        payload = _err(resp)
        assert payload['errno'] == 1062
        assert payload['constraint'] == 'PRIMARY'
        assert payload['table'] == 'agent_instructions'

    def test_duplicate_slot_is_409_with_uq_agent_instructions_slot(
            self, invoke, registry, db_connection):
        """req #3075, migration 073: two instructions may not share one agent's
        NUMBERED load slot.

        The composite PK is satisfied by both rows here — different
        instruction_fk — which is precisely why this was invisible before the key
        existed. `nextInstructionSortOrder` computes max+1 from a pre-write cache,
        so two concurrent binds against the same agent both propose the same slot
        and, without this key, both inserts succeed.

        The key name is asserted because it is a CONTRACT. req #3059 changed HOW
        it travels — it is now the `constraint` field of a 409 body rather than a
        token to be regexed out of a 500's pymysql string — but not THAT it
        travels: `agentRegistryUtils.restErrorMessage` and darwin-mcp's
        `link_agent_instruction` both key on this exact name to turn the failure
        into something a human can act on. Rename the key and both go silently
        generic.
        """
        agent = registry['agent']('slot')
        first = registry['instruction']('slot-a')
        second = registry['instruction']('slot-b')

        assert invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent, 'instruction_fk': first, 'sort_order': 1},
        ])['statusCode'] == 201

        resp = invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent, 'instruction_fk': second, 'sort_order': 1},
        ])
        assert resp['statusCode'] == 409
        payload = _err(resp)
        assert payload['errno'] == 1062
        assert payload['constraint'] == 'uq_agent_instructions_slot'
        assert payload['table'] == 'agent_instructions'

        # The rejected row was NOT written — the agent keeps exactly one link.
        assert [(r['instruction_fk'], r['sort_order'])
                for r in _links(db_connection, agent)] == [(first, 1)]

    def test_null_slots_are_unconstrained(self, invoke, registry, db_connection):
        """The deliberate SCOPE of uq_agent_instructions_slot: NULL claims no slot,
        and MySQL UNIQUE treats NULLs as distinct, so one agent may hold any number
        of unordered links.

        This is the shape `link_agent_instruction` produces when `sort_order` is
        omitted (req #3049 COALESCE contract), so a key that rejected it would
        break every "ensure it is bound" re-seed."""
        agent = registry['agent']('nullslot')
        first = registry['instruction']('nullslot-a')
        second = registry['instruction']('nullslot-b')

        assert invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent, 'instruction_fk': first, 'sort_order': None},
            {'agent_fk': agent, 'instruction_fk': second, 'sort_order': None},
        ])['statusCode'] == 201

        rows = _links(db_connection, agent)
        assert len(rows) == 2
        assert all(r['sort_order'] is None for r in rows)

    def test_two_agents_may_hold_the_same_slot(self, invoke, registry, db_connection):
        """agent_fk LEADS the key. Every agent has its own slot 1 — the banded
        scheme puts per-agent rules at 1..N on all of them — so this must stay
        legal. A global UNIQUE(sort_order) would have broken the whole registry."""
        agent_a = registry['agent']('shared-a')
        agent_b = registry['agent']('shared-b')
        instruction = registry['instruction']('shared-i')

        assert invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent_a, 'instruction_fk': instruction, 'sort_order': 1},
            {'agent_fk': agent_b, 'instruction_fk': instruction, 'sort_order': 1},
        ])['statusCode'] == 201

        assert [(r['instruction_fk'], r['sort_order'])
                for r in _links(db_connection, agent_a)] == [(instruction, 1)]
        assert [(r['instruction_fk'], r['sort_order'])
                for r in _links(db_connection, agent_b)] == [(instruction, 1)]

    def test_bad_foreign_key_is_409_conflict(self, invoke, registry):
        instruction = registry['instruction']('badfk-a')
        resp = invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': 999999999, 'instruction_fk': instruction, 'sort_order': 1},
        ])
        assert resp['statusCode'] == 409
        payload = _err(resp)
        assert payload['errno'] == 1452
        assert payload['table'] == 'agent_instructions'


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


class TestAgentInstructionsReorder:
    """req #3075: the reorder path replayed through the REST surface it uses.

    This class exists to pin the reason a plain UNIQUE key is safe on this table.
    `setAgentInstructionOrder` was described during requirement authoring as
    "DELETE-then-POST, so a swap transiently holds both rows at overlapping
    values" — it does not. It DELETEs EVERY row in the write set first and only
    then re-creates them all in ONE array-body POST. Nothing here is atomic (each
    call is a separate Lambda invocation under autocommit), but at no instant do
    two rows of one agent hold the same numbered slot.

    If someone later "optimizes" that into a per-row delete-then-post, this test
    is what fails.
    """

    def test_delete_all_then_repost_swaps_two_slots(
            self, invoke, registry, db_connection):
        agent = registry['agent']('swap')
        first = registry['instruction']('swap-a')
        second = registry['instruction']('swap-b')

        invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent, 'instruction_fk': first, 'sort_order': 1},
            {'agent_fk': agent, 'instruction_fk': second, 'sort_order': 2},
        ])

        for instruction in (first, second):
            assert invoke('DELETE', '/darwin_dev/agent_instructions', body={
                'agent_fk': agent, 'instruction_fk': instruction,
            })['statusCode'] == 200

        assert invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent, 'instruction_fk': first, 'sort_order': 2},
            {'agent_fk': agent, 'instruction_fk': second, 'sort_order': 1},
        ])['statusCode'] == 201

        assert [(r['instruction_fk'], r['sort_order'])
                for r in _links(db_connection, agent)] == [(second, 1), (first, 2)]

    def test_moving_onto_an_occupied_slot_is_rejected_and_rolls_back(
            self, invoke, registry, db_connection):
        """A per-row move — delete one row, re-post it onto a slot it did not
        vacate. Rejection is the DESIRED outcome, not a regression: before
        migration 073 this silently produced two instructions at slot 1.

        This is the shape `link_agent_instruction` USED to have, and the reason
        req #3075 changed it: under the key a per-row move can no longer express a
        reorder at all, so that function now deletes both rows before re-posting
        either (a swap). Kept here as a raw-REST replay because any writer that
        reaches for the old shape — a seed script, a repair tool — lands exactly
        here, and the recovery replayed below (re-post the OLD value) is what
        keeps such a writer from degrading into a silent unlink."""
        agent = registry['agent']('move')
        first = registry['instruction']('move-a')
        second = registry['instruction']('move-b')

        invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent, 'instruction_fk': first, 'sort_order': 1},
            {'agent_fk': agent, 'instruction_fk': second, 'sort_order': 2},
        ])

        # Move `second` onto slot 1, which `first` still holds.
        assert invoke('DELETE', '/darwin_dev/agent_instructions', body={
            'agent_fk': agent, 'instruction_fk': second,
        })['statusCode'] == 200
        resp = invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent, 'instruction_fk': second, 'sort_order': 1},
        ])
        assert resp['statusCode'] == 500
        assert 'uq_agent_instructions_slot' in _err(resp)

        # Restore the old value, exactly as link_agent_instruction's except branch
        # does — the link is back where it was, not lost.
        assert invoke('POST', '/darwin_dev/agent_instructions', body=[
            {'agent_fk': agent, 'instruction_fk': second, 'sort_order': 2},
        ])['statusCode'] == 201
        assert [(r['instruction_fk'], r['sort_order'])
                for r in _links(db_connection, agent)] == [(first, 1), (second, 2)]


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
