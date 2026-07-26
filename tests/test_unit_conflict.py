"""Unit tests for the 409 CONFLICT mapping (req #3059).

Pure-function tests over `rest_api_utils` — no database, no `exports.sh`. The
integration counterparts that prove the real Lambda emits these live in
`test_instructions.py` (1062 on a UNIQUE name) and `test_agent_instructions.py`
(1062 on a composite PK, 1452 on a bad FK).

The two things worth locking here are the boundary and the parsing:

- WHICH errnos become a 409. A 409 tells the caller "retry with different data
  and this can succeed". 1054 (unknown column) and 1364 (no default) do not keep
  that promise and must stay 500s, or a client will retry forever.
- The `constraint` extraction, because both regexes read attacker-influenced
  text: the duplicated VALUE is echoed inside the 1062 message.
"""
import json

import pymysql
import pytest

from rest_api_utils import (INTEGRITY_ERRNOS, compose_conflict_response,
                            constraint_name, error_detail, integrity_errno)


DUP_INSTRUCTION = ("Duplicate entry 'binding-rules' for key "
                   "'instructions.uq_instructions_name'")
DUP_JUNCTION = "Duplicate entry '10-6' for key 'agent_instructions.PRIMARY'"
FK_CHILD = ("Cannot add or update a child row: a foreign key constraint fails "
            "(`darwin_dev`.`areas`, CONSTRAINT `areas_ibfk_1` FOREIGN KEY "
            "(`domain_fk`) REFERENCES `domains` (`id`))")
FK_PARENT = ("Cannot delete or update a parent row: a foreign key constraint "
             "fails (`darwin_dev`.`requirements`, CONSTRAINT "
             "`fk_requirements_category` FOREIGN KEY (`category_fk`) "
             "REFERENCES `categories` (`id`))")


def err(errno, message):
    return pymysql.Error(errno, message)


class TestIntegrityErrno:

    @pytest.mark.parametrize('errno', [1062, 1451, 1452])
    def test_the_three_conflict_errnos_are_recognised(self, errno):
        assert integrity_errno(err(errno, 'whatever')) == errno

    @pytest.mark.parametrize('errno, why', [
        (1054, 'unknown column — the request is malformed, not conflicting'),
        (1364, "field has no default — retrying identical data won't help"),
        (1048, 'column cannot be null — same'),
        (2013, 'lost connection — the database really is broken'),
    ])
    def test_everything_else_stays_a_500(self, errno, why):
        assert integrity_errno(err(errno, 'whatever')) is None, why

    def test_the_errno_set_is_exactly_three(self):
        # Guards against a casual addition: widening this set changes the
        # promise 409 makes to every client of every table.
        assert INTEGRITY_ERRNOS == frozenset({1062, 1451, 1452})

    def test_an_exception_with_no_args_does_not_raise(self):
        # pymysql raises arg-less errors from the connection layer. This is
        # called from inside an `except` block, so a crash here would escape and
        # be swallowed by handler.py's blanket catch as a 503 naming nothing.
        assert integrity_errno(pymysql.Error()) is None

    def test_an_unhashable_args0_does_not_raise(self):
        # `[] in frozenset(...)` raises TypeError in CPython. pymysql never does
        # this, but the cost of being total here is one except clause.
        assert integrity_errno(pymysql.Error([], 'weird')) is None


class TestErrorDetail:
    """The accessor the CRUD modules build their error line from.

    pymysql raises ONE-arg errors from its own plumbing —
    `ProgrammingError("Cursor closed")`, `Error("Already closed")`. Every module
    used to format `f"{e.args[0]} {e.args[1]}"`, which raised IndexError from
    inside the `except pymysql.Error` block; handler.py's blanket catch turned
    that into a 503 SERVICE_UNAVAILABLE that named nothing.
    """

    def test_the_normal_two_arg_shape(self):
        assert error_detail(err(1062, DUP_INSTRUCTION)) == (1062, DUP_INSTRUCTION)

    def test_a_one_arg_error_yields_an_empty_message_not_an_indexerror(self):
        assert error_detail(pymysql.ProgrammingError('Cursor closed')) \
            == ('Cursor closed', '')

    def test_a_zero_arg_error_yields_nones(self):
        assert error_detail(pymysql.Error()) == (None, '')

    def test_extra_args_are_ignored(self):
        assert error_detail(pymysql.Error(1062, 'msg', 'extra')) == (1062, 'msg')


