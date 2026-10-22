"""Pipeline 2.0 derivation (req #3349, MOVED HERE by req #3367) — beside
`darwin-mcp/services/pipeline_derive.py` (the 1.0 module, a different
repository), not in place of it. Both eras run at once until 1.0 is eradicated
(`memory/pipeline-2-first-principles.md` § 10); this module must not import
from, call, or otherwise touch `pipeline_derive.py`, and that module is
untouched by this requirement — byte-identical to what it was before.

**This is now the ONE copy.** Req #3367 (remediation B, composing form —
`memory/pipeline-2-orchestration-algorithm.md` § 8) moved this file out of
`darwin-mcp/services/` and into Lambda-Rest, where `pipeline2_compose.py`
imports it directly. darwin-mcp no longer carries a copy — its own
`get_pipeline2_composed` / `get_pipeline2_epic_composed` are now a ONE-CALL
passthrough to the composing route this module is imported by. `derive_plan2`
is the "guarded call to a real deriver" that module's docstring once promised;
the guard now lives in `pipeline2_compose.py`.

## Scope — what this module is, and what it deliberately is not

Req #3345's own docstring names "eligibility/state/display-order/launch-batch
logic" as this requirement's scope, written before req #3329 authored the
stage-3 split. That split is now the ground truth (`memory/pipeline-2-
orchestration-algorithm.md` § 11), and the authoritative boundary is the
verification register `scripts/swarm/verification/pipeline2_behaviours.json`
(req #3376's coverage gate, which this requirement's own acceptance criteria
name): DRV-001 through DRV-018, DRV-020 and DRV-021 are `req: 3349`. That set
DOES include a plain step-scoped `eligibility` (DRV-005/006 — a pending
step's own dep graph and its own `not_before` against the payload's clock,
with no batch or cross-step term) and pause-driven launch suppression
(DRV-016/017/018 — `launch_suppressed`/`suppressed_by` per row and the
`pause` block, epic-scoped because containment gives epic pause a real scope
key). It does NOT include reservations, debounce or commanded-requirement
tracking (owned by req #3368 — see ENG-005/006/009, CLI-012 through CLI-016
in the same register) — those are the ENGINE'S restatement, which consumes
`derived['pause']`/`eligible` rather than recomputing them, and DRV-019
("a derived block carrying no `pause` state is a hard stop") is that
consumer's own defensive posture toward a payload this module did not
produce, not a second implementation. There is also no `launch_batches`
here at all — Batch does not exist in 2.0
(`memory/pipeline-2-first-principles.md` § 6, DRV-021): the Step is the
launch unit, so what 1.0 computes once per batch this module computes once
per row.

**Serial "turn" suppression IS this module's, and the register above is
INCOMPLETE about it, not silent on purpose.** Req #3349's own GATE DELTAS
section (stage-2 gate, req #3336, 2026-08-08) names it directly: "SERIAL
MODE (req #3388, live on 1.0 since 2026-08-08): consume `execution_mode`;
emit the `derived.serial` block mirroring 1.0's shipped shape". That
sentence is an instruction TO this requirement, not a description of
something already built, and `scripts/swarm/verification/
pipeline2_behaviours.json` has no `DRV-*` entry for it at all — on ANY
requirement, not just this one — which is a gap in the register, not
evidence the work is out of scope. `serial_state` and `serial_deadlocks`
below restate 1.0's `pipeline_derive.serial_state`, with one addition the
gate delta itself calls for and 1.0 has no equivalent of: cross-epic edges
are legal here (item 4), so a BACKWARD one — a step depending on a
not-yet-live epic's step — is a structural deadlock under `serial` and is
reported as a LOUD `serial-deadlock` violation rather than an
indistinguishable stall.

## What changed, item by item (req #3349's own numbering)

1. **`epic_id` is a column read.** `pipeline2_steps.epic_fk` is NOT NULL, so
   there is no tally, no tie-break, and no inheritance walk. `dominant_labels`,
   `inherited_labels` and the `label_inherited` flag do not exist here;
   `epic_id` and `epic_labels` and their retired middle-tier counterparts do
   not appear on a derived row — an unlabelled step cannot exist under this
   schema, so there is nothing to borrow from a dependency. Measured against
   the live plan (163 steps) via the 1.0 field this module's `epic_id` column
   replaces: `label_inherited` was set on exactly 1 of 163 rows (step 11, a
   req-less gate) — that one walk is what this item deletes, not seventeen.

2. **`requirement_counts` groups by the STEP's `epic_fk`**, not by a chain
   through the requirement's own retired middle-tier link -> `epic_fk` —
   that tier does not exist in 2.0, so there is no other chain to read. This
   changes the ANSWER where a requirement's step sits under a different epic
   than its retired middle-tier record did.
   **Measured against the live plan, 2026-08-09** (206 non-tracking
   requirements, re-grouped by the step each is linked to in the live 1.0
   composed read's own `derived.rows[].epic_id`, which is the field the 2.0
   importer itself reads — see `memory/pipeline-2-data-architecture.md`
   § 7.2): **zero requirements change bucket, and both the overall and the
   per-epic met/total numbers are byte-identical before and after.** One
   requirement (#3077) links two steps (14 and 15), both seated in epic 5,
   which is also its own feature's epic — the sole multi-seat case on this
   plan (`memory/pipeline-2-mcp-surface.md`'s "1 of 255", req #3077) does not
   disturb the count. This is a real, reproducible measurement and not an
   assumption that the two groupings agree in general — they diverge exactly
   when a requirement's step is seated under a different epic than the
   requirement's own feature, which is zero times on today's plan and is not
   zero by construction.

3. **The time-gate branch is deleted.** `pipeline2_step_deps.dep_step_fk` is
   NOT NULL (data record § 3) — a dep row has exactly one meaning, so there is
   no discriminator to branch on and no `time_deps` bucket to build. The
   per-row `time_deps` field this module's rows once might have carried does
   not exist; a step's own time gate is already visible to any reader of
   `model['steps'][*]['not_before']` without this module re-surfacing it.
   `now` still rides `derive_plan2`'s output, for the reason given in
   "Scope" above.

4. **Display order is a tree walk**, epic order first
   (`memory/pipeline-2-orchestration-algorithm.md`'s gate delta, recorded on
   req #3364): a manual `pipeline2_epics.sort_order` wins where set; epics
   with no manual order are placed after, started ones first by an earliest-
   activity proxy (ascending), unstarted ones last in creation (id) order.
   See `_epic_block_order`'s docstring for the honest residue here — the
   composed read carries no `started_at` anywhere (steps or the light
   requirement projection), so "start" is approximated from a step's own
   `create_ts`, not the richer timestamp chain the browser's separate
   derivation (req #3372) can afford to read.

   **CROSS-EPIC DEPENDENCY EDGES ARE LEGAL** — this requirement's own
   stage-2 gate delta (req #3336, 2026-08-08) reverses the body text above:
   "the walk and the banding invariant handle crossing edges exactly as the
   live 1.0 plan already does". So `display_order` is ONE global
   topological walk (structurally `pipeline_derive.
   display_order`'s algorithm, minus the batch/stream machinery — there is
   no batch to cluster) with epic order used as a CLUSTERING tie-break, not
   a hard partition: a row still never renders before a dependency in
   another epic, and epic blocks are not guaranteed contiguous, exactly as
   1.0 is not guaranteed contiguous by first-appearance today.

   There is no state band and no banding self-check: a step has no state
   (req #3750), so the walk orders by topology, then epic, then run mode,
   then id.

5. **The conformance corpus is untouched here, on purpose.** All 34 cases in
   `tests/conformance/pipeline_conformance.json` mention the retired middle
   tier, and re-expressing it is, in this requirement's own words, "the largest single
   dependency here and it cannot be finished alone" — its fate depends on req
   #3329's single-source-of-truth choice, which is now decided: **Remediation
   B, in its composing form** (`memory/pipeline-2-orchestration-algorithm.md`
   § 8.1 — one derivation, moved into Lambda-Rest behind a composing route;
   `pipelineModel.js` deleted). Stated as that record instructs: **under B the
   corpus stops being a drift control and becomes an ordinary test suite of
   ONE implementation** — it is not deleted, its 34 cases still encode real
   derivation behaviour, but re-pointing and re-expressing it in the 2.0 shape
   is req #3367's job ("the corpus re-pointed at one target"), which depends
   on this requirement rather than the reverse. There is, today, no second 2.0
   implementation for a corpus to detect drift against in the first place —
   `pipelineModel.js`'s 2.0 counterpart has never been built and, under B, one
   never will be. This module's own test suite (`tests/unit/
   test_pipeline2_derive.py`) is the ordinary-test-suite half of that answer
   in the meantime.

6. **Tests** live in `tests/unit/test_pipeline2_derive.py`: one per deleted
   field asserting it is absent from a derived row, the tree-walk order
   including the amended three-step case, and `requirement_counts` grouping
   by the seated epic.

## Added after the fact: DEPENDENCIES ARE A PRIORITY, NOT A GATE (req #3597, 2026-10-17)

User rule, every plan, always: whenever the machine has a free slot, launch-
ready work is started even when its step's dependency gate is not satisfied.
`launch_candidacy` answers "may this step's work be announced" WITHOUT asking
about its dependencies (it keeps the time gate and the `swarm_ready` rule),
and `launch_candidate_step_ids` lists the candidates gate-open first, then
down the chain in display order. The gate is still computed and REPORTED
(`gate_open`, and `eligible` for the view's eligible-now ring).

**One dependency stays a gate** (the user's amendment, same day; a per-step
FLAG since req #3649): a CHECKPOINT — `pipeline_steps.checkpoint`, on by
default — holds every step downstream of it, transitively, while it holds
OPEN WORK. `checkpoint_blocked_by` names the checkpoints holding a row.

## A STEP HAS NO STATE (req #3750, user ruling 2026-10-21)

"A step exists to hold requirements. It can hold none, all closed, all open
or any mix, and it has no state. A step just exists as a holder and has
orchestration engine controls." So there is no pending/running/done, no
`completed_at` stamp (the column is dropped) and no way to complete or
reopen a step. Every question the engine used to ask of a step's state is
asked of the requirements it holds, through ONE per-row fact:

  `open_req_ids` — the step's GATING requirements (non-tracking) whose
  status is not terminal (`met`/`deferred`/`wontfix`). An id the composed
  read did not resolve counts as open: holding is the safe direction.

A dependency is CLEAR when that step's `open_req_ids` is empty; a checkpoint
HOLDS while its own is not; an epic's serial turn ends when no step in it
holds open work. A step holding nothing holds nothing — it never gates.
Answered fresh from requirement statuses on every read, nothing here can go
stale when a requirement is added to a step later; a stored "done" could.
"""

