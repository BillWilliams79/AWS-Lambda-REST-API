"""pipeline_lifecycle.py — a pipeline's status and its two timestamps (req #3965).

`pipelines.pipeline_status` uses the requirement vocabulary since req #3965
(user ruling 2026-10-30): authoring | authorized | orchestration_ready |
orchestrating | met | wontfix | deferred, born `authoring`. Only
`orchestrating` launches work (`pipeline2_derive.py` suppresses every other
status). `started_at` / `completed_at` are DERIVED from the status a write
sets, never chosen by a caller:

  * `orchestrating`                 stamp started_at if unset; clear completed_at
  * `met` | `wontfix` | `deferred`  stamp completed_at if unset
  * the other three                 clear completed_at (started_at is history)

WHY HERE. darwin-mcp derived these until #3965, and the browser could not
write a status at all for that reason: the Pipelines page writes the table
directly through the generic PUT/POST (`Darwin/src/Pipelines/pipelinesApi.js`),
so a rule in darwin-mcp covered one writer of two. Every pipeline editor now
sets any of the seven values, so the rule lives where every write passes —
the same reason `plan_lock.py` sits at the gateway.

THE DOMAIN IS ENFORCED HERE, unlike every other column in `ENUM_COLUMNS`
(`auth_utils.py`, which refuses only a blank). A value this file does not know
has no timestamp rule, so writing it would leave the two stamps saying
something the status does not; that is a 400, before any statement runs.
darwin-mcp validates the same list (`_VALID_PIPELINE2_STATUSES`); the two are
held together by `tests/test_unit_pipeline_lifecycle.py`.

A caller that names `started_at` / `completed_at` itself keeps its value — a
repair of a lost stamp is a legitimate write.
"""
from datetime import datetime, timezone

import pymysql

from auth_utils import body_column, _reference_value
from rest_api_utils import compose_rest_response, error_detail

PIPELINE_STATUSES = ('authoring', 'authorized', 'orchestration_ready',
                     'orchestrating', 'met', 'wontfix', 'deferred')
ORCHESTRATING = 'orchestrating'
TERMINAL_STATUSES = frozenset({'met', 'wontfix', 'deferred'})

_TABLE = 'pipelines'
_STATUS = 'pipeline_status'


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def _rule(status):
    """`{column: 'stamp' | 'clear'}` for a status."""
    if status == ORCHESTRATING:
        return {'started_at': 'stamp', 'completed_at': 'clear'}
    if status in TERMINAL_STATUSES:
        return {'completed_at': 'stamp'}
    return {'completed_at': 'clear'}


def plan_lifecycle(table, bodies, method):
    """Pure: `(work, lookups, refusal)`.

    `work` is `[(body, status), ...]` for every body that names the status;
    `lookups` the canonical ids a PUT must read to know whether a stamp is
    already set; `refusal` a `(code, message)` for an unknown status or an id
    MySQL would coerce."""
    if table != _TABLE:
        return [], [], None
    work, lookups = [], []
    for body in bodies or ():
        if not isinstance(body, dict):
            return [], [], (400, 'BAD REQUEST')
        present, status = body_column(body, _STATUS)
        if not present:
            continue
        if status not in PIPELINE_STATUSES:
            print(f"HTTP {method} pipelines: unknown pipeline_status {status!r} — "
                  f"must be one of {', '.join(PIPELINE_STATUSES)}")
            return [], [], (400, 'BAD REQUEST')
        work.append((body, status))
        if method == 'PUT' and 'stamp' in _rule(status).values():
            present, value = body_column(body, 'id')
            try:
                row_id = _reference_value(value) if present else None
            except ValueError:
                return [], [], (400, 'BAD REQUEST')
            if row_id is not None:
                lookups.append(row_id)
    return work, lookups, None


def _current_stamps(conn, ids, authenticated_user):
    """`{id: {'started_at': ..., 'completed_at': ...}}` for the rows the caller
    owns. A row it does not own is absent, and its write falls through to the
    ownership scoping the statement already applies."""
    placeholders = ', '.join(['%s'] * len(ids))
    sql = f"SELECT id, started_at, completed_at FROM pipelines WHERE id IN ({placeholders})"
    params = list(ids)
    if authenticated_user is not None:
        sql += " AND creator_fk = %s"
        params.append(authenticated_user)
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
    out = {}
    for row in rows:
        if isinstance(row, dict):
            out[str(row['id'])] = {'started_at': row['started_at'],
                                   'completed_at': row['completed_at']}
        else:
            out[str(row[0])] = {'started_at': row[1], 'completed_at': row[2]}
    return out


def pipeline_lifecycle_guard(conn, table, bodies, authenticated_user, method):
    """Validate the status every body names and write the derived timestamps
    into those bodies. Returns a refusal response or None. Mutates `bodies`.

    A POST has no current row, so a stamp is always written; a PUT reads the
    rows first (one SELECT) and stamps only what is unset. On a bulk POST every
    item must name the same columns, so a derived column added to one item is
    added to all of them as NULL — which is what an INSERT omitting it stores.
    """
    work, lookups, refusal = plan_lifecycle(table, bodies, method)
    if refusal is not None:
        return compose_rest_response(refusal[0], '', refusal[1])
    if not work:
        return None

    current = {}
    if lookups:
        try:
            current = _current_stamps(conn, sorted(set(lookups)), authenticated_user)
        except pymysql.Error as e:
            errno, detail = error_detail(e)
            print(f"HTTP {method} pipelines: lifecycle read failed: {errno} {detail}")
            return compose_rest_response(500, '', 'INTERNAL SERVER ERROR')

    now = _now()
    added = set()
    for body, status in work:
        row = None
        if method == 'PUT':
            present, value = body_column(body, 'id')
            try:
                row = current.get(_reference_value(value)) if present else None
            except ValueError:
                # Only a stamping status validated its id in planning; a
                # clearing one reaches here with whatever the caller sent.
                return compose_rest_response(400, '', 'BAD REQUEST')
        for column, action in _rule(status).items():
            if body_column(body, column)[0]:
                continue                       # the caller's own value wins
            if action == 'clear':
                if method == 'POST':
                    continue                   # an INSERT stores NULL anyway
                body[column] = 'NULL'
            elif method == 'POST' or (row is not None and row.get(column) is None):
                body[column] = now
                added.add(column)
    if method == 'POST' and len(bodies) > 1:
        for body in bodies:
            for column in added:
                if not body_column(body, column)[0]:
                    body[column] = 'NULL'
    return None
