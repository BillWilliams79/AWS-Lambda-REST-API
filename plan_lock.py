"""plan_lock.py — LOCKED is a relic in time (req #3649).

`pipelines.locked`, `initiatives.locked` and `pipeline_steps.locked` (migration
20261019100448) say a plan-layer row may no longer be AUTHORED. This module is
the one place that rule is enforced, and it sits at the gateway for the same
reason the ownership registries do: the browser writes these five tables
directly through the generic PUT/POST/DELETE (`Darwin/src/Steps/stepsApi.js`,
`Initiatives/initiativesApi.js`, `Pipelines/pipelinesApi.js`), so a check in darwin-mcp's
services would cover one of the two writers. Lambda-Rest is the single DB
gateway (req #3050); a lock lives where every write passes.

WHAT A LOCK FREEZES — structure AND authoring fields, cascading:

  * a locked PIPELINE freezes itself, every initiative in it and every step in
    those initiatives; a locked INITIATIVE freezes itself and its steps; a locked STEP
    freezes itself. "Effectively locked" = the row's own flag OR any
    ancestor's. There is one column per layer and no copy of an ancestor's
    state — the cascade is derived in one SELECT, never stored.
  * frozen: creating, deleting or moving a child (an initiative under the plan, a
    step under the initiative); linking or unlinking a requirement; adding or
    removing a dependency edge; and every authoring field — title,
    description, notes, run, checkpoint, not_before, sort_order, category_fk,
    machine_fk, execution_mode, and the parent columns a move rewrites.
  * NOT frozen: the lock itself (so it can be lifted through the same call),
    and orchestration/lifecycle state — `pipeline_status` with its derived
    `started_at`/`completed_at`, `initiative_status`, `closed`. A step carries no
    lifecycle state at all (req #3750). A locked plan can still be orchestrated;
    it cannot be rewritten.

A DELETE THAT CASCADES INTO THE PLAN LAYER IS AUTHORING TOO (req #3706).
Deleting a requirement removes its step seat (`fk_psr_requirement` is ON
DELETE CASCADE since migration 20261021060108), so a requirement seated on an
effectively locked step is refused exactly as unlinking it would be.
`_CASCADES_INTO` names that one non-plan table.

THE ANSWER IS 423 LOCKED, a JSON object (like the 409 CONFLICT body) carrying
`table`, `id`, `locked_by` (the OUTERMOST locked level — unlocking the step
helps nobody while its plan is locked) and `locked_id`, plus a `message` that
`RestApi.jsx` and darwin-mcp's client both surface verbatim.

THE SHAPE IS `parent_reference_guard`'s: planning is PURE (what to look up,
decided without a cursor), one SELECT per request resolves the chain, a
failure of the check itself is a 500 and never a pass, and a write that
touches nothing a lock protects — `PUT [{"id": 5, "locked": 0}]`, an unauthenticated call, a table not in
`PLAN_LOCK` (other than a `_CASCADES_INTO` DELETE) — returns before any cursor
is opened.
"""
import pymysql

from auth_utils import _reference_value, body_column
from rest_api_utils import compose_rest_response, error_detail

# table -> (the column naming its parent, the parent table, the keys a PUT may
# still write on an effectively locked row). `id` and `creator_fk` (forced
# from the token by rest_put) are always tolerated.
PLAN_LOCK = {
    'pipelines': {
        'parent': None,
        'unlocked': frozenset({'locked', 'pipeline_status', 'started_at',
                               'completed_at'})},
    'initiatives': {
        'parent': ('pipeline_fk', 'pipelines'),
        'unlocked': frozenset({'locked', 'initiative_status', 'closed'})},
    'pipeline_steps': {
        'parent': ('initiative_fk', 'initiatives'),
        'unlocked': frozenset({'locked'})},
    'pipeline_step_requirements': {
        'parent': ('step_fk', 'pipeline_steps'),
        'unlocked': frozenset()},
    'pipeline_step_deps': {
        'parent': ('step_fk', 'pipeline_steps'),
        'unlocked': frozenset()},
}

_ALWAYS_WRITABLE = frozenset({'id', 'creator_fk'})