import re
from datetime import datetime, timezone

__all__ = [
    'TERMINAL_REQUIREMENT_STATUSES', 'LAUNCHABLE_REQUIREMENT_STATUSES',
    'PAUSED_STATUS', 'MODE_PARALLEL', 'MODE_SERIAL',
    'is_tracking_requirement', 'open_requirement_ids',
    'build_plan_rows', 'display_order', 'verify_order', 'eligibility',
    'launch_candidacy', 'is_checkpoint',
    'open_checkpoints_upstream', 'plan_graph_outside',
    'pause_state', 'serial_state', 'requirement_counts', 'derive_plan2',
]

# Requirement statuses that are no longer open work. Byte-identical to
# `pipeline_derive.TERMINAL_REQUIREMENT_STATUSES` — this fact about the state
# machine did not change with Feature or containment, so it is not "ported",
# it is simply also true here.
TERMINAL_REQUIREMENT_STATUSES = ('met', 'deferred', 'wontfix')

# The ONLY status a `/swarm-start` argument may carry (req #3360, carried
# forward as gate delta F9 on THIS requirement — "without this the fix seated
# at step 266 dies"). See `pipeline_derive.LAUNCHABLE_REQUIREMENT_STATUSES`
# for the full reasoning on why `approved` and `development` are excluded;
# that reasoning is a property of the requirement state machine, not of
# Feature or containment, and is unchanged here.
LAUNCHABLE_REQUIREMENT_STATUSES = ('swarm_ready',)

# Why a requirement id is not in a step's launch argument list. One flat
# string per exclusion, `"<req_id> <reason>"` — matches
# `pipeline_derive`'s shape so a consumer reading both eras' payloads reads
# one grammar, not two.
EXCLUDED_CONTAINER = 'tracking container'
EXCLUDED_UNRESOLVED = 'unresolved — not in the composed read'
EXCLUDED_NO_STATUS = 'no status'

# The enum behind a step's `no_launch_reason` (gate delta F9). Per STEP, not
# per batch — 2.0 has no batch.
BLOCK_NO_LINKS = 'no-links'
BLOCK_CONTAINERS = 'containers'
BLOCK_NOT_READY = 'not-ready'

# The one value that means "do not swarm-start this scope" (req #3223),
# shared by `pipelines.pipeline_status`/`epics.epic_status` and their 2.0
# counterparts — one word, one meaning, at both scopes, in both eras.
PAUSED_STATUS = 'paused'

# How a plan runs its epics (req #3388, gate delta on THIS requirement:
# "consume `execution_mode`; emit the `derived.serial` block mirroring 1.0's
# shipped shape"). `parallel` is every epic at once and is the DEFAULT — an
# ABSENT value reads as parallel, matching every `pipeline2_pipelines` row
# written before this column existed a meaning for.
MODE_PARALLEL = 'parallel'
MODE_SERIAL = 'serial'

# Statuses that say a requirement's work has begun — the epic-order proxy's
# "started" test (`_epic_block_order`).
_STARTED_REQUIREMENT_STATUSES = ('development',) + TERMINAL_REQUIREMENT_STATUSES

_RUN_RANK = {'auto': 0, 'manual': 1}

# Byte-identical to `pipeline_derive._TIMESTAMP_RE` / `_to_epoch` — the
# grammar and the parse hazards it guards against (naive-UTC ambiguity,
# `datetime.fromisoformat`'s grammar widening across Python versions, NaN/inf
# poisoning a comparison) are properties of the TIMESTAMP data type, not of
# Feature or containment, so this is restated rather than imported (module
# docstring: this module must not import `pipeline_derive`).
_TIMESTAMP_RE = re.compile(
    r'^([0-9]{4})-([0-9]{2})-([0-9]{2})'
    r'(?:[ T]([0-9]{2}):([0-9]{2})(?::([0-9]{2})(?:\.([0-9]{1,6}))?)?'
    r'(Z|z|[+-][0-9]{2}:[0-9]{2})?)?\Z', re.ASCII)


def _to_epoch(value):
    """Darwin timestamps are NAIVE UTC; see `pipeline_derive._to_epoch` for
    the full parse-hazard rationale this restates verbatim. Returns `None`
    for anything unparseable — the caller treats that as NOT ELIGIBLE, never
    as passed."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            epoch = float(value)
        except OverflowError:
            return None
        return None if epoch != epoch or epoch in (float('inf'), float('-inf')) else epoch
    if not isinstance(value, str):
        return None
    match = _TIMESTAMP_RE.match(value)
    if not match:
        return None
    year, month, day, hour, minute, second, fraction, zone = match.groups()
    milli = int((fraction + '00')[:3]) if fraction else 0
    try:
        parsed = datetime(int(year), int(month), int(day),
                          int(hour or 0), int(minute or 0), int(second or 0),
                          milli * 1000, tzinfo=timezone.utc)
    except ValueError:
        return None
    epoch = parsed.timestamp()
    if zone and zone not in ('Z', 'z'):
        offset = int(zone[1:3]) * 60 + int(zone[4:6])
        if int(zone[1:3]) > 23 or int(zone[4:6]) > 59:
            return None
        epoch -= (-offset if zone[0] == '-' else offset) * 60
    return epoch


# ---------------------------------------------------------------------------
# Requirement-level derivation — unchanged by Feature's removal or epic_fk's
# arrival, so this is not a redesign, it is the same fact restated where this
# module needs it.
# ---------------------------------------------------------------------------

def is_tracking_requirement(req):
    """True when a requirement carries the req #3123 CONTAINER flag.

    Identical rule and identical numeric coercion to
    `pipeline_derive.is_tracking_requirement` — see that module's docstring
    for why a bare truthiness check is wrong on the string `"0"`. Two engines
    reading the same `requirements.tracking` column have to agree, so this is
    restated rather than imported (`pipeline2_derive` must not import from
    `pipeline_derive` — module docstring).
    """
    return _flag((req or {}).get('tracking'), default=False)


def _flag(value, default):
    """A TINYINT(1) column as a bool, with the column's own DEFAULT standing in
    for an absent or blank value — the coercion `is_tracking_requirement` has
    always used (`"0"` is False, `1`/`"1"`/`True` are True), shared by the
    req #3649 flags `checkpoint` (default 1) and `locked` (default 0)."""
    if value is None or value == '':
        return default
    if isinstance(value, bool):
        return value
    try:
        return float(value) != 0
    except (TypeError, ValueError):
        return default


