# Project: REST API Lambda

AWS Lambda function serving a REST API backed by MySQL (RDS) via API Gateway proxy integration.

## Architecture

- `handler.py` — Lambda entry point (`lambda_handler`). Parses the URL path into database + table, routes by httpMethod.
- `rest_api_utils.py` — `compose_rest_response(status_code, body, http_message)` builds the API Gateway Lambda proxy response dict. Always calls `json.dumps(body)` on the body before inserting it. On error status codes (not 200/201/204), replaces body with http_message.
- `classifier.py` — `varDump(value, description, dump_type)` for debug printing, `pretty_print_sql()` collapses whitespace for readable SQL logs.
- `pymysql/` — Vendored MySQL driver (do not modify)

### Request Flow

1. API Gateway sends a Lambda proxy event with `httpMethod`, `path`, `queryStringParameters`, `body`
2. `handler.py` parses path: first segment = database name, second segment = table name
3. The database name is matched against `db_dict` (from `db_name` env var) to find the connection
4. `rest_api_from_table()` dispatches to the appropriate rest_* module by HTTP method
5. For POST/PUT/DELETE, the body is `json.loads`'d from the event before dispatch
6. For GET, the raw event is passed (the module reads `queryStringParameters` directly)

### Database Connection

- Connection is established at module load time (Lambda cold start), stored in `connection` dict keyed by database name
- Currently only one database (`darwin2`) is configured
- Uses pymysql with credentials from environment variables

## CRUD Modules

### rest_get_database.py
- Triggered when GET path has no table segment (e.g., `/darwin2`)
- Runs `SHOW tables`, returns list of table name strings
- Triple-encoded: calls `json.dumps(columns_array)` then passes result to `compose_rest_response` which calls `json.dumps` again

### rest_get_table.py
- Triggered when GET path has a table segment (e.g., `/darwin2/areas2`)
- Step 1: `DESC {table}` to discover columns (used to validate QSPs and build JSON_OBJECT)
- Step 2: Parse query string parameters into WHERE clause, ORDER BY, fields/count/group_by
- Step 3: Build and execute SQL using `CONCAT('[', GROUP_CONCAT(JSON_OBJECT(...)), ']')` to produce JSON directly from MySQL
- QSP features: column=value filters, IN clause via `col=(1,2,3)`, `sort=col:asc`, `fields=col1,col2`, `fields=count(*),group_col`, `filter_ts=(col,start,end)`
- Returns `row[0]` (a tuple) to `compose_rest_response` — causes double-encoding

### rest_post.py
- Accepts a single object (dict) body, not an array
- INSERT into table, then SELECT LAST_INSERT_ID(), then re-reads the full row using JSON_OBJECT and returns it
- Three separate try/except blocks: insert, get ID, read-back
- On partial failure (insert succeeds but read-back fails), returns 201 with empty body
- Returns `row[0]` (tuple) to `compose_rest_response` — causes double-encoding

### rest_put.py
- Accepts an array of objects, each must have `id`
- Single record: simple `UPDATE SET col=val WHERE id=X`
- Multiple records: uses `CASE id WHEN X THEN val` syntax to batch updates in one statement
- Returns empty body on success (200) or "NO DATA CHANGED" on 204
- `body.pop('id')` mutates the input dicts — be aware if reusing body data after a PUT call
- NULL values: pass the string `"NULL"` and it gets unquoted via string replace

### rest_delete.py
- Accepts an object body, keys become AND-ed WHERE conditions
- Returns empty body on success (200), 404 if no rows matched

## Test Framework

- Tests live in `_rest_api_lambda_test/`
- `lambda_test.py` — Generic test executor with pass/fail assertions. Checks `expected_status` and `expected_body_contains` (list of substrings). Tracks results in `_test_results` list. Call `lambda_test_summary()` at end.
- `lambda_test_darwin.py` — Darwin database tests: 3 GET tests + CUD lifecycle (POST/PUT/GET/DELETE that creates and cleans up its own record)
- Run tests: `cd _rest_api_lambda_test && . ../exports.sh && python3 lambda_test_darwin.py`
- Tests import handler.py via `sys.path.append('./..')` so must run from the test directory
- CUD lifecycle test includes an unwrap step for the double-encoded POST response

