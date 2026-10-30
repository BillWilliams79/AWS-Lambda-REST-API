"""Pipeline 2.0 — the composing route (req #3367, remediation B, composing
form: `memory/pipeline-2-orchestration-algorithm.md` § 8).

The ONE non-generic Lambda-Rest route over the `pipeline2_*` tables. Where the
generic gateway (`rest_get_table.py`) answers one table per round trip,
this module answers the WHOLE composed plan read in one Lambda invocation —
several SQL SELECTs over an already-open connection, never a second Lambda
call — because "no JOIN" is a property of the generic table gateway, not of
Lambda-Rest itself.

Mirrors `darwin-mcp/services/pipelines2.py`'s (pre-#3367) `get_pipeline2_composed`
/ `get_pipeline2_initiative_composed` read shape and tier-skip logic EXACTLY, so the
payload this emits is what those functions used to build by hand over six
gateway round trips — byte-compatible, so a consumer cannot tell which
produced it. That module is now a ONE-CALL passthrough to this route.

    {pipeline, initiatives[], initiative_deps[], epics[], epic_requirements[],
     epic_deps[], requirements[], derived{}}

`initiative_deps[]` (req #3823) is the WHOLE PLAN's initiative-to-initiative
edges on both reads — a handful of rows, and the initiative-scoped
derivation needs every one of them to walk the gate transitively.

`pipeline2_derive.derive_plan2` (moved here from darwin-mcp by this same
requirement — see that module's docstring) computes `derived`. A deriver
exception must never take the real rows down with it, so it degrades to a
WITHHELD stub exactly as darwin-mcp's `_derive` guard did.

Scoping mirrors what the generic gateway already does for every read of a
`CREATOR_FK_TABLES` table (`rest_get_table.py`): every `pipelines` /
`initiatives` / `epics` / `requirements` SELECT carries
`creator_fk = %s` explicitly, not merely inherited through containment — the
same defense-in-depth the generic gateway gave for free, replicated by hand
because this route bypasses it. `epic_requirements` and
`epic_deps` carry no `creator_fk` (JUNCTION_OWNERSHIP, req #3122) —
scoped by narrowing to the already-scoped `epic_fk` ids fetched above them,
exactly as the daemon's own composed read did.
"""

import json
from datetime import date, datetime
from decimal import Decimal

import pymysql

import pipeline2_derive

# ---------------------------------------------------------------------------
# The budget ladder (req #3345 deliverable 4 / #3367 deliverable 3) — ported
# from darwin-mcp/services/common.py. This route is now THE PRODUCER of the
# composed payload, so the same three-regime ladder that used to run in the
# daemon (`server._bounded_plan2`) has to run here instead: the payload this
# emits is subject to the identical API Gateway / Lambda response cap the
# daemon's own outbound calls were always subject to (req #3078) — moving the
# compose epic into Lambda does not change that ceiling, it just moves who
# has to respect it.
# ---------------------------------------------------------------------------

PAYLOAD_BUDGET_BYTES = 3_000_000
TRUNCATION_KEY = '_truncated'

WITHHELD_DERIVATION_FAILED = 'derivation_failed'
WITHHELD_BUDGET_DERIVED_ONLY = 'budget_derived_only'
WITHHELD_BUDGET_ROWS_TRUNCATED = 'budget_rows_truncated'