# The chain each table resolves, innermost row first: FROM/JOIN clause, the
# alias whose id the WHERE names, and the (level, id column, lock column)
# triples in OUTERMOST-first order so the verdict names the right level.
_CHAINS = {
    'pipelines': (
        'pipelines t',
        't',
        (('pipeline', 't.id', 't.locked'),)),
    'initiatives': (
        'initiatives t JOIN pipelines p ON p.id = t.pipeline_fk',
        't',
        (('pipeline', 'p.id', 'p.locked'), ('initiative', 't.id', 't.locked'))),
    'pipeline_steps': (
        'pipeline_steps t JOIN initiatives e ON e.id = t.initiative_fk '
        'JOIN pipelines p ON p.id = e.pipeline_fk',
        't',
        (('pipeline', 'p.id', 'p.locked'), ('initiative', 'e.id', 'e.locked'),
         ('step', 't.id', 't.locked'))),
    'pipeline_step_requirements': (
        'pipeline_step_requirements t JOIN pipeline_steps s ON s.id = t.step_fk '
        'JOIN initiatives e ON e.id = s.initiative_fk JOIN pipelines p ON p.id = e.pipeline_fk',
        's',
        (('pipeline', 'p.id', 'p.locked'), ('initiative', 'e.id', 'e.locked'),
         ('step', 's.id', 's.locked'))),
    'pipeline_step_deps': (
        'pipeline_step_deps t JOIN pipeline_steps s ON s.id = t.step_fk '
        'JOIN initiatives e ON e.id = s.initiative_fk JOIN pipelines p ON p.id = e.pipeline_fk',
        's',
        (('pipeline', 'p.id', 'p.locked'), ('initiative', 'e.id', 'e.locked'),
         ('step', 's.id', 's.locked'))),
}


def is_plan_table(table):
    return table in PLAN_LOCK


def _parent_of(table):
    return PLAN_LOCK[table]['parent']


# ---------------------------------------------------------------------------
# Planning — pure
# ---------------------------------------------------------------------------

def plan_lock_lookups(table, bodies, method):
    """What a POST/PUT must look up before it may write: `(rows, parents,
    refusal)`.

    `rows` are ids of `table` whose body writes something a lock protects (a
    PUT only); `parents` are ids of the parent table a body names (a POST's
    container, or the destination of a PUT that moves the row). Both are
    canonical id strings. `refusal` is `(400, 'BAD REQUEST')` for an id MySQL
    would silently coerce (the req #3122 rule, via `_reference_value`).

    Decided without a cursor, so the common PUTs — `locked` itself, a
    lifecycle status — cost no read at all.
    """
    if table not in PLAN_LOCK:
        return [], [], None
    spec = PLAN_LOCK[table]
    parent = spec['parent']
    rows, parents = [], []
    try:
        for body in bodies or ():
            if not isinstance(body, dict):
                return [], [], (400, 'BAD REQUEST')
            keys = {k.lower() for k in body if isinstance(k, str)}
            if parent is not None:
                present, value = body_column(body, parent[0])
                if present:
                    parent_id = _reference_value(value)
                    if parent_id is not None:
                        parents.append(parent_id)
            if method == 'PUT':
                protected = keys - _ALWAYS_WRITABLE - spec['unlocked']
                if protected:
                    present, value = body_column(body, 'id')
                    row_id = _reference_value(value) if present else None
                    if row_id is not None:
                        rows.append(row_id)
    except ValueError:
        return [], [], (400, 'BAD REQUEST')
    return rows, parents, None


# ---------------------------------------------------------------------------
# Resolution — one SELECT
# ---------------------------------------------------------------------------

def _chain_sql(table, where):
    from_clause, _, levels = _CHAINS[table]
    # Aliased per level, so a DictCursor row (which `auth_utils` tolerates)
    # does not collapse three `id`/`locked` pairs into one.
    columns = ', '.join('%s AS %s_id, %s AS %s_locked' % (id_col, level, lock_col, level)
                        for level, id_col, lock_col in levels)
    return ('SELECT DISTINCT %s FROM %s WHERE %s AND p.creator_fk = %%s'
            % (columns, from_clause, where)
            if table != 'pipelines' else
            'SELECT DISTINCT %s FROM %s WHERE %s AND t.creator_fk = %%s'
            % (columns, from_clause, where))


def resolve_locks(cursor, table, where, params, authenticated_user):
    """The effectively locked rows `where` selects, as
    `[(row_id, locked_by, locked_id), ...]` — `locked_by` the OUTERMOST locked
    level. Rows another creator owns are simply not returned, and fall
    through to the ownership scoping every verb already applies.

    `where` is written against the chain's aliases (`t` for the table's own
    row, `s`/`e`/`p` for step/initiative/pipeline); `params` fill its placeholders.
    """
    levels = _CHAINS[table][2]
    cursor.execute(_chain_sql(table, where), tuple(params) + (authenticated_user,))
    locked = []
    for row in cursor.fetchall():
        if isinstance(row, dict):
            row = [v for level, _, _ in levels
                   for v in (row['%s_id' % level], row['%s_locked' % level])]
        pairs = list(zip(levels, row[0::2], row[1::2]))
        own_id = pairs[-1][1]
        for (level, _, _), level_id, flag in pairs:
            if flag:
                locked.append((own_id, level, level_id))
                break
    return locked


