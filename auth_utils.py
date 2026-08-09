"""
Authentication utilities for Lambda-Rest.


Extracts the authenticated user identity from API Gateway Cognito authorizer
claims and defines how each table is scoped to that user. There are exactly
three answers to "WHOSE ROW IS THIS", and every table in the schema has one:

  * `CREATOR_FK_TABLES` — the table carries `creator_fk`; scoping is a column
    comparison.
  * `PROFILE_TABLE` — the row IS the user; scoping compares `id`.
  * `JUNCTION_OWNERSHIP` — the table carries NO `creator_fk`; scoping is DERIVED
    by joining through to the parent that owns the row (req #3122).

A table in none of the three is unscoped, which means every user's rows on every
verb. `tests/test_unit_junction_scoping.py` and darwin-mcp's
`test_validation_full.py` both fail if `schema.sql` grows one.

Owning the ROW is not the whole of authorization, which is what req #3125 adds.
A fourth registry, `CREATOR_TABLE_REFERENCES`, answers the separate question
"WHOSE ROW DOES THIS ROW POINT AT" for the tables in the first group. Scoping a
row to its creator says nothing about the rows it REFERENCES, and every one of
the three answers above is silent on that — which is the whole vulnerability.
"""

import re

# MySQL's integer grammar for a string cast to an INT column, and NOTHING WIDER.
# `[0-9]` is deliberate where `\d` would be shorter: Python's `\d` matches Unicode
# digit classes ('٩٨٢٥', '１９８２５') that MySQL reads as 0, and
# `str.isdigit()`/`isnumeric()` are Unicode-aware for the same reason.
_ASCII_INT_RE = re.compile(r'[+-]?[0-9]+')

# The whitespace MySQL skips ahead of a numeric cast — MEASURED, not assumed to
# be C `isspace`. It is space and tab and nothing else: `'\n9825'`, `'\r9825'`,
# `'\v9825'` and `'\f9825'` all store 0 in an INT column. Stripped explicitly
# rather than with a bare `str.strip()`, which additionally removes Unicode
# spaces (U+00A0 and friends) MySQL does not skip either.
_SQL_SPACE = ' \t'

# INT range. Outside it MySQL CLAMPS rather than rejects, so `'2147483648'` names
# row 2147483647 to the database while naming a different row to this check —
# the `'9825_0'` divergence in another costume. It fails closed today only
# because the highest parent id in either database is ~907k, which is a property
# of the DATA and nothing enforces it; an explicit-id insert or a seeded import
# could put a row at the boundary at any time.
_INT_MIN, _INT_MAX = -2 ** 31, 2 ** 31 - 1


# A MySQL identifier as `rest_post`/`rest_put` may safely interpolate one: the
# unquoted identifier charset and nothing else. See `check_body_keys` below for
# why a body key has to be held to it.
_PLAIN_IDENTIFIER_RE = re.compile(r'[A-Za-z0-9_$]+')


def check_body_keys(table, bodies):
    """`(status, message)` when a body's KEYS cannot be trusted, else None.

    A body's keys become SQL IDENTIFIERS: `rest_post` interpolates them into the
    INSERT column list and `rest_put` into the SET clause, raw. Every other check
    in this file then reads those same keys back out of the dict with
    `body.get('area_fk')` — an exact Python string match.
    **MySQL does not match column names that way, and the gap between the two is
    an authorization bypass** (req #3125; the same trick defeated req #3122's
    junction registry, which is why this is applied to every table rather than
    the registered ones).

    Measured against darwin_dev, every one of these wrote `tasks.area_fk` while
    `body.get('area_fk')` returned None, so the ownership guard saw no reference
    at all and waved the write through with a 200:

        {"AREA_FK": n}        column names are CASE-INSENSITIVE in MySQL
        {"Area_Fk": n}
        {"`area_fk`": n}      backticks are quoting syntax, stripped by the parser
        {"area_fk ": n}       trailing space is just token separation
        {"area_fk/*x*/": n}   an inline comment the parser removes

    The last one is why this is a CHARSET restriction and not a normalization
    routine: no amount of case-folding and stripping can enumerate everything
    MySQL's lexer discards, and each miss is silent. Constraining the key to
    `[A-Za-z0-9_$]+` leaves case as the only variance MySQL still has, which the
    callers of this module then handle explicitly.

    The second rule is the one a normalizer alone would have missed. Two keys
    that differ only in case name the SAME column, MySQL allows a column to be
    assigned twice in one UPDATE, and the LAST assignment wins:

        PUT [{"id": <mine>, "test_plan_fk": <my plan>,     <- the guard checks this
                            "TEST_PLAN_FK": <their plan>}] <- the SET clause applies this

    A guard that merely matched case-insensitively would look up whichever key it
    found first, approve, and green-light the opposite write. So a collision is
    refused outright rather than resolved — it is never a legitimate body.

    Nothing legitimate is lost: every column in `schema.sql` is
    `[a-z0-9_]`, and a key outside that charset could only ever have been a typo,
    a SQL error, or an injection attempt. `rest_delete` already holds its body
    keys to the real column list for exactly this reason (req #3122).
    """
    for body in bodies:
        if not isinstance(body, dict):
            return (400, 'BAD REQUEST')
        seen = {}
        for key in body:
            if not isinstance(key, str) or not _PLAIN_IDENTIFIER_RE.fullmatch(key):
                print(f"Auth: {table} write with a key that is not a plain column "
                      f"name: {key!r} — it would reach MySQL as an identifier "
                      "spelled differently from the one this gateway checked")
                return (400, 'BAD REQUEST')
            folded = key.lower()
            if folded in seen:
                print(f"Auth: {table} write naming the same column twice as "
                      f"{seen[folded]!r} and {key!r} — MySQL applies the last one, "
                      "so any check of the first would be meaningless")
                return (400, 'BAD REQUEST')
            seen[folded] = key
    return None