class TestConstraintName:

    def test_mysql8_duplicate_key_is_unqualified(self):
        assert constraint_name(1062, DUP_INSTRUCTION) == 'uq_instructions_name'

    def test_mysql57_duplicate_key_has_no_qualifier_to_strip(self):
        assert constraint_name(
            1062, "Duplicate entry 'x' for key 'uq_instructions_name'") \
            == 'uq_instructions_name'

    def test_a_composite_primary_key_reports_PRIMARY(self):
        # Unqualified, so it is only meaningful next to the response's `table`.
        assert constraint_name(1062, DUP_JUNCTION) == 'PRIMARY'

    def test_a_value_containing_the_key_phrase_does_not_fool_the_regex(self):
        # The duplicated VALUE is echoed into the message, so it is caller-
        # controlled text. Only the trailing key is the key.
        message = ("Duplicate entry 'evil' for key 'fake' for key "
                   "'instructions.uq_instructions_name'")
        assert constraint_name(1062, message) == 'uq_instructions_name'

    def test_child_row_fk_reports_the_constraint(self):
        assert constraint_name(1452, FK_CHILD) == 'areas_ibfk_1'

    def test_parent_row_fk_reports_the_constraint(self):
        assert constraint_name(1451, FK_PARENT) == 'fk_requirements_category'

    def test_an_unparseable_message_yields_none_rather_than_guessing(self):
        assert constraint_name(1451, 'a foreign key constraint fails') is None
        assert constraint_name(1062, '') is None
        assert constraint_name(1062, None) is None


class TestComposeConflictResponse:

    def test_the_wire_shape(self):
        wire = "HTTP PUT SQL FAILED: 1062 " + DUP_INSTRUCTION
        resp = compose_conflict_response('instructions',
                                         err(1062, DUP_INSTRUCTION), wire)

        assert resp['statusCode'] == 409
        assert json.loads(resp['body']) == {
            'error': 'CONFLICT',
            'errno': 1062,
            'constraint': 'uq_instructions_name',
            'table': 'instructions',
            'message': wire,
        }

    def test_the_message_is_echoed_verbatim(self):
        """The compatibility promise the rollout depends on.

        darwin-mcp's client._translate falls back to substring-matching this
        string when a response carries no `errno`, and log greps written against
        the 500 era read it too.
        """
        wire = "HTTP POST bulk failed: 1062 " + DUP_JUNCTION
        body = json.loads(compose_conflict_response(
            'agent_instructions', err(1062, DUP_JUNCTION), wire)['body'])
        assert body['message'] == wire
        assert 'Duplicate entry' in body['message']

    def test_table_comes_from_the_handler_not_the_message(self):
        # `constraint` is 'PRIMARY' for every table, so `table` is what makes the
        # pair identifying — and it must not be parsed out of driver prose.
        body = json.loads(compose_conflict_response(
            'agent_instructions', err(1062, DUP_JUNCTION), 'x')['body'])
        assert (body['table'], body['constraint']) == ('agent_instructions', 'PRIMARY')

    def test_body_is_single_encoded_json(self):
        # compose_rest_response json.dumps() once. A dict that arrived
        # pre-stringified would land on the wire double-encoded and every client
        # would read a string where it expects an object.
        resp = compose_conflict_response('areas', err(1452, FK_CHILD), 'x')
        assert isinstance(json.loads(resp['body']), dict)

    def test_an_exception_missing_its_message_arg_still_composes(self):
        body = json.loads(compose_conflict_response(
            'areas', pymysql.Error(1062), 'HTTP POST failed: 1062')['body'])
        assert body['errno'] == 1062
        assert body['constraint'] is None
