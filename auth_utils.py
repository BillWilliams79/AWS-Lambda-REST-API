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
    # Req #2719 — swarm_undo log (migration 053).
    'swarm_undos',
})

PROFILE_TABLE = 'profiles'