def body_column(body, column):
    """The value a body carries for `column`, matched the way MySQL matches it.

    Column names are case-insensitive, so `{"AREA_FK": 5}` names `area_fk`.
    `check_body_keys` has already refused any body where two keys could both
    match, so at most one can.

    Returns `(present, value)` rather than just the value: `None` is a meaningful
    VALUE here (SQL NULL) and must not be confused with "the caller did not
    mention this column", which on an UPDATE means *unchanged*.

    `column` is folded too. Every name in the registries is already lowercase, so
    this changes nothing today — but a helper whose whole job is "match a column
    name the way MySQL does" that then compared its OWN argument case-sensitively
    would be a trap set for exactly the bug it exists to prevent.
    """
    column = column.lower()
    if column in body:
        return True, body[column]
    for key, value in body.items():
        if isinstance(key, str) and key.lower() == column:
            return True, value
    return False, None


def force_column(body, column, value):
    """Set `column` to `value`, replacing whatever spelling the body used.

    `body['creator_fk'] = <sub>` alone is not enough. `PUT [{"id": <my task>,
    "CREATOR_FK": "<their sub>"}]` names the same column to MySQL but not to
    Python, so the override missed it, the `creator_fk = %s` predicate matched on
    the row's CURRENT owner, and the SET clause then handed the row to the victim
    — verified against darwin_dev, a row given away through a 200. On INSERT the
    same body instead produced MySQL 1110 ("column specified twice") as a 500,
    because the override ADDED a second spelling rather than replacing the first.
    """
    column = column.lower()
    for key in [k for k in body
                if isinstance(k, str) and k.lower() == column and k != column]:
        del body[key]
    body[column] = value


def get_authenticated_user(event):
    """Extract the user's sub (UUID) from API Gateway Cognito authorizer claims.

    Uses 'sub' because profiles.id = Cognito sub (set by Lambda-Cognito at signup).
    'cognito:username' can differ (e.g. email) and would cause FK violations.

    Returns the authenticated user's ID (str) or None if not present.
    """
    try:
        return event['requestContext']['authorizer']['claims']['sub']
    except (KeyError, TypeError):
        return None


# Tables that have a creator_fk column and must be scoped to the authenticated user
CREATOR_FK_TABLES = frozenset({
    'domains', 'areas', 'tasks',
    'projects', 'categories', 'requirements',
    'dev_servers', 'swarm_sessions', 'recurring_tasks',
    'map_routes', 'map_runs', 'map_views',
    'map_partners',
    'user_integrations',
    # Req #2380 — Swarm Features & Test Cases registry (migrations 042/043/044).
    # Missing entries here are a silent security gap: unauthenticated writes
    # to these tables would be accepted by the generic Lambda-Rest passthrough.
    'features', 'test_cases', 'test_plans', 'test_runs', 'test_results',
    # Req #2422 — swarm_start log (migration 046). swarm_start_sessions is a
    # junction table with no creator_fk and stays out of this set.
    'swarm_starts',
    # Req #2604 — Customer Release (migration 049). customers table carries
    # creator_fk; every CRUD must scope to the authenticated user.
    'customers',
    # Req #2606 — SQL-backed Build Visualizer data model (migration 050).
    # build_projects, branches, builds, customer_releases all carry creator_fk.
    'build_projects', 'branches', 'builds', 'customer_releases',
    # Req #2633 — Acceptance Tests (migration 061). acceptance_tests carries
    # creator_fk; branch_acceptance_tests is a junction (no creator_fk) and
    # stays out of this set.
    'acceptance_tests',
    # Req #2719 — swarm_undo log (migration 053).
    'swarm_undos',
    # Req #2497 — swarm_complete log. swarm_complete_sessions
    # is a junction table with no creator_fk and stays out of this set.
    'swarm_completes',
    # Req #2943 — machines registry. Carries creator_fk but was never added
    # here; caught by the req #2998 audit of this file.
    'machines',
    # Req #2997/#2998 — agents registry (migration 067). agents, instructions,
    # and architecture_documents each carry creator_fk. agent_documents and
    # agent_instructions are junctions with no creator_fk and stay out.
    'agents', 'instructions', 'architecture_documents',
    # Req #3031 — agent context telemetry (migration 069). Both the run header
    # and the per-agent rows carry creator_fk; scope generic passthrough to the
    # authenticated user.
    'agent_telemetry_runs', 'agent_telemetry_rows',
    # Req #3096 — per-document actual-token rows (migration 074). Carries
    # creator_fk like its parent row; scope generic passthrough the same way.
    'agent_telemetry_row_docs',
    # Req #3111 — Swarm Orchestration foundation (migration 076). epics,
    # pipelines and pipeline_steps each carry a NOT NULL creator_fk, so
    # membership here is not optional hardening — it is what makes the generic
    # passthrough work at all: rest_post injects creator_fk only for tables in
    # this set, so an unregistered table's INSERT fails outright (the column has
    # no default), and its GET would return every user's rows unscoped.
    #
    # pipeline_step_requirements and pipeline_step_deps stay OUT: neither has a
    # creator_fk. They inherit ownership from their step, the same call made for
    # every other junction (swarm_start_sessions, agent_documents, ...) — and
    # since req #3122 that inheritance is ENFORCED, in JUNCTION_OWNERSHIP below,
    # rather than merely asserted in a migration comment.
    'epics', 'pipelines', 'pipeline_steps',
    # Req #3224 — the durable orchestration reservation (migration
    # 20260801150404). Carries a NOT NULL creator_fk, so membership here is what
    # makes the generic passthrough work at all, exactly as for the #3111 three
    # above. It is also the security-relevant half of a COORDINATION table: an
    # unscoped LIST read would publish which machine and terminal every user is
    # orchestrating from, and an unscoped DELETE would let anyone release
    # somebody else's live reservation — which is not a leak but a way to make
    # two orchestrators believe they both hold a scope.
    'orchestration_claims',
    # Req #3337 — Pipeline 2.0 plan layer (migration 20260808115509). The
    # parallel-era images of epics/pipelines/pipeline_steps: each carries a NOT
    # NULL creator_fk, so membership here is what makes the generic passthrough
    # work at all, exactly as for the #3111 three above.
    #
    # pipeline2_step_requirements and pipeline2_step_deps stay OUT: neither has
    # a creator_fk. They inherit ownership from their step, in JUNCTION_OWNERSHIP
    # below.
    'pipeline2_pipelines', 'pipeline2_epics', 'pipeline2_steps',
})

