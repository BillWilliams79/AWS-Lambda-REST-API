# Project: REST API Lambda

AWS Lambda function serving a REST API backed by MySQL (RDS) via API Gateway proxy integration.

## Architecture

- `handler.py` — Lambda entry point (`lambda_handler`). Parses the URL path into database + table, routes by httpMethod.
- `rest_api_utils.py` — `compose_rest_response(status_code, body, http_message)` builds the API Gateway Lambda proxy response dict. Always calls `json.dumps(body)` on the body before inserting it. On error status codes (not 200/201/204), replaces body with http_message. Also owns the 409 CONFLICT mapping (see below).
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
- Two databases configured: `darwin` (production), `darwin_dev` (testing)
- Uses pymysql with credentials from environment variables

## Row Ownership — three registries for the row, one more for what it points at

`auth_utils.py` answers *who owns this row* for the whole gateway (req #3122),
and separately *who owns the rows it references* (req #3125). The second is not
implied by the first — see § Outbound references below. A fifth registry in the
same file answers a different question entirely — *may this column be written
blank* — and is documented under § Bounded value domains (req #3432).

| Registry | Applies when | Predicate injected |
|---|---|---|
| `CREATOR_FK_TABLES` | the table carries `creator_fk` | `creator_fk = <sub>` |
| `PROFILE_TABLE` | `profiles` — the row IS the user | `id = <sub>` |
| `JUNCTION_OWNERSHIP` | the table has **no** `creator_fk` | `<col> IN (SELECT id FROM <parent> WHERE creator_fk = <sub>)` |

Thirteen tables are in the third group and had **no scoping at all** before
req #3122: an unscoped `GET /darwin/pipeline_step_deps` returned every user's
rows, and PUT/DELETE by id fell into the unscoped `else` branch of `rest_put.py` /
`rest_delete.py`. Authorization is now DERIVED from the parent that owns the row
rather than stored on it — a `creator_fk` column here would be a second copy of
ownership that MySQL cannot keep in agreement with the first.

- **GET / PUT / DELETE** append `junction_scope_clause(table)` to the WHERE clause,
  so a foreign row simply is not there: 404 on a read or delete, 204 on a PUT.
- **POST and PUT** additionally call `parent_reference_guard()` (rest_api_utils),
  which resolves the referenced parents BEFORE the statement — one SELECT per
  distinct parent table, never per row, so a 3,000-row `map_coordinates` import
  costs one extra query. It plans the lookups purely and returns *before opening
  a cursor* whenever there is nothing to look up.
- The unauthenticated **403 gate in `handler.py`** covers these tables too: with
  no identity there is nothing to derive scoping from.

**Scoping the WHERE clause is not sufficient on a PUT, and this bit.** The
predicate proves ownership of the row's parent *before* the statement, while the
`SET` clause is built from every key in the body — including the scope column. So
`PUT [{"id": <my edge>, "step_fk": <their step>}]` passed the predicate on its
current parent and then handed the row over; `dep_step_fk` was worse, because
`ON DELETE RESTRICT` then made the victim's step undeletable. That is why PUT
carries the write guard too (`require_scope=False` there — on an UPDATE an absent
scope column means *unchanged*). `rest_put` also force-overrides `creator_fk` from
the token exactly as `rest_post` does, so a body cannot push a row into another
account.

**Parent ids are canonicalized before comparison.** Every scope/verify column is
an INT FK and this RDS instance runs a **non-strict `sql_mode`**
(`NO_ENGINE_SUBSTITUTION` — no `STRICT_TRANS_TABLES`), so MySQL truncates
`'9825abc'` to 9825 silently rather than rejecting it. Comparing the request's raw
text against the database's canonical id made every non-canonical form
(`9825.0`, `' 9825'`, `'09825'`, …) read as "row does not exist", fall through to
the FK, and get coerced back and written. The verdict is now derived from the rows
the database returned, never from the request, and `_reference_value()`
canonicalizes at the door.

That canonicalizer matches **MySQL's** integer grammar, not Python's, and the
distinction is exploitable: `int()` accepts PEP 515 underscores and Unicode
digits, so `int('9825_0')` is 98250 — nonexistent, waved through to the FK — while
MySQL truncates at the `_` and writes the row onto 9825. Hence an explicit
`[+-]?[0-9]+` (**`[0-9]`, never `\d`** — `\d` matches the Unicode digits MySQL
reads as 0; likewise never `str.isdigit()`) and an ASCII-only whitespace strip.
Anything else is a 400 before any lookup.

**A DELETE body's keys are SQL identifiers and are now validated.** They are
interpolated into the WHERE clause, so `{"id = 1 OR 1=1 OR id": 1}` rendered as
`WHERE id = 1 OR 1=1 OR id = %s AND creator_fk = %s` — parsed as `id=1 OR TRUE OR
(…)` because AND binds tighter than OR, with the placeholder and argument counts
still balanced. Measured against darwin_dev: it deleted every row in the table and
cancelled the junction predicate *and* the pre-existing `creator_fk` scoping alike.
`_unknown_columns()` now checks every key against `DESC {table}` — the same check
`rest_get_table` has always made — and 400s otherwise. It raises rather than
swallowing a `pymysql.Error`, and is called from inside the statement's own try
block, so an unreachable database stays a 500 instead of becoming a misleading 400.

`verify` columns are checked on INSERT only, never ANDed into a read — `dep_step_fk`
is NULL on a wall-clock gate row, and a read predicate would hide every time gate
in a plan.

**Adding a table with no `creator_fk` obliges you to register it.** Conformance
tests in `tests/test_unit_junction_scoping.py` derive the set from `schema.sql`
and fail otherwise; `UNSCOPED_TABLES` is the written-down exemption set and is
empty.

## Outbound references — owning a row is not owning what it points at (req #3125)

`CREATOR_TABLE_REFERENCES` is the fourth registry: **41 columns across 26
tables** — every `*_fk` on a `creator_fk`-bearing table whose target is also
creator-scoped. (36 at req #3125; req #3186 added `swarm_sessions.pipeline_fk`
and `.epic_fk`; req #3224 added `orchestration_claims.pipeline_fk`, `.epic_fk`
and `.machine_fk`. Every number is DERIVED — see the closing note of this
section.)

**The attack does not defeat `creator_fk` scoping, it rides on it.** The attacker
POSTs a row of their OWN, so the token-forced `creator_fk` is theirs and every
check above passes; the row merely names a **victim's** parent in a `*_fk`
nobody was looking at. Where the FK is `ON DELETE RESTRICT` (14 of the 38) that
is a **grief-lock**: `DELETE /darwin/test_plans?id=<the victim's own>` answers 409
naming `fk_test_runs_plan`, held by a `test_runs` row scoped to the attacker —
invisible to the victim's GET, unaddressable by their PUT, untouchable by their
DELETE. **No self-service recovery exists.** The other 24 (CASCADE / SET NULL) are
cross-tenant attachment: the attacker's row living inside the victim's tree.

Shape differs from `JUNCTION_OWNERSHIP` in two ways, both deliberate:

- **No scope column.** Ownership is settled by `creator_fk`, so every entry is
  checked *when present* and never *required*. An absent reference means "not
  set" on POST and "unchanged" on PUT; a genuinely missing NOT NULL column is
  MySQL's 1364 to report, not a 400 from here.
- **No `fk_enforced` flag.** Every column came from a real `FOREIGN KEY`, so
  `priority_card_order`'s exception cannot arise — "parent does not exist" always
  falls through to 409/1452.

**PUT needs the guard as much as POST**, for the same reason it did for
junctions: `PUT /darwin/test_runs [{"id": <my run>, "test_plan_fk": <their
plan>}]` passes the `creator_fk = %s` predicate on a row the caller really owns,
then re-points it. The guard used to sit in the `else` of `if table in
CREATOR_FK_TABLES`, so no creator table ever reached it.

Everything else is inherited from #3122 unchanged — canonicalization by MySQL's
grammar, verdict derived from returned rows, 403 / 400 / 409-1452, one SELECT per
parent table.

### A body's KEYS are SQL identifiers — `check_body_keys()`

Found reviewing #3125 and it defeated **both** registries. Every ownership check
reads a key with `body.get('area_fk')` (exact Python match); `rest_post`/`rest_put`
interpolate that key as a **SQL identifier**, where MySQL's rules differ. Measured
against darwin_dev, each of these wrote `tasks.area_fk` while the guard saw
nothing and answered 200: `{"AREA_FK": n}` (case-insensitive), `` {"`area_fk`": n} ``
(backticks are quoting syntax), `{"area_fk ": n}` (token separation),
`{"area_fk/*x*/": n}` (comment the lexer discards).

- **Charset restriction, not normalization.** Keys must be `[A-Za-z0-9_$]+`; no
  fold-and-strip routine can enumerate what MySQL's lexer throws away. That
  leaves case, which `body_column()` then matches explicitly.
- **A post-fold collision is refused, never resolved.** MySQL applies the LAST
  assignment of a repeated column, so `{"test_plan_fk": <mine>, "TEST_PLAN_FK":
  <theirs>}` would have the guard approve one value and the statement apply the
  other. 400.
- **`creator_fk` had the same hole.** `if 'creator_fk' in body` missed
  `{"CREATOR_FK": "<their sub>"}`, so `rest_put`'s override — the thing that
  stops a body pushing a row into another account — was bypassed and the row was
  handed over. `force_column()` replaces whatever spelling was used.
- Applied on POST and PUT for **every** table. `rest_delete` already validated
  keys against `DESC` (req #3122).

Bulk POST gained a column-uniformity check with it: a column in item 0 but absent
later raised `KeyError` outside the try block and became a **503 naming nothing**;
absent from item 0 but present later was silently **dropped** from the INSERT
while the guard still inspected it. Both are now a 400.

> **The rule:** anything this gateway both CHECKS and WRITES must be read by the
> check exactly as the writer writes it — keys as well as values. #3122 learned
> it for values (`'9825_0'`); this is the same lesson for keys.

**Status note:** on the 25 newly-covered tables a non-integer reference is now a
**400** where MySQL used to coerce it into a 409/1452. That is the #3122 rule
reaching new tables, not a new rule.

**The list is DERIVED, never hand-maintained.** The audit that filed this
requirement counted eleven columns; `schema.sql` says thirty-six.
`test_unit_creator_fk_references.py` re-derives it on every run — a new FK column
fails the build until registered. `UNCHECKED_CREATOR_REFERENCES` is the
written-down exemption set and is empty. Cross-tenant coverage is
`tests/test_creator_fk_references.py` (21 tests; 16 fail without the fix, the
other 5 being victim-side regression tests that must pass either way).

## Bounded value domains — a NOT NULL enum is never written BLANK (req #3432)

`ENUM_COLUMNS` is the fifth registry in `auth_utils.py` and the only one that is not
about authorization. It answers *is the empty string a legitimate value for this
column*, and for a column whose value set is `haiku|sonnet|opus|fable` the answer is
always no. `check_enum_blanks()` refuses a write that NAMES such a column and supplies
`''`, whitespace, JSON `null`, or the `"NULL"` clear-sentinel — **400**, before any
statement runs, on `rest_post` (single + bulk) and `rest_put`. Not on `rest_delete`:
there a body key is a WHERE filter, and `ai_model=''` is a legitimate query.

**`''` is a legal VARCHAR, which is the whole problem.** Nothing in the schema forbids
it, this RDS instance runs a non-strict `sql_mode` (`NO_ENGINE_SUBSTITUTION`), and every
reader that switches on the enum then matches no branch. Measured in production
2026-08-09: 18 `requirements` rows carried `ai_model=''` and/or `effort=''`, and
`/swarm-start` reads those two columns straight into the launch command — an affected
requirement launches as `claude --model '' --effort ''`.

**The mechanism that produced those rows is the OTHER one, deliberately.** They came
from OMISSION — `requirements.ai_model` and `.effort` are the only enum columns in the
schema with no column `DEFAULT`, so an INSERT that does not name them gets MySQL's
implicit empty-string fill. Req #3434 closes that by giving both a `DEFAULT`, which is
why **an absent key is untouched here**: on a POST it means "take the column default",
on a PUT "unchanged". This registry closes the door #3434 does not — a caller that sends
the key with nothing in it. No such caller existed in the codebase when this was written;
it lives at the gateway precisely because the gateway is the single DB gateway and is the
only place that covers the writer nobody has written yet.

**Only blank is refused, never the domain.** The allowed values are deliberately not
stored: a value list this file did not enforce would drift from darwin-mcp, which does
enforce them, and a value list it DID enforce would refuse a new enum member the day it
ships in code and before it is copied here. Blank is the one value that is wrong under
every version of every domain.

**Keys are read with `body_column()`**, so `{"AI_MODEL": ""}` is caught — the § *A body's
KEYS are SQL identifiers* rule, which had already defeated two other registries.
`check_body_keys` runs first on every path, so at most one spelling can match.

**The candidates are DERIVED, the classification is written down.**
`tests/test_unit_enum_blank.py` re-parses `schema.sql` for every NOT NULL column that is
a real `ENUM(...)` or a CHAR/VARCHAR no wider than 32 — 46 columns today — and fails
unless each is in `ENUM_COLUMNS` or `FREE_TEXT_NOT_NULL_COLUMNS` (41 + 5). A new enum
column fails the build until registered.

**That width rule is a FILTER, NOT A PROOF, and the difference is load-bearing.** It
sweeps the shapes an enum is usually written in; a bounded domain declared wider is real
and simply will not be swept. Two are — `swarm_completes.skill_name` VARCHAR(64)
(`VALID_COMPLETE_SKILL_NAMES`, two members) and `user_integrations.provider` VARCHAR(50)
(`'strava'`) — both accepted `''` silently until they were **registered by hand**, which
brings `ENUM_COLUMNS` to **43 columns across 28 tables**. The test asks a different
question of those: they are checked to EXIST in the DDL, not to have been swept. Raising
the bound instead would drag in every VARCHAR(64) name and `creator_fk` itself, trading a
reviewable exemption list for an unreviewable one. NOT NULL `TINYINT` flags are outside
the registry altogether — `''` coerces to `0` there, a real member of the domain.

Unlike `UNSCOPED_TABLES` and
`UNCHECKED_CREATOR_REFERENCES`, the exemption set here is **not empty and cannot be** —
the candidate rule is structural, so genuine free-text columns match it:
`domains.domain_name`, `areas.area_name`, `map_views.name` (user-typed, and Darwin's
"type into the blank row" pattern POSTs them empty), `map_runs.activity_name` (whatever
the Cyclemeter/Strava/KML import found), `agents.ai_model` (the RESOLVED model id
`opus[1m]`, which the schema comment marks as explicitly NOT the family enum — while
`agents.effort` IS that family and is registered).

## Error Status Contract

Every failure used to be a 500 whose body was the raw pymysql string, so a client
could not tell "you picked a taken name" from "the database is broken" without
regexing prose. **Req #3059** carved out the conflicts:

| MySQL errno | Meaning | Status |
|---|---|---|
| 1062 | Duplicate entry — UNIQUE / PRIMARY KEY collision | **409** |
| 1451 | Cannot delete or update a parent row (FK RESTRICT) | **409** |
| 1452 | Cannot add or update a child row (FK target missing) | **409** |
| everything else | 1054 unknown column, 1364 no default, 2013 lost connection, … | 500 |

**403 is not on this table and that is the point (req #3122).** It is not a MySQL
outcome at all — it is the gateway refusing before the statement runs, when a
write names a parent row that *exists and belongs to another creator*. A parent
that does not exist stays a **409/1452**: absent is not the same as foreign, and
retrying a typo'd FK with different data genuinely can succeed, which is the
promise 409 makes and 403 does not. The body is a bare `"FORBIDDEN"` — the log
carries which ids were refused, the response never does.

The line is the promise a 409 makes: *retrying with different data can succeed*.
Do not widen `INTEGRITY_ERRNOS` without checking a new errno keeps it — a client
that retries on a 409 it can never satisfy loops forever.

409 body (single-encoded JSON **object**, unlike every other error status, which
sends a bare JSON string):

```json
{"error": "CONFLICT", "errno": 1062,
 "constraint": "uq_instructions_name", "table": "instructions",
 "message": "HTTP PUT SQL FAILED: 1062 Duplicate entry 'x' for key 'instructions.uq_instructions_name'"}
```

- `constraint` is **unqualified** — MySQL 8 reports the key as `table.index`, 5.7
  as `index`; the qualifier is stripped so it matches the name the DDL declares.
  Every table has a `PRIMARY`, so it only identifies anything paired with `table`.
- `table` comes from the handler, not from parsing the driver message.
- `message` is byte-identical to what the 500 path used to send. That is a
  compatibility promise: `darwin-mcp/darwin_rest/client.py` falls back to
  substring-matching it, and log greps written against the 500 era still work.

Applies to `rest_post.py` (single + bulk), `rest_put.py`, `rest_delete.py`
(single + bulk). **NOT** to rest_post's post-insert read-back failure — that 500
means the INSERT already committed, and `darwin-mcp`'s `post_junction` reads it
that way. Helpers + boundary are unit-tested in `tests/test_unit_conflict.py`
(no DB needed).

## CRUD Modules

### rest_get_database.py
- Triggered when GET path has no table segment (e.g., `/darwin_dev`)
- Runs `SHOW tables`, returns list of table name strings
- Triple-encoded: calls `json.dumps(columns_array)` then passes result to `compose_rest_response` which calls `json.dumps` again

### rest_get_table.py
- Triggered when GET path has a table segment (e.g., `/darwin_dev/areas`)
- Step 1: `DESC {table}` to discover columns (used to validate QSPs and build JSON_OBJECT)
- Step 2: Parse query string parameters into WHERE clause, ORDER BY, fields/count/group_by
- Step 3: Build and execute SQL using `CONCAT('[', GROUP_CONCAT(JSON_OBJECT(...)), ']')` to produce JSON directly from MySQL
- QSP features: column=value filters, IN clause via `col=(1,2,3)`, `sort=col:asc`, `fields=col1,col2`, `fields=count(*),group_col`, `filter_ts=(col,start,end)`
- Returns `row[0]` (a tuple) to `compose_rest_response` — causes double-encoding

### rest_post.py
- Accepts a single object (dict) body, or an array (bulk path, `_rest_post_bulk`)
- Single object: INSERT into table, then `DESC {table}`, then SELECT LAST_INSERT_ID() **only if the body supplied no id and `DESC` says `id` is `auto_increment`**, then re-reads the full row using JSON_OBJECT and returns it (200)
- Four separate try/except blocks: insert, DESC, get ID, read-back
- **The INSERT is the only step that can produce a 500.** Once it commits (autocommit), every later step — DESC, LAST_INSERT_ID, the read-back, and any `pymysql.Error` out of any of them — degrades to `201 CREATED` with an empty body. Reporting a committed row as a failed write is what req #3057 fixed; a lost connection or a read timeout during the read-back is the same lie under a different error code
- **A table with no `id` column skips the read-back entirely** and returns 201 — that is every junction table (composite PK). The `DESC` runs before LAST_INSERT_ID precisely so the column list is available to make that call (req #3057)
- **Which id the read-back uses (req #3094).** In order: the id the **body** supplied; else `LAST_INSERT_ID()`, but **only when `DESC` says the `id` column is `auto_increment`** (column 6, `Extra`); else 201 with no body. `LAST_INSERT_ID()` is meaningful only for a value MySQL *generated* — it stays 0 both on a non-`AUTO_INCREMENT` id and on an explicit id written into an `AUTO_INCREMENT` column, and `db_connection.py` opens a fresh connection per invocation so there is no earlier value to inherit. **A `LAST_INSERT_ID()` of 0 must never reach the read-back.** `profiles.id` is a `varchar(64)` Cognito sub, so `WHERE id=0` made MySQL coerce the column to a number and match every id not starting with a digit — `GROUP_CONCAT` with no `GROUP BY` then handed the POSTing caller a pile of other users' profiles. Regression-locked in `tests/test_profiles_readback.py` (the `TestReadBackIdSelection` half needs no DB)
- **The read-back id is bound, not interpolated** — `WHERE id=%s`. A non-generated id binds as a **string** so MySQL compares varchar to varchar; binding a number would coerce the column instead, which is the #3094 defect
- Array body: one multi-value INSERT, no read-back, `201 {"inserted": N, "first_id": M}`. The whole statement rolls back on failure
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

- **`db_dict` is a string, not a dict (line 27-70)**: `db_dict = os.environ['db_name']` assigns the string (e.g., `'darwin,darwin_dev'`). The check `db_info['database'] in db_dict` (line 70) performs a **substring match** on the string, not a dict key lookup. Works because `db_names` was fixed to use `set(os.environ['db_name'].split(','))` with proper set membership test.

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
- Database: MySQL on AWS RDS (darwin for production, darwin_dev for testing)
- Env vars: `endpoint`, `username`, `db_password`, `db_name`
