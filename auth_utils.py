"""
Authentication utilities for Lambda-Rest.

Extracts the authenticated user identity from API Gateway Cognito
authorizer claims and defines which tables require creator_fk scoping.
"""


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
    # every other junction (swarm_start_sessions, agent_documents, ...).
    'epics', 'pipelines', 'pipeline_steps',
})

PROFILE_TABLE = 'profiles'