PROFILE_TABLE = 'profiles'


# ---------------------------------------------------------------------------
# Junction / child-table ownership — authorization is DERIVED (req #3122)
# ---------------------------------------------------------------------------
#
# THE HOLE THIS CLOSES. Thirteen tables carry no `creator_fk`, so until this
# registry existed the generic passthrough applied NO scoping to any of them.
# Measured against the code as shipped by req #3113: `GET /darwin/
# pipeline_step_deps` returned every user's dependency edges; `PUT`/`DELETE`
# with another user's `id` fell into the unscoped `else` branch of rest_put /
# rest_delete and rewrote or deleted that user's gate; `POST` with a foreign
# `step_fk` injected a gate into their plan. Same shape on the other twelve.
#
# NOT "the first junction with a surrogate id". Req #3111 flagged
# `pipeline_step_deps` as the first junction whose rows are individually
# addressable by id. It is not — `map_run_partners` (id + UNIQUE(map_run_fk,
# map_partner_fk)) already was, and `map_coordinates` is a surrogate-id child
# table with the same exposure. The id made the hole EASIER TO REACH; it did not
# create it. **The unscoped LIST read was always the leak**, id or no id, and it
# is the reason this registry covers all thirteen rather than the two the
# requirement named.
#
# WHY DERIVE RATHER THAN ADD A `creator_fk` COLUMN. Migration 076 already states
# the rule in prose — "an edge is not independently owned; it inherits the step's
# ownership and dies with it" — and this makes the code say it. A `creator_fk`
# column would make ownership a second, STORABLE fact that can disagree with the
# parent's, which is precisely the failure req #3080 design rule 1 exists to
# prevent inside this very feature. MySQL cannot express "junction.creator_fk
# must equal parent.creator_fk", so that divergence would ship with no guard.
# Deriving also needs no DDL, no backfill, and no per-table migration ever again.
#
# THE SHAPE. `scope` is the column that carries ownership and the table it
# resolves through; it is always the FIRST key column — the parent the row
# BELONGS TO, not the one it points at. It becomes a predicate on every read,
# update and delete:
#
#     step_fk IN (SELECT id FROM pipeline_steps WHERE creator_fk = %s)
#
# `verify` names the OTHER parent references, checked on INSERT only. A write is
# refused when any of them names a row the caller does not own, which is what
# stops a caller wiring their own plan to somebody else's step or requirement.
# They are deliberately NOT read predicates: `dep_step_fk` is NULL on a
# wall-clock gate row, so ANDing it into a SELECT would hide those rows entirely.
#
# ADDING A TABLE. Every table without `creator_fk` belongs here — surrogate id or
# not, junction or child. A `verify` entry is only correct where the database
# already enforces the reference with a real FK; see `priority_card_order` below
# for the one place that rule bites.