def _index_by_id(rows):
    return {row['id']: row for row in (rows or []) if row and 'id' in row}


def _id_sort_key(value):
    """Numbers before strings, each in their own natural order — see
    `pipeline_derive._id_sort_key`. Restated for the same reason as above."""
    try:
        return (0, float(value), '')
    except (TypeError, ValueError):
        return (1, 0.0, str(value))


def _linked_req_ids(step_id, model):
    """Requirement ids linked to a step, in junction order."""
    return [link['requirement_fk'] for link in (model.get('step_requirements') or [])
            if link.get('step_fk') == step_id]


def _split_launchable(req_ids, tracking_ids, reqs_by_id):
    """Gate delta F9 (req #3360's rule, restated for 2.0). Returns
    `(launch_ids, excluded)` — the ids a step's `/swarm-start` may carry, and
    one record per id it may not, each carrying the reason. Order is the
    step's own junction order — the command a reader is told to run must be
    stable across cycles."""
    tracking = set(tracking_ids or [])
    launch_ids, excluded = [], []

    def note(rid, reason):
        excluded.append('%s %s' % (rid, reason))

    for rid in (req_ids or []):
        if rid in tracking:
            note(rid, EXCLUDED_CONTAINER)
            continue
        req = reqs_by_id.get(rid)
        if req is None:
            note(rid, EXCLUDED_UNRESOLVED)
            continue
        status = req.get('requirement_status')
        if status in LAUNCHABLE_REQUIREMENT_STATUSES:
            launch_ids.append(rid)
        else:
            note(rid, status if status else EXCLUDED_NO_STATUS)
    return launch_ids, excluded


def _launch_block(req_ids, tracking_ids, launch_ids):
    """WHICH of the three no-command cases this step is in — the enum, not
    the sentence. `None` when something IS launchable. Per STEP: 2.0 has no
    batch to ask this of, so there is exactly one member, always."""
    if launch_ids:
        return None
    if not req_ids:
        return BLOCK_NO_LINKS
    if set(req_ids) <= set(tracking_ids):
        return BLOCK_CONTAINERS
    return BLOCK_NOT_READY


_NO_LAUNCH_SENTENCE = {
    BLOCK_NO_LINKS: lambda excluded: 'no linked requirements — nothing to launch',
    BLOCK_CONTAINERS: lambda excluded: ('every linked requirement is a tracking '
                                        'container — nothing to launch'),
    BLOCK_NOT_READY: lambda excluded: (
        'nothing launchable — only %s launches: %s'
        % (', '.join(LAUNCHABLE_REQUIREMENT_STATUSES), ', '.join(excluded))),
}


def _no_launch_reason(block, excluded):
    return _NO_LAUNCH_SENTENCE[block](excluded)


def open_requirement_ids(req_ids, tracking_ids, reqs_by_id):
    """The step's OPEN WORK (req #3750): its gating (non-tracking) requirement
    ids whose status is not terminal, in junction order.

    THE ONE FACT every orchestration question about a step is asked through —
    a step has no state of its own. An id `reqs_by_id` does not resolve counts
    as OPEN: a checkpoint that cannot see its work keeps holding, which is the
    recoverable direction.
    """
    tracking = set(tracking_ids or [])
    open_ids = []
    for rid in (req_ids or []):
        if rid in tracking:
            continue
        req = reqs_by_id.get(rid)
        if req is None or req.get('requirement_status') not in TERMINAL_REQUIREMENT_STATUSES:
            open_ids.append(rid)
    return open_ids


# ---------------------------------------------------------------------------
# Build plan rows
# ---------------------------------------------------------------------------

def build_plan_rows(model):
    """Join the model tables into self-contained plan rows, in steps-array
    (insertion) order — callers MUST reorder via `display_order` before
    rendering or sequencing, exactly as 1.0 requires of its own rows.

    `epic_id` is `step['epic_fk']`, A COLUMN READ (item 1) — no tally, no
    tie-break, no inheritance walk, and no `epic`/`epic_labels`/
    `label_inherited` (nor their retired middle-tier counterparts) on the
    row: none of those concepts exist once a step's epic is a NOT NULL
    column. A consumer
    wanting the epic's title reads it off `model['epics']` by id — this
    module does not duplicate data the composed read already carries once.

    `dep_ids` come from `pipeline2_step_deps`, where every row is a plain
    step-to-step edge (`dep_step_fk` NOT NULL, data record § 3) — there is no
    second condition kind to bucket separately, so unlike
    `pipeline_derive.build_plan_rows` there is no `time_deps` output at all
    (item 3).
    """
    reqs_by_id = _index_by_id(model.get('requirements'))
    steps = model.get('steps') or []

    dep_ids_by_step = {}
    for dep in model.get('step_deps') or []:
        dep_ids_by_step.setdefault(dep['step_fk'], []).append(dep['dep_step_fk'])

    rows = []
    for step in steps:
        req_ids = _linked_req_ids(step['id'], model)
        unresolved = [rid for rid in req_ids if rid not in reqs_by_id]
        tracking_ids = [rid for rid in req_ids
                        if is_tracking_requirement(reqs_by_id.get(rid))]
        launch_ids, launch_excluded = _split_launchable(req_ids, tracking_ids,
                                                         reqs_by_id)
        block = _launch_block(req_ids, tracking_ids, launch_ids)
        tracking_set = set(tracking_ids)
        started = any(
            (reqs_by_id.get(rid) or {}).get('requirement_status')
            in _STARTED_REQUIREMENT_STATUSES
            for rid in req_ids if rid not in tracking_set)
        rows.append({
            'id': step['id'],
            'title': step.get('title'),
            'run': step.get('run') or 'auto',
            # req #3649 — the step's two stored flags. `checkpoint` is what
            # the hold walk reads (`is_checkpoint`); `locked` is carried for
            # the view and enforced by the gateway, never here.
            'checkpoint': _flag(step.get('checkpoint'), default=True),
            'locked': _flag(step.get('locked'), default=False),
            'notes': step.get('notes'),
            'open_req_ids': open_requirement_ids(req_ids, tracking_ids,
                                                 reqs_by_id),
            'epic_id': step.get('epic_fk'),
            'req_ids': req_ids,
            'tracking_req_ids': tracking_ids,
            'unresolved_req_ids': unresolved,
            'launch_req_ids': launch_ids,
            'launch_excluded': launch_excluded,
            'launch_block': block,
            'swarm_start_command': (
                f"/swarm-start {' '.join(str(r) for r in launch_ids)}"
                if launch_ids else None),
            'no_launch_reason': (None if launch_ids
                                 else _no_launch_reason(block, launch_excluded)),
            'dep_ids': dep_ids_by_step.get(step['id'], []),
            # Internal to this module's ordering/eligibility passes only —
            # never on the payload a caller of `derive_plan2` sees (stripped
            # in `derive_plan2`'s own row projection, matching 1.0's compact-
            # block discipline, `test_the_derived_block_is_compact_ids_and_
            # enums_only`'s 2.0 counterpart). `_not_before` is the raw gate
            # `eligibility()` resolves into the public boolean `eligible` —
            # the raw value itself is item 3's `time_deps` deletion target
            # and must not reappear on the public row.
            '_create_ts': step.get('create_ts'),
            '_started': started,
            '_not_before': step.get('not_before'),
        })
    return rows


# ---------------------------------------------------------------------------
# Ordering — the tree walk (item 4)
# ---------------------------------------------------------------------------

