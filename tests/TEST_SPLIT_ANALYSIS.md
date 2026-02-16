# Lambda-Rest Test Split Analysis

## Summary

**55 existing tests** — all integration (require DB connection). Analysis identifies **~15 pure-logic functions** suitable for unit testing without database access.

## Current Test Inventory (All Integration)

| Test File | Tests | Category |
|-----------|-------|----------|
| test_crud_lifecycle.py | 9 | CRUD operations with FK chains |
| test_error_paths.py | 18 | POST/PUT/DELETE error conditions |
| test_get_filtering.py | 17 | GET query parameters, sorting, aggregation |
| test_handler_routing.py | 8 | HTTP method routing, path parsing |
| **Total** | **55** | All require `darwin2` database |

### test_crud_lifecycle.py (9 tests)
- CRUD-01: Areas POST → PUT → GET → DELETE → GET(404)
- CRUD-02: Tasks lifecycle
- CRUD-03: Cross-table FK integrity (domain → area → task cascade)
- CRUD-04: Bulk task operations (3 tasks, bulk PUT, IN clause)
- CRUD-05: Special characters + SQL injection attempt
- CRUD-06: Task priority/done flag updates
- CRUD-07: Area sort_order update
- CRUD-08: Task sort_order update
- CRUD-09: Area soft delete and reopen (closed flag toggle)

### test_error_paths.py (18 tests)
- POST-01–06: Empty body, missing fields, FK violation, encoding, NULL, full populate
- PUT-01–08: Empty array, missing id, no fields, nonexistent id, invalid column, bulk errors, NULL, bulk update
- DELETE-01–03: Empty body, nonexistent id, multi-condition WHERE
- RESPONSE-01–04: statusCode type, error message, CORS headers, GET /database encoding

### test_get_filtering.py (17 tests)
- GET-01–03: Filter by creator_fk, by id, multiple filters (AND)
- GET-04: IN clause
- GET-05: Date range filter (filter_ts BETWEEN)
- GET-06–08: Sort ascending, descending, multi-field
- GET-09: Sparse fields
- GET-10: COUNT + GROUP BY aggregation
- GET-11–17: Invalid QSP, invalid field, nonexistent table, no rows, invalid sort, encoding, too many group-by fields

### test_handler_routing.py (8 tests)
- HANDLER-01: OPTIONS → 200
- HANDLER-02: No path → 400
- HANDLER-03: Invalid database → 404
- HANDLER-04: db_names set membership (no substring match)
- HANDLER-05–07: None body for POST/PUT/DELETE → 400
- HANDLER-08: None body GET succeeds

## Unit-Testable Functions

### 1. `compose_rest_response()` — `rest_api_utils.py` (40 lines)

**Purity**: Fully pure. No DB, no env vars, no side effects (prints are safe to ignore).

**Proposed unit tests** (~10):
| Test | Input | Expected |
|------|-------|----------|
| Success 200 with list body | `(200, [{'id': 1}])` | statusCode=200, body=JSON string |
| Success 201 with list body | `(201, [{'id': 1}])` | statusCode=201, body=JSON string |
| Success 204 no content | `(204, '')` | statusCode=204, body='""' |
| Error 400 replaces body | `(400, 'ignored', 'Bad request')` | body='"Bad request"' |
| Error 500 replaces body | `(500, 'ignored', 'Server error')` | body='"Server error"' |
| None body handling | `(200, None)` | No 'body' key or body is null |
| Empty string body | `(200, '')` | body='""' |
| CORS headers present | Any call | All 4 CORS headers present |
| isBase64Encoded is boolean | Any call | `False` not `"false"` |
| statusCode is int | `(200, '')` | `type(response['statusCode']) is int` |

**Import requirement**: `from rest_api_utils import compose_rest_response` — safe, no env vars at module scope.

### 2. `SAFE_NAME_RE` — `handler.py:50`

**Purity**: Compiled regex constant.

**Proposed unit tests** (~5):
| Test | Input | Expected |
|------|-------|----------|
| Valid table name | `'profiles2'` | Match |
| Underscore prefix | `'_private'` | Match |
| SQL injection attempt | `'tasks; DROP TABLE'` | No match |
| Number prefix | `'2tables'` | No match |
| Empty string | `''` | No match |