JUNCTION_OWNERSHIP = {
    # Swarm Orchestration (req #3111 migration 076; MCP surface req #3113).
    # An edge and a requirement link both belong to their STEP.
    'pipeline_step_deps': {
        'scope': ('step_fk', 'pipeline_steps'),
        # A cross-tenant edge is not just a leak: `dep_step_fk` is ON DELETE
        # RESTRICT, so an edge pointing at somebody else's step would make THEIR
        # step undeletable — a denial of service on another user's plan edit.
        'verify': (('dep_step_fk', 'pipeline_steps'),),
    },
    'pipeline_step_requirements': {
        'scope': ('step_fk', 'pipeline_steps'),
        'verify': (('requirement_fk', 'requirements'),),
    },

    # Pipeline 2.0 plan layer (req #3337, migration 20260808115509). Identical
    # shape to the 1.0 pair above and for identical reasons. `dep_step_fk` needs
    # `verify` because it is ON DELETE RESTRICT: a cross-tenant edge would make
    # somebody else's step undeletable, a denial of service rather than merely a
    # leak.
    'pipeline2_step_deps': {
        'scope': ('step_fk', 'pipeline2_steps'),
        'verify': (('dep_step_fk', 'pipeline2_steps'),),
    },
    'pipeline2_step_requirements': {
        'scope': ('step_fk', 'pipeline2_steps'),
        'verify': (('requirement_fk', 'requirements'),),
    },

    # Swarm log junctions. `requirement_sessions` is the one whose old,
    # deliberately-unscoped behaviour was pinned by a test
    # (darwin-mcp/tests/test_gateway_write_scoping.py) with the note that it was
    # "a design question rather than changed here". This registry is that answer.
    'requirement_sessions': {
        'scope': ('requirement_fk', 'requirements'),
        'verify': (('session_fk', 'swarm_sessions'),),
    },
    'swarm_start_sessions': {
        'scope': ('swarm_start_fk', 'swarm_starts'),
        'verify': (('session_fk', 'swarm_sessions'),),
    },
    'swarm_complete_sessions': {
        'scope': ('swarm_complete_fk', 'swarm_completes'),
        'verify': (('session_fk', 'swarm_sessions'),),
    },

    # Features / test registry (req #2380, migrations 042-044).
    'feature_test_cases': {
        'scope': ('feature_fk', 'features'),
        'verify': (('test_case_fk', 'test_cases'),),
    },
    # Pipeline 2.0 Feature retirement — test cases re-home onto Requirement
    # (req #3352, migration 20260809002149). Stands beside `feature_test_cases`
    # above, not in its place, until req #3334's eradication sequencing.
    'requirement_test_cases': {
        'scope': ('requirement_fk', 'requirements'),
        'verify': (('test_case_fk', 'test_cases'),),
    },
    'test_plan_cases': {
        'scope': ('test_plan_fk', 'test_plans'),
        'verify': (('test_case_fk', 'test_cases'),),
    },

    # Build Visualizer acceptance tests (req #2633, migration 061). darwin_dev
    # only — production dropped these tables in migration 057.
    'branch_acceptance_tests': {
        'scope': ('branch_fk', 'branches'),
        'verify': (('acceptance_test_fk', 'acceptance_tests'),),
    },

    # Agents registry (req #2997, migration 067).
    'agent_instructions': {
        'scope': ('agent_fk', 'agents'),
        'verify': (('instruction_fk', 'instructions'),),
    },
    'agent_documents': {
        'scope': ('agent_fk', 'agents'),
        'verify': (('document_fk', 'architecture_documents'),),
    },

    # Maps. `map_coordinates` is a child table rather than a junction and is here
    # for exactly the same reason: no creator_fk, a surrogate id, and a GPS track
    # per row. An unscoped LIST on it hands over every user's routes.
    'map_coordinates': {
        'scope': ('map_run_fk', 'map_runs'),
    },
    'map_run_partners': {
        'scope': ('map_run_fk', 'map_runs'),
        'verify': (('map_partner_fk', 'map_partners'),),
    },

    # Task plan hand-sort order. `domain_id` carries ownership.
    #
    # `fk_enforced: False` — this table declares NO foreign keys at all, so the
    # "a parent that does not exist falls through to the FK" rule below has
    # nothing to fall through TO: the INSERT would simply succeed. A row naming a
    # domain that does not exist yet is invisible to everyone until
    # AUTO_INCREMENT reaches that id, at which point it silently becomes its new
    # owner's. Cheap to refuse, so it is refused here.
    #
    # `task_id` is deliberately ABSENT from `verify`, and this is the exception
    # that fixes the rule: `priority_card_order` declares NO foreign keys at all,
    # so the database already tolerates a dangling `task_id`. Verifying it would
    # convert a tolerated dangling reference into a 403 — new referential
    # integrity smuggled in under an authorization change, and PriorityCard.jsx
    # has a real race that would hit it (a task deleted in another tab between
    # the sort and the POST). Nothing leaks: the row is readable only by the
    # owner of its domain and carries no data from the task it names.
    'priority_card_order': {
        'scope': ('domain_id', 'domains'),
        'fk_enforced': False,
    },
}

# Tables that are legitimately unscoped. Empty, and that is the point: it exists
# so a future exemption has to be WRITTEN DOWN and reviewed rather than achieved
# by leaving a table out of both registries. The conformance tests treat this set
# as the only permitted third answer.
UNSCOPED_TABLES = frozenset()


# ---------------------------------------------------------------------------
# Outbound references FROM a creator_fk-bearing table (req #3125)
# ---------------------------------------------------------------------------
#
# THE HOLE THIS CLOSES — the GRIEF-LOCK. `JUNCTION_OWNERSHIP` above answers "who
# owns this row" for tables that cannot answer it themselves. This registry
# answers a different question for the tables that CAN: who owns the rows this
# row POINTS AT.
#
# A table with `creator_fk` is scoped correctly on every verb, and that is
# exactly what makes the attack work. The attacker inserts THEIR OWN row —
# `creator_fk` is forced from their token, so it passes every check in this file
# — carrying a `*_fk` that names a VICTIM's parent. Nothing ever looked at the
# target. Two consequences, and the second is the one that has no recovery:
#
#   * ATTACHMENT. The attacker's row is now a child of the victim's row. On the
#     22 columns below that are CASCADE or SET NULL, that is the whole of it: a
#     cross-tenant write, the same refusal req #3122 makes for junctions.
#
#   * GRIEF-LOCK. On the 14 columns that are ON DELETE RESTRICT, the victim can
#     no longer delete their own parent. `DELETE /darwin/test_plans?id=<mine>`
#     answers 409 naming `fk_test_runs_plan` — a constraint held by a `test_runs`
#     row the victim cannot see (it is scoped to the attacker), cannot list, and
#     cannot delete. There is no self-service recovery: every tool the victim has
#     is `creator_fk`-scoped away from the row pinning them. A permanent,
#     unattributable denial of service on a single row, for the price of one
#     POST.
#
# WHY IT IS ONLY LATENT TODAY. Darwin has one Cognito account, so no second
# creator exists to be either attacker or victim. That is a property of the
# DEPLOYMENT, not of the code, and it stops being true the moment a second
# account is created. It is the only reason this shipped after req #3122 rather
# than with it.
#
# THE SHAPE. `{table: ((column, parent_table), ...)}` — every `*_fk` on a
# `creator_fk`-bearing table whose target is ALSO creator-scoped. There is no
# `scope` entry and no `fk_enforced` flag, and both absences are load-bearing:
#
#   * No scope column. Ownership of the row is settled by `creator_fk`, forced
#     from the token by rest_post/rest_put. Every column here is a `verify`
#     entry in `JUNCTION_OWNERSHIP` terms — checked when PRESENT, never required.
#     Absent means "not set" on INSERT and "unchanged" on UPDATE; a NOT NULL
#     column that is genuinely missing is the database's 1364 to report, not an
#     authorization answer.
#
#   * No `fk_enforced` flag. Every column here was DERIVED from a real
#     `FOREIGN KEY` declaration in `schema.sql`, so "the parent does not exist"
#     always falls through to a 409/1452 — `priority_card_order`'s exception
#     cannot arise. `test_every_column_is_backed_by_a_real_foreign_key` re-derives
#     that from the DDL rather than trusting this sentence.
#
# COLUMNS DELIBERATELY NOT HERE. `creator_fk` itself (forced from the token, and
# the only FK on these tables that targets `profiles`), and any FK whose target
# is NOT creator-scoped — there is nobody to steal from. As of migration
# 20260808115509 there are no such columns: all 45 non-`creator_fk` FKs on the 42
# creator-scoped tables target creator-scoped tables.
#
# ADDING A COLUMN. You do not — `test_every_cross_tenant_fk_column_is_registered`
# re-derives the whole set from `schema.sql` on every run, so a new FK column
# fails the build until it is registered or written into
# `UNCHECKED_CREATOR_REFERENCES` below. That is the same call req #3122 made for
# `JUNCTION_OWNERSHIP`, and for the same reason: the previous audit of this class
# reported "test_runs.test_plan_fk plus ten siblings" and the real count is 36.
# A hand-maintained list of a security boundary drifts silently; a derived one
# cannot.
#
# Comments give each column's ON DELETE action: RESTRICT is grief-lock capable
# outright, CASCADE and SET NULL are cross-tenant attachment.

