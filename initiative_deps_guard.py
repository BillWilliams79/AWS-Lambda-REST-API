"""initiative_deps_guard.py — an initiative edge must be SATISFIABLE (req #3823).

`initiative_deps` says "initiative B waits for all of initiative A", and the
derivation (`pipeline2_derive.py`) turns it into a GATE: no epic under B is
announced while any epic under A holds open work. Three edges can never be
satisfied, and each is refused here, before the INSERT, as a 409 CONFLICT
whose `message` the browser (`RestApi.jsx`) and darwin-mcp's client surface
verbatim:

  * a SELF edge (`initiative-self-dependency`);
  * an edge between two PLANS (`initiative-cross-plan`) — an initiative's
    plan is its containment, and a gate across plans would be read by no
    orchestrator that could release it;
  * an edge that closes a CYCLE on the GATE GRAPH (`initiative-cycle`):
    initiative edges and epic edges together, at EPIC granularity
    (`pipeline2_derive.gate_graph`). B->A plus an epic in A waiting on an epic
    in B is a deadlock under the default barrier (each holds the other while
    it holds open work). Epic edges that merely cross initiatives in both
    directions are not, when the epics they join are unrelated — lifting them
    to initiative pairs would refuse plans that are satisfiable.

The same combined-graph rule refuses the OTHER write that can close such a
cycle: an `epic_deps` POST whose edge crosses initiatives in the direction an
initiative edge forbids. So the outcome never depends on which edge was
written first. Anything that slips in another way — an epic or an initiative
MOVED under existing edges — is flagged by the derivation as an
`initiative-cycle` violation instead.

WHY HERE. The browser writes `initiative_deps` and `epic_deps` directly
through the generic POST, so a check in darwin-mcp would cover one of the two
writers — the reason `plan_lock.py` sits at the gateway too. The walk itself
is `pipeline2_derive.gate_graph` / `gate_path`, the one implementation the
derivation's violation report uses.

COST. Nothing for any other table. An `epic_deps` write costs one SELECT for
its epics and three light ones for the plan's graph; a plan with no
initiative edge is answered there and then. A PUT that re-points an initiative edge is refused outright (400): it
is added and removed, never edited. An epic edge MAY be re-pointed by its
owner (an established contract), so such a PUT is judged on the edge it
would leave, read from the stored row.
"""
import pymysql

from auth_utils import _reference_value, body_column
from pipeline2_derive import gate_cycle_text, gate_graph, gate_path, initiative_edge_cycle
from rest_api_utils import compose_rest_response, error_detail

_EDGE_COLUMNS = ('initiative_fk', 'dep_initiative_fk')


def _in_clause(n):
    return '(' + ', '.join(['%s'] * n) + ')'


def _conflict(table, rule, message, method):
    print('HTTP %s refused: %s' % (method, message))
    return compose_rest_response(409, '', {
        'error': 'CONFLICT', 'errno': None, 'constraint': rule,
        'table': table, 'message': message})


def _check_failed(method, exc):
    errno, detail = error_detail(exc)
    message = 'HTTP %s initiative dependency check failed: %s %s' % (method, errno, detail)
    print(message)
    return compose_rest_response(500, '', message)


def _pairs(bodies, first, second):
    """`[(int, int), ...]` for every body naming both columns, canonicalized by
    MySQL's integer grammar (`_reference_value`). Raises ValueError on an id
    MySQL would coerce. A body missing either column is MySQL's to refuse."""
    pairs = []
    for body in bodies or ():
        if not isinstance(body, dict):
            raise ValueError('body is not an object')
        a_present, a = body_column(body, first)
        b_present, b = body_column(body, second)
        if not (a_present and b_present):
            continue
        a, b = _reference_value(a), _reference_value(b)
        if a is None or b is None:
            continue
        pairs.append((int(a), int(b)))
    return pairs


def _rows(cursor):
    out = []
    for row in cursor.fetchall():
        out.append(tuple(row.values()) if isinstance(row, dict) else tuple(row))
    return out