def _json_safe(value):
    """Recursively convert DB-native values (datetime, Decimal) to the exact
    shape darwin-mcp's `json_default` used to serialize them as, so a
    passthrough consumer forwards these bytes unchanged (req #3367's own
    byte-compatibility acceptance criterion)."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def payload_bytes(data):
    return len(json.dumps(data))


def truncate_to_budget(rows, *, resource, budget=PAYLOAD_BUDGET_BYTES, hint=None):
    """Byte-identical algorithm to `services.common.truncate_to_budget` — see
    that function's docstring for the reasoning. `rows` must already be
    JSON-safe (this module always converts before calling it)."""
    if not isinstance(rows, list):
        raise TypeError(f"truncate_to_budget expects a list, got {type(rows)}")

    total = len(rows)
    sizes = [payload_bytes(row) for row in rows]
    prefix = [0]
    for size in sizes:
        prefix.append(prefix[-1] + size)
    if 2 + prefix[total] + 2 * max(0, total - 1) <= budget:
        return rows

    def build(kept):
        return {TRUNCATION_KEY: {
            'resource': resource,
            'returned': kept,
            'total': total,
            'omitted': total - kept,
            'budget_bytes': budget,
            'reason': f"payload exceeded the {budget:,}-byte MCP list-read budget "
                      f"(req #3078); the first {kept} of {total} rows are returned "
                      "in this resource's own order",
            'hint': hint or "narrow the read with a filtered resource, or fetch a "
                            "single row by id for full detail",
        }}

    def payload_size(kept):
        return 2 + prefix[kept] + 2 * kept + payload_bytes(build(kept))

    allowance = budget - max(payload_bytes(build(0)),
                             payload_bytes(build(total))) - 2
    used, kept = 2, 0
    for size in sizes:
        epic = size + (2 if kept else 0)
        if used + epic > allowance:
            break
        used += epic
        kept += 1

    while kept > 0 and payload_size(kept) > budget:
        kept -= 1

    return rows[:kept] + [build(kept)]


def withheld(reason_code, *, rows_complete, message):
    return {
        'withheld': True,
        'withheld_reason': reason_code,
        'rows_complete': rows_complete,
        'reason': message,
    }


def _derive(model, *, initiative_scoped=False):
    try:
        return pipeline2_derive.derive_plan2(model, initiative_scoped=initiative_scoped)
    except Exception as e:                                 # noqa: BLE001
        print(f"pipeline2_derive.derive_plan2 failed: {e}")
        return withheld(
            WITHHELD_DERIVATION_FAILED, rows_complete=True,
            message=(f"the 2.0 derivation raised {e!r}. The rows above are "
                     "intact and complete; only the derived answers are "
                     "absent. Do not sequence or launch from this response."))


def _bounded(uri, composed, *, initiative_scoped=False):
    """The THREE-REGIME budget ladder — byte-identical logic to darwin-mcp's
    (pre-#3367) `server._bounded_plan2`. See that function's (moved) docstring
    reasoning in the git history; restated briefly here:

    Regime A — whole payload fits, `derived` included. Ship it.
    Regime B — does not fit; withholding `derived` alone is enough. Every row
        survives; `derived` becomes `budget_derived_only`, `rows_complete=True`.
    Regime C — does not fit even without `derived`. `epics` is truncated
        against the allowance regime B's absence actually buys, `epic_requirements`
        / `epic_deps` are pruned to the surviving epic ids, `_truncated` is
        hoisted to the top level, and `derived` becomes `budget_rows_truncated`,
        `rows_complete=False` — a hard stop.
    """
    if not composed.get('epics'):
        return composed

    escape_hatch = (
        "" if initiative_scoped else
        " Read the initiative-scoped route for a smaller, complete slice of one "
        "initiative if you need `derived` for it.")
    count_field = "`initiatives[0].epic_count`" if initiative_scoped else "`pipeline.epic_count`"

    if payload_bytes(composed) <= PAYLOAD_BUDGET_BYTES:
        return composed

    with_stub = dict(composed)
    with_stub['derived'] = withheld(
        WITHHELD_BUDGET_DERIVED_ONLY, rows_complete=True,
        message=(
            f"the payload exceeded the {PAYLOAD_BUDGET_BYTES:,}-byte MCP budget "
            "(req #3078) with `derived` included. Every row above is present "
            f"and complete — only the convenience block was withheld to fit."
            f"{escape_hatch}"))
    if payload_bytes(with_stub) <= PAYLOAD_BUDGET_BYTES:
        return with_stub

    hint = (f"an epic's `notes` is uncapped TEXT; trim the evidence prose."
            f"{escape_hatch} {count_field} still reports the true total for "
            "what was requested.")

    def marker_of(rows):
        return next((row[TRUNCATION_KEY] for row in rows
                     if TRUNCATION_KEY in row), None)

    # Budget `remaining` against the REGIME-C derived block — the one that
    # actually ships below — never against regime B's. The two messages are
    # different lengths and there is no reason they would stay in a
    # particular order relative to each other; measuring against whichever
    # one is NOT shipped is exactly the "a few bytes apart" approximation
    # that flips silently the next time either message's wording changes.
    regime_c_derived = withheld(
        WITHHELD_BUDGET_ROWS_TRUNCATED, rows_complete=False,
        message=(
            f"the payload exceeded the {PAYLOAD_BUDGET_BYTES:,}-byte MCP budget "
            "(req #3078) even with `derived` withheld, so `epics` was "
            "truncated. The dependency graph in this payload is INCOMPLETE — "
            f"read `_truncated` and {count_field} for the shortfall, and do "
            "not sequence or launch from this response."))
    others = {k: v for k, v in with_stub.items() if k != 'epics'}
    others['derived'] = regime_c_derived
    remaining = PAYLOAD_BUDGET_BYTES - payload_bytes(others)

    bounded = truncate_to_budget(composed['epics'], resource=uri,
                                 budget=max(remaining, 0), hint=hint)
    reserve = payload_bytes({TRUNCATION_KEY: marker_of(bounded)}) + 2
    bounded = truncate_to_budget(composed['epics'], resource=uri,
                                 budget=max(remaining - reserve, 0), hint=hint)

    kept = {epic['id'] for epic in bounded if TRUNCATION_KEY not in epic}
    out = dict(with_stub)
    out['epics'] = bounded
    out[TRUNCATION_KEY] = marker_of(bounded)
    out['epic_requirements'] = [
        row for row in composed['epic_requirements'] if row['epic_fk'] in kept]
    out['epic_deps'] = [
        row for row in composed['epic_deps']
        if row['epic_fk'] in kept and row.get('dep_epic_fk') in kept]
    out['derived'] = regime_c_derived
    return out


# ---------------------------------------------------------------------------
# Column projections — byte-identical to darwin-mcp's (pre-#3367) `pipelines2.py`
# ---------------------------------------------------------------------------

_PIPELINE_COLUMNS = ('id', 'title', 'description', 'pipeline_status',
                     'locked', 'sort_order', 'machine_fk', 'creator_fk',
                     'started_at', 'completed_at', 'create_ts', 'update_ts')
_INITIATIVE_COLUMNS = ('id', 'pipeline_fk', 'title', 'description', 'initiative_status',
                 'locked', 'sort_order', 'category_fk', 'closed')
_EPIC_COLUMNS = ('id', 'initiative_fk', 'title', 'run', 'checkpoint', 'locked',
                 'not_before', 'notes', 'creator_fk',
                 'create_ts', 'update_ts')
# `sort_order` on the plan: req #3804 (migration 20261024230223). The plan's
# `closed` flag that migration added is no longer projected (req #3965) —
# `pipeline_status` alone feeds `pause_state`; the column itself is dormant
# until #3965's follow-on drops it.
# `checkpoint` and the three `locked` flags: req #3649 (migration
# 20261019100448). `checkpoint` feeds the derivation's hold walk; `locked` is
# carried so the view can draw the lock — the gateway (`plan_lock.py`) is what
# enforces it.
_LINK_COLUMNS = ('epic_fk', 'requirement_fk')
_DEP_COLUMNS = ('id', 'epic_fk', 'dep_epic_fk')
_INITIATIVE_DEP_COLUMNS = ('id', 'initiative_fk', 'dep_initiative_fk')
_REQUIREMENT_COLUMNS = ('id', 'title', 'requirement_status', 'coordination_type',
                        'ai_model', 'effort', 'machine_fk', 'tracking',
                        'started_at', 'completed_at', 'deferred_at')
# `deferred_at` added by req #3825: an epic card's END is the moment its last
# gating requirement closed, and `deferred` stamps `deferred_at` while clearing
# `completed_at` — without it an epic closed by a deferral has no end.
# `started_at`/`completed_at` added by req #3381's code review (2026-08-09),
# widening the light projection req #3345 originally specified. Without them
# the browser's `planTimeAxis` (Darwin/src/SwarmView/pipelines/
# pipelinePlanTime.js, unchanged by req #3367/#3381 — it still runs
# client-side, fed by this composed read) has no per-requirement start
# evidence at all: measured against the live payload before this fix, EVERY
# row's `requirementStart()` returned null, `epicStart()` collapsed to
# UNKNOWN/FUTURE for all 64 epics, and the plan visualizer's time axis fell
# back to two dead slots — the exact defect req #3201 was filed to remove,
# regressed by omission rather than by intent. Two more DATETIME columns on
# a read already fetching 101 rows costs no extra gateway round trip (the
# read count this whole route exists to fix is unchanged) and ~4KB on a
# payload well under the 3,000,000-byte budget.


def _select(cursor, columns, table, where, params, order_by=None):
    cols = ', '.join(columns)
    sql = f"SELECT {cols} FROM {table} WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    cursor.execute(sql, params)
    return [_json_safe(row) for row in cursor.fetchall()]


def _in_clause(n):
    return '(' + ','.join(['%s'] * n) + ')'


def _initiative_deps(cursor, initiative_ids):
    """The plan's initiative-to-initiative edges (req #3823): every edge whose
    WAITING side is one of `initiative_ids`, already scoped by `creator_fk`
    where they were read. One light SELECT; none for an empty plan."""
    if not initiative_ids:
        return []
    return _select(cursor, _INITIATIVE_DEP_COLUMNS, 'initiative_deps',
                   f"initiative_fk IN {_in_clause(len(initiative_ids))}",
                   tuple(sorted(initiative_ids)),
                   order_by='initiative_fk ASC, id ASC')


def _upstream_initiatives(initiative_id, edges):
    """Every initiative `initiative_id` waits for, transitively, over `edges`."""
    deps = pipeline2_derive.initiative_dep_map(edges)
    seen, stack = set(), list(deps.get(initiative_id) or [])
    while stack:
        dep = stack.pop()
        if dep in seen or dep == initiative_id:
            continue
        seen.add(dep)
        stack.extend(deps.get(dep) or [])
    return sorted(seen)


def _outside_seats(cursor, plan_graph, requirement_ids):
    """This initiative's requirements' seats on the plan's OTHER epics (req
    #3757) — what `seat_violations` needs to report a double seat across
    initiatives. One light SELECT, none when either side is empty; the outside
    epic ids are already scoped by `creator_fk` in `plan_graph`."""
    outside_ids = sorted(e['id'] for e in plan_graph.get('epics') or [])
    if not outside_ids or not requirement_ids:
        return []
    return _select(cursor, _LINK_COLUMNS, 'epic_requirements',
                   f"epic_fk IN {_in_clause(len(outside_ids))} "
                   f"AND requirement_fk IN {_in_clause(len(requirement_ids))}",
                   tuple(outside_ids) + tuple(requirement_ids))


def _work_evidence(cursor, requirements, authenticated_user):
    """Who is working each `development` requirement (req #3757) — the stall
    evidence `pipeline2_derive.stall_requirement_ids` reads, so the engine
    computes no stall of its own (rule R1). Two light SELECTs, same invocation,
    and none at all when nothing in the read is in `development`.

    Returns None when either read fails: the derivation then says
    `stall_evidence: unavailable` rather than reporting every unworked
    requirement as stalled — or none of them as fine. The rows feed the
    derivation and are dropped from the response, like `plan_graph`."""
    developing = [r['id'] for r in requirements
                  if r.get('requirement_status') == 'development']
    if not developing:
        return {'live_req_ids': [], 'primary_req_ids': []}
    refs = ['requirement:%d' % rid for rid in developing]
    statuses = pipeline2_derive.LIVE_SESSION_STATUSES
    try:
        sessions = _select(
            cursor, ('source_ref', 'swarm_status', 'terminal_window_id', 'terminal_number'),
            'swarm_sessions',
            f"creator_fk = %s AND swarm_status IN {_in_clause(len(statuses))} "
            f"AND source_ref IN {_in_clause(len(refs))}",
            (authenticated_user,) + tuple(statuses) + tuple(refs))
        tag = pipeline2_derive.PRIMARY_START_TAG + '%'
        starts = _select(
            cursor, ('id', 'arguments',
                     '(SELECT COUNT(*) FROM swarm_start_sessions l '
                     'WHERE l.swarm_start_fk = s.id) AS linked_session_count'),
            'swarm_starts s',
            # Every primary birth record, and every start after the oldest one
            # (a later start naming its requirement retires it).
            "s.creator_fk = %s AND s.id >= (SELECT COALESCE(MIN(p.id), 2147483647) "
            "FROM swarm_starts p WHERE p.creator_fk = %s AND TRIM(p.arguments) LIKE %s)",
            (authenticated_user, authenticated_user, tag), order_by='s.id ASC')
    except pymysql.Error as e:
        print(f"pipeline2_compose work evidence read failed: {e}")
        return None
    return pipeline2_derive.work_evidence(sessions, starts)


# ---------------------------------------------------------------------------
# The two composed reads
# ---------------------------------------------------------------------------

def compose_pipeline2(conn, pipeline_id, authenticated_user):
    """THE whole-plan composed render. Returns None when not found (or not
    owned by `authenticated_user`) — the caller answers 404."""
    with conn.cursor(pymysql.cursors.DictCursor) as cursor:
        pipelines = _select(cursor, _PIPELINE_COLUMNS, 'pipelines',
                            'id = %s AND creator_fk = %s',
                            (pipeline_id, authenticated_user))               # read 1
        if not pipelines:
            return None
        pipeline = pipelines[0]

        initiatives = _select(cursor, _INITIATIVE_COLUMNS, 'initiatives',
                        'pipeline_fk = %s AND creator_fk = %s',
                        (pipeline_id, authenticated_user), order_by='id ASC')  # read 2

        epics = []
        initiative_deps = _initiative_deps(
            cursor, [e['id'] for e in initiatives])                           # read 2b
        if initiatives:
            initiative_ids = sorted(e['id'] for e in initiatives)
            epics = _select(
                cursor, _EPIC_COLUMNS, 'epics',
                f'initiative_fk IN {_in_clause(len(initiative_ids))} AND creator_fk = %s',
                tuple(initiative_ids) + (authenticated_user,), order_by='id ASC')    # read 3
        pipeline['epic_count'] = len(epics)

        links, deps = [], []
        if epics:
            epic_ids = sorted(s['id'] for s in epics)
            in_clause = _in_clause(len(epic_ids))
            links = _select(cursor, _LINK_COLUMNS, 'epic_requirements',
                            f'epic_fk IN {in_clause}', tuple(epic_ids),
                            order_by='epic_fk ASC, requirement_fk ASC')       # read 4
            deps = _select(cursor, _DEP_COLUMNS, 'epic_deps',
                           f'epic_fk IN {in_clause}', tuple(epic_ids),
                           order_by='epic_fk ASC, id ASC')                    # read 5

        requirements = []
        requirement_ids = sorted({link['requirement_fk'] for link in links})
        if requirement_ids:
            requirements = _select(
                cursor, _REQUIREMENT_COLUMNS, 'requirements',
                f"id IN {_in_clause(len(requirement_ids))} AND creator_fk = %s",
                tuple(requirement_ids) + (authenticated_user,), order_by='id ASC')  # read 6
        evidence = _work_evidence(cursor, requirements, authenticated_user)

    model = {
        'pipeline': pipeline, 'initiatives': initiatives,
        'initiative_deps': initiative_deps, 'epics': epics,
        'epic_requirements': links, 'epic_deps': deps,
        'requirements': requirements, 'work_evidence': evidence,
    }
    model['derived'] = _derive(model)
    model.pop('work_evidence')
    # `uri` only ever surfaces inside a truncation marker's `resource` field
    # (regime C, `_bounded`) — nothing parses it. It is the ROUTE's own
    # identifier, not `darwin://pipeline2/{id}`: this payload now serves the
    # browser directly as well as the daemon, and the browser has no
    # `darwin://` scheme to make sense of. A daemon-only diagnostic string
    # would be a false fidelity, not a real one.
    return _bounded(f"pipeline2_compose/{pipeline_id}", model)


def compose_pipeline2_initiative(conn, initiative_id, authenticated_user):
    """THE initiative-scoped composed render. Same shape, narrowed to one initiative —
    six reads, not five, because the initiative's own row AND the pipeline's own
    row are both required (two independent pause scopes). Returns None when
    not found / not owned.

    PLUS UP TO FOUR LIGHT READS OF THE REST OF THE PLAN'S GRAPH (req #3597,
    the user's amendment: an epic closed by hand blocks everything downstream).
    A checkpoint in ANOTHER initiative must hold this initiative's epics exactly as a
    whole-plan read holds them, and only the plan's epic ids, checkpoint
    flags, dependency edges, links and requirement statuses can say where one
    is and whether it still holds open work. Same
    invocation, so still ONE gateway round trip; ids and timestamps only.
    The graph feeds the derivation and is then DROPPED — it is not part of
    the response shape."""
    with conn.cursor(pymysql.cursors.DictCursor) as cursor:
        initiatives = _select(cursor, _INITIATIVE_COLUMNS, 'initiatives',
                        'id = %s AND creator_fk = %s',
                        (initiative_id, authenticated_user))                        # read 1
        if not initiatives:
            return None
        initiative = initiatives[0]

        pipelines = _select(cursor, _PIPELINE_COLUMNS, 'pipelines',
                            'id = %s AND creator_fk = %s',
                            (initiative['pipeline_fk'], authenticated_user))        # read 2
        if not pipelines:
            raise ValueError(
                f"Pipeline2 initiative {initiative_id} names pipeline_fk="
                f"{initiative['pipeline_fk']!r}, which does not resolve for this "
                "creator. Data integrity issue — report it.")
        pipeline = pipelines[0]

        epics = _select(cursor, _EPIC_COLUMNS, 'epics',
                        'initiative_fk = %s AND creator_fk = %s',
                        (initiative_id, authenticated_user), order_by='id ASC')     # read 3
        initiative['epic_count'] = len(epics)

        links, deps = [], []
        if epics:
            epic_ids = sorted(s['id'] for s in epics)
            in_clause = _in_clause(len(epic_ids))
            links = _select(cursor, _LINK_COLUMNS, 'epic_requirements',
                            f'epic_fk IN {in_clause}', tuple(epic_ids),
                            order_by='epic_fk ASC, requirement_fk ASC')       # read 4
            deps = _select(cursor, _DEP_COLUMNS, 'epic_deps',
                           f'epic_fk IN {in_clause}', tuple(epic_ids),
                           order_by='epic_fk ASC, id ASC')                    # read 5

        requirements = []
        requirement_ids = sorted({link['requirement_fk'] for link in links})
        if requirement_ids:
            requirements = _select(
                cursor, _REQUIREMENT_COLUMNS, 'requirements',
                f"id IN {_in_clause(len(requirement_ids))} AND creator_fk = %s",
                tuple(requirement_ids) + (authenticated_user,), order_by='id ASC')  # read 6

        plan_initiative_ids = [row['id'] for row in _select(
            cursor, ('id',), 'initiatives', 'pipeline_fk = %s AND creator_fk = %s',
            (pipeline['id'], authenticated_user))]                            # read 6b
        initiative_deps = _initiative_deps(cursor, plan_initiative_ids)       # read 6c
        upstream = _upstream_initiatives(initiative_id, initiative_deps)
        plan_graph = _plan_graph_outside_initiative(cursor, pipeline['id'], initiative_id,
                                              authenticated_user, upstream)
        plan_graph['initiative_ids'] = plan_initiative_ids
        plan_graph['upstream_initiative_ids'] = upstream
        plan_graph['outside_seats'] = _outside_seats(cursor, plan_graph, requirement_ids)
        evidence = _work_evidence(cursor, requirements, authenticated_user)

    model = {
        'pipeline': pipeline, 'initiatives': [initiative],
        'initiative_deps': initiative_deps, 'epics': epics,
        'epic_requirements': links, 'epic_deps': deps,
        'requirements': requirements, 'plan_graph': plan_graph,
        'work_evidence': evidence,
    }
    model['derived'] = _derive(model, initiative_scoped=True)
    model.pop('plan_graph')
    model.pop('work_evidence')
    return _bounded(f"pipeline2_compose_initiative/{initiative_id}", model, initiative_scoped=True)


def _plan_graph_outside_initiative(cursor, pipeline_id, initiative_id, authenticated_user,
                                   upstream_initiative_ids=()):
    """The plan's epics OUTSIDE this initiative, as the derivation's checkpoint walk
    needs them (`pipeline2_derive.plan_graph_outside`). Reads 7-10, each
    skipped when the one before it finds nothing.

    req #3823 — every outside epic carries its `initiative_fk` (the combined
    graph lifts epic edges to initiative edges), and the links and requirement
    rows are read for the epics of every initiative this one WAITS FOR
    (`upstream_initiative_ids`) as well as for the checkpoints, so the
    initiative gate is answered by the same rule as a whole-plan read."""
    graph = {'epics': [], 'epic_deps': [], 'epic_requirements': [],
             'requirements': []}
    graph['epics'] = _select(
        cursor, ('id', 'initiative_fk', 'checkpoint'), 'epics',
        'initiative_fk IN (SELECT id FROM initiatives WHERE pipeline_fk = %s '
        'AND creator_fk = %s) AND initiative_fk <> %s AND creator_fk = %s',
        (pipeline_id, authenticated_user, initiative_id, authenticated_user),
        order_by='id ASC')                                                    # read 7
    if not graph['epics']:
        return graph
    ids = tuple(sorted(s['id'] for s in graph['epics']))
    in_clause = _in_clause(len(ids))
    graph['epic_deps'] = _select(cursor, ('epic_fk', 'dep_epic_fk'),
                                 'epic_deps', f'epic_fk IN {in_clause}',
                                 ids)                                         # read 8
    # Only a CHECKPOINT's open work matters to the walk (req #3649): a
    # non-checkpoint outside epic contributes its edges for traversal and
    # nothing else, so its links are not read — unless its initiative is one
    # this initiative waits for (req #3823), whose open work is the gate.
    upstream = set(upstream_initiative_ids or ())
    checkpoint_ids = tuple(sorted(s['id'] for s in graph['epics']
                                  if s.get('checkpoint')
                                  or s.get('initiative_fk') in upstream))
    if not checkpoint_ids:
        return graph
    graph['epic_requirements'] = _select(
        cursor, _LINK_COLUMNS, 'epic_requirements',
        f'epic_fk IN {_in_clause(len(checkpoint_ids))}', checkpoint_ids)     # read 9
    req_ids = sorted({link['requirement_fk']
                      for link in graph['epic_requirements']})
    if req_ids:
        # A checkpoint holds while any gating requirement is not terminal
        # (req #3750), so the derivation gets the rows
        # `open_requirement_ids` needs, not just the tracking ids.
        graph['requirements'] = _select(
            cursor, ('id', 'requirement_status', 'tracking'), 'requirements',
            f"id IN {_in_clause(len(req_ids))} AND creator_fk = %s",
            tuple(req_ids) + (authenticated_user,))                           # read 10
    return graph