def _epic_block_order(epics, rows_by_id):
    """Epic block order: manual `sort_order` wins where set; else started
    epics by an earliest-activity proxy ascending; unstarted epics after, in
    creation (id) order. (`memory/pipeline-2-orchestration-algorithm.md`'s
    gate delta, recorded on req #3364.)

    **The residue, stated plainly.** The browser's own derivation of "start"
    (req #3372) reads a requirement's `started_at`/`completed_at` — columns
    this composed read's light requirement projection does not carry
    (`memory/pipeline-2-mcp-surface.md` § 6.2's `_REQUIREMENT_FIELDS`), and
    which no `pipeline2_*` table carries at the epic level either. The only
    timestamp available to a server-side reader of THIS payload is a step's
    own `create_ts`. So "start" here is approximated as the earliest
    `create_ts` among an epic's own steps holding work that has begun (a
    gating requirement in `development` or terminal) —
    when a step actually started work is not recoverable from this payload,
    when it was authored into the plan is. This is a proxy, not a
    reproduction of the browser's richer chain, and a future session
    reconciling the two derivations should re-measure rather than assume
    they agree.

    An epic with no such step (including an empty epic) is
    "unstarted" and sorts by id — AUTO_INCREMENT order is creation order on
    this schema, the same idiom `pipeline_derive._id_sort_key` documents.
    """
    manual, derived = [], []
    for epic in epics:
        eid = epic['id']
        sort_order = epic.get('sort_order')
        epic_row_ids = [rid for rid, row in rows_by_id.items()
                        if row.get('epic_id') == eid]
        started_ts = [rows_by_id[rid]['_create_ts'] for rid in epic_row_ids
                     if rows_by_id[rid].get('_started')
                     and rows_by_id[rid].get('_create_ts')]
        entry = {'id': eid, 'sort_order': sort_order,
                 'started': bool(started_ts),
                 'start_proxy': min(started_ts) if started_ts else ''}
        (manual if sort_order is not None else derived).append(entry)

    manual.sort(key=lambda e: (_id_sort_key(e['sort_order']), e['id']))

    def derived_key(e):
        if e['started']:
            return (0, e['start_proxy'], e['id'])
        return (1, '', e['id'])

    derived.sort(key=derived_key)
    return [e['id'] for e in manual] + [e['id'] for e in derived]


def display_order(rows, epics):
    """Design rule 3, re-derived for containment — and CORRECTED against the
    stage-2 gate delta on this requirement (req #3336, 2026-08-08): **cross-
    epic dependency edges are LEGAL**, reversing item 4's own body text
    ("a dependency edge cannot cross an epic"). The gate delta's instruction
    is explicit: "the walk and the banding invariant handle crossing edges
    exactly as the live 1.0 plan already does" — so this is ONE global
    topological walk, structurally identical to
    `pipeline_derive.display_order`'s core algorithm, with epic order
    (`_epic_block_order`'s override-tier sequence) standing in for 1.0's
    first-appearance `epic_idx` as a clustering tie-break — NOT a hard
    partition. What is dropped relative to 1.0 is only the batch/stream
    apparatus: 2.0 has no batch (`memory/pipeline-2-first-principles.md`
    § 6), so `stream()`/`group_tail` and everything that clustered pending
    batch-mates do not exist here.

    A row still never renders before a dependency, whichever epic that
    dependency belongs to. Epic blocks are consequently NOT guaranteed
    contiguous in the presence of a crossing edge — exactly as 1.0 is not
    guaranteed contiguous by first-appearance today — but `epic_idx` pulls
    same-epic rows together wherever topology leaves a choice.

    No state band (req #3750): a step has no state, so among the rows whose
    dependencies have all rendered the tie-break is the latest dependency's
    position, then epic order, then run mode, then id.

    Rows carrying an `epic_id` absent from `epics` (a truncated composed read
    withheld that epic's own row) sort after every known epic, in ascending
    epic-id order — the safe direction, matching 1.0's dangling-dependency
    posture of reporting rather than guessing.

    Cycle contract, matching 1.0: detect, report, deterministic fallback to
    stored (insertion) order for whatever is left standing.

    Returns `{rows, cycle_detected, cycle_step_ids, duplicate_step_ids,
    epic_order}`.
    """
    duplicate_step_ids = []
    seen_ids = set()
    for row in rows:
        if row['id'] in seen_ids:
            if row['id'] not in duplicate_step_ids:
                duplicate_step_ids.append(row['id'])
        else:
            seen_ids.add(row['id'])

    by_id = {row['id']: row for row in rows}       # last occurrence wins on a dup
    dedup_rows = list(by_id.values())
    epic_ids_known = {epic['id'] for epic in (epics or [])}

    epic_order = _epic_block_order(epics or [], by_id)
    unresolved_epic_ids = sorted(
        {row['epic_id'] for row in dedup_rows
         if row.get('epic_id') not in epic_ids_known},
        key=_id_sort_key)
    full_epic_order = epic_order + unresolved_epic_ids
    epic_pos = {eid: position for position, eid in enumerate(full_epic_order)}

    def epic_idx(row):
        return epic_pos.get(row.get('epic_id'), len(full_epic_order))

    idx = {row['id']: position for position, row in enumerate(dedup_rows)}

    def num_id(row):
        try:
            return float(row['id'])
        except (TypeError, ValueError):
            return float(idx[row['id']])

    remaining = {row['id']: row for row in dedup_rows}
    out, pos = [], {}
    cycle_detected, cycle_step_ids = False, []

    def sort_key(row):
        anchor = max([-1] + [pos[d] for d in (row.get('dep_ids') or []) if d in pos])
        return (float(anchor), epic_idx(row),
                _RUN_RANK.get(row.get('run') or 'auto', 0), num_id(row))

    while remaining:
        avail = [row for row in remaining.values()
                 if all(d not in remaining for d in (row.get('dep_ids') or []))]
        if not avail:
            rest = sorted(remaining.values(), key=lambda r: idx[r['id']])
            cycle_detected = True
            cycle_step_ids = [row['id'] for row in rest]
            out.extend(rest)
            break
        pick = min(avail, key=sort_key)
        pos[pick['id']] = len(out)
        out.append(pick)
        del remaining[pick['id']]

    return {'rows': out, 'cycle_detected': cycle_detected,
            'cycle_step_ids': cycle_step_ids,
            'duplicate_step_ids': duplicate_step_ids,
            'epic_order': full_epic_order}