CREATOR_TABLE_REFERENCES = {
    'agent_telemetry_row_docs': (
        ('row_fk', 'agent_telemetry_rows'),                  # CASCADE
    ),
    'agent_telemetry_rows': (
        ('run_fk', 'agent_telemetry_runs'),                  # CASCADE
    ),
    'agent_telemetry_runs': (
        ('machine_fk', 'machines'),                          # RESTRICT
    ),
    'areas': (
        ('domain_fk', 'domains'),                            # CASCADE
    ),
    'branches': (
        ('project_fk', 'build_projects'),                    # CASCADE
        ('parent_build_fk', 'builds'),                       # SET NULL
    ),
    'build_projects': (
        ('trunk_branch_fk', 'branches'),                     # SET NULL
    ),
    'builds': (
        ('branch_fk', 'branches'),                           # CASCADE
    ),
    'categories': (
        ('project_fk', 'projects'),                          # CASCADE
    ),
    'customer_releases': (
        ('customer_fk', 'customers'),                        # RESTRICT
        ('build_fk', 'builds'),                              # CASCADE
    ),
    'dev_servers': (
        ('session_fk', 'swarm_sessions'),                    # SET NULL
        ('machine_fk', 'machines'),                          # RESTRICT
    ),
    'epics': (
        ('category_fk', 'categories'),                       # RESTRICT
    ),
    'features': (
        ('category_fk', 'categories'),                       # RESTRICT
        ('epic_fk', 'epics'),                                # SET NULL
    ),
    'map_runs': (
        ('map_route_fk', 'map_routes'),                      # SET NULL
    ),
    'orchestration_claims': (                                # req #3224
        ('pipeline_fk', 'pipelines'),                        # CASCADE
        ('epic_fk', 'epics'),                                # CASCADE
        ('machine_fk', 'machines'),                          # RESTRICT
        ('pipeline2_fk', 'pipeline2_pipelines'),             # CASCADE, req #3369
        ('epic2_fk', 'pipeline2_epics'),                     # CASCADE, req #3369
    ),
    'pipeline_steps': (
        ('pipeline_fk', 'pipelines'),                        # CASCADE
    ),
    'pipeline2_epics': (                                     # req #3337
        ('pipeline_fk', 'pipeline2_pipelines'),              # CASCADE
        ('category_fk', 'categories'),                       # RESTRICT
    ),
    'pipeline2_pipelines': (                                 # req #3337
        ('machine_fk', 'machines'),                          # RESTRICT
    ),
    'pipeline2_steps': (                                     # req #3337
        ('epic_fk', 'pipeline2_epics'),                      # CASCADE
    ),
    'pipelines': (
        ('machine_fk', 'machines'),                          # RESTRICT
    ),
    'recurring_tasks': (
        ('area_fk', 'areas'),                                # CASCADE
    ),
    'requirements': (
        ('project_fk', 'projects'),                          # SET NULL
        ('category_fk', 'categories'),                       # RESTRICT
        ('machine_fk', 'machines'),                          # RESTRICT
        ('feature_fk', 'features'),                          # SET NULL
    ),
    'swarm_sessions': (
        ('machine_fk', 'machines'),                          # RESTRICT
        ('pipeline_fk', 'pipelines'),                        # SET NULL  (req #3186)
        ('epic_fk', 'epics'),                                # SET NULL  (req #3186)
        ('pipeline2_fk', 'pipeline2_pipelines'),             # SET NULL  (req #3350)
        ('epic2_fk', 'pipeline2_epics'),                     # SET NULL  (req #3350)
    ),
    'swarm_completes': (
        # req #3202, migration 20260809002208. The one envelope context column
        # this table lacked — req #2943 registered `machine_fk` on
        # swarm_sessions and swarm_starts, req #3098 on agent_telemetry_runs,
        # and swarm_completes was skipped by both. Registered here on the same
        # terms as its three siblings: RESTRICT, so an unchecked write would be
        # a grief-lock on the victim's `machines` row.
        ('machine_fk', 'machines'),                          # RESTRICT
    ),
    'swarm_starts': (
        ('machine_fk', 'machines'),                          # RESTRICT
    ),
    'swarm_undos': (
        ('session_fk', 'swarm_sessions'),                    # SET NULL
        ('swarm_start_fk_at_undo', 'swarm_starts'),          # SET NULL
        ('req_id_at_undo', 'requirements'),                  # SET NULL
    ),
    'tasks': (
        ('area_fk', 'areas'),                                # CASCADE
        ('recurring_task_fk', 'recurring_tasks'),            # SET NULL
    ),
    'test_cases': (
        ('category_fk', 'categories'),                       # RESTRICT
    ),
    'test_plans': (
        ('category_fk', 'categories'),                       # RESTRICT
    ),
    'test_results': (
        ('test_run_fk', 'test_runs'),                        # CASCADE
        ('test_case_fk', 'test_cases'),                      # RESTRICT
    ),
    'test_runs': (
        ('test_plan_fk', 'test_plans'),                      # RESTRICT
    ),
}