# What a DELETE of a container must also ask (req #3649 review W1): the
# cascade runs DOWN, so a locked descendant is as much a refusal as a locked
# ancestor. FROM clause with the deleted table as `t`, and the descendant
# level each SELECT names.
_BELOW = {
    'initiatives': (
        ('step', 'initiatives t JOIN pipeline_steps s ON s.initiative_fk = t.id', 's'),),
    'pipelines': (
        ('initiative', 'pipelines t JOIN initiatives e ON e.pipeline_fk = t.id', 'e'),
        ('step', 'pipelines t JOIN initiatives e ON e.pipeline_fk = t.id '
                 'JOIN pipeline_steps s ON s.initiative_fk = e.id', 's')),
}


def resolve_locked_below(cursor, table, where, params, authenticated_user):
    """`[(row_id, level, level_id), ...]` — the LOCKED rows underneath the
    `table` rows `where` selects, outermost level first. Empty for a table
    with nothing under it."""
    locked = []
    for level, from_clause, alias in _BELOW.get(table, ()):
        cursor.execute(
            'SELECT DISTINCT t.id AS own_id, %s.id AS below_id FROM %s '
            'WHERE %s AND %s.locked = 1 AND t.creator_fk = %%s'
            % (alias, from_clause, where, alias),
            tuple(params) + (authenticated_user,))
        for row in cursor.fetchall():
            own_id, below_id = ((row['own_id'], row['below_id'])
                                if isinstance(row, dict) else (row[0], row[1]))
            locked.append((own_id, level, below_id))
    return locked


# req #3706 — a table OUTSIDE the plan layer whose DELETE cascades into it:
# table -> (the plan table its rows are seated in, the column naming them).
_CASCADES_INTO = {
    'requirements': ('pipeline_step_requirements', 'requirement_fk'),
}


def resolve_locked_seats(cursor, table, where, params, authenticated_user):
    """`[(row_id, step_id, level, level_id), ...]` — the `table` rows `where`
    selects (alias `t`) that are seated on an effectively locked step,
    `level` the OUTERMOST locked one. Seats in another creator's plan are not
    returned, as in `resolve_locks`."""
    child, column = _CASCADES_INTO[table]
    from_clause, _, levels = _CHAINS[child]
    columns = ', '.join('%s AS %s_id, %s AS %s_locked' % (id_col, level, lock_col, level)
                        for level, id_col, lock_col in levels)
    # The subquery re-binds `t` to `table`, so the caller's `where` reads
    # exactly as it does against the DELETE itself.
    cursor.execute(
        'SELECT DISTINCT t.%s AS seated_id, %s FROM %s '
        'WHERE t.%s IN (SELECT t.id FROM %s t WHERE %s) AND p.creator_fk = %%s'
        % (column, columns, from_clause, column, table, where),
        tuple(params) + (authenticated_user,))
    locked = []
    for row in cursor.fetchall():
        if isinstance(row, dict):
            row = [row['seated_id']] + [v for level, _, _ in levels
                                        for v in (row['%s_id' % level],
                                                  row['%s_locked' % level])]
        pairs = list(zip(levels, row[1::2], row[2::2]))
        for (level, _, _), level_id, flag in pairs:
            if flag:
                locked.append((row[0], pairs[-1][1], level, level_id))
                break
    return locked


def _in_clause(n):
    return '(' + ', '.join(['%s'] * n) + ')'


def _flag_on(value):
    """A TINYINT(1) body value as a bool — `0`, `'0'`, `''`, `None`, `'NULL'`
    and `False` are off; anything else is on."""
    if value in (None, '', 'NULL', False):
        return False
    try:
        return float(value) != 0
    except (TypeError, ValueError):
        return True