def verify_order(rows, epic_scoped=False):
    """Design rule 3 self-check — structured violations, NEVER raised.

    `duplicate-id`, `cycle` and `topology` stay plan-wide, because they must:
    cross-epic dependency edges are LEGAL (gate delta, req #3336,
    2026-08-08), so a dependency can genuinely name a step in a different
    epic and these invariants have to see the whole graph to mean anything.
    There is no state-banding invariant: a step has no state (req #3750).

    `dangling-dependency` is CONDITIONAL on `epic_scoped`, and this is the
    fix for a real defect a code review caught: `get_pipeline2_epic_composed`
    narrows `steps` at the gateway (`epic_fk = E`) but fetches `step_deps` by
    `step_fk`, so an OUTGOING cross-epic edge arrives with its `dep_step_fk`
    pointing at a step this payload never fetched. Under `epic_scoped=True`
    that is EXPECTED — not a defect in the plan, a property of the scope —
    and reporting it as `dangling-dependency` (which reads as data loss or a
    stale FK) sends a reader chasing a corruption that does not exist while
    `eligibility` correctly, silently, and PERMANENTLY refuses to launch a
    step that was actually ready. The fix is not to make it launchable —
    this render genuinely cannot see whether the out-of-scope dependency
    holds open work — it is to say so honestly: those ids are collected into
    `out_of_scope_dep_ids` instead of a violation, and a caller wanting the
    true state reads the whole-plan render. `epic_scoped=False` (the
    default, matching `get_pipeline2_composed`) keeps 1.0's posture: every
    epic is present, so a dep not in `rows` is genuinely dangling — a
    truncated payload or a real data defect — and stays a loud violation.

    There is no `batch-contiguity` invariant here — 2.0 has no batch.

    Returns `(violations, out_of_scope_dep_ids)`.
    """
    violations = []
    posn = {row['id']: position for position, row in enumerate(rows)}

    seen_ids, dup_ids = set(), []
    for row in rows:
        if row['id'] in seen_ids:
            if row['id'] not in dup_ids:
                dup_ids.append(row['id'])
        else:
            seen_ids.add(row['id'])
    if dup_ids:
        violations.append({
            'invariant': 'duplicate-id', 'step_ids': dup_ids,
            'message': (f"duplicate step ids {', '.join(str(i) for i in dup_ids)} — "
                        "rows collapse silently; the rendered plan is missing steps"),
        })

    out_of_scope = set()
    for row in rows:
        for dep in (row.get('dep_ids') or []):
            if dep in posn:
                continue
            if epic_scoped:
                out_of_scope.add(dep)
            else:
                violations.append({
                    'invariant': 'dangling-dependency', 'step_ids': [row['id'], dep],
                    'message': (f"step {row['id']} depends on step {dep}, which is "
                                "not in the rendered rows"),
                })

    peeled, progress = set(), True
    while progress:
        progress = False
        for row in rows:
            if row['id'] in peeled:
                continue
            if all(d not in posn or d in peeled for d in (row.get('dep_ids') or [])):
                peeled.add(row['id'])
                progress = True
    stuck = [row['id'] for row in rows if row['id'] not in peeled]
    if stuck:
        violations.append({
            'invariant': 'cycle', 'step_ids': stuck,
            'message': (f"dependency cycle: steps {', '.join(str(i) for i in stuck)} "
                        "are in or gated behind a cycle; display fell back to "
                        "stored order"),
        })

    for row in rows:
        for dep in (row.get('dep_ids') or []):
            if dep in posn and posn[dep] > posn[row['id']]:
                violations.append({
                    'invariant': 'topology', 'step_ids': [row['id'], dep],
                    'message': f"step {row['id']} renders before its dependency {dep}",
                })

    return violations, sorted(out_of_scope, key=_id_sort_key)


# ---------------------------------------------------------------------------
# Eligibility (DRV-005/006) — a plain per-step predicate, no batch term
# ---------------------------------------------------------------------------

def _deps_clear(row, by_id):
    """No step dependency of this row holds open work (`open_req_ids`). ONE
    HALF of the gate.

    Split out of `_gates_open` by req #3597, which made this half a PRIORITY
    rather than a precondition for launching: `launch_candidacy` below asks
    only the time half, and orders candidates by this one. An unknown
    dependency (absent from `by_id`) is NOT clear — the safe direction.
    """
    for dep_id in (row.get('dep_ids') or []):
        dep = by_id.get(dep_id)
        if not dep or dep.get('open_req_ids'):
            return False
    return True


def _time_gate_passed(row, now):
    """This row's own `not_before` (if any) has passed relative to `now`. The
    OTHER half of the gate, and the one req #3597 left a precondition: a time
    gate is a person's stated "not before", not a dependency on other work, so
    a free slot is no reason to start early.

    No `now` — or an unparseable gate — while a gate exists means NOT passed,
    never passed: the safe direction, matching 1.0's posture exactly.
    """
    gate = row.get('_not_before')
    if not gate:
        return True
    now_epoch = _to_epoch(now)
    if now_epoch is None:
        return False
    gate_epoch = _to_epoch(gate)
    if gate_epoch is None or gate_epoch > now_epoch:
        return False
    return True


def _gates_open(row, by_id, now):
    """THE GATE, read by `eligibility` and reported per row as `gate_open`:
    no dependency holds open work, and this row's
    own `not_before` (if any) passed relative to the caller-supplied `now`.
    This module never reads the clock itself (`derive_plan2` is the one
    caller, and it is told `now` by ITS caller for the same reason
    `pipeline_derive.eligibility` documents: a stale clock must be visible as
    stale, not invisible).

    No batch term exists here — 1.0's `eligibility` is keyed off a batch's
    shared launch key; 2.0 has no batch, so this is purely a function of one
    row's own `dep_ids` and `_not_before` (DRV-005).

    **Since req #3597 this is a REPORT and a SORT KEY, not a launch
    precondition.** It still decides `eligible` (the view's eligible-now ring)
    and it orders `launch_candidate_step_ids`; it no
    longer decides whether work may be announced — `launch_candidacy` does.

    **An open CHECKPOINT upstream closes it too** (the user's amendment).
    `_deps_clear` sees only DIRECT dependencies, so a step whose own deps are
    clear while a checkpoint further up still holds would otherwise read
    gate-open — `eligible`, so the engine admitted it and announced it past
    the checkpoint (review C1, measured). The checkpoint term lives HERE so
    every predicate built on the gate honours it, not only candidacy.
    """
    return (_deps_clear(row, by_id) and _time_gate_passed(row, now)
            and not _checkpoint_blockers(row, by_id))


def eligibility(row, by_id, now=None):
    """IS THERE WORK HERE THAT MAY START NOW, GATE AND ALL? The view's
    eligible-now ring.

    A step has no state (req #3750), so this asks the requirements: the step
    holds launch-ready work (`launch_req_ids`) and its gate is open. Before
    #3750 it was split in two by step state — `eligible` for a pending step,
    `top_up_eligible` for a running one (req #3507) — and that split existed
    only because the state did; one predicate now answers both.
    """
    if not (row.get('launch_req_ids') or []):
        return False
    return _gates_open(row, by_id, now)


def is_checkpoint(row):
    """Is this step a CHECKPOINT — one that holds everything downstream of it
    while it holds open work? **The answer is the `pipeline_steps.checkpoint` column
    (req #3649), default ON**, never an inference from the step's links.

    Before #3649 a checkpoint was IMPLIED: a step with no work requirement
    (no links, or only tracking containers) was the one kind of step a
    person closes by hand, and only that kind held its downstream. The
    user's rule (2026-10-19) is that every step holds by default and a person
    turns the hold OFF to make a step a mere launch priority — so the fact is
    stored, and link shape says nothing about it any more. A checkpoint
    holds while its `open_req_ids` is non-empty (req #3750) — one holding no
    work holds nothing.
    """
    return _flag((row or {}).get('checkpoint'), default=True)


def _checkpoint_blockers(row, by_id):
    """`open_checkpoints_upstream`, read from the row's cache when
    `derive_plan2` has already walked it (one walk per row, not one per
    predicate), computed otherwise — for a caller handing in bare rows."""
    cached = (row or {}).get('_checkpoint_blockers')
    if cached is not None:
        return cached
    return open_checkpoints_upstream(row, by_id or {})


def plan_graph_outside(model, by_id):
    """The steps of this PLAN that this payload's rows do not carry, as
    `{step_id: {'dep_ids', 'checkpoint', 'open'}}` — so an EPIC-scoped read
    can still see a checkpoint in another epic (review I1: without it an
    epic-scoped orchestrator launched straight past one that a whole-plan
    orchestrator held).

    Read from `model['plan_graph']` — `{steps: [{id, checkpoint}],
    step_deps, step_requirements, requirements: [{id, requirement_status,
    tracking}]}` — which only the epic-scoped compose supplies; a whole-plan
    model carries every step already and has no outside. A step outside is a
    CHECKPOINT by its own column (req #3649, `is_checkpoint`), and it holds
    by exactly the rule applied inside the epic: it has open work
    (`open_requirement_ids`). The compose reads links and requirement rows
    for the outside checkpoints only.
    """
    graph = (model or {}).get('plan_graph') or {}
    reqs_by_id = _index_by_id(graph.get('requirements'))
    links = {}
    for link in graph.get('step_requirements') or []:
        links.setdefault(link['step_fk'], []).append(link['requirement_fk'])
    deps = {}
    for dep in graph.get('step_deps') or []:
        deps.setdefault(dep['step_fk'], []).append(dep['dep_step_fk'])
    outside = {}
    for step in graph.get('steps') or []:
        if step['id'] in by_id:
            continue
        checkpoint = is_checkpoint(step)
        req_ids = links.get(step['id'], [])
        tracking_ids = [r for r in req_ids
                        if is_tracking_requirement(reqs_by_id.get(r))]
        outside[step['id']] = {
            'dep_ids': deps.get(step['id'], []),
            'checkpoint': checkpoint,
            # Only a checkpoint's open work is ever read (the compose reads
            # links for checkpoints alone), so it is only claimed for one.
            'open': checkpoint and bool(
                open_requirement_ids(req_ids, tracking_ids, reqs_by_id))}
    return outside