def _plan_graph(cursor, pipeline_ids, authenticated_user):
    """`(initiative_edges, epic_initiative, epic_edges)` for the plans named:
    every initiative edge, every epic's initiative, every epic edge as
    `(id, waiter, waited-on)`. Three light SELECTs, ids only."""
    marks = _in_clause(len(pipeline_ids))
    params = tuple(pipeline_ids) + (authenticated_user,)
    cursor.execute(
        'SELECT d.initiative_fk, d.dep_initiative_fk FROM initiative_deps d '
        'JOIN initiatives i ON i.id = d.initiative_fk '
        'WHERE i.pipeline_fk IN %s AND i.creator_fk = %%s' % marks, params)
    initiative_edges = _rows(cursor)
    cursor.execute(
        'SELECT s.id, s.initiative_fk FROM epics s '
        'JOIN initiatives i ON i.id = s.initiative_fk '
        'WHERE i.pipeline_fk IN %s AND i.creator_fk = %%s' % marks, params)
    epic_initiative = dict(_rows(cursor))
    cursor.execute(
        'SELECT d.id, d.epic_fk, d.dep_epic_fk FROM epic_deps d '
        'JOIN epics s ON s.id = d.epic_fk JOIN initiatives i ON i.id = s.initiative_fk '
        'WHERE i.pipeline_fk IN %s AND i.creator_fk = %%s' % marks, params)
    epic_edges = _rows(cursor)
    return initiative_edges, epic_initiative, epic_edges


def _guard_initiative_edges(conn, table, bodies, authenticated_user, method):
    if method == 'PUT':
        for body in bodies or ():
            if isinstance(body, dict) and any(body_column(body, c)[0] for c in _EDGE_COLUMNS):
                return compose_rest_response(
                    400, '', 'an initiative dependency is added and removed, '
                    'never re-pointed — DELETE the edge and POST the new one')
        return None
    try:
        pairs = _pairs(bodies, *_EDGE_COLUMNS)
    except ValueError:
        return compose_rest_response(400, '', 'BAD REQUEST')
    if not pairs:
        return None
    for waiter, dep in pairs:
        if waiter == dep:
            return _conflict(table, 'initiative-self-dependency',
                             'initiative %s cannot depend on itself' % waiter, method)
    named = sorted({i for pair in pairs for i in pair})
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT id, pipeline_fk FROM initiatives WHERE id IN %s '
                'AND creator_fk = %%s' % _in_clause(len(named)),
                tuple(named) + (authenticated_user,))
            plan_of = dict(_rows(cursor))
            # An initiative that is absent or not the caller's is the ownership
            # guard's (403) or the FK's (409/1452) to answer — never ours.
            for waiter, dep in pairs:
                if waiter in plan_of and dep in plan_of and plan_of[waiter] != plan_of[dep]:
                    return _conflict(
                        table, 'initiative-cross-plan',
                        'initiative %s (pipeline %s) cannot depend on initiative %s '
                        '(pipeline %s): an initiative dependency never crosses a plan'
                        % (waiter, plan_of[waiter], dep, plan_of[dep]), method)
            plans = sorted({plan_of[i] for i in named if i in plan_of})
            if not plans:
                return None
            initiative_edges, epic_initiative, epic_edges = _plan_graph(
                cursor, plans, authenticated_user)
    except pymysql.Error as exc:
        return _check_failed(method, exc)
    adj = gate_graph(list(initiative_edges) + list(pairs),
                     [(a, b) for _id, a, b in epic_edges], epic_initiative)
    for waiter, dep in pairs:
        cycle = initiative_edge_cycle(adj, waiter, dep, epic_initiative)
        if cycle is not None:
            return _conflict(
                table, 'initiative-cycle',
                'initiative %s cannot depend on initiative %s: %s would wait for each '
                'other forever' % (waiter, dep, gate_cycle_text(cycle)), method)
    return None