def _locked_response(table, locked, method, adding=None, below=False):
    row_id, level, level_id = locked[0]
    if below:
        message = ('cannot delete %s %s: %s %s under it is locked — unlock it first'
                   % (table, row_id, level, level_id))
    elif adding:
        message = ('cannot %s %s under %s %s: locked by %s %s — unlock it first'
                   % ('add' if method == 'POST' else 'move', adding,
                      table, row_id, level, level_id))
    else:
        message = ('%s %s is locked by %s %s — unlock it first'
                   % (table, row_id, level, level_id))
    print('HTTP %s refused: %s' % (method, message))
    return compose_rest_response(423, '', {
        'error': 'LOCKED', 'table': table, 'id': row_id,
        'locked_by': level, 'locked_id': level_id, 'message': message})


def _seated_response(table, seated, method):
    row_id, step_id, level, level_id = seated[0]
    message = ('cannot delete %s %s: it is seated on step %s, locked by %s %s'
               ' — unlock it first' % (table, row_id, step_id, level, level_id))
    print('HTTP %s refused: %s' % (method, message))
    return compose_rest_response(423, '', {
        'error': 'LOCKED', 'table': table, 'id': row_id,
        'locked_by': level, 'locked_id': level_id, 'message': message})


def _check_failed(method, exc):
    errno, detail = error_detail(exc)
    message = 'HTTP %s lock check failed: %s %s' % (method, errno, detail)
    print(message)
    return compose_rest_response(500, '', message)


# ---------------------------------------------------------------------------
# The guards — one for writes, one for deletes
# ---------------------------------------------------------------------------

def plan_lock_guard(conn, table, bodies, authenticated_user, method):
    """423 when a POST/PUT would author a locked plan-layer row, 400 on an
    uncanonical id, 500 when the check itself failed, else None.

    Hooked beside `parent_reference_guard` in rest_post (single and bulk) and
    rest_put (before the single/CASE split, while bodies still carry `id`).
    """
    if authenticated_user is None or table not in PLAN_LOCK:
        return None
    rows, parents, refusal = plan_lock_lookups(table, bodies, method)
    if refusal is not None:
        return compose_rest_response(refusal[0], '', refusal[1])
    if not rows and not parents:
        return None
    # A PUT THAT LIFTS THE ROW'S OWN LOCK MAY EDIT IN THE SAME STATEMENT
    # (req #3649 review W4): the lock it is checked against is the one it is
    # removing. An ANCESTOR's lock is not this row's to lift, and still holds.
    own_level = _CHAINS[table][2][-1][0]
    unlocking = set()
    if method == 'PUT':
        for body in bodies or ():
            present, value = body_column(body, 'locked')
            if present and not _flag_on(value):
                present, row_id = body_column(body, 'id')
                if present:
                    unlocking.add(str(_reference_value(row_id)))
    try:
        with conn.cursor() as cursor:
            if rows:
                locked = [entry for entry in resolve_locks(
                    cursor, table, 't.id IN %s' % _in_clause(len(rows)), rows,
                    authenticated_user)
                    if not (entry[1] == own_level and str(entry[0]) in unlocking)]
                if locked:
                    return _locked_response(table, locked, method)
            if parents:
                parent_table = _parent_of(table)[1]
                locked = resolve_locks(
                    cursor, parent_table,
                    't.id IN %s' % _in_clause(len(parents)), parents,
                    authenticated_user)
                if locked:
                    return _locked_response(parent_table, locked, method,
                                            adding=table)
    except pymysql.Error as exc:
        return _check_failed(method, exc)
    return None


def plan_lock_guard_delete(conn, table, where, params, authenticated_user,
                           method='DELETE'):
    """423 when a DELETE would remove an effectively locked plan-layer row
    (or a link/edge under a locked step), 500 when the check failed, else
    None. `where` names the deleting request's own filters against alias `t`
    — the keys have already been validated against `DESC` by the caller.

    A table in `_CASCADES_INTO` (req #3706) is asked whether any row it would
    delete is seated on a locked step, since the cascade would unlink it."""
    if authenticated_user is None:
        return None
    if table in _CASCADES_INTO:
        try:
            with conn.cursor() as cursor:
                seated = resolve_locked_seats(cursor, table, where, params,
                                              authenticated_user)
        except pymysql.Error as exc:
            return _check_failed(method, exc)
        return _seated_response(table, seated, method) if seated else None
    if table not in PLAN_LOCK:
        return None
    try:
        with conn.cursor() as cursor:
            locked = resolve_locks(cursor, table, where, params,
                                   authenticated_user)
            below = ([] if locked else
                     resolve_locked_below(cursor, table, where, params,
                                          authenticated_user))
    except pymysql.Error as exc:
        return _check_failed(method, exc)
    if locked:
        return _locked_response(table, locked, method)
    if below:
        return _locked_response(table, below, method, below=True)
    return None