# `(table, column)` pairs a future maintainer has decided NOT to ownership-check.
# Empty, and the same call as `UNSCOPED_TABLES`: an exemption has to be written
# here and reviewed rather than achieved by quietly omitting a column, because
# omission and exemption are indistinguishable in a hand-written registry.
#
# The bar is `priority_card_order`'s: an exemption is right only where checking
# would refuse something legitimate. A pointer to a row the caller does not own,
# on a column the database enforces, is not that.
UNCHECKED_CREATOR_REFERENCES = frozenset()


def junction_parent_columns(table):
    """[(column, parent_table), ...] — every reference that must resolve to a row
    the caller owns before a write to `table` is allowed. [] for other tables.

    The scope column comes first; `verify` entries follow in declaration order.
    """
    entry = JUNCTION_OWNERSHIP.get(table)
    if entry is None:
        return []
    return [entry['scope']] + list(entry.get('verify', ()))


def creator_table_reference_columns(table):
    """[(column, parent_table), ...] a write to a creator_fk table must own (#3125).

    [] for anything not in `CREATOR_TABLE_REFERENCES`. None of these is a scope
    column: the row's own owner is `creator_fk`, forced from the token, so every
    entry here is checked WHEN PRESENT and never required.
    """
    return list(CREATOR_TABLE_REFERENCES.get(table, ()))


def referenced_parent_columns(table):
    """Every (column, parent_table) a write to `table` must own, either registry.

    The two are mutually exclusive by construction — `JUNCTION_OWNERSHIP` holds
    tables with no `creator_fk`, `CREATOR_TABLE_REFERENCES` holds tables that have
    one — and `test_the_two_registries_never_name_the_same_table` keeps it that
    way, so the order of these branches can never matter.
    """
    if table in JUNCTION_OWNERSHIP:
        return junction_parent_columns(table)
    return creator_table_reference_columns(table)


def _scope_column(table):
    """The column that carries ownership of a row in `table`, or None.

    Only a `JUNCTION_OWNERSHIP` table has one. A `creator_fk` table's ownership is
    a column comparison, so its references are all optional — which is the one
    behavioural difference between the two registries.
    """
    entry = JUNCTION_OWNERSHIP.get(table)
    return entry['scope'][0] if entry else None


def junction_scope_clause(table):
    """The SQL predicate scoping `table` to its owner, or None.

    Returns a fragment carrying exactly ONE `%s` placeholder, which the caller
    binds to the authenticated user::

        step_fk IN (SELECT id FROM pipeline_steps WHERE creator_fk = %s)

    Table and column names come from the hard-coded registry above, never from a
    request, so the interpolation here introduces no injection surface. The
    subquery always targets a DIFFERENT table than the statement it scopes, so it
    is legal inside UPDATE and DELETE (MySQL 1093 does not apply).
    """
    entry = JUNCTION_OWNERSHIP.get(table)
    if entry is None:
        return None
    column, parent = entry['scope']
    return f"{column} IN (SELECT id FROM {parent} WHERE creator_fk = %s)"


def _reference_value(raw):
    """The id a body field names, CANONICALIZED, or None when it names nothing.

    `None`, the `"NULL"` sentinel and `""` all mean "no value" on this wire —
    Darwin's "type into the blank row" pattern POSTs `id: ''` templates, and
    rest_post/rest_put map the string `"NULL"` to SQL NULL.

    Everything else is canonicalized to `str(int(...))`, and that is a security
    property, not tidiness. Every scope/verify column in `JUNCTION_OWNERSHIP` is
    an INT foreign key, so MySQL coerces whatever arrives into an integer — but
    this RDS instance runs a NON-STRICT sql_mode (`NO_ENGINE_SUBSTITUTION`, no
    `STRICT_TRANS_TABLES`), so it does that coercion SILENTLY, truncating any
    string with a numeric prefix instead of rejecting it. A bare `str(raw)` left
    the ownership lookup comparing `'9825.0'`, `' 9825'`, `'09825'` or
    `'9825abc'` against a database that answers `'9825'` — no match, so a foreign
    parent was classified as "does not exist", fell through to the FK, and then
    MySQL coerced it back to 9825 and wrote the row. Measured: every one of those
    forms landed a gate on another user's step through a 200 while the plain
    integer got a 403.

    A value that is not an integer at all raises ValueError, which the caller
    turns into a 400 — MySQL would have truncated it to something the caller
    never named.
    """
    if raw is None or raw == 'NULL' or raw == '':
        return None
    # `int(True)` is 1, so a bool would silently name row 1.
    if isinstance(raw, bool):
        raise ValueError(f"{raw!r} is not an id")
    if isinstance(raw, int):
        number = raw
    elif isinstance(raw, float):
        try:
            # `int(9825.7)` is 9825 — a DIFFERENT row, chosen silently. Only an
            # exact integer may pass. inf/nan raise out of int(), so both are
            # funnelled into the same refusal rather than escaping as
            # OverflowError past the caller's `except ValueError`.
            if raw != int(raw):
                raise ValueError
            number = int(raw)
        except (ValueError, OverflowError):
            raise ValueError(f"{raw!r} is not an integer id") from None
    elif isinstance(raw, str) and _ASCII_INT_RE.fullmatch(raw.strip(_SQL_SPACE)):
        number = int(raw.strip(_SQL_SPACE))
    else:
        raise ValueError(f"{raw!r} is not an integer id")

    # Applied once, so it covers the int, float and str paths alike.
    if not _INT_MIN <= number <= _INT_MAX:
        raise ValueError(f"{raw!r} is outside MySQL's INT range, which CLAMPS "
                         "rather than rejects — it would name a different row "
                         "to the database than it names here")
    return str(number)