## Known Bugs

### Deferred (do not fix without coordinating with frontend consumers)

- **Double-JSON-encoded response bodies**: The SQL modules build JSON strings via CONCAT/JSON_OBJECT, then pass `row[0]` (a tuple containing the JSON string) to `compose_rest_response`, which calls `json.dumps()` on it again. Affects `rest_post.py`, `rest_get_table.py`, and `rest_get_database.py` (which is triple-encoded since it also pre-calls `json.dumps`). Consumers currently work around this.

### handler.py

- **`db_dict` is a string, not a dict (line 27-70)**: `db_dict = os.environ['db_name']` assigns the string `'darwin2'`. The check `db_info['database'] in db_dict` (line 70) performs a **substring match** on the string, not a dict key lookup. Works by coincidence because the name matches exactly, but a database named `'dar'` would incorrectly match `'darwin2'` since `'dar' in 'darwin2'` is True.

- **Unbound `body` variable (line 97-98)**: If `event['body']` is None, the `if` block is skipped and `body` is never assigned. The method dispatch at lines 106/119/124 still passes `body` to the rest_* modules, which would raise `UnboundLocalError`. GET is unaffected since it doesn't use `body`.

### rest_api_utils.py

- **status_code type inconsistency (line 25)**: Some callers pass int (e.g., `400`), others pass string (e.g., `'200'`). The error-path check `status_code != '200' and status_code != '201' and status_code != '204'` uses string comparison. When called with int `400`, this always enters the error branch (correct by accident). If called with int `200`, it would also enter the error branch (incorrect — would overwrite body with http_message).

### rest_get_database.py

- **Missing f-string prefix (line 24)**: `print('HTTP {get_method}: show tables command failed')` prints the literal text `{get_method}` instead of the variable's value. Should be `f'HTTP {get_method}:...'`.

- **String literal instead of variable (line 30)**: `compose_rest_response('500', '', "errorMsg")` passes the string `"errorMsg"` instead of the variable `errorMsg` that holds the actual pymysql error message.

### rest_get_table.py

- **String literal instead of variable (line 165)**: Same issue as rest_get_database.py — passes `"errorMsg"` string literal instead of the `errorMsg` variable.

### rest_put.py

- **Error dict silently discarded (line 113)**: `compose_rest_response('500', {'error': errorMsg})` passes a dict as body, but status `'500'` triggers the error branch in `compose_rest_response`, which overwrites body with `json.dumps(http_message)`. Since `http_message` defaults to `''`, the actual error details are thrown away and the client receives an empty error message.

### Security

- **SQL injection (all rest_* modules)**: All SQL statements are built with f-string interpolation. Table names, column values, query string parameter keys and values are inserted directly into SQL without parameterized queries or escaping. API Gateway provides some upstream validation, but the Lambda itself performs no input sanitization.

## URL Path Structure

- `/{database}` — GET returns list of tables
- `/{database}/{table}` — CRUD operations on the table
- PUT body is always an array of objects (even for single updates), each must have `id`
- POST body is a single object (not an array)
- DELETE body is an object whose keys become AND-ed WHERE conditions

## Documentation

- `javascript_rest_api_guide.txt` — JavaScript fetch examples for all CRUD operations with a reusable helper function

## Environment

- `exports.sh` contains database credentials (db_name, db_password, endpoint, username) — in `.gitignore`, never commit
- Must be sourced before running tests: `. ./exports.sh` (use POSIX dot syntax, not `source`)
- Database: MySQL on AWS RDS (darwin2)
- Env vars: `endpoint`, `username`, `db_password`, `db_name`
