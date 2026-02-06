# Project: REST API Lambda

AWS Lambda function serving a REST API backed by MySQL (RDS). Handles CRUD operations via API Gateway proxy events.

## Architecture

- `handler.py` — Lambda entry point, routes by httpMethod to rest_get/post/put/delete modules
- `rest_api_utils.py` — `compose_rest_response()` builds API Gateway proxy responses
- `classifier.py` — Utility functions (varDump, pretty_print_sql)
- `pymysql/` — Vendored MySQL driver (do not modify)

## Test Framework

- Tests live in `_rest_api_lambda_test/`
- `lambda_test.py` — Generic test executor with pass/fail assertions
- `lambda_test_darwin.py` — Darwin database tests (GET tests + CUD lifecycle)
- Run tests: `cd _rest_api_lambda_test && . ../exports.sh && python3 lambda_test_darwin.py`
- Tests import handler.py via `sys.path.append('./..')` so must run from the test directory

## Known Bugs

- **Double-JSON-encoded response body in rest_post.py**: The SQL builds a JSON string via CONCAT/JSON_OBJECT, then `compose_rest_response` calls `json.dumps()` on the result again. This means `json.loads(response['body'])` returns a list containing a JSON *string*, not a parsed object. The CUD lifecycle test works around this with an unwrap step. The same pattern likely exists in `rest_put.py` and `rest_get_table.py` — check before assuming response bodies are single-decoded.

## Environment

- `exports.sh` contains database credentials (db_name, db_password, endpoint, username) — do not commit this file
- Must be sourced before running tests: `. ./exports.sh` (use dot syntax, not `source`, for shell compatibility)
- Database: MySQL on AWS RDS (darwin2)
