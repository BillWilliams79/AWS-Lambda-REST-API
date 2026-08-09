"""Pipeline 2.0 — the composing route (req #3367, remediation B, composing
form: `memory/pipeline-2-orchestration-algorithm.md` § 8).

The ONE non-generic Lambda-Rest route over the `pipeline2_*` tables. Where the
generic gateway (`rest_get_table.py`) answers one table per round trip,
this module answers the WHOLE composed plan read in one Lambda invocation —
several SQL SELECTs over an already-open connection, never a second Lambda
call — because "no JOIN" is a property of the generic table gateway, not of
Lambda-Rest itself.

Mirrors `darwin-mcp/services/pipelines2.py`'s (pre-#3367) `get_pipeline2_composed`
/ `get_pipeline2_epic_composed` read shape and tier-skip logic EXACTLY, so the
payload this emits is what those functions used to build by hand over six
gateway round trips — byte-compatible, so a consumer cannot tell which
produced it. That module is now a ONE-CALL passthrough to this route.

    {pipeline, epics[], steps[], step_requirements[], step_deps[],
     requirements[], derived{}}

`pipeline2_derive.derive_plan2` (moved here from darwin-mcp by this same
requirement — see that module's docstring) computes `derived`. A deriver
exception must never take the real rows down with it, so it degrades to a
WITHHELD stub exactly as darwin-mcp's `_derive` guard did.

Scoping mirrors what the generic gateway already does for every read of a
`CREATOR_FK_TABLES` table (`rest_get_table.py`): every `pipeline2_pipelines` /
`pipeline2_epics` / `pipeline2_steps` / `requirements` SELECT carries
`creator_fk = %s` explicitly, not merely inherited through containment — the
same defense-in-depth the generic gateway gave for free, replicated by hand
because this route bypasses it. `pipeline2_step_requirements` and
`pipeline2_step_deps` carry no `creator_fk` (JUNCTION_OWNERSHIP, req #3122) —
scoped by narrowing to the already-scoped `step_fk` ids fetched above them,
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
# compose step into Lambda does not change that ceiling, it just moves who
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
        step = size + (2 if kept else 0)
        if used + step > allowance:
            break
        used += step
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


def _derive(model, *, epic_scoped=False):
    try:
        return pipeline2_derive.derive_plan2(model, epic_scoped=epic_scoped)
    except Exception as e:                                 # noqa: BLE001
        print(f"pipeline2_derive.derive_plan2 failed: {e}")
        return withheld(
            WITHHELD_DERIVATION_FAILED, rows_complete=True,
            message=(f"the 2.0 derivation raised {e!r}. The rows above are "
                     "intact and complete; only the derived answers are "
                     "absent. Do not sequence or launch from this response."))


def _bounded(uri, composed, *, epic_scoped=False):
    """The THREE-REGIME budget ladder — byte-identical logic to darwin-mcp's
    (pre-#3367) `server._bounded_plan2`. See that function's (moved) docstring
    reasoning in the git history; restated briefly here:

    Regime A — whole payload fits, `derived` included. Ship it.
    Regime B — does not fit; withholding `derived` alone is enough. Every row
        survives; `derived` becomes `budget_derived_only`, `rows_complete=True`.
    Regime C — does not fit even without `derived`. `steps` is truncated
        against the allowance regime B's absence actually buys, `step_requirements`
        / `step_deps` are pruned to the surviving step ids, `_truncated` is
        hoisted to the top level, and `derived` becomes `budget_rows_truncated`,
        `rows_complete=False` — a hard stop.
    """
    if not composed.get('steps'):
        return composed

    escape_hatch = (
        "" if epic_scoped else
        " Read the epic-scoped route for a smaller, complete slice of one "
        "epic if you need `derived` for it.")
    count_field = "`epics[0].step_count`" if epic_scoped else "`pipeline.step_count`"

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

    hint = (f"a step's `notes` is uncapped TEXT; trim the evidence prose."
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
            "(req #3078) even with `derived` withheld, so `steps` was "
            "truncated. The dependency graph in this payload is INCOMPLETE — "
            f"read `_truncated` and {count_field} for the shortfall, and do "
            "not sequence or launch from this response."))
    others = {k: v for k, v in with_stub.items() if k != 'steps'}
    others['derived'] = regime_c_derived
    remaining = PAYLOAD_BUDGET_BYTES - payload_bytes(others)

    bounded = truncate_to_budget(composed['steps'], resource=uri,
                                 budget=max(remaining, 0), hint=hint)
    reserve = payload_bytes({TRUNCATION_KEY: marker_of(bounded)}) + 2
    bounded = truncate_to_budget(composed['steps'], resource=uri,
                                 budget=max(remaining - reserve, 0), hint=hint)

    kept = {step['id'] for step in bounded if TRUNCATION_KEY not in step}
    out = dict(with_stub)
    out['steps'] = bounded
    out[TRUNCATION_KEY] = marker_of(bounded)
    out['step_requirements'] = [
        row for row in composed['step_requirements'] if row['step_fk'] in kept]
    out['step_deps'] = [
        row for row in composed['step_deps']
        if row['step_fk'] in kept and row.get('dep_step_fk') in kept]
    out['derived'] = regime_c_derived
    return out


# ---------------------------------------------------------------------------
# Column projections — byte-identical to darwin-mcp's (pre-#3367) `pipelines2.py`
# ---------------------------------------------------------------------------

_PIPELINE_COLUMNS = ('id', 'title', 'description', 'pipeline_status',
                     'execution_mode', 'machine_fk', 'creator_fk',
                     'started_at', 'completed_at', 'create_ts', 'update_ts')
_EPIC_COLUMNS = ('id', 'pipeline_fk', 'title', 'description', 'epic_status',
                 'sort_order', 'category_fk', 'closed')
_STEP_COLUMNS = ('id', 'epic_fk', 'title', 'run', 'not_before', 'notes',
                 'completed_at', 'creator_fk', 'create_ts', 'update_ts')
_LINK_COLUMNS = ('step_fk', 'requirement_fk')
_DEP_COLUMNS = ('id', 'step_fk', 'dep_step_fk')
_REQUIREMENT_COLUMNS = ('id', 'title', 'requirement_status', 'coordination_type',
                        'ai_model', 'effort', 'machine_fk', 'tracking')


def _select(cursor, columns, table, where, params, order_by=None):
    cols = ', '.join(columns)
    sql = f"SELECT {cols} FROM {table} WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    cursor.execute(sql, params)
    return [_json_safe(row) for row in cursor.fetchall()]


def _in_clause(n):
    return '(' + ','.join(['%s'] * n) + ')'


# ---------------------------------------------------------------------------
# The two composed reads
# ---------------------------------------------------------------------------

def compose_pipeline2(conn, pipeline_id, authenticated_user):
    """THE whole-plan composed render. Returns None when not found (or not
    owned by `authenticated_user`) — the caller answers 404."""
    with conn.cursor(pymysql.cursors.DictCursor) as cursor:
        pipelines = _select(cursor, _PIPELINE_COLUMNS, 'pipeline2_pipelines',
                            'id = %s AND creator_fk = %s',
                            (pipeline_id, authenticated_user))               # read 1
        if not pipelines:
            return None
        pipeline = pipelines[0]

        epics = _select(cursor, _EPIC_COLUMNS, 'pipeline2_epics',
                        'pipeline_fk = %s AND creator_fk = %s',
                        (pipeline_id, authenticated_user), order_by='id ASC')  # read 2

        steps = []
        if epics:
            epic_ids = sorted(e['id'] for e in epics)
            steps = _select(
                cursor, _STEP_COLUMNS, 'pipeline2_steps',
                f'epic_fk IN {_in_clause(len(epic_ids))} AND creator_fk = %s',
                tuple(epic_ids) + (authenticated_user,), order_by='id ASC')    # read 3
        pipeline['step_count'] = len(steps)

        links, deps = [], []
        if steps:
            step_ids = sorted(s['id'] for s in steps)
            in_clause = _in_clause(len(step_ids))
            links = _select(cursor, _LINK_COLUMNS, 'pipeline2_step_requirements',
                            f'step_fk IN {in_clause}', tuple(step_ids),
                            order_by='step_fk ASC, requirement_fk ASC')       # read 4
            deps = _select(cursor, _DEP_COLUMNS, 'pipeline2_step_deps',
                           f'step_fk IN {in_clause}', tuple(step_ids),
                           order_by='step_fk ASC, id ASC')                    # read 5

        requirements = []
        requirement_ids = sorted({link['requirement_fk'] for link in links})
        if requirement_ids:
            requirements = _select(
                cursor, _REQUIREMENT_COLUMNS, 'requirements',
                f"id IN {_in_clause(len(requirement_ids))} AND creator_fk = %s",
                tuple(requirement_ids) + (authenticated_user,), order_by='id ASC')  # read 6

    model = {
        'pipeline': pipeline, 'epics': epics, 'steps': steps,
        'step_requirements': links, 'step_deps': deps,
        'requirements': requirements,
    }
    model['derived'] = _derive(model)
    # `uri` only ever surfaces inside a truncation marker's `resource` field
    # (regime C, `_bounded`) — nothing parses it. It is the ROUTE's own
    # identifier, not `darwin://pipeline2/{id}`: this payload now serves the
    # browser directly as well as the daemon, and the browser has no
    # `darwin://` scheme to make sense of. A daemon-only diagnostic string
    # would be a false fidelity, not a real one.
    return _bounded(f"pipeline2_compose/{pipeline_id}", model)


def compose_pipeline2_epic(conn, epic_id, authenticated_user):
    """THE epic-scoped composed render. Same shape, narrowed to one epic —
    six reads, not five, because the epic's own row AND the pipeline's own
    row are both required (two independent pause scopes). Returns None when
    not found / not owned."""
    with conn.cursor(pymysql.cursors.DictCursor) as cursor:
        epics = _select(cursor, _EPIC_COLUMNS, 'pipeline2_epics',
                        'id = %s AND creator_fk = %s',
                        (epic_id, authenticated_user))                        # read 1
        if not epics:
            return None
        epic = epics[0]

        pipelines = _select(cursor, _PIPELINE_COLUMNS, 'pipeline2_pipelines',
                            'id = %s AND creator_fk = %s',
                            (epic['pipeline_fk'], authenticated_user))        # read 2
        if not pipelines:
            raise ValueError(
                f"Pipeline2 epic {epic_id} names pipeline_fk="
                f"{epic['pipeline_fk']!r}, which does not resolve for this "
                "creator. Data integrity issue — report it.")
        pipeline = pipelines[0]

        steps = _select(cursor, _STEP_COLUMNS, 'pipeline2_steps',
                        'epic_fk = %s AND creator_fk = %s',
                        (epic_id, authenticated_user), order_by='id ASC')     # read 3
        epic['step_count'] = len(steps)

        links, deps = [], []
        if steps:
            step_ids = sorted(s['id'] for s in steps)
            in_clause = _in_clause(len(step_ids))
            links = _select(cursor, _LINK_COLUMNS, 'pipeline2_step_requirements',
                            f'step_fk IN {in_clause}', tuple(step_ids),
                            order_by='step_fk ASC, requirement_fk ASC')       # read 4
            deps = _select(cursor, _DEP_COLUMNS, 'pipeline2_step_deps',
                           f'step_fk IN {in_clause}', tuple(step_ids),
                           order_by='step_fk ASC, id ASC')                    # read 5

        requirements = []
        requirement_ids = sorted({link['requirement_fk'] for link in links})
        if requirement_ids:
            requirements = _select(
                cursor, _REQUIREMENT_COLUMNS, 'requirements',
                f"id IN {_in_clause(len(requirement_ids))} AND creator_fk = %s",
                tuple(requirement_ids) + (authenticated_user,), order_by='id ASC')  # read 6

    model = {
        'pipeline': pipeline, 'epics': [epic], 'steps': steps,
        'step_requirements': links, 'step_deps': deps,
        'requirements': requirements,
    }
    model['derived'] = _derive(model, epic_scoped=True)
    return _bounded(f"pipeline2_compose_epic/{epic_id}", model, epic_scoped=True)