def open_checkpoints_upstream(row, by_id, outside=None):
    """Every CHECKPOINT this row depends on, directly or transitively, that
    still holds open work — in id order. Empty means no checkpoint holds it.

    THE USER'S AMENDMENT TO req #3597 (2026-10-17): "requirements that I close
    by hand should block progress ... until I have cleared them". A
    checkpoint is the one dependency that is NOT a mere launch priority: it
    is a person's decision point, so everything downstream of it waits. Once
    its requirements are all closed (or it holds none) it blocks nothing.

    The walk goes THROUGH every ancestor, checkpoint or not, so a checkpoint
    two edges up holds the step as surely as one edge up, and a clear
    checkpoint does not release anything an open one further up still holds.
    A dependency absent from `by_id` is looked up in `outside` (the rest of
    the plan, which the epic-scoped compose supplies — `plan_graph_outside`),
    so a checkpoint in another epic holds this step exactly as it would under
    a whole-plan read. One found in neither is unknowable and does not block:
    treating every unseen edge as a possible checkpoint would withhold all
    cross-epic work, the opposite of the rule. A `visited` set makes a cycle
    terminate.
    """
    blockers, visited = set(), set()
    stack = list((row or {}).get('dep_ids') or [])
    while stack:
        dep_id = stack.pop()
        if dep_id in visited:
            continue
        visited.add(dep_id)
        dep = by_id.get(dep_id)
        if dep is not None:
            if is_checkpoint(dep) and dep.get('open_req_ids'):
                blockers.add(dep_id)
            stack.extend(dep.get('dep_ids') or [])
            continue
        far = (outside or {}).get(dep_id)
        if far is None:
            continue
        if far['checkpoint'] and far['open']:
            blockers.add(dep_id)
        stack.extend(far['dep_ids'])
    return sorted(blockers, key=_id_sort_key)


def launch_candidacy(row, by_id=None, now=None):
    """MAY THIS STEP'S WORK BE ANNOUNCED FOR LAUNCH? (req #3597.)

    THE USER RULE (2026-10-17, plan 10): bias orchestration toward STARTING
    work. A step's dependencies are a PRIORITY ORDER for launching, not a
    hard gate, on every plan, always — no mode, no flag. So this predicate
    deliberately does NOT ask `_deps_clear`; the engine fills free slots from
    gate-open candidates first (`launch_candidate_step_ids` carries that
    order) and then cascades down the dependency chain.

    THREE CONJUNCTS:

    * At least one `launch_req_ids` entry — only `swarm_ready`, non-tracking
      work is ever launch-ready (rule 8, req #3360). A step with nothing to
      command is not a candidate.
    * Its own time gate (`_time_gate_passed`). A `not_before` is a person's
      scheduling intention, not a dependency on other work.
    * No CHECKPOINT upstream is still open (`open_checkpoints_upstream`). A
      checkpoint step — `pipeline_steps.checkpoint`, ON by default (req
      #3649) — holds everything downstream of it while it holds open work,
      the one dependency that stays a gate; a step with the flag OFF is a launch
      priority and nothing more.

    Pause and serial turn-taking are NOT conjuncts here, exactly as they are
    not conjuncts of `eligible`: they are SUPPRESSION, carried separately on
    `launch_suppressed`/`suppressed_by`, so a reader can tell "may launch but
    is held by a person" from "has nothing to launch".

    A SUPERSET of every `eligible` step, never a replacement for it:
    `eligible` keeps answering the gate question for the view.
    """
    if not (row.get('launch_req_ids') or []):
        return False
    if not _time_gate_passed(row, now):
        return False
    return not _checkpoint_blockers(row, by_id)


def launch_queue(candidate_ids, by_id, reqs_by_id):
    """THE LAUNCH PRIORITY, as one ordered list — the only place it is stated
    (req #3649: "minimal and well tested … focused in a single area").

    `[{'step_id', 'requirement_id'}, ...]`: every requirement the engine may
    announce, in the order it hands out free slots. The engine consumes this
    list and ranks by position in it; it keeps no ordering rule of its own.

    THE ORDER:

    1. `candidate_ids` — launch candidates (`launch_candidacy`) gate-open
       first, then past their gate, each half in display order (req #3597:
       a dependency is WHO GOES FIRST, never WHETHER; a CHECKPOINT upstream
       has already removed a held step from candidacy).
    2. Within a step, `coordination_type == 'deployed'` first (a deployed
       worker closes itself through `/swarm-complete`, so its slot frees and
       the plan drains), then ascending requirement id — FIFO, since ids
       are allocated in creation order. **Within a step only** (user ruling
       2026-10-19, superseding req #3623's scope-wide preference): a later
       step's deployed work never jumps an earlier step's implemented work.

    A `launch_suppressed` step (pause, serial turn) is LEFT OUT — this is what
    WOULD be announced, and suppression is reported beside it on the row. A
    `run=manual` step is IN: where its READY-MANUAL reminder ranks against
    auto work is policy too, and the engine must not keep a second rule for
    it. Only *expiry* of a reminder's announce window — debounce state the
    derivation cannot see — stays an engine term.
    """
    queue = []
    for step_id in candidate_ids:
        row = by_id.get(step_id) or {}
        if row.get('launch_suppressed'):
            continue
        ids = list(row.get('launch_req_ids') or [])
        ids.sort(key=lambda rid: (
            0 if (reqs_by_id.get(rid) or {}).get('coordination_type') == 'deployed'
            else 1,
            _id_sort_key(rid)))
        queue.extend({'step_id': step_id, 'requirement_id': rid} for rid in ids)
    return queue


# ---------------------------------------------------------------------------
# Pause (DRV-016/017/018) — launch suppression, epic-scoped
# ---------------------------------------------------------------------------

def pause_state(model, rows):
    """Which scopes are paused, and therefore which steps must not be
    launched — restated for containment from `pipeline_derive.pause_state`,
    and simpler here: a step has exactly ONE epic (a column, not a
    tie-broken tally), so "the step's dominant epic is paused" collapses to
    a plain membership test.

    TWO SCOPES, ONE RULE, unchanged from 1.0: a step is suppressed when its
    PLAN is paused, or when its OWN epic is paused (DRV-017 — an epic pause
    suppresses that epic's steps and not its neighbour, because containment
    gives epic pause a real scope key no 1.0 epic ever had). An epic pause
    binds a WHOLE-PLAN orchestrator too (DRV-018): suppression is a property
    of the STEP, computed here regardless of which scope is asking, so there
    is nothing for a whole-plan orchestrator to opt out of.

    `eligible` (from `eligibility` above) is left UNCHANGED by this function
    (DRV-016) — it is called separately, over the same rows, and neither
    writes the other's field. A consumer distinguishes "eligible and
    suppressed" (waits on a person) from "not eligible" (waits on a gate) by
    reading both.

    `suppressed_by` is a LIST: when both clauses fire, naming only one would
    leave a reader who unpaused just the plan surprised the step is still
    held. A missing `epic_status` reads as `active` — the column's own
    default, and what every row written before an epic pause ever existed
    is.
    """
    pipeline = model.get('pipeline') or {}
    pipeline_status = pipeline.get('pipeline_status')
    pipeline_paused = pipeline_status == PAUSED_STATUS

    paused_epics = {epic.get('id') for epic in model.get('epics') or []
                    if epic.get('epic_status') == PAUSED_STATUS
                    and epic.get('id') is not None}

    suppressed = []
    for row in rows:
        reasons = []
        if pipeline_paused:
            reasons.append('pipeline')
        if row.get('epic_id') in paused_epics:
            reasons.append('epic')
        row['launch_suppressed'] = bool(reasons)
        row['suppressed_by'] = reasons
        if reasons:
            suppressed.append(row['id'])

    return {
        'pipeline_status': pipeline_status,
        'pipeline_paused': pipeline_paused,
        'paused_epic_ids': sorted(paused_epics, key=_id_sort_key),
        # In DISPLAY order — `derive_plan2` calls this after `display_order`,
        # so `rows` already carries the caller's rendered sequence.
        'suppressed_step_ids': suppressed,
    }


