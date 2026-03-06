"""
Authentication utilities for Lambda-Rest.

Extracts the authenticated user identity from API Gateway Cognito
authorizer claims and defines which tables require creator_fk scoping.
"""


def get_authenticated_user(event):
    """Extract cognito:username from the API Gateway authorizer claims.

    Returns the authenticated user's ID (str) or None if not present.
    """
    try:
        return event['requestContext']['authorizer']['claims']['cognito:username']
    except (KeyError, TypeError):
        return None


# Tables that have a creator_fk column and must be scoped to the authenticated user
CREATOR_FK_TABLES = frozenset({
    'domains', 'areas', 'tasks',
    'projects', 'categories', 'priorities',
    'dev_servers', 'swarm_sessions',
})

PROFILE_TABLE = 'profiles'