**Import challenge**: `handler.py` reads env vars at lines 25-28 (`os.environ['endpoint']`, etc.) at module scope. To import `SAFE_NAME_RE`, the test must mock these env vars BEFORE importing handler.

### 3. `parse_path()` — `handler.py:52-69`

**Purity**: Mostly pure logic — splits path, validates table name, looks up database in `db_names`. Calls `get_connection()` as side effect.

**Proposed unit tests** (~6, with mocked `get_connection`):
| Test | Input | Expected |
|------|-------|----------|
| Valid path | `'/darwin2/areas2'` | `{'database': 'darwin2', 'table': 'areas2', ...}` |
| Database only | `'/darwin2'` | `{'table': '', ...}` |
| Invalid table name | `'/darwin2/bad;name'` | `{'error': ...}` |
| Unknown database | `'/unknown/table'` | `{'conn': ''}` |
| Deep path (3+ segments) | `'/darwin2/areas2/extra'` | Extracts first 2 segments |
| Root path | `'/'` | `{'database': '', 'table': ''}` |

**Import challenge**: Same as SAFE_NAME_RE — env vars at module scope. Must use `unittest.mock.patch.dict(os.environ, {...})` before import.

### 4. `rest_api_from_table()` routing — `handler.py:95-148`

**Purity**: Dispatches by HTTP method — pure routing logic if `conn` is mocked.

**Proposed unit tests** (~4, with mocked CRUD functions):
| Test | Input | Expected |
|------|-------|----------|
| No event | Empty event | 500 response |
| No connection | `conn=''` | 500 response |
| No HTTP method | Missing httpMethod | 500 response |
| OPTIONS method | OPTIONS event | 200 directly |

## Import-Time Challenge

`handler.py` lines 25-28 execute at import time:
```python
endpoint = os.environ['endpoint']
username = os.environ['username']
password = os.environ['db_password']
db_names = set(os.environ['db_name'].split(','))
```

**Impact on unit tests**:
- `compose_rest_response` (in `rest_api_utils.py`) is **unaffected** — separate module, no env vars
- `SAFE_NAME_RE`, `parse_path`, `rest_api_from_table` all require handler import
- **Solution**: Set env vars via `@pytest.fixture(autouse=True)` or `unittest.mock.patch.dict` before handler import

**Recommended pattern**:
```python
import os
from unittest.mock import patch

# Set env vars before importing handler
with patch.dict(os.environ, {
    'endpoint': 'localhost',
    'username': 'test',
    'db_password': 'test',
    'db_name': 'darwin2',
}):
    from handler import SAFE_NAME_RE, parse_path, rest_api_from_table
```

## Existing Tests That Are Near-Unit

Some handler routing tests (HANDLER-02, HANDLER-04–07) call `lambda_handler()` directly with crafted events, but still trigger handler's module-level code. These could be reclassified if the env var issue is addressed.

## Proposed Test Split

### New files:
- `test_unit_response.py` — ~10 tests for `compose_rest_response()` (no DB, no env vars)
- `test_unit_handler.py` — ~8 tests for `SAFE_NAME_RE`, `parse_path()`, routing (mocked env vars)

### Markers:
```ini
# pytest.ini additions
markers =
    unit: runs without database (no exports.sh needed)
    integration: requires database connection
```

### Run commands:
```bash
pytest tests/test_unit_*.py -v              # No DB needed, no exports.sh
pytest tests/ -m integration -v             # DB required
pytest tests/ -v                            # All ~70 tests
```

## Functions That Must Remain Integration-Only

| Module | Function | Reason |
|--------|----------|--------|
| rest_get_table.py | `rest_get_table()` | Complex SQL with JSON_OBJECT, GROUP_CONCAT |
| rest_post.py | `rest_post()` | INSERT + LAST_INSERT_ID + read-back |
| rest_put.py | `rest_put()` | Single + bulk CASE/WHEN UPDATE |
| rest_delete.py | `rest_delete()` | DELETE + affected_rows check |
| rest_get_database.py | `rest_get_database()` | SHOW TABLES |
| handler.py | `get_connection()` | pymysql connection management |

These functions are tightly coupled to MySQL cursor operations. Mocking them would test the mock, not the code.
