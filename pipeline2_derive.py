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
   `epic_id`, `feature_id`, `feature`, `epic_labels` and `feature_labels` do
   not appear on a derived row — an unlabelled step cannot exist under this
   schema, so there is nothing to borrow from a dependency. Measured against
   the live plan (163 steps) via the 1.0 field this module's `epic_id` column
   replaces: `label_inherited` was set on exactly 1 of 163 rows (step 11, a
   req-less gate) — that one walk is what this item deletes, not seventeen.

2. **`requirement_counts` groups by the STEP's `epic_fk`**, not by the
   requirement's own `feature_fk` -> `epic_fk` chain — Feature does not exist
   in 2.0, so there is no other chain to read. This changes the ANSWER where a
   requirement's step sits under a different epic than its feature did.
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
   topological-then-state-band walk (structurally `pipeline_derive.
   display_order`'s algorithm, minus the batch/stream machinery — there is
   no batch to cluster) with epic order used as a CLUSTERING tie-break, not
   a hard partition: a row still never renders before a dependency in
   another epic, and epic blocks are not guaranteed contiguous, exactly as
   1.0 is not guaranteed contiguous by first-appearance today.

   **The state-banding self-check is EPIC-SCOPED, and this is not optional**
   (`memory/pipeline-2-visualizer-design.md` § 5, req #3331's correction to
   stage 1's claim that forbidding cross-epic edges makes the violation class
   disappear structurally — measured FALSE: a global check over a tree-walked
   plan reports 15 false violations on live pipeline 2, all of the form "a
   finished epic's done steps render below an unrelated epic's still-pending
   ones"). Scoping the check to each epic's own block is the fix, and it does
   NOT relax away the genuine WITHIN-epic case the amended acceptance
   criterion pins: three steps in one epic (1 pending, 2 pending, 3 done
   depending on 2) still reports, because the greedy pass can legitimately
   place an unrelated pending row ahead of a satisfied gate. That residue is
   real but LATENT on the live plan — 0 of 145 dependency edges have a step
   outranking its own gate — so a hand fixture stands in for a live-plan
   reproduction here (see the test suite): it is the specific shape §5.3
   names, not a question a bigger sweep would answer any differently.

5. **The conformance corpus is untouched here, on purpose.** All 34 cases in
   `tests/conformance/pipeline_conformance.json` mention `features`, and
   re-expressing it is, in this requirement's own words, "the largest single
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
"""

import re
from datetime import datetime, timezone

__all__ = [
    'STEP_DONE', 'STEP_RUNNING', 'STEP_PENDING',
    'TERMINAL_REQUIREMENT_STATUSES', 'LAUNCHABLE_REQUIREMENT_STATUSES',
    'PAUSED_STATUS', 'MODE_PARALLEL', 'MODE_SERIAL',
    'is_tracking_requirement', 'derive_step_state',
    'build_plan_rows', 'display_order', 'verify_order', 'eligibility',
    'pause_state', 'serial_state', 'requirement_counts', 'derive_plan2',
]

STEP_DONE = 'done'
STEP_RUNNING = 'running'
STEP_PENDING = 'pending'

# Requirement statuses that close a step (design rule 1). Byte-identical to
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

_STATE_RANK = {STEP_DONE: 0, STEP_RUNNING: 1, STEP_PENDING: 2}
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
    value = (req or {}).get('tracking')
    if value is None or value == '':
        return False
    if isinstance(value, bool):
        return value
    try:
        return float(value) != 0
    except (TypeError, ValueError):
        return False


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


def derive_step_state(step, linked_reqs):
    """Design rule 1: STEP STATE IS DERIVED, NEVER STORED-BY-HAND.

    Byte-identical rule to `pipeline_derive.derive_step_state` — Feature's
    removal and containment change WHERE a step's epic comes from, not how its
    state is computed. Any gating requirement in `development` -> running; all
    terminal -> done; else pending. With no gating requirements the step's own
    `completed_at` stamp decides.
    """
    reqs = [r for r in (linked_reqs or []) if r]
    gating = [r for r in reqs if not is_tracking_requirement(r)]
    if not gating:
        return STEP_DONE if (step or {}).get('completed_at') else STEP_PENDING
    if any(r.get('requirement_status') == 'development' for r in gating):
        return STEP_RUNNING
    if all(r.get('requirement_status') in TERMINAL_REQUIREMENT_STATUSES
           for r in gating):
        return STEP_DONE
    return STEP_PENDING


# ---------------------------------------------------------------------------
# Build plan rows
# ---------------------------------------------------------------------------

def build_plan_rows(model):
    """Join the model tables into self-contained plan rows, in steps-array
    (insertion) order — callers MUST reorder via `display_order` before
    rendering or sequencing, exactly as 1.0 requires of its own rows.

    `epic_id` is `step['epic_fk']`, A COLUMN READ (item 1) — no tally, no
    tie-break, no inheritance walk, and no `epic`/`feature`/`feature_id`/
    `epic_labels`/`feature_labels`/`label_inherited` on the row: none of
    those concepts exist once a step's epic is a NOT NULL column. A consumer
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
        linked = [reqs_by_id[rid] for rid in req_ids if rid in reqs_by_id]
        unresolved = [rid for rid in req_ids if rid not in reqs_by_id]
        tracking_ids = [rid for rid in req_ids
                        if is_tracking_requirement(reqs_by_id.get(rid))]
        launch_ids, launch_excluded = _split_launchable(req_ids, tracking_ids,
                                                         reqs_by_id)
        block = _launch_block(req_ids, tracking_ids, launch_ids)
        rows.append({
            'id': step['id'],
            'title': step.get('title'),
            'run': step.get('run') or 'auto',
            'notes': step.get('notes'),
            'completed_at': step.get('completed_at'),
            'state': derive_step_state(step, linked),
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
    `create_ts` among an epic's own non-pending (running or done) steps —
    when a step actually started work is not recoverable from this payload,
    when it was authored into the plan is. This is a proxy, not a
    reproduction of the browser's richer chain, and a future session
    reconciling the two derivations should re-measure rather than assume
    they agree.

    An epic with zero non-pending steps (including an empty epic) is
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
                     if rows_by_id[rid]['state'] != STEP_PENDING
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
    topological-then-state-band walk, structurally identical to
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
    same-epic rows together wherever topology leaves a choice, which is what
    measurement A (`memory/pipeline-2-visualizer-design.md` § 5.2) shows
    costs nothing on the live plan's 9 crossing edges: 0 state-banding
    violations once that check is scoped per epic (`verify_order` below).

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
        if row.get('state') == STEP_DONE:
            # Storage position is the FINAL tie-break for done work, matching
            # 1.0 — done history is chronological and insertion order is the
            # honest record of it, where pending/running work has none yet.
            return (0, epic_idx(row), float(idx[row['id']]))
        anchor = max([-1] + [pos[d] for d in (row.get('dep_ids') or []) if d in pos])
        band = 1 if row.get('state') == STEP_RUNNING else 2
        return (band, float(anchor), epic_idx(row),
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


def _epic_banding_violations(epic_rows, depends_on):
    """The state-banding invariant, compared over ONE epic's own rows only —
    item 4's epic-scoped self-check (`memory/pipeline-2-visualizer-design.md`
    § 5.4, measurement D). A band inversion is a violation only when it was
    AVOIDABLE: the lower-band row does not depend, TRANSITIVELY, on the
    higher-band row it renders below.

    `depends_on` is the caller's GLOBAL closure (over every row in the whole
    plan, not just this epic) — this is corrected from an earlier version
    that computed the closure locally per epic, which was WRONG: cross-epic
    dependency edges are legal, so a transitive path can legitimately leave
    this epic and come back (A -> B in another epic -> C, back in this one),
    and a closure that cannot see B reports a false "unavoidable" inversion
    between A and C. Only the COMPARISON — which pairs of rows are even
    checked against each other — is epic-scoped; what counts as "avoidable"
    is a fact about the whole dependency graph and must be computed there.
    (Measured over 3000 fuzzed plans: an epic-local closure produced 50 false
    positives beyond the 386 a global closure finds — 11.5% of the total.)

    This is the check the amended acceptance criterion's three-step case
    exercises: `1 pending, 2 pending, 3 done depending on 2` in one epic
    reports `3` rendering below `1`, because `1` is not a dependency of `3`
    and the greedy topological pass had no reason to place it after `2, 3`.
    """
    def band_of(row):
        return _STATE_RANK.get(row.get('state'), 2)

    violations = []
    for position, row in enumerate(epic_rows):
        band = band_of(row)
        avoidable = [prev for prev in epic_rows[:position]
                     if band_of(prev) > band and prev['id'] not in depends_on(row['id'])]
        if avoidable:
            worst = avoidable[-1]
            violations.append({
                'invariant': 'state-banding', 'step_ids': [row['id'], worst['id']],
                'message': (f"{row.get('state')} step {row['id']} renders below "
                            f"{worst.get('state')} step {worst['id']}, which it "
                            "does not depend on — done>running>pending banding "
                            "broken (epic-scoped)"),
            })
    return violations


def verify_order(rows, epic_scoped=False):
    """Design rule 3 self-check — structured violations, NEVER raised.

    `duplicate-id`, `cycle` and `topology` stay plan-wide, because they must:
    cross-epic dependency edges are LEGAL (gate delta, req #3336,
    2026-08-08), so a dependency can genuinely name a step in a different
    epic and these invariants have to see the whole graph to mean anything.
    `state-banding` is the one invariant that MUST be epic-scoped instead
    (item 4's amendment, `memory/pipeline-2-visualizer-design.md` § 5) — a
    global check over a plan clustered-but-not-partitioned by epic reports
    false violations for every finished epic that happens to render above an
    unrelated epic still holding pending work (measurement C: 15 false
    positives on the live plan), which is not a defect, it is what
    containment asks for. `_epic_banding_violations` groups `rows` by
    `epic_id` wherever they fall in the global order — it does not require
    (and `display_order` does not guarantee) that one epic's rows are
    contiguous, and it is handed a GLOBAL `depends_on` closure so a
    transitive path through another epic is still seen.

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
    this render genuinely cannot see whether the out-of-scope dependency is
    done — it is to say so honestly: those ids are collected into
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

    # ONE global closure, over every row regardless of epic — see
    # `_epic_banding_violations`'s docstring for why a per-epic closure is
    # wrong (a cross-epic transitive path is invisible to it).
    by_id = {row['id']: row for row in rows}
    closure = {}

    def depends_on(step_id):
        if step_id in closure:
            return closure[step_id]
        out = set()
        closure[step_id] = out
        row = by_id.get(step_id)
        for dep in (row or {}).get('dep_ids') or []:
            if dep not in posn:
                continue
            out.add(dep)
            out.update(depends_on(dep))
        return out

    # `rows` arrive in epic-block order (`display_order`'s contract), so a
    # plain first-appearance walk visits each epic's rows together and in the
    # same order the caller rendered them — nothing here re-derives epic
    # order a second time.
    by_epic = {}
    for row in rows:
        by_epic.setdefault(row.get('epic_id'), []).append(row)
    for epic_rows in by_epic.values():
        violations.extend(_epic_banding_violations(epic_rows, depends_on))

    return violations, sorted(out_of_scope, key=_id_sort_key)


# ---------------------------------------------------------------------------
# Eligibility (DRV-005/006) — a plain per-step predicate, no batch term
# ---------------------------------------------------------------------------

def eligibility(row, by_id, now=None):
    """A pending row is eligible when every dependency is `done` AND its own
    `not_before` (if any) has passed relative to the caller-supplied `now` —
    this module never reads the clock itself (`derive_plan2` is the one
    caller, and it is told `now` by ITS caller for the same reason
    `pipeline_derive.eligibility` documents: a stale clock must be visible as
    stale, not invisible).

    No batch term exists here — 1.0's `eligibility` is keyed off a batch's
    shared launch key; 2.0 has no batch, so this is purely a function of one
    row's own `dep_ids` and `_not_before` (DRV-005). No `now` — or an
    unparseable gate — while a gate exists means NOT eligible, never passed:
    the safe direction, matching 1.0's posture exactly.
    """
    if row.get('state') != STEP_PENDING:
        return False
    for dep_id in (row.get('dep_ids') or []):
        dep = by_id.get(dep_id)
        if not dep or dep.get('state') != STEP_DONE:
            return False
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
    Everything else is DERIVED: an epic is CLOSED when every step it owns is
    `done`; the LIVE epic is the first one in `epic_order` that is not
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
        if all(row.get('state') == STEP_DONE
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
    HELD by `serial_state` until its own epic goes live — which can never
    happen while it is itself blocking an earlier epic from closing. That is
    a structural deadlock, not a data defect that resolves itself, and it
    must be LOUD (`design rule 7`) rather than a silent stall indistinguishable
    from ordinary in-progress work.

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
                    "edge under serial execution. That dependency can never "
                    "be released: its epic never goes live while this one, "
                    "blocked on it, never closes. The gate can never open — "
                    "this is a deadlock, not a stall. Re-order the epics, "
                    "move both steps into one epic, or drop the edge."),
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
    numerator is `TERMINAL_REQUIREMENT_STATUSES`, matching the state machine
    a step's own `done` derivation already uses.

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
    Batch does not exist in 2.0. `eligible`, `pause` AND `serial` ARE built
    here (DRV-005/006/016/017/018 for the first two — the verification
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
    payload cannot see whether that dependency is done, and the safe
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
    eligible_ids = [row['id'] for row in rows if eligibility(row, by_id, now)]
    eligible_set = set(eligible_ids)
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
            'state': row['state'],
            'run': row['run'],
            'eligible': row['id'] in eligible_set,
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