# ---------------------------------------------------------------------------
# Serial execution (gate delta, req #3388 — "live on 1.0 since 2026-08-08")
# ---------------------------------------------------------------------------

def serial_state(model, rows, epic_order):
    """Which epic's turn it is, and therefore which steps must WAIT for it —
    the `derived.serial` block, mirroring 1.0's shipped shape
    (`pipeline_derive.serial_state`): `{execution_mode, serial, epic_order,
    closed_epic_ids, live_epic_id, waiting_epic_ids, held_step_ids}`.

    `execution_mode` is the ONE stored fact — an intention, like a pause.
    Everything else is DERIVED: an epic's turn is CLOSED when no step it owns
    holds open work (`open_req_ids`, req #3750); the LIVE epic is the first one in `epic_order` that is not
    closed; an epic is BEHIND, LIVE, or AHEAD, and only the ones AHEAD are
    held.

    **`epic_order` is the caller's — this module's OWN tree-walk order
    (`display_order`'s `epic_order`), not a re-derivation from first
    appearance in `rows`.** This is a deliberate divergence from 1.0:
    1.0 has no stored or derived epic-order concept at all before this
    field exists, so its `serial_state` had to invent one from first
    appearance; 2.0 already has a principled epic order (item 4's
    override-tier rule — manual `sort_order`, else earliest-activity, else
    creation order), and re-deriving a second, cruder one here would be two
    answers to one question.

    A step whose epic is not the live one is suppressed with reason `turn`,
    appended to `suppressed_by` (which `pause_state` — called first — has
    already populated), never replacing it: a step held by both a pause and
    a turn must name both. A step with NO epic label cannot happen under
    2.0's `epic_fk NOT NULL` (unlike 1.0, where a req-less step could carry
    no label at all) — so unlike `pipeline_derive.serial_state` there is no
    "no epic label -> never held" carve-out to make here; every step has an
    epic and therefore a turn.

    Under `parallel` nothing is suppressed and no row is touched — the order
    and closure facts are still computed and returned, because they cost
    nothing over rows already in hand.
    """
    pipeline = model.get('pipeline') or {}
    mode = pipeline.get('execution_mode') or MODE_PARALLEL
    serial = mode == MODE_SERIAL

    rows_by_epic = {}
    for row in rows:
        rows_by_epic.setdefault(row.get('epic_id'), []).append(row)

    closed_epic_ids = [
        epic_id for epic_id in epic_order
        if not any(row.get('open_req_ids')
                   for row in rows_by_epic.get(epic_id, []))
    ]
    closed = set(closed_epic_ids)

    live_epic_id = None
    for epic_id in epic_order:
        if epic_id not in closed:
            live_epic_id = epic_id
            break

    waiting = {epic_id for epic_id in epic_order
               if epic_id not in closed and epic_id != live_epic_id}

    held = []
    if serial and live_epic_id is not None:
        for row in rows:
            epic_id = row.get('epic_id')
            if epic_id not in waiting:
                continue
            row['suppressed_by'] = list(row.get('suppressed_by') or []) + ['turn']
            row['launch_suppressed'] = True
            held.append(row['id'])

    return {
        'execution_mode': mode,
        'serial': serial,
        'epic_order': list(epic_order),
        'closed_epic_ids': closed_epic_ids,
        'live_epic_id': live_epic_id,
        'waiting_epic_ids': [e for e in epic_order if e in waiting],
        'held_step_ids': held,
    }


def serial_deadlocks(rows, epic_order, serial):
    """A BACKWARD cross-epic dependency edge on a `serial` plan — the gate
    delta's own new invariant, unique to 2.0: cross-epic edges are legal
    (item 4's gate delta), so a step can name a dependency in an epic that
    has not had its turn yet. Under serial execution that dependency is
    HELD by `serial_state` until its own epic goes live, which is after the
    depending step's epic has closed — so the edge can NEVER be honoured as
    an ordering.

    **IT IS NO LONGER A DEADLOCK (req #3597)**, and the message says so. It
    was one while a dependency GATED a launch: the depending step could not
    start, so its epic could not close, so the dependency's turn never came.
    Now a dependency is a launch PRIORITY, the depending step launches ahead
    of it and the plan runs. The edge is still reported, LOUDLY (design rule
    7), because an ordering the author wrote that the plan structurally
    inverts is almost certainly not what they meant. The invariant keeps its
    `serial-deadlock` key so no consumer of the wire format changes.

    A "backward" edge is one where the DEPENDENCY's epic sits AFTER the
    DEPENDING step's epic in `epic_order` — the depending step's turn
    finishes before the dependency's turn even starts. Only meaningful under
    `serial`; a parallel plan has no turn order for an edge to violate.

    Returns a list of `serial-deadlock` violations, empty when `serial` is
    False or no edge is backward.
    """
    if not serial:
        return []
    epic_pos = {eid: position for position, eid in enumerate(epic_order)}
    by_id = {row['id']: row for row in rows}
    violations = []
    for row in rows:
        row_pos = epic_pos.get(row.get('epic_id'))
        if row_pos is None:
            continue
        for dep_id in (row.get('dep_ids') or []):
            dep = by_id.get(dep_id)
            if dep is None:
                continue
            dep_pos = epic_pos.get(dep.get('epic_id'))
            if dep_pos is None or dep_pos <= row_pos:
                continue
            violations.append({
                'invariant': 'serial-deadlock',
                'step_ids': [row['id'], dep_id],
                'message': (
                    f"step {row['id']} (epic turn {row_pos}) depends on step "
                    f"{dep_id} (epic turn {dep_pos}) — a BACKWARD cross-epic "
                    "edge under serial execution. The dependency's epic only "
                    "goes live after this one closes, so this step ALWAYS "
                    "launches ahead of it (a dependency is a launch priority, "
                    "not a gate — req #3597) and the edge can never be "
                    "honoured as an ordering. Re-order the epics, move both "
                    "steps into one epic, or drop the edge."),
            })
    return violations


# ---------------------------------------------------------------------------
# Requirement counts (item 2)
# ---------------------------------------------------------------------------

def requirement_counts(model):
    """Met/total requirement counts, per epic and for the whole plan —
    RE-POINTED at the step's `epic_fk` (item 2): a requirement's bucket is
    now where its work is SEATED, not where its (nonexistent) feature was
    filed. `pipeline2_step_requirements` carries `PRIMARY KEY
    (requirement_fk)` alone (gate delta, req #3336) — one step per
    requirement, structural — so the lookup is a plain one-to-one join, not a
    tie-break.

    Tracking requirements are excluded from both the numerator and the
    denominator, unchanged from 1.0 (req #3123's container exemption). The
    numerator is `TERMINAL_REQUIREMENT_STATUSES` — the same statuses
    `open_requirement_ids` treats as no longer open.

    `by_epic` is a LIST, sorted by epic id ascending — matching 1.0's reason
    for the same shape: a Python dict with int keys silently stringifies
    under `json.dumps`, which would make this module's wire shape disagree
    with any 2.0 counterpart that renders a JS `Map` (not JSON at all) the
    same way. See the module docstring for the measured before/after delta
    on the live plan.

    **`overall`'s POPULATION follows `model['requirements']`, which is a
    different set depending on which composed read produced `model`** — the
    same "which population" caveat `get_pipeline2_epic_composed`'s own
    docstring states for `step_count` (req #3287). On the whole-plan read
    it is every requirement in the plan; on the epic-scoped read it is only
    the requirements linked to THAT epic's own steps, so `overall` there is
    identical to that epic's own `by_epic` entry — never the plan's true
    total. A caller rendering "N/M requirements complete" from an
    epic-scoped read is showing the epic's number, not the plan's, and must
    label it that way.
    """
    steps_by_id = _index_by_id(model.get('steps'))
    req_to_step = {}
    for link in model.get('step_requirements') or []:
        req_to_step[link['requirement_fk']] = link['step_fk']

    overall = {'met': 0, 'total': 0}
    by_epic = {}
    for req in model.get('requirements') or []:
        if not req or is_tracking_requirement(req):
            continue
        met = req.get('requirement_status') in TERMINAL_REQUIREMENT_STATUSES
        overall['total'] += 1
        if met:
            overall['met'] += 1
        step = steps_by_id.get(req_to_step.get(req['id']))
        epic_id = step.get('epic_fk') if step else None
        if epic_id is None:
            continue
        bucket = by_epic.setdefault(epic_id, {'epic_id': epic_id, 'met': 0, 'total': 0})
        bucket['total'] += 1
        if met:
            bucket['met'] += 1
    return {
        'overall': overall,
        'by_epic': sorted(by_epic.values(), key=lambda b: _id_sort_key(b['epic_id'])),
    }