def _repointed_pairs(cursor, bodies, authenticated_user):
    """A PUT on `epic_deps` that names `epic_fk` or `dep_epic_fk` RE-POINTS an
    edge (owners may move their own edges — the junction-scoping suite pins
    it). The edges it would leave: `([(a, b), ...], {replaced edge ids})`, the
    column the body does not name taken from the stored row."""
    wanted = {}
    for body in bodies or ():
        if not isinstance(body, dict):
            raise ValueError('body is not an object')
        names = {c: body_column(body, c) for c in ('epic_fk', 'dep_epic_fk')}
        if not any(present for present, _v in names.values()):
            continue
        present, row_id = body_column(body, 'id')
        row_id = _reference_value(row_id) if present else None
        if row_id is None:
            continue
        wanted[int(row_id)] = {c: _reference_value(v) for c, (p, v) in names.items() if p}
    if not wanted:
        return [], set()
    cursor.execute(
        'SELECT d.id, d.epic_fk, d.dep_epic_fk FROM epic_deps d JOIN epics s ON s.id = d.epic_fk '
        'WHERE d.id IN %s AND s.creator_fk = %%s' % _in_clause(len(wanted)),
        tuple(sorted(wanted)) + (authenticated_user,))
    pairs, replaced = [], set()
    for row_id, a, b in _rows(cursor):
        change = wanted.get(row_id) or {}
        a = int(change['epic_fk']) if change.get('epic_fk') is not None else a
        b = int(change['dep_epic_fk']) if change.get('dep_epic_fk') is not None else b
        pairs.append((a, b))
        replaced.add(row_id)
    return pairs, replaced


def _guard_epic_edges(conn, table, bodies, authenticated_user, method):
    replaced = set()
    try:
        if method == 'PUT':
            with conn.cursor() as cursor:
                pairs, replaced = _repointed_pairs(cursor, bodies, authenticated_user)
        else:
            pairs = _pairs(bodies, 'epic_fk', 'dep_epic_fk')
    except ValueError:
        return compose_rest_response(400, '', 'BAD REQUEST')
    except pymysql.Error as exc:
        return _check_failed(method, exc)
    if not pairs:
        return None
    named = sorted({i for pair in pairs for i in pair})
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT s.id, s.initiative_fk, i.pipeline_fk FROM epics s '
                'JOIN initiatives i ON i.id = s.initiative_fk '
                'WHERE s.id IN %s AND s.creator_fk = %%s' % _in_clause(len(named)),
                tuple(named) + (authenticated_user,))
            where = {row[0]: (row[1], row[2]) for row in _rows(cursor)}
            # EVERY pair, not only those crossing initiatives: an edge inside
            # one initiative can close a gate cycle too (a->b in X, b waits on
            # an epic of V, V waits for Y, Y's epic waits on a — code review,
            # req #3823). Pairs naming an epic that is absent or not the
            # caller's are the ownership guard's or the FK's to answer.
            checked = [(a, b) for a, b in pairs if a in where and b in where]
            if not checked:
                return None
            plans = sorted({where[a][1] for a, _ in checked})
            initiative_edges, epic_initiative, epic_edges = _plan_graph(
                cursor, plans, authenticated_user)
    except pymysql.Error as exc:
        return _check_failed(method, exc)
    if not initiative_edges:
        return None
    # A re-pointed edge leaves its old place: judge the graph without it.
    kept = [(a, b) for edge_id, a, b in epic_edges if edge_id not in replaced]
    adj = gate_graph(initiative_edges, kept + list(pairs), epic_initiative)
    for a, b in checked:
        back = gate_path(adj, [('e', b)], ('e', a), need_gate=True)
        if back is not None:
            return _conflict(
                table, 'initiative-cycle',
                'epic %s cannot depend on epic %s: through an initiative dependency, '
                '%s would wait for each other forever — remove that initiative '
                'dependency first' % (a, b, gate_cycle_text([('e', a)] + back)), method)
    return None


def initiative_deps_guard(conn, table, bodies, authenticated_user, method):
    """409 when a write would add an unsatisfiable initiative dependency (or an
    epic edge contradicting one), 400 on an uncanonical id or a re-pointing
    PUT, 500 when the check failed, else None. Hooked after
    `plan_lock_guard` in rest_post (single and bulk) and rest_put."""
    if authenticated_user is None:
        return None
    if table == 'initiative_deps':
        return _guard_initiative_edges(conn, table, bodies, authenticated_user, method)
    if table == 'epic_deps':
        return _guard_epic_edges(conn, table, bodies, authenticated_user, method)
    return None