def _written_value(body, column):
    """What the STATEMENT will put in `column` — which is what must be checked.

    Two ways this differs from `body.get(column)`, both of them cases where the
    check and the writer would otherwise read the same body differently:

      * **Case.** `body_column` resolves the name the way MySQL does.
      * **The empty string.** `''` is NOT the NULL sentinel — `rest_post` and
        `rest_put` map only the literal `"NULL"` to SQL NULL, so `''` is passed
        through and this instance's non-strict `sql_mode` coerces it to **0** in
        an INT column. Reading it as "names nothing" left a value the statement
        writes entirely unchecked. Harmless in the tables that declare a FK — no
        `id = 0` row exists, so it fails 1452 and the caller sees the same 409
        either way — but `priority_card_order` declares no FK at all, so on a PUT
        it wrote a `domain_id = 0` row that is invisible to everyone until
        AUTO_INCREMENT reaches 0, which is the exact hazard req #3122 refused
        `'\\n9825'` to prevent. Checked as 0 so the two layers agree.

    A column the body does not mention returns None: on an UPDATE that means
    *unchanged*, and it must not be confused with an explicit NULL.
    """
    present, value = body_column(body, column)
    if not present:
        return None
    return '0' if value == '' else value


def plan_parent_lookups(table, bodies, require_scope=True):
    """`(lookups, refusal)` — WHAT to ask the database, decided without asking it.

    `lookups` is `{parent_table: [canonical id, ...]}`, de-duplicated and in first
    -seen order: one entry per distinct PARENT TABLE across every body, never per
    row and never per column. `refusal` is `(status, message)` when the bodies are
    malformed enough to answer without a lookup at all, else None.

    Split out of the check (req #3125) so a caller can discover that there is
    NOTHING TO LOOK UP before opening a cursor. That is not a micro-optimisation:
    `CREATOR_TABLE_REFERENCES` covers `tasks`, `areas` and `requirements` — the
    gateway's hottest tables — and the overwhelming majority of their writes name
    no parent at all (`PUT /darwin/tasks [{"id": 5, "done": 1}]`). Opening a
    cursor for those would put the request's first cursor acquisition ahead of the
    INSERT, so a connection that dies on `cursor()` would fail with nothing
    written and nothing to roll back — the shape of failure
    `tests/test_unit_error_detail_wiring.py` exists for. (That file cannot pin
    THIS property: every case in it passes `authenticated_user=None`, so the
    guard returns at its first line. The `ExplodingConn` cases in
    `tests/test_unit_junction_scoping.py` are what actually hold it.)

    Pure: no cursor, no database, no I/O.
    """
    columns = referenced_parent_columns(table)
    if not columns:
        return {}, None

    scope_column = _scope_column(table)
    lookups = {}
    for body in bodies:
        if not isinstance(body, dict):
            return {}, (400, 'BAD REQUEST')
        try:
            # `body_column`, not `body.get`: MySQL resolves a column name
            # case-insensitively, so `{"AREA_FK": n}` writes `area_fk` while
            # `body.get('area_fk')` returns None — a reference the statement
            # carries and this check never saw. `check_body_keys` runs first and
            # has already refused the spellings a case-fold cannot cover.
            named = {column: _reference_value(_written_value(body, column))
                     for column, _ in columns}
        except ValueError as e:
            # Not an integer id. MySQL would have truncated it silently under
            # this instance's non-strict sql_mode; say no instead.
            print(f"Auth: {table} write with a non-integer parent reference: {e}")
            return {}, (400, 'BAD REQUEST')

        # Only a junction has a scope column, and only INSERT requires it. A
        # creator_fk table's ownership is settled by its own column, so every
        # reference it declares is optional on both verbs.
        if require_scope and scope_column is not None and named[scope_column] is None:
            print(f"Auth: {table} write with no {scope_column} — ownership "
                  "cannot be established")
            return {}, (400, 'BAD REQUEST')

        for column, parent in columns:
            value = named[column]
            if value is None:
                continue
            ids = lookups.setdefault(parent, [])
            if value not in ids:
                ids.append(value)

    return lookups, None