# ---------------------------------------------------------------------------
# The whole derivation, in one call
# ---------------------------------------------------------------------------

def derive_plan2(model, now=None, epic_scoped=False):
    """Everything this requirement derives from one composed 2.0 payload:
    derive -> order -> check. Pure CPU over rows the composed read already
    fetched — zero additional gateway reads, matching design rule 5.

    Narrower than `pipeline_derive.derive_plan` in one respect: no batches —
    Batch does not exist in 2.0. `eligible`, `open_req_ids` (req #3750),
    `gate_open` / `launch_candidate` (req #3597),
    `pause` AND `serial` ARE built here (DRV-005/006/016/017/018 for the first two — the verification
    register's boundary, not req #3345's stale docstring; `serial` per the
    gate delta naming req #3388 explicitly, which the register does not
    cover at all — see the module docstring's Scope section). `now` rides
    the payload for the same reason 1.0 carries it, and because
    `eligibility` above is one of this module's own consumers of it.

    `epic_scoped` MUST be `True` when `model` came from
    `get_pipeline2_epic_composed` — it changes only how `verify_order`
    reports a dependency it cannot see (an honest `out_of_scope_dep_ids`
    entry instead of a false `dangling-dependency` alarm; see that
    function's docstring for the defect this fixes). It does not change
    ordering or eligibility: a step gated on an out-of-scope dependency is
    correctly, and unavoidably, `eligible: False` here either way — this
    payload cannot see whether that dependency holds open work, and the safe
    direction is not to guess. A caller that needs the true answer reads the
    whole-plan render instead.

    Every per-row field here is an id, an enum string, a boolean, or a short
    list of one of those — no re-embedded requirement or epic rows, matching
    1.0's "compact block" discipline (`test_the_derived_block_is_compact_
    ids_and_enums_only`'s reason, req #3078's payload budget).
    """
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

    plan_rows = build_plan_rows(model)
    ordered = display_order(plan_rows, model.get('epics') or [])
    rows = ordered['rows']
    violations, out_of_scope_dep_ids = verify_order(rows, epic_scoped=epic_scoped)
    # AFTER `display_order`, so `suppressed_step_ids` comes out in display
    # order, and it writes `launch_suppressed`/`suppressed_by` onto the same
    # row dicts the payload below projects — matching 1.0's ordering of the
    # two calls and its stated reason.
    pause = pause_state(model, rows)
    # AFTER `pause_state`, because it APPENDS to the `suppressed_by` list
    # that call creates rather than replacing it — a step held by both a
    # pause and a turn must name both (matches 1.0's ordering, req #3388).
    serial = serial_state(model, rows, ordered['epic_order'])
    violations = violations + serial_deadlocks(rows, ordered['epic_order'], serial['serial'])

    by_id = {row['id']: row for row in rows}
    # The user's amendment to req #3597 — ONE checkpoint walk per row, cached
    # on the row, before any predicate reads it (`_checkpoint_blockers`).
    outside = plan_graph_outside(model, by_id)
    for row in rows:
        row['_checkpoint_blockers'] = open_checkpoints_upstream(row, by_id,
                                                                outside)
    eligible_ids = [row['id'] for row in rows if eligibility(row, by_id, now)]
    eligible_set = set(eligible_ids)
    # req #3597 — the gate as a REPORT, and launch candidacy past it. The
    # candidate list is in LAUNCH PRIORITY order: gate-open candidates first,
    # then the rest, each half in display order — so a consumer filling free
    # slots walks it front to back and cascades down the dependency chain.
    gate_open_set = {row['id'] for row in rows if _gates_open(row, by_id, now)}
    candidates = [row['id'] for row in rows if launch_candidacy(row, by_id, now)]
    candidate_set = set(candidates)
    candidate_ids = ([i for i in candidates if i in gate_open_set]
                     + [i for i in candidates if i not in gate_open_set])
    # req #3649 — THE launch order, requirement by requirement. The engine
    # ranks by position in this list and nothing else.
    queue = launch_queue(candidate_ids, by_id,
                         _index_by_id(model.get('requirements')))
    out_of_scope_set = set(out_of_scope_dep_ids)

    unresolved = []
    for row in rows:
        for rid in row.get('unresolved_req_ids') or []:
            if rid not in unresolved:
                unresolved.append(rid)

    return {
        'now': (now.isoformat(timespec='seconds') + 'Z'
                if isinstance(now, datetime) else now),
        'epic_order': ordered['epic_order'],
        'display_order': [row['id'] for row in rows],
        'rows': [{
            'id': row['id'],
            'run': row['run'],
            # req #3649 — the two stored flags, so a reader can say WHY a
            # step holds its downstream (checkpoint) and draw the lock.
            'checkpoint': row['checkpoint'],
            'locked': row['locked'],
            'eligible': row['id'] in eligible_set,
            # req #3750 — the step's OPEN WORK, the one fact every question
            # about a step is asked through (a step has no state).
            'open_req_ids': row['open_req_ids'],
            # req #3597. `gate_open` is the gate REPORTED (no dep holds open
            # work and the time gate passed) — the view's "gate satisfied / waiting".
            # `launch_candidate` is whether this step's work may be announced
            # for launch, which no longer requires the gate.
            'gate_open': row['id'] in gate_open_set,
            'launch_candidate': row['id'] in candidate_set,
            # The amendment: checkpoint steps upstream that still hold open
            # work (req #3649: the flag, on by default). Non-empty means this
            # step's work is NOT announced until they are.
            'checkpoint_blocked_by': row['_checkpoint_blockers'],
            'epic_id': row['epic_id'],
            'dep_ids': row['dep_ids'],
            # Which of THIS row's own deps are out of scope (a subset of
            # `dep_ids`, always empty unless `epic_scoped`) — so a reader
            # deciding why a row is `eligible: False` does not have to
            # intersect `dep_ids` against the plan-level
            # `out_of_scope_dep_ids` by hand to find the honest reason.
            'out_of_scope_dep_ids': [d for d in row['dep_ids'] if d in out_of_scope_set],
            'req_ids': row['req_ids'],
            'tracking_req_ids': row['tracking_req_ids'],
            'unresolved_req_ids': row['unresolved_req_ids'],
            'launch_req_ids': row['launch_req_ids'],
            'launch_excluded': row['launch_excluded'],
            'launch_block': row['launch_block'],
            'swarm_start_command': row['swarm_start_command'],
            'no_launch_reason': row['no_launch_reason'],
            'launch_suppressed': row['launch_suppressed'],
            'suppressed_by': row['suppressed_by'],
        } for row in rows],
        'pause': pause,
        'serial': serial,
        'eligible_step_ids': eligible_ids,
        # req #3597 — every launch candidate, in launch PRIORITY order
        # (gate-open first, then display order), NOT display order.
        'launch_candidate_step_ids': candidate_ids,
        # req #3649 — THE launch order, one entry per announceable
        # requirement (`launch_queue`): the engine ranks by position here.
        'launch_queue': queue,
        'violations': violations,
        'cycle_detected': ordered['cycle_detected'],
        'cycle_step_ids': ordered['cycle_step_ids'],
        'duplicate_step_ids': ordered['duplicate_step_ids'],
        'unresolved_req_ids': unresolved,
        # Only ever non-empty when `epic_scoped=True` — a dependency this
        # epic-scoped payload never fetched, not a plan defect. See
        # `verify_order`'s docstring.
        'out_of_scope_dep_ids': out_of_scope_dep_ids,
        'requirement_counts': requirement_counts(model),
    }
