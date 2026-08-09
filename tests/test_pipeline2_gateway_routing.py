"""Pipeline 2.0 API Gateway routing — Lambda-side half (req #3338).

# COVERS: SCH-023

**What this file proves, and what it deliberately does not.** SCH-023 states
"ten API Gateway resources exist — five tables across both stages — and each
answers." That splits into two halves this session verified two different
ways:

- **The Lambda-side half — asserted HERE.** `lambda_handler` correctly parses
  the path, applies `auth_utils` registration, and executes a real SQL query
  for each of the five `pipeline2_*` tables, proving no application-level
  obstacle (missing registration, an invalid table-name regex match, a
  connection failure) would make a route fail even once the AWS wiring is in
  place. Exercised via `/darwin_dev/*` only, matching this suite's existing
  convention (`invoke`'s own docstring example in `conftest.py`) of never
  touching `/darwin/*` production data from a test.
- **The AWS-wiring half — NOT assertable from any repository, by design.**
  Whether all ten resources (both `/darwin/*` and `/darwin_dev/*`) are
  actually deployed in API Gateway and answer over real HTTP is register
  behaviour SCH-025, `testability: untestable` — API Gateway is console-built
  with no IaC, so nothing in source control can prove the route SET is
  complete. That half's compensating control (a live per-table reachability
  probe through the real gateway, all ten resources) was run manually
  2026-08-08 and is recorded in `memory/api-gateway.md`, not re-derived here.

SCH-024 ("no Lambda-policy change... because the wildcard grants glob every
child route") is a different claim about `add-api-route.sh`'s own AWS-policy
verification, not about `lambda_handler` — it is covered by
`tests/deploy/test-add-api-route-policy.sh` in DarwinAI-Config, which drives
the real script against a fixture policy. See that file and
`scripts/swarm/verification/pipeline2_behaviours.json`'s SCH-024 entry for why
it does not belong in this repository.

Requires `exports.sh` (real `darwin_dev` connection), consistent with every
other CRUD-style test in this directory.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth_utils import CREATOR_FK_TABLES, JUNCTION_OWNERSHIP

# Derived, not hand-counted (house style — see test_unit_creator_fk_references.py's
# own rationale for the same choice): the five pipeline2_* tables are exactly
# those two registries already name. A sixth pipeline2_* table registered in
# either registry is picked up here automatically; one registered in neither
# would still be missed, but that is auth_utils's own registration gap to
# catch (test_unit_creator_fk_references.py / test_unit_junction_scoping.py),
# not this file's.
PIPELINE2_TABLES = sorted(
    {t for t in CREATOR_FK_TABLES if t.startswith('pipeline2_')}
    | {t for t in JUNCTION_OWNERSHIP if t.startswith('pipeline2_')}
)


def test_pipeline2_table_count_is_five():
    """Sanity check on the derivation above, so a registry regression fails
    loud here rather than silently shrinking the parametrized set below."""
    assert len(PIPELINE2_TABLES) == 5, PIPELINE2_TABLES


class TestFiveTablesAnswer:
    """SCH-023 (Lambda-side half): every pipeline2_* table is reachable
    end-to-end through `lambda_handler` — path parsing, `auth_utils`
    registration, and a real SQL query against `darwin_dev`, for all five.

    A well-formed answer here is 200 (rows present) or 404 "NOT FOUND" (the
    documented empty-result shape for a GET matching zero rows — see
    `memory/lambda-patterns.md` § "A GET returning no rows is a 404"). Neither
    is a routing or wiring failure; a 400/403/500/503 would be.
    """

    @pytest.mark.integration
    @pytest.mark.parametrize('table', PIPELINE2_TABLES)
    def test_get_answers_without_error(self, invoke, table):
        response = invoke('GET', f'/darwin_dev/{table}')
        assert response['statusCode'] in (200, 404), (
            f"/darwin_dev/{table} returned {response['statusCode']}, expected "
            f"200 (rows) or 404 (documented empty-result shape): {response.get('body')}"
        )
        if response['statusCode'] == 404:
            assert response['body'] == '"NOT FOUND"', (
                f"/darwin_dev/{table} 404 body was {response['body']!r}, not the "
                f"documented empty-result shape — this would indicate a real "
                f"routing/auth failure disguised as the expected empty case"
            )