def resolve_parent_lookups(cursor, table, lookups, authenticated_user):
    """`(status, message)` when a planned lookup names a foreign row, else None.

    One SELECT per distinct parent table. THE VERDICT IS DERIVED FROM THE ROWS THE
    DATABASE RETURNED, never from the request's own values — see the comment on
    the loop below; that distinction was itself a shipped bug once.
    """
    fk_enforced = JUNCTION_OWNERSHIP.get(table, {}).get('fk_enforced', True)

    for parent, ids in lookups.items():
        # Selecting creator_fk rather than filtering on it is what separates
        # "somebody else's row" from "no row at all" — the distinction the
        # docstring above turns on. An absent id simply is not in the result.
        placeholders = ', '.join(['%s'] * len(ids))
        cursor.execute(
            f"SELECT id, creator_fk FROM {parent} WHERE id IN ({placeholders})",
            tuple(ids))
        # Tolerate either cursor class. db_connection.py opens a plain (tuple)
        # cursor today, but tests/conftest.py builds a DictCursor connection, so
        # both shapes live in this repo — and a KeyError raised here is NOT a
        # pymysql.Error, so it would escape the caller's guard.
        #
        # THE VERDICT IS DERIVED FROM THE ROWS THE DATABASE RETURNED, never from
        # the request's own values. An earlier version keyed a dict on the DB's
        # ids and then iterated the REQUEST's strings to decide — so any id whose
        # text differed from MySQL's canonical form matched nothing, was read as
        # "does not exist", and fell straight through to the FK, which coerced it
        # back and wrote the row. `_reference_value` now canonicalizes as well;
        # both halves are needed, because only this one is guaranteed to be
        # comparing what the database actually said.
        found = []
        for row in cursor.fetchall():
            if isinstance(row, dict):
                found.append((str(row['id']), row['creator_fk']))
            else:
                found.append((str(row[0]), row[1]))

        foreign = sorted(row_id for row_id, owner in found
                         if owner != authenticated_user)
        if foreign:
            # Detail to the log, never to the client: the response body is a bare
            # 'FORBIDDEN' so it cannot report back which ids were the problem.
            print(f"Auth: refused {table} write referencing {parent} row(s) "
                  f"{foreign} owned by another creator")
            return (403, 'FORBIDDEN')

        # A parent that does not exist is normally left to the FK (see the
        # docstring). Where the table declares no FK, nothing would reject it, so
        # it is refused here instead — otherwise the row sits invisible until
        # AUTO_INCREMENT reaches that id and hands it to whoever gets there.
        # Compared by COUNT, so a canonicalization slip cannot turn this into a
        # false refusal of the caller's own row either.
        if not fk_enforced and len(found) != len(ids):
            present = {row_id for row_id, _ in found}
            absent = sorted(i for i in ids if i not in present)
            print(f"Auth: refused {table} write referencing {parent} row(s) "
                  f"{absent} that do not exist ({table} declares no foreign "
                  "key, so nothing else would reject them)")
            return (403, 'FORBIDDEN')

    return None


def check_parent_ownership(cursor, table, bodies, authenticated_user,
                           require_scope=True):
    """Verify a write only references rows the caller owns — EITHER registry.

    The single entry point behind both halves of the rule:

      * a `JUNCTION_OWNERSHIP` table, where the references ARE the ownership
        (req #3122), and
      * a `CREATOR_FK_TABLES` table listed in `CREATOR_TABLE_REFERENCES`, where
        the row's own owner is settled but its targets were never checked
        (req #3125 — the grief-lock).

    Returns None when the write is allowed, or `(status_code, message)`.
    """
    if authenticated_user is None:
        return None
    lookups, refusal = plan_parent_lookups(table, bodies, require_scope)
    if refusal is not None:
        return refusal
    if not lookups:
        return None
    return resolve_parent_lookups(cursor, table, lookups, authenticated_user)


def check_junction_parent_ownership(cursor, table, bodies, authenticated_user,
                                    require_scope=True):
    """Verify a write to a junction/child table only references rows the caller owns.

    The `JUNCTION_OWNERSHIP` half of `check_parent_ownership`, kept as its own
    entry point because the two registries answer different questions and a
    caller that means "junctions" should not silently start covering 25 more
    tables. Returns None for a table in the other registry.

    Returns None when the write is allowed, or `(status_code, message)` to answer
    with. `rest_post` and `rest_put` turn that into a response.

    This is the WRITTEN-VALUE half of join-through scoping, and it is needed on
    both verbs for different reasons:

      * **INSERT** has no WHERE clause to attach `junction_scope_clause()` to, so
        the parent references are the only thing that can be checked.
      * **UPDATE** has one, but the predicate only proves ownership of the row's
        parent *before* the statement. The SET clause is built from every key in
        the body, so `PUT [{"id": <my edge>, "step_fk": <their step>}]` passes the
        WHERE on its current parent and then HANDS THE ROW TO THEM — verified
        against darwin_dev, and it defeated the POST guard entirely by taking the
        other door. `dep_step_fk` was worse: an edge re-pointed at another user's
        step makes that step undeletable through `ON DELETE RESTRICT`.

    `require_scope` is the only difference between the two callers. On INSERT the
    scope column is mandatory (it is NOT NULL everywhere here). On UPDATE its
    absence means "unchanged", which is the common case and must not be a 400 —
    `PriorityCard.jsx` bulk-PUTs `{id, sort_order}` on every hand-sort save.

    One SELECT per distinct parent TABLE, not per row and not per column, so a
    3,000-row `map_coordinates` bulk import costs exactly one extra query.

    Three answers, and the third is the subtle one:

      * **Scope column missing or NULL -> 400.** It is NOT NULL in every
        registered table, so the INSERT could only fail anyway, and answering 403
        would blame the caller's identity for a malformed body.
      * **Parent EXISTS and belongs to another creator -> 403.** The refusal this
        function exists for.
      * **Parent DOES NOT EXIST -> allowed through, to fail as a 409/1452.**

    That last one is deliberate and was reconsidered once. Refusing a missing
    parent with 403 too would hide whether an id is real — but the id space is a
    dense auto-increment any caller can already infer, so the oracle is worth
    almost nothing, while the cost is charged on every ordinary FK typo: `403
    FORBIDDEN — references a row another creator owns` is a CONFIDENTLY WRONG
    explanation of a mistyped id. The 409 contract (`Lambda-Rest/CLAUDE.md` §
    Error Status Contract) already answers this case correctly, promises exactly
    what is true of it — *retrying with different data can succeed* — and names
    the constraint. Pinned by `tests/test_agent_instructions.py::
    test_bad_foreign_key_is_409_conflict`, which this function broke when it
    collapsed the two.
    """
    if table not in JUNCTION_OWNERSHIP:
        return None
    return check_parent_ownership(cursor, table, bodies, authenticated_user,
                                  require_scope=require_scope)
