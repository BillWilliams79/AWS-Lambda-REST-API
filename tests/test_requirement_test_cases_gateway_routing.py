"""requirement_test_cases API Gateway routing — Lambda-side half (req #3352).

# COVERS: SCH-033

Mirrors test_pipeline2_gateway_routing.py's split for the same reason: SCH-033
("both requirement_test_cases gateway routes exist and answer") splits into a
Lambda-side half assertable here and an AWS-wiring half that is not.

- **The Lambda-side half — asserted HERE.** `lambda_handler` correctly parses
  `/darwin_dev/requirement_test_cases`, applies `auth_utils` registration
  (`JUNCTION_OWNERSHIP`), and executes a real SQL query against `darwin_dev`,
  proving no application-level obstacle would make the route fail once the AWS
  wiring is in place. Exercised via `/darwin_dev/*` only — this suite's
  existing convention (`invoke`'s own docstring example in `conftest.py`) is
  to never touch `/darwin/*` production data from a test, and production has
  no `requirement_test_cases` table yet regardless (req #3352 body item 2 —
  a later requirement's gate).
- **The AWS-wiring half — NOT assertable from any repository, by design.**
  Whether both resources (`/darwin/requirement_test_cases` and
  `/darwin_dev/requirement_test_cases`) are actually deployed in API Gateway
  is not something source control can prove — API Gateway is console-built
  with no IaC. Both were created via `DarwinSQL/scripts/add-api-route.sh`
  (`--database=darwin_dev` and `--database=darwin`) and confirmed present via
  `add-api-route.sh --list` at creation time.

Requires `exports.sh` (real `darwin_dev` connection), consistent with every
other CRUD-style test in this directory.
"""
import pytest


class TestRequirementTestCasesAnswers:
    """SCH-033 (Lambda-side half): requirement_test_cases is reachable
    end-to-end through `lambda_handler` — path parsing, `auth_utils`
    registration, and a real SQL query against `darwin_dev`.

    A well-formed answer here is 200 (rows present) or 404 "NOT FOUND" (the
    documented empty-result shape for a GET matching zero rows — see
    `memory/lambda-patterns.md` § "A GET returning no rows is a 404"). Neither
    is a routing or wiring failure; a 400/403/500/503 would be.
    """

    @pytest.mark.integration
    def test_get_answers_without_error(self, invoke):
        response = invoke('GET', '/darwin_dev/requirement_test_cases')
        assert response['statusCode'] in (200, 404), (
            f"/darwin_dev/requirement_test_cases returned "
            f"{response['statusCode']}, expected 200 (rows) or 404 (documented "
            f"empty-result shape): {response.get('body')}"
        )
        if response['statusCode'] == 404:
            assert response['body'] == '"NOT FOUND"', (
                f"/darwin_dev/requirement_test_cases 404 body was "
                f"{response['body']!r}, not the documented empty-result shape "
                f"— this would indicate a real routing/auth failure disguised "
                f"as the expected empty case"
            )
