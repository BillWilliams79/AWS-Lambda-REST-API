"""
Unit tests for classifier.py's debug dumps — no database required.

req #4021: varDump and pretty_print_sql were ~82% of Lambda-Rest's CloudWatch
log bytes. They must be silent unless the `debug_log` env var opts in.

Run: pytest tests/test_unit_classifier.py -v
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from classifier import varDump, pretty_print_sql, print_failed_sql


pytestmark = pytest.mark.unit


@pytest.mark.parametrize('value', [None, '', '0', 'false', 'no', 'off'])
def test_silent_unless_opted_in(monkeypatch, capsys, value):
    if value is None:
        monkeypatch.delenv('debug_log', raising=False)
    else:
        monkeypatch.setenv('debug_log', value)
    varDump({'secret': 'x' * 1000}, 'body inside rest_post')
    varDump({'a': 1}, 'json dump', 'json')
    pretty_print_sql("INSERT INTO tasks (a)\n    VALUES (%s);", 'POST')
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('value', ['1', 'true', 'TRUE', ' yes '])
def test_prints_when_opted_in(monkeypatch, capsys, value):
    monkeypatch.setenv('debug_log', value)
    varDump({'a': 1}, 'body inside rest_post')
    pretty_print_sql("INSERT INTO tasks (a)\n    VALUES (%s);", 'POST')
    out = capsys.readouterr().out
    assert "body inside rest_post" in out
    assert "{'a': 1}" in out
    assert "POST SQL statement is: INSERT INTO tasks (a) VALUES (%s);" in out


@pytest.mark.parametrize('value', [None, '0'])
def test_failed_sql_always_logged(monkeypatch, capsys, value):
    # The error path keeps the statement that failed, whatever debug_log says.
    if value is None:
        monkeypatch.delenv('debug_log', raising=False)
    else:
        monkeypatch.setenv('debug_log', value)
    print_failed_sql("UPDATE tasks SET\n    a = %s\n WHERE id = %s;", 'PUT')
    print_failed_sql(None, 'DELETE')  # failed before a statement was built
    assert capsys.readouterr().out == \
        "PUT FAILED SQL statement was: UPDATE tasks SET a = %s WHERE id = %s;\n"


def test_failed_sql_is_capped(capsys):
    from classifier import FAILED_SQL_MAX_CHARS
    sql = "INSERT INTO t (a) VALUES " + ', '.join(['(%s)'] * 2000)
    print_failed_sql(sql, 'POST')
    out = capsys.readouterr().out
    assert out.startswith("POST FAILED SQL statement was: INSERT INTO t (a) VALUES (%s)")
    assert f"…(+{len(sql) - FAILED_SQL_MAX_CHARS} chars)" in out
    assert len(out) < FAILED_SQL_MAX_CHARS + 100
