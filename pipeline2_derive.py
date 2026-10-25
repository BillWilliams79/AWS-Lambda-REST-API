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
`get_pipeline2_composed` / `get_pipeline2_initiative_composed` are now a ONE-CALL
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
DOES include a plain epic-scoped `eligibility` (DRV-005/006 — a pending
epic's own dep graph and its own `not_before` against the payload's clock,
with no batch or cross-epic term) and pause-driven launch suppression
(DRV-016/017/018 — `launch_suppressed`/`suppressed_by` per row and the
`pause` block, initiative-scoped because containment gives initiative pause a real scope
key). It does NOT include reservations, debounce or commanded-requirement
tracking (owned by req #3368 — see ENG-005/006/009, CLI-012 through CLI-016
in the same register) — those are the ENGINE'S restatement, which consumes
`derived['pause']`/`eligible` rather than recomputing them, and DRV-019
("a derived block carrying no `pause` state is a hard stop") is that
consumer's own defensive posture toward a payload this module did not
produce, not a second implementation. There is also no `launch_batches`
here at all — Batch does not exist in 2.0
(`memory/pipeline-2-first-principles.md` § 6, DRV-021): the Epic is the
launch unit, so what 1.0 computes once per batch this module computes once
per row.

## What changed, item by item (req #3349's own numbering)

1. **`initiative_id` is a column read.** `pipeline2_epics.initiative_fk` is NOT NULL, so
   there is no tally, no tie-break, and no inheritance walk. `dominant_labels`,
   `inherited_labels` and the `label_inherited` flag do not exist here;
   `initiative_id` and `initiative_labels` and their retired middle-tier counterparts do
   not appear on a derived row — an unlabelled epic cannot exist under this
   schema, so there is nothing to borrow from a dependency. Measured against
   the live plan (163 epics) via the 1.0 field this module's `initiative_id` column
   replaces: `label_inherited` was set on exactly 1 of 163 rows (epic 11, a
   req-less gate) — that one walk is what this item deletes, not seventeen.

2. **`requirement_counts` groups by the EPIC's `initiative_fk`**, not by a chain
   through the requirement's own retired middle-tier link -> `initiative_fk` —
   that tier does not exist in 2.0, so there is no other chain to read. This
   changes the ANSWER where a requirement's epic sits under a different initiative
   than its retired middle-tier record did.
   **Measured against the live plan, 2026-08-09** (206 non-tracking
   requirements, re-grouped by the epic each is linked to in the live 1.0
   composed read's own `derived.rows[].initiative_id`, which is the field the 2.0
   importer itself reads — see `memory/pipeline-2-data-architecture.md`
   § 7.2): **zero requirements change bucket, and both the overall and the
   per-initiative met/total numbers are byte-identical before and after.** One
   requirement (#3077) links two epics (14 and 15), both seated in initiative 5,
   which is also its own feature's initiative — the sole multi-seat case on this
   plan (`memory/pipeline-2-mcp-surface.md`'s "1 of 255", req #3077) does not
   disturb the count. This is a real, reproducible measurement and not an
   assumption that the two groupings agree in general — they diverge exactly
   when a requirement's epic is seated under a different initiative than the
   requirement's own feature, which is zero times on today's plan and is not
   zero by construction.

3. **The time-gate branch is deleted.** `pipeline2_epic_deps.dep_epic_fk` is
   NOT NULL (data record § 3) — a dep row has exactly one meaning, so there is
   no discriminator to branch on and no `time_deps` bucket to build. The
   per-row `time_deps` field this module's rows once might have carried does
   not exist; an epic's own time gate is already visible to any reader of
   `model['epics'][*]['not_before']` without this module re-surfacing it.
   `now` still rides `derive_plan2`'s output, for the reason given in
   "Scope" above.

4. **Display order is a tree walk**, initiative order first
   (`memory/pipeline-2-orchestration-algorithm.md`'s gate delta, recorded on
   req #3364): a manual `pipeline2_initiatives.sort_order` wins where set; initiatives
   with no manual order are placed after, started ones first by an earliest-
   activity proxy (ascending), unstarted ones last in creation (id) order.
   See `_initiative_block_order`'s docstring for the honest residue here — the
   composed read carries no `started_at` anywhere (epics or the light
   requirement projection), so "start" is approximated from an epic's own
   `create_ts`, not the richer timestamp chain the browser's separate
   derivation (req #3372) can afford to read.

   **CROSS-INITIATIVE DEPENDENCY EDGES ARE LEGAL** — this requirement's own
   stage-2 gate delta (req #3336, 2026-08-08) reverses the body text above:
   "the walk and the banding invariant handle crossing edges exactly as the
   live 1.0 plan already does". So `display_order` is ONE global
   topological walk (structurally `pipeline_derive.
   display_order`'s algorithm, minus the batch/stream machinery — there is
   no batch to cluster) with initiative order used as a CLUSTERING tie-break, not
   a hard partition: a row still never renders before a dependency in
   another initiative, and initiative blocks are not guaranteed contiguous, exactly as
   1.0 is not guaranteed contiguous by first-appearance today.

   There is no state band and no banding self-check: an epic has no state
   (req #3750), so the walk orders by topology, then initiative, then run mode,
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
   including the amended three-epic case, and `requirement_counts` grouping
   by the seated initiative.

## Added after the fact: DEPENDENCIES ARE A PRIORITY, NOT A GATE (req #3597, 2026-10-17)

User rule, every plan, always: whenever the machine has a free slot, launch-
ready work is started even when its epic's dependency gate is not satisfied.
`launch_candidacy` answers "may this epic's work be announced" WITHOUT asking
about its dependencies (it keeps the time gate and the `swarm_ready` rule),
and `launch_candidate_epic_ids` lists the candidates gate-open first, then
down the chain in display order. The gate is still computed and REPORTED
(`gate_open`, and `eligible` for the view's eligible-now ring).

**One dependency stays a gate** (the user's amendment, same day; a per-epic
FLAG since req #3649): a CHECKPOINT — `epics.checkpoint`, on by
default — holds every epic downstream of it, transitively, while it holds
OPEN WORK. `checkpoint_blocked_by` names the checkpoints holding a row.

## A EPIC HAS NO STATE (req #3750, user ruling 2026-10-21)

"An epic exists to hold requirements. It can hold none, all closed, all open
or any mix, and it has no state. An epic just exists as a holder and has
orchestration engine controls." So there is no pending/running/done, no
`completed_at` stamp (the column is dropped) and no way to complete or
reopen an epic. Every question the engine used to ask of an epic's state is
asked of the requirements it holds, through ONE per-row fact:

  `open_req_ids` — the epic's GATING requirements (non-tracking) whose
  status is not terminal (`met`/`deferred`/`wontfix`). An id the composed
  read did not resolve counts as open: holding is the safe direction.

A dependency is CLEAR when that epic's `open_req_ids` is empty; a checkpoint
HOLDS while its own is not. An epic holding nothing holds nothing — it never gates.
Answered fresh from requirement statuses on every read, nothing here can go
stale when a requirement is added to an epic later; a stored "done" could.

## AN INITIATIVE CAN WAIT FOR AN INITIATIVE (req #3823)

`initiative_deps` says "initiative B waits for ALL of initiative A": no epic
under B is announced while any epic under A holds open work. It is a GATE,
not a launch priority — an epic edge is a priority (req #3597) because a free
slot is worth more than the order, but an initiative edge exists precisely to
say "wait", so a free slot does not override it. Transitive (C waits on B
waits on A holds C while A or B holds open work), derived on every read from
the same `open_req_ids` the barrier reads, and indifferent to pause (a paused
initiative with open work still holds its dependents). An initiative that
holds no work holds nothing. `initiative_blocked_by` names the holders on
each row, kept apart from `checkpoint_blocked_by` so a reader can say which
gate holds.

THE COMBINED-GRAPH RULE. An initiative edge and the epic edges can contradict
each other: B waits for A while an epic in A waits on an epic in B holds both
forever under the default barrier. The test is made at EPIC granularity, on
the gate graph (`gate_graph`): every epic waits on its initiative's gate, and
an initiative edge sends that gate to every epic of the initiative waited on
(and on to that initiative's own gate — the hold is transitive). A cycle
through a gate is a real deadlock; lifting epic edges to initiative pairs
would refuse plans that are satisfiable. The gateway REFUSES such a cycle
when either edge is written (`initiative_deps_guard.py`); anything that slips
in another way — an epic or initiative moved under existing edges — is
FLAGGED here as an `initiative-cycle` violation. `gate_graph` / `gate_path`
are the one implementation both use.
"""

import re
from datetime import datetime, timezone

__all__ = [
    'TERMINAL_REQUIREMENT_STATUSES', 'LAUNCHABLE_REQUIREMENT_STATUSES',
    'PAUSED_STATUS',
    'is_tracking_requirement', 'open_requirement_ids',
    'build_plan_rows', 'display_order', 'verify_order', 'eligibility',
    'launch_candidacy', 'is_checkpoint',
    'open_checkpoints_upstream', 'plan_graph_outside',
    'pause_state', 'requirement_counts', 'derive_plan2',
    'LIVE_SESSION_STATUSES', 'PRIMARY_START_TAG', 'STALL_GRACE_SECONDS',
    'work_evidence', 'stall_requirement_ids', 'seat_violations',
    'initiative_dep_map', 'initiative_open_work', 'open_initiatives_upstream',
    'plan_graph_initiative_open',
    'gate_graph', 'gate_path', 'initiative_edge_cycle', 'gate_cycle_text',
    'initiative_violations',
]

# Requirement statuses that are no longer open work. Byte-identical to
# `pipeline_derive.TERMINAL_REQUIREMENT_STATUSES` — this fact about the state
# machine did not change with Feature or containment, so it is not "ported",
# it is simply also true here.
TERMINAL_REQUIREMENT_STATUSES = ('met', 'deferred', 'wontfix')

# The ONLY status a `/swarm-start` argument may carry (req #3360, carried
# forward as gate delta F9 on THIS requirement — "without this the fix seated
# at epic 266 dies"). See `pipeline_derive.LAUNCHABLE_REQUIREMENT_STATUSES`
# for the full reasoning on why `approved` and `development` are excluded;
# that reasoning is a property of the requirement state machine, not of
# Feature or containment, and is unchanged here.
LAUNCHABLE_REQUIREMENT_STATUSES = ('swarm_ready',)

# Why a requirement id is not in an epic's launch argument list. One flat
# string per exclusion, `"<req_id> <reason>"` — matches
# `pipeline_derive`'s shape so a consumer reading both eras' payloads reads
# one grammar, not two.
EXCLUDED_CONTAINER = 'tracking container'
EXCLUDED_UNRESOLVED = 'unresolved — not in the composed read'
EXCLUDED_NO_STATUS = 'no status'

# The enum behind an epic's `no_launch_reason` (gate delta F9). Per EPIC, not
# per batch — 2.0 has no batch.
BLOCK_NO_LINKS = 'no-links'
BLOCK_CONTAINERS = 'containers'
BLOCK_NOT_READY = 'not-ready'

# The one value that means "do not swarm-start this scope" (req #3223),
# shared by `pipelines.pipeline_status`/`initiatives.initiative_status` and their 2.0
# counterparts — one word, one meaning, at both scopes, in both eras.
PAUSED_STATUS = 'paused'

# ---------------------------------------------------------------------------
# Stall evidence (req #3757) — "is anybody working this?", answered HERE so the
# engine computes nothing about the plan (rule R1, `memory/engine-rules.md`).
# THIS IS THE ONE STALL PREDICATE (req #3898): the engine and
# `scripts/swarm/status_report.py` both read `stall_req_ids` and judge nothing
# themselves — the client-side copy in `pipeline_regression.py` was deleted
# because the MCP session list it was fed omits the terminal columns (req
# #3881). Over rows the composing route reads in the same invocation: a live
# session names the requirement in `source_ref`, or an OPEN primary birth
# record does (req #3290 — the Primary executes work under a birth record and
# no session). Either kind of evidence covers a requirement.
# ---------------------------------------------------------------------------

# Every swarm session status that is NOT finished. Same list as
# `pipeline_regression.LIVE_SESSION_STATUSES`.
LIVE_SESSION_STATUSES = ('starting', 'waiting', 'planning', 'active', 'review',
                         'completing')

# The tag `primary-start-record.sh` writes into `swarm_starts.arguments` for a
# `/primary-ai-swarm-start` birth record — the only mark of primary-executed
# work.
PRIMARY_START_TAG = 'primary req#'

# How long a requirement must have been in `development` before nobody working
# it is a stall. `session-init.sh` writes `development` BEFORE it creates the
# session, so a requirement read the instant after a launch is legitimately
# unworked. The old engine got the same effect by only judging requirements it
# had watched past its announce window.
STALL_GRACE_SECONDS = 300

# Statuses that say a requirement's work has begun — the initiative-order proxy's
# "started" test (`_initiative_block_order`).
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
# Requirement-level derivation — unchanged by Feature's removal or initiative_fk's
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


def _linked_req_ids(epic_id, model):
    """Requirement ids linked to an epic, in junction order."""
    return [link['requirement_fk'] for link in (model.get('epic_requirements') or [])
            if link.get('epic_fk') == epic_id]


def _split_launchable(req_ids, tracking_ids, reqs_by_id):
    """Gate delta F9 (req #3360's rule, restated for 2.0). Returns
    `(launch_ids, excluded)` — the ids an epic's `/swarm-start` may carry, and
    one record per id it may not, each carrying the reason. Order is the
    epic's own junction order — the command a reader is told to run must be
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
    """WHICH of the three no-command cases this epic is in — the enum, not
    the sentence. `None` when something IS launchable. Per EPIC: 2.0 has no
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
    """The epic's OPEN WORK (req #3750): its gating (non-tracking) requirement
    ids whose status is not terminal, in junction order.

    THE ONE FACT every orchestration question about an epic is asked through —
    an epic has no state of its own. An id `reqs_by_id` does not resolve counts
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
    """Join the model tables into self-contained plan rows, in epics-array
    (insertion) order — callers MUST reorder via `display_order` before
    rendering or sequencing, exactly as 1.0 requires of its own rows.

    `initiative_id` is `epic['initiative_fk']`, A COLUMN READ (item 1) — no tally, no
    tie-break, no inheritance walk, and no `initiative`/`initiative_labels`/
    `label_inherited` (nor their retired middle-tier counterparts) on the
    row: none of those concepts exist once an epic's initiative is a NOT NULL
    column. A consumer
    wanting the initiative's title reads it off `model['initiatives']` by id — this
    module does not duplicate data the composed read already carries once.

    `dep_ids` come from `pipeline2_epic_deps`, where every row is a plain
    epic-to-epic edge (`dep_epic_fk` NOT NULL, data record § 3) — there is no
    second condition kind to bucket separately, so unlike
    `pipeline_derive.build_plan_rows` there is no `time_deps` output at all
    (item 3).
    """
    reqs_by_id = _index_by_id(model.get('requirements'))
    epics = model.get('epics') or []

    dep_ids_by_epic = {}
    for dep in model.get('epic_deps') or []:
        dep_ids_by_epic.setdefault(dep['epic_fk'], []).append(dep['dep_epic_fk'])

    rows = []
    for epic in epics:
        req_ids = _linked_req_ids(epic['id'], model)
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
            'id': epic['id'],
            'title': epic.get('title'),
            'run': epic.get('run') or 'auto',
            # req #3649 — the epic's two stored flags. `checkpoint` is what
            # the hold walk reads (`is_checkpoint`); `locked` is carried for
            # the view and enforced by the gateway, never here.
            'checkpoint': _flag(epic.get('checkpoint'), default=True),
            'locked': _flag(epic.get('locked'), default=False),
            'notes': epic.get('notes'),
            'open_req_ids': open_requirement_ids(req_ids, tracking_ids,
                                                 reqs_by_id),
            'initiative_id': epic.get('initiative_fk'),
            'req_ids': req_ids,
            # req #3757 — the epic's GATING set: every seated requirement but
            # the tracking containers, unresolved ones included (holding is the
            # safe direction). The engine reads it instead of re-deriving it.
            'gating_req_ids': [rid for rid in req_ids if rid not in tracking_set],
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
            'dep_ids': dep_ids_by_epic.get(epic['id'], []),
            # Internal to this module's ordering/eligibility passes only —
            # never on the payload a caller of `derive_plan2` sees (stripped
            # in `derive_plan2`'s own row projection, matching 1.0's compact-
            # block discipline, `test_the_derived_block_is_compact_ids_and_
            # enums_only`'s 2.0 counterpart). `_not_before` is the raw gate
            # `eligibility()` resolves into the public boolean `eligible`.
            # The public row carries it too, as `not_before` (req #3757 —
            # Engine 2's NOT_BEFORE detail, rule R1), normalised to ISO UTC.
            '_create_ts': epic.get('create_ts'),
            '_started': started,
            '_not_before': epic.get('not_before'),
        })
    return rows


# ---------------------------------------------------------------------------
# Ordering — the tree walk (item 4)
# ---------------------------------------------------------------------------

def _initiative_block_order(initiatives, rows_by_id):
    """Initiative block order: manual `sort_order` wins where set; else started
    initiatives by an earliest-activity proxy ascending; unstarted initiatives after, in
    creation (id) order. (`memory/pipeline-2-orchestration-algorithm.md`'s
    gate delta, recorded on req #3364.)

    **The residue, stated plainly.** The browser's own derivation of "start"
    (req #3372) reads a requirement's `started_at`/`completed_at` — columns
    this composed read's light requirement projection does not carry
    (`memory/pipeline-2-mcp-surface.md` § 6.2's `_REQUIREMENT_FIELDS`), and
    which no `pipeline2_*` table carries at the initiative level either. The only
    timestamp available to a server-side reader of THIS payload is an epic's
    own `create_ts`. So "start" here is approximated as the earliest
    `create_ts` among an initiative's own epics holding work that has begun (a
    gating requirement in `development` or terminal) —
    when an epic actually started work is not recoverable from this payload,
    when it was authored into the plan is. This is a proxy, not a
    reproduction of the browser's richer chain, and a future session
    reconciling the two derivations should re-measure rather than assume
    they agree.

    An initiative with no such epic (including an empty initiative) is
    "unstarted" and sorts by id — AUTO_INCREMENT order is creation order on
    this schema, the same idiom `pipeline_derive._id_sort_key` documents.
    """
    manual, derived = [], []
    for initiative in initiatives:
        eid = initiative['id']
        sort_order = initiative.get('sort_order')
        initiative_row_ids = [rid for rid, row in rows_by_id.items()
                        if row.get('initiative_id') == eid]
        started_ts = [rows_by_id[rid]['_create_ts'] for rid in initiative_row_ids
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


def display_order(rows, initiatives):
    """Design rule 3, re-derived for containment — and CORRECTED against the
    stage-2 gate delta on this requirement (req #3336, 2026-08-08): **cross-
    initiative dependency edges are LEGAL**, reversing item 4's own body text
    ("a dependency edge cannot cross an initiative"). The gate delta's instruction
    is explicit: "the walk and the banding invariant handle crossing edges
    exactly as the live 1.0 plan already does" — so this is ONE global
    topological walk, structurally identical to
    `pipeline_derive.display_order`'s core algorithm, with initiative order
    (`_initiative_block_order`'s override-tier sequence) standing in for 1.0's
    first-appearance `initiative_idx` as a clustering tie-break — NOT a hard
    partition. What is dropped relative to 1.0 is only the batch/stream
    apparatus: 2.0 has no batch (`memory/pipeline-2-first-principles.md`
    § 6), so `stream()`/`group_tail` and everything that clustered pending
    batch-mates do not exist here.

    A row still never renders before a dependency, whichever initiative that
    dependency belongs to. Initiative blocks are consequently NOT guaranteed
    contiguous in the presence of a crossing edge — exactly as 1.0 is not
    guaranteed contiguous by first-appearance today — but `initiative_idx` pulls
    same-initiative rows together wherever topology leaves a choice.

    No state band (req #3750): an epic has no state, so among the rows whose
    dependencies have all rendered the tie-break is the latest dependency's
    position, then initiative order, then run mode, then id.

    Rows carrying an `initiative_id` absent from `initiatives` (a truncated composed read
    withheld that initiative's own row) sort after every known initiative, in ascending
    initiative-id order — the safe direction, matching 1.0's dangling-dependency
    posture of reporting rather than guessing.

    Cycle contract, matching 1.0: detect, report, deterministic fallback to
    stored (insertion) order for whatever is left standing.

    Returns `{rows, cycle_detected, cycle_epic_ids, duplicate_epic_ids,
    initiative_order}`.
    """
    duplicate_epic_ids = []
    seen_ids = set()
    for row in rows:
        if row['id'] in seen_ids:
            if row['id'] not in duplicate_epic_ids:
                duplicate_epic_ids.append(row['id'])
        else:
            seen_ids.add(row['id'])

    by_id = {row['id']: row for row in rows}       # last occurrence wins on a dup
    dedup_rows = list(by_id.values())
    initiative_ids_known = {initiative['id'] for initiative in (initiatives or [])}

    initiative_order = _initiative_block_order(initiatives or [], by_id)
    unresolved_initiative_ids = sorted(
        {row['initiative_id'] for row in dedup_rows
         if row.get('initiative_id') not in initiative_ids_known},
        key=_id_sort_key)
    full_initiative_order = initiative_order + unresolved_initiative_ids
    initiative_pos = {eid: position for position, eid in enumerate(full_initiative_order)}

    def initiative_idx(row):
        return initiative_pos.get(row.get('initiative_id'), len(full_initiative_order))

    idx = {row['id']: position for position, row in enumerate(dedup_rows)}

    def num_id(row):
        try:
            return float(row['id'])
        except (TypeError, ValueError):
            return float(idx[row['id']])

    remaining = {row['id']: row for row in dedup_rows}
    out, pos = [], {}
    cycle_detected, cycle_epic_ids = False, []

    def sort_key(row):
        anchor = max([-1] + [pos[d] for d in (row.get('dep_ids') or []) if d in pos])
        return (float(anchor), initiative_idx(row),
                _RUN_RANK.get(row.get('run') or 'auto', 0), num_id(row))

    while remaining:
        avail = [row for row in remaining.values()
                 if all(d not in remaining for d in (row.get('dep_ids') or []))]
        if not avail:
            rest = sorted(remaining.values(), key=lambda r: idx[r['id']])
            cycle_detected = True
            cycle_epic_ids = [row['id'] for row in rest]
            out.extend(rest)
            break
        pick = min(avail, key=sort_key)
        pos[pick['id']] = len(out)
        out.append(pick)
        del remaining[pick['id']]

    return {'rows': out, 'cycle_detected': cycle_detected,
            'cycle_epic_ids': cycle_epic_ids,
            'duplicate_epic_ids': duplicate_epic_ids,
            'initiative_order': full_initiative_order}


def verify_order(rows, initiative_scoped=False):
    """Design rule 3 self-check — structured violations, NEVER raised.

    `duplicate-id`, `cycle` and `topology` stay plan-wide, because they must:
    cross-initiative dependency edges are LEGAL (gate delta, req #3336,
    2026-08-08), so a dependency can genuinely name an epic in a different
    initiative and these invariants have to see the whole graph to mean anything.
    There is no state-banding invariant: an epic has no state (req #3750).

    `dangling-dependency` is CONDITIONAL on `initiative_scoped`, and this is the
    fix for a real defect a code review caught: `get_pipeline2_initiative_composed`
    narrows `epics` at the gateway (`initiative_fk = E`) but fetches `epic_deps` by
    `epic_fk`, so an OUTGOING cross-initiative edge arrives with its `dep_epic_fk`
    pointing at an epic this payload never fetched. Under `initiative_scoped=True`
    that is EXPECTED — not a defect in the plan, a property of the scope —
    and reporting it as `dangling-dependency` (which reads as data loss or a
    stale FK) sends a reader chasing a corruption that does not exist while
    `eligibility` correctly, silently, and PERMANENTLY refuses to launch a
    epic that was actually ready. The fix is not to make it launchable —
    this render genuinely cannot see whether the out-of-scope dependency
    holds open work — it is to say so honestly: those ids are collected into
    `out_of_scope_dep_ids` instead of a violation, and a caller wanting the
    true state reads the whole-plan render. `initiative_scoped=False` (the
    default, matching `get_pipeline2_composed`) keeps 1.0's posture: every
    initiative is present, so a dep not in `rows` is genuinely dangling — a
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
            'invariant': 'duplicate-id', 'epic_ids': dup_ids,
            'message': (f"duplicate epic ids {', '.join(str(i) for i in dup_ids)} — "
                        "rows collapse silently; the rendered plan is missing epics"),
        })

    out_of_scope = set()
    for row in rows:
        for dep in (row.get('dep_ids') or []):
            if dep in posn:
                continue
            if initiative_scoped:
                out_of_scope.add(dep)
            else:
                violations.append({
                    'invariant': 'dangling-dependency', 'epic_ids': [row['id'], dep],
                    'message': (f"epic {row['id']} depends on epic {dep}, which is "
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
            'invariant': 'cycle', 'epic_ids': stuck,
            'message': (f"dependency cycle: epics {', '.join(str(i) for i in stuck)} "
                        "are in or gated behind a cycle; display fell back to "
                        "stored order"),
        })

    for row in rows:
        for dep in (row.get('dep_ids') or []):
            if dep in posn and posn[dep] > posn[row['id']]:
                violations.append({
                    'invariant': 'topology', 'epic_ids': [row['id'], dep],
                    'message': f"epic {row['id']} renders before its dependency {dep}",
                })

    return violations, sorted(out_of_scope, key=_id_sort_key)


# ---------------------------------------------------------------------------
# Eligibility (DRV-005/006) — a plain per-epic predicate, no batch term
# ---------------------------------------------------------------------------

def _deps_clear(row, by_id):
    """No epic dependency of this row holds open work (`open_req_ids`). ONE
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
    and it orders `launch_candidate_epic_ids`; it no
    longer decides whether work may be announced — `launch_candidacy` does.

    **An open CHECKPOINT upstream closes it too** (the user's amendment).
    `_deps_clear` sees only DIRECT dependencies, so an epic whose own deps are
    clear while a checkpoint further up still holds would otherwise read
    gate-open — `eligible`, so the engine admitted it and announced it past
    the checkpoint (review C1, measured). The checkpoint term lives HERE so
    every predicate built on the gate honours it, not only candidacy.
    """
    return (_deps_clear(row, by_id) and _time_gate_passed(row, now)
            and not _checkpoint_blockers(row, by_id)
            and not (row or {}).get('_initiative_blockers'))


def eligibility(row, by_id, now=None):
    """IS THERE WORK HERE THAT MAY START NOW, GATE AND ALL? The view's
    eligible-now ring.

    An epic has no state (req #3750), so this asks the requirements: the epic
    holds launch-ready work (`launch_req_ids`) and its gate is open. Before
    #3750 it was split in two by epic state — `eligible` for a pending epic,
    `top_up_eligible` for a running one (req #3507) — and that split existed
    only because the state did; one predicate now answers both.
    """
    if not (row.get('launch_req_ids') or []):
        return False
    return _gates_open(row, by_id, now)


def is_checkpoint(row):
    """Is this epic a CHECKPOINT — one that holds everything downstream of it
    while it holds open work? **The answer is the `epics.checkpoint` column
    (req #3649), default ON**, never an inference from the epic's links.

    Before #3649 a checkpoint was IMPLIED: an epic with no work requirement
    (no links, or only tracking containers) was the one kind of epic a
    person closes by hand, and only that kind held its downstream. The
    user's rule (2026-10-19) is that every epic holds by default and a person
    turns the hold OFF to make an epic a mere launch priority — so the fact is
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
    """The epics of this PLAN that this payload's rows do not carry, as
    `{epic_id: {'dep_ids', 'checkpoint', 'open'}}` — so an INITIATIVE-scoped read
    can still see a checkpoint in another initiative (review I1: without it an
    initiative-scoped orchestrator launched straight past one that a whole-plan
    orchestrator held).

    Read from `model['plan_graph']` — `{epics: [{id, checkpoint}],
    epic_deps, epic_requirements, requirements: [{id, requirement_status,
    tracking}]}` — which only the initiative-scoped compose supplies; a whole-plan
    model carries every epic already and has no outside. An epic outside is a
    CHECKPOINT by its own column (req #3649, `is_checkpoint`), and it holds
    by exactly the rule applied inside the initiative: it has open work
    (`open_requirement_ids`). The compose reads links and requirement rows
    for the outside checkpoints only.
    """
    graph = (model or {}).get('plan_graph') or {}
    reqs_by_id = _index_by_id(graph.get('requirements'))
    links = {}
    for link in graph.get('epic_requirements') or []:
        links.setdefault(link['epic_fk'], []).append(link['requirement_fk'])
    deps = {}
    for dep in graph.get('epic_deps') or []:
        deps.setdefault(dep['epic_fk'], []).append(dep['dep_epic_fk'])
    outside = {}
    for epic in graph.get('epics') or []:
        if epic['id'] in by_id:
            continue
        checkpoint = is_checkpoint(epic)
        req_ids = links.get(epic['id'], [])
        tracking_ids = [r for r in req_ids
                        if is_tracking_requirement(reqs_by_id.get(r))]
        outside[epic['id']] = {
            'dep_ids': deps.get(epic['id'], []),
            'checkpoint': checkpoint,
            # Only a checkpoint's open work is ever read (the compose reads
            # links for checkpoints alone), so it is only claimed for one.
            'open': checkpoint and bool(
                open_requirement_ids(req_ids, tracking_ids, reqs_by_id))}
    return outside


def plan_graph_initiative_open(model, by_id):
    """`{initiative_id: bool}` for the plan's initiatives an INITIATIVE-scoped
    read does not carry but an initiative edge reaches (req #3823): the
    compose names them in `plan_graph.upstream_initiative_ids` and reads
    their epics' links and requirement rows, so their open work is computed
    here by the rule applied inside the read. Empty for a whole-plan model,
    which carries every epic as a row."""
    graph = (model or {}).get('plan_graph') or {}
    upstream = set(graph.get('upstream_initiative_ids') or [])
    if not upstream:
        return {}
    reqs_by_id = _index_by_id(graph.get('requirements'))
    links = {}
    for link in graph.get('epic_requirements') or []:
        links.setdefault(link['epic_fk'], []).append(link['requirement_fk'])
    open_by = {iid: False for iid in upstream}
    for epic in graph.get('epics') or []:
        iid = epic.get('initiative_fk')
        if epic['id'] in by_id or iid not in upstream:
            continue
        req_ids = links.get(epic['id'], [])
        tracking_ids = [r for r in req_ids
                        if is_tracking_requirement(reqs_by_id.get(r))]
        if open_requirement_ids(req_ids, tracking_ids, reqs_by_id):
            open_by[iid] = True
    return open_by


def open_checkpoints_upstream(row, by_id, outside=None):
    """Every CHECKPOINT this row depends on, directly or transitively, that
    still holds open work — in id order. Empty means no checkpoint holds it.

    THE USER'S AMENDMENT TO req #3597 (2026-10-17): "requirements that I close
    by hand should block progress ... until I have cleared them". A
    checkpoint is the one dependency that is NOT a mere launch priority: it
    is a person's decision point, so everything downstream of it waits. Once
    its requirements are all closed (or it holds none) it blocks nothing.

    The walk goes THROUGH every ancestor, checkpoint or not, so a checkpoint
    two edges up holds the epic as surely as one edge up, and a clear
    checkpoint does not release anything an open one further up still holds.
    A dependency absent from `by_id` is looked up in `outside` (the rest of
    the plan, which the initiative-scoped compose supplies — `plan_graph_outside`),
    so a checkpoint in another initiative holds this epic exactly as it would under
    a whole-plan read. One found in neither is unknowable and does not block:
    treating every unseen edge as a possible checkpoint would withhold all
    cross-initiative work, the opposite of the rule. A `visited` set makes a cycle
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
    """MAY THIS EPIC'S WORK BE ANNOUNCED FOR LAUNCH? (req #3597.)

    THE USER RULE (2026-10-17, plan 10): bias orchestration toward STARTING
    work. An epic's dependencies are a PRIORITY ORDER for launching, not a
    hard gate, on every plan, always — no mode, no flag. So this predicate
    deliberately does NOT ask `_deps_clear`; the engine fills free slots from
    gate-open candidates first (`launch_candidate_epic_ids` carries that
    order) and then cascades down the dependency chain.

    FOUR CONJUNCTS:

    * At least one `launch_req_ids` entry — only `swarm_ready`, non-tracking
      work is ever launch-ready (rule 8, req #3360). An epic with nothing to
      command is not a candidate.
    * Its own time gate (`_time_gate_passed`). A `not_before` is a person's
      scheduling intention, not a dependency on other work.
    * No CHECKPOINT upstream is still open (`open_checkpoints_upstream`). A
      checkpoint epic — `epics.checkpoint`, ON by default (req
      #3649) — holds everything downstream of it while it holds open work,
      the one EPIC dependency that stays a gate; an epic with the flag OFF is a
      launch priority and nothing more.
    * No initiative its initiative waits for (`initiative_deps`, req #3823),
      directly or transitively, still holds open work.

    Pause is NOT a conjunct here, exactly as it is
    not a conjunct of `eligible`: it is SUPPRESSION, carried separately on
    `launch_suppressed`/`suppressed_by`, so a reader can tell "may launch but
    is held by a person" from "has nothing to launch".

    A SUPERSET of every `eligible` epic, never a replacement for it:
    `eligible` keeps answering the gate question for the view.
    """
    if not (row.get('launch_req_ids') or []):
        return False
    if not _time_gate_passed(row, now):
        return False
    # req #3823 — an initiative this epic's initiative waits for still holds
    # open work. A gate, like the barrier: no free slot overrides it.
    if (row or {}).get('_initiative_blockers'):
        return False
    return not _checkpoint_blockers(row, by_id)


def launch_queue(candidate_ids, by_id, reqs_by_id):
    """THE LAUNCH PRIORITY, as one ordered list — the only place it is stated
    (req #3649: "minimal and well tested … focused in a single area").

    `[{'epic_id', 'requirement_id'}, ...]`: every requirement the engine may
    announce, in the order it hands out free slots. The engine consumes this
    list and ranks by position in it; it keeps no ordering rule of its own.

    THE ORDER:

    1. `candidate_ids` — launch candidates (`launch_candidacy`) gate-open
       first, then past their gate, each half in display order (req #3597:
       a dependency is WHO GOES FIRST, never WHETHER; a CHECKPOINT upstream
       has already removed a held epic from candidacy).
    2. Within an epic, `coordination_type == 'deployed'` first (a deployed
       worker closes itself through `/swarm-complete`, so its slot frees and
       the plan drains), then ascending requirement id — FIFO, since ids
       are allocated in creation order. **Within an epic only** (user ruling
       2026-10-19, superseding req #3623's scope-wide preference): a later
       epic's deployed work never jumps an earlier epic's implemented work.

    A `launch_suppressed` (paused) epic is LEFT OUT — this is what
    WOULD be announced, and suppression is reported beside it on the row. A
    `run=manual` epic is IN: where its READY-MANUAL reminder ranks against
    auto work is policy too, and the engine must not keep a second rule for
    it. Only *expiry* of a reminder's announce window — debounce state the
    derivation cannot see — stays an engine term.
    """
    queue = []
    for epic_id in candidate_ids:
        row = by_id.get(epic_id) or {}
        if row.get('launch_suppressed'):
            continue
        ids = list(row.get('launch_req_ids') or [])
        ids.sort(key=lambda rid: (
            0 if (reqs_by_id.get(rid) or {}).get('coordination_type') == 'deployed'
            else 1,
            _id_sort_key(rid)))
        queue.extend({'epic_id': epic_id, 'requirement_id': rid} for rid in ids)
    return queue


# ---------------------------------------------------------------------------
# Initiative-to-initiative dependencies (req #3823) — a gate, derived
# ---------------------------------------------------------------------------

def initiative_dep_map(edges):
    """`{initiative_id: [dep_initiative_id, ...]}` from `initiative_deps` rows,
    each list in row order with duplicates dropped."""
    deps = {}
    for edge in edges or []:
        waiter, dep = edge.get('initiative_fk'), edge.get('dep_initiative_fk')
        if waiter is None or dep is None:
            continue
        bucket = deps.setdefault(waiter, [])
        if dep not in bucket:
            bucket.append(dep)
    return deps


def initiative_open_work(rows, outside_open=None):
    """`{initiative_id: bool}` — does any epic under the initiative hold open
    work? Read from the rows' `open_req_ids` (the one fact, req #3750) and,
    for the initiatives an initiative-scoped read does not carry, from
    `outside_open` (`plan_graph_initiative_open`). An initiative with no epics
    holds nothing and is simply absent here; `known` membership is the
    caller's to judge."""
    open_by = dict(outside_open or {})
    for row in rows or []:
        iid = row.get('initiative_id')
        if iid is None:
            continue
        open_by[iid] = open_by.get(iid, False) or bool(row.get('open_req_ids'))
    return open_by


def open_initiatives_upstream(initiative_id, deps, open_by, known):
    """Every initiative `initiative_id` waits for, directly or transitively,
    that still holds open work — in id order. Empty means nothing holds it.

    The walk goes THROUGH every upstream initiative, open or not, so a clear
    middle link does not release what an open one further up still holds
    (C -> B -> A: C waits while A holds work even when B holds none). An
    upstream id outside `known` (the plan's initiatives) is unknowable — a
    dangling edge the gateway should never have let in — and HOLDS: this is a
    gate, and holding is the recoverable direction; `initiative_violations`
    reports it. A `visited` set makes a cycle terminate."""
    blockers, visited = set(), set()
    stack = list(deps.get(initiative_id) or [])
    while stack:
        dep = stack.pop()
        if dep in visited:
            continue
        visited.add(dep)
        if dep not in known or open_by.get(dep):
            blockers.add(dep)
        stack.extend(deps.get(dep) or [])
    return sorted(blockers, key=_id_sort_key)


def gate_graph(initiative_edges, epic_edges, epic_initiative):
    """THE GATE GRAPH (req #3823) — what an initiative edge MEANS, at the
    granularity it is enforced at: the epic.

    Nodes are epics `('e', id)` and one GATE per initiative `('g', id)` —
    "everything this initiative's epics wait for". Every epic waits on its own
    initiative's gate (`e -> g(X)`); an epic edge is itself (`a -> b`); an
    initiative edge X waits for Y is `g(X) -> e` for every epic of Y, and
    `g(X) -> g(Y)` because the hold is transitive (the derivation walks THROUGH
    Y to whatever Y waits for, epics or none). A cycle through a gate node is a
    deadlock the derivation would really hold forever; a cycle of epic edges
    alone is the epic layer's own concern (`set_epic_deps`, `verify_order`).

    Lifting epic edges to initiative pairs instead — the first cut — refused
    satisfiable plans: with C waits for A, `a1 -> b1` and `b2 -> c1` lift to
    A -> B -> C -> A, yet b1 and b2 are unrelated epics and nothing waits
    forever (code review, req #3823).

    `initiative_edges` are `(waiter, waited-on)` initiative pairs,
    `epic_edges` `(waiter, waited-on)` epic pairs, `epic_initiative` maps every
    epic of the plan to its initiative. Returns `{node: [successor, ...]}`,
    successors in a fixed order so a walk is deterministic."""
    adj = {}
    epics_of = {}
    for eid, iid in (epic_initiative or {}).items():
        if iid is None:
            continue
        epics_of.setdefault(iid, []).append(eid)
        adj.setdefault(('e', eid), []).append(('g', iid))
    for a, b in epic_edges or []:
        adj.setdefault(('e', a), []).append(('e', b))
    for x, y in initiative_edges or []:
        succ = adj.setdefault(('g', x), [])
        succ.append(('g', y))
        succ.extend(('e', eid) for eid in epics_of.get(y, []))
    for succ in adj.values():
        succ.sort(key=lambda n: (n[0], _id_sort_key(n[1])))
    return adj


def gate_path(adj, starts, target, need_gate=False):
    """The shortest path from any of `starts` to `target` in `gate_graph`
    output, as a node list, or None. `need_gate`: only a path that leaves a
    gate node somewhere counts — what makes a cycle through a new EPIC edge an
    initiative deadlock rather than a plain epic cycle. Breadth-first over
    (node, left-a-gate) states, so the answer is deterministic."""
    queue, parent = [], {}
    for node in starts:
        state = (node, False)
        if state not in parent:
            parent[state] = None
            queue.append(state)
    while queue:
        state = queue.pop(0)
        node, used = state
        if node == target and (used or not need_gate):
            path, cursor = [], state
            while cursor is not None:
                path.append(cursor[0])
                cursor = parent[cursor]
            return list(reversed(path))
        for nxt in adj.get(node, ()):
            nstate = (nxt, used or node[0] == 'g')
            if nstate not in parent:
                parent[nstate] = state
                queue.append(nstate)
    return None


def initiative_edge_cycle(adj, waiter, dep, epic_initiative):
    """The cycle an initiative edge `waiter` waits for `dep` closes, as a node
    list from `g(waiter)` back to it — or None. Walks from what the edge
    points at (`dep`'s gate and its epics) back to `waiter`'s gate."""
    starts = [('g', dep)] + sorted(
        (('e', e) for e, i in (epic_initiative or {}).items() if i == dep),
        key=lambda n: _id_sort_key(n[1]))
    back = gate_path(adj, starts, ('g', waiter))
    return None if back is None else [('g', waiter)] + back


def gate_cycle_text(path):
    """A gate-graph cycle in words: `initiative 3 -> epic 9 -> epic 4 -> initiative 3`."""
    return ' -> '.join(('initiative %s' if kind == 'g' else 'epic %s') % nid
                       for kind, nid in path)


def initiative_violations(initiative_edges, epic_edges, epic_initiative, known):
    """`initiative-cycle` (an initiative edge on a cycle of the gate graph —
    epics held forever) and `dangling-initiative-dependency` (an edge naming an
    initiative outside this plan) — what slipped past the gateway's refusal.
    One violation per distinct cycle; `initiative_ids` and `epic_ids` name the
    initiatives and epics on it."""
    violations, seen = [], set()
    adj = gate_graph(initiative_edges, epic_edges, epic_initiative)
    for waiter, dep in initiative_edges or []:
        if dep not in known or waiter not in known:
            violations.append({
                'invariant': 'dangling-initiative-dependency', 'epic_ids': [],
                'initiative_ids': [waiter, dep],
                'message': (f"initiative {waiter} waits for initiative {dep}, which "
                            "is not in this plan — it holds until the edge is removed"),
            })
            continue
        cycle = initiative_edge_cycle(adj, waiter, dep, epic_initiative)
        if cycle is None:
            continue
        key = frozenset(cycle)
        if key in seen:
            continue
        seen.add(key)
        initiative_ids, epic_ids = [], []
        for kind, nid in cycle:
            bucket = initiative_ids if kind == 'g' else epic_ids
            if nid not in bucket:
                bucket.append(nid)
        violations.append({
            'invariant': 'initiative-cycle', 'epic_ids': epic_ids,
            'initiative_ids': initiative_ids,
            'message': (f"{gate_cycle_text(cycle)} wait for each other — every epic "
                        "on it is held until an edge is removed"),
        })
    return violations


# ---------------------------------------------------------------------------
# Pause (DRV-016/017/018) — launch suppression, initiative-scoped
# ---------------------------------------------------------------------------

def pause_state(model, rows):
    """Which scopes are paused, and therefore which epics must not be
    launched — restated for containment from `pipeline_derive.pause_state`,
    and simpler here: an epic has exactly ONE initiative (a column, not a
    tie-broken tally), so "the epic's dominant initiative is paused" collapses to
    a plain membership test.

    TWO SCOPES, ONE RULE, unchanged from 1.0: an epic is suppressed when its
    PLAN is paused, or when its OWN initiative is paused (DRV-017 — an initiative pause
    suppresses that initiative's epics and not its neighbour, because containment
    gives initiative pause a real scope key no 1.0 initiative ever had). An initiative pause
    binds a WHOLE-PLAN orchestrator too (DRV-018): suppression is a property
    of the EPIC, computed here regardless of which scope is asking, so there
    is nothing for a whole-plan orchestrator to opt out of.

    `eligible` (from `eligibility` above) is left UNCHANGED by this function
    (DRV-016) — it is called separately, over the same rows, and neither
    writes the other's field. A consumer distinguishes "eligible and
    suppressed" (waits on a person) from "not eligible" (waits on a gate) by
    reading both.

    `suppressed_by` is a LIST: when both clauses fire, naming only one would
    leave a reader who unpaused just the plan surprised the epic is still
    held. A missing `initiative_status` reads as `active` — the column's own
    default, and what every row written before an initiative pause ever existed
    is.
    """
    pipeline = model.get('pipeline') or {}
    pipeline_status = pipeline.get('pipeline_status')
    pipeline_paused = pipeline_status == PAUSED_STATUS

    paused_initiatives = {initiative.get('id') for initiative in model.get('initiatives') or []
                    if initiative.get('initiative_status') == PAUSED_STATUS
                    and initiative.get('id') is not None}

    suppressed = []
    for row in rows:
        reasons = []
        if pipeline_paused:
            reasons.append('pipeline')
        if row.get('initiative_id') in paused_initiatives:
            reasons.append('initiative')
        row['launch_suppressed'] = bool(reasons)
        row['suppressed_by'] = reasons
        if reasons:
            suppressed.append(row['id'])

    return {
        'pipeline_status': pipeline_status,
        'pipeline_paused': pipeline_paused,
        'paused_initiative_ids': sorted(paused_initiatives, key=_id_sort_key),
        # In DISPLAY order — `derive_plan2` calls this after `display_order`,
        # so `rows` already carries the caller's rendered sequence.
        'suppressed_epic_ids': suppressed,
    }


# ---------------------------------------------------------------------------
# Requirement counts (item 2)
# ---------------------------------------------------------------------------

def requirement_counts(model):
    """Met/total requirement counts, per initiative and for the whole plan —
    RE-POINTED at the epic's `initiative_fk` (item 2): a requirement's bucket is
    now where its work is SEATED, not where its (nonexistent) feature was
    filed. `pipeline2_epic_requirements` carries `PRIMARY KEY
    (requirement_fk)` alone (gate delta, req #3336) — one epic per
    requirement, structural — so the lookup is a plain one-to-one join, not a
    tie-break.

    Tracking requirements are excluded from both the numerator and the
    denominator, unchanged from 1.0 (req #3123's container exemption). The
    numerator is `TERMINAL_REQUIREMENT_STATUSES` — the same statuses
    `open_requirement_ids` treats as no longer open.

    `by_initiative` is a LIST, sorted by initiative id ascending — matching 1.0's reason
    for the same shape: a Python dict with int keys silently stringifies
    under `json.dumps`, which would make this module's wire shape disagree
    with any 2.0 counterpart that renders a JS `Map` (not JSON at all) the
    same way. See the module docstring for the measured before/after delta
    on the live plan.

    **`overall`'s POPULATION follows `model['requirements']`, which is a
    different set depending on which composed read produced `model`** — the
    same "which population" caveat `get_pipeline2_initiative_composed`'s own
    docstring states for `epic_count` (req #3287). On the whole-plan read
    it is every requirement in the plan; on the initiative-scoped read it is only
    the requirements linked to THAT initiative's own epics, so `overall` there is
    identical to that initiative's own `by_initiative` entry — never the plan's true
    total. A caller rendering "N/M requirements complete" from an
    initiative-scoped read is showing the initiative's number, not the plan's, and must
    label it that way.
    """
    epics_by_id = _index_by_id(model.get('epics'))
    req_to_epic = {}
    for link in model.get('epic_requirements') or []:
        req_to_epic[link['requirement_fk']] = link['epic_fk']

    overall = {'met': 0, 'total': 0}
    by_initiative = {}
    for req in model.get('requirements') or []:
        if not req or is_tracking_requirement(req):
            continue
        met = req.get('requirement_status') in TERMINAL_REQUIREMENT_STATUSES
        overall['total'] += 1
        if met:
            overall['met'] += 1
        epic = epics_by_id.get(req_to_epic.get(req['id']))
        initiative_id = epic.get('initiative_fk') if epic else None
        if initiative_id is None:
            continue
        bucket = by_initiative.setdefault(initiative_id, {'initiative_id': initiative_id, 'met': 0, 'total': 0})
        bucket['total'] += 1
        if met:
            bucket['met'] += 1
    return {
        'overall': overall,
        'by_initiative': sorted(by_initiative.values(), key=lambda b: _id_sort_key(b['initiative_id'])),
    }


# ---------------------------------------------------------------------------
# Engine 2's three plan facts (req #3757) — rule R1: a fact the engine needs is
# added to the derivation, never computed beside it
# ---------------------------------------------------------------------------

def _session_requirement_id(source_ref):
    """`requirement:<id>` -> id, else None — the `source_ref` shape `/swarm-start` writes."""
    if not isinstance(source_ref, str) or not source_ref.startswith('requirement:'):
        return None
    try:
        return int(source_ref.split(':', 1)[1])
    except ValueError:
        return None


def _primary_requirement_id(arguments):
    """The requirement a primary birth record is for; None for a worker launch
    or an unreadable id."""
    if not isinstance(arguments, str):
        return None
    text = arguments.strip()
    if not text.startswith(PRIMARY_START_TAG):
        return None
    rest = text[len(PRIMARY_START_TAG):].split()
    try:
        return int(rest[0]) if rest else None
    except ValueError:
        return None


def _named_requirement_ids(arguments):
    """Every requirement id a `swarm_starts.arguments` value names."""
    if not isinstance(arguments, str):
        return set()
    text = arguments.strip()
    if text.startswith(PRIMARY_START_TAG):
        text = text[len(PRIMARY_START_TAG):]
    found = set()
    for token in text.split():
        try:
            found.add(int(token))
        except ValueError:
            continue
    return found


def _is_stranded_start(session):
    """A `starting` session that never reached a terminal (req #3881).

    `/swarm-start` writes the session row at `starting` and the worker's
    terminal is stamped once it is running. A launch that dies in `checkout`
    leaves the row at `starting` with BOTH terminal columns null, still linked
    to its requirement and with no terminal status — a LIVE status, so counting
    it as work meant the requirement was never stalled and nothing anywhere told
    a person. Only the composing route's row dicts can say so; a bare
    `source_ref` string carries no terminal and counts as work, as it always did.
    A fresh launch is also terminal-less for a moment: `STALL_GRACE_SECONDS`
    covers that, as it covers every requirement just written to `development`."""
    if not isinstance(session, dict):
        return False
    return (session.get('swarm_status') == 'starting'
            and session.get('terminal_window_id') in (None, '')
            and session.get('terminal_number') is None)


def work_evidence(session_refs, start_rows):
    """`{live_req_ids, primary_req_ids}` from the rows the composing route read.

    `session_refs` are the LIVE sessions — each a `source_ref` string, or a row
    dict (`source_ref`, `swarm_status`, `terminal_window_id`, `terminal_number`)
    from which a session stranded at `starting` with no terminal is dropped
    (req #3881: it is not work evidence). `start_rows`
    are `swarm_starts` rows (`id`, `arguments`, `linked_session_count`) — every
    primary birth record and every row after the oldest of them. A primary
    record is OPEN while no session is linked to it and no LATER start names
    its requirement (req #3290: the closeout's link is best-effort, so a later
    launch also retires it)."""
    live = sorted({rid for rid in (
        _session_requirement_id(r.get('source_ref') if isinstance(r, dict) else r)
        for r in session_refs or () if not _is_stranded_start(r))
        if rid is not None})
    rows = [r for r in start_rows or () if isinstance(r, dict) and isinstance(r.get('id'), int)]
    primary = set()
    for row in rows:
        rid = _primary_requirement_id(row.get('arguments'))
        if rid is None or (row.get('linked_session_count') or 0) != 0:
            continue
        later = any(other['id'] > row['id'] and rid in _named_requirement_ids(other.get('arguments'))
                    for other in rows)
        if not later:
            primary.add(rid)
    return {'live_req_ids': live, 'primary_req_ids': sorted(primary)}


def _evidence(model):
    """The work evidence the composing route attached, or None when it could
    not be read (or this caller supplied none)."""
    evidence = model.get('work_evidence')
    if not isinstance(evidence, dict):
        return None
    live, primary = evidence.get('live_req_ids'), evidence.get('primary_req_ids')
    if not isinstance(live, list) or not isinstance(primary, list):
        return None
    return {'live': set(live), 'primary': set(primary)}


def stall_requirement_ids(row, reqs_by_id, evidence, now):
    """`stall_req_ids` for one row: its gating requirements at `development`
    that NOBODY is working — no live session and no open primary birth record —
    and that have been in `development` past `STALL_GRACE_SECONDS` (a missing
    `started_at` counts as past it). Empty when the evidence is unavailable:
    `stall_evidence` says so, and an unread sweep never claims a stall."""
    if evidence is None:
        return []
    now_epoch = _to_epoch(now)
    stalled = []
    for rid in row.get('gating_req_ids') or []:
        req = reqs_by_id.get(rid) or {}
        if req.get('requirement_status') != 'development':
            continue
        if rid in evidence['live'] or rid in evidence['primary']:
            continue
        started = _to_epoch(req.get('started_at'))
        if started is not None and now_epoch is not None \
                and now_epoch - started < STALL_GRACE_SECONDS:
            continue
        stalled.append(rid)
    return stalled


def seat_violations(model):
    """`one-epic-per-requirement` — a work requirement seated on more than one
    epic would be announced, and launched, once per seat. The junction's key
    permits it, so the derivation reports it (retirement map item 4, req #3757).
    Tracking containers are never launched and are not counted."""
    reqs_by_id = _index_by_id(model.get('requirements'))
    epic_ids = {e.get('id') for e in model.get('epics') or []}
    # An initiative-scoped read also carries this initiative's requirements'
    # seats in the plan's OTHER initiatives (`plan_graph.outside_seats`), so a
    # double seat across initiatives is reported in both scopes.
    outside = list((model.get('plan_graph') or {}).get('outside_seats') or [])
    epic_ids |= {link.get('epic_fk') for link in outside}
    seats = {}
    for link in list(model.get('epic_requirements') or []) + outside:
        rid, eid = link.get('requirement_fk'), link.get('epic_fk')
        if eid not in epic_ids or is_tracking_requirement(reqs_by_id.get(rid)):
            continue
        if eid not in seats.setdefault(rid, []):
            seats[rid].append(eid)
    return [{'invariant': 'one-epic-per-requirement',
             'epic_ids': sorted(eids, key=_id_sort_key), 'requirement_id': rid,
             'message': (f"requirement {rid} is seated on epics "
                         f"{', '.join(str(e) for e in sorted(eids, key=_id_sort_key))} "
                         "— it would be launched once per seat")}
            for rid, eids in sorted(seats.items(), key=lambda kv: _id_sort_key(kv[0]))
            if len(eids) > 1]


def _public_time(value):
    """A stored timestamp as the payload carries it: ISO-8601 UTC with `Z`."""
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat(timespec='seconds') + 'Z'
    text = str(value).strip().replace(' ', 'T')
    if len(text) == 10:
        text += 'T00:00:00'
    if _to_epoch(text) is None:
        return text
    return text if text.endswith(('Z', 'z')) or '+' in text[10:] or '-' in text[10:] else text + 'Z'


# ---------------------------------------------------------------------------
# The whole derivation, in one call
# ---------------------------------------------------------------------------

def _initiative_gate(model, rows, by_id):
    """The initiative gate for one read (req #3823): `{blocked_by, rows,
    violations}` — `blocked_by` per initiative id, the per-initiative rows the
    payload carries, and the combined-graph violations.

    The plan's initiatives are `model['initiatives']` plus, on an
    initiative-scoped read, `plan_graph.initiative_ids` (the compose reads the
    plan's ids so a dependency on another initiative is KNOWN, not dangling).
    `model['initiative_deps']` is the whole plan's edges on both reads; the
    epic edges the gate graph adds are this read's own plus, scoped, the
    plan graph's (each outside epic carrying its `initiative_fk`)."""
    graph = (model or {}).get('plan_graph') or {}
    edges_rows = model.get('initiative_deps') or []
    deps = initiative_dep_map(edges_rows)
    known = {i.get('id') for i in model.get('initiatives') or []}
    known |= set(graph.get('initiative_ids') or [])
    open_by = initiative_open_work(rows, plan_graph_initiative_open(model, by_id))

    waiting = set(deps)
    blocked_by = {iid: open_initiatives_upstream(iid, deps, open_by, known)
                  for iid in waiting}

    initiative_of = {row['id']: row.get('initiative_id') for row in rows}
    for epic in graph.get('epics') or []:
        initiative_of.setdefault(epic['id'], epic.get('initiative_fk'))
    epic_edges = sorted({(d.get('epic_fk'), d.get('dep_epic_fk'))
                         for d in list(model.get('epic_deps') or [])
                         + list(graph.get('epic_deps') or [])
                         if d.get('epic_fk') is not None and d.get('dep_epic_fk') is not None},
                        key=lambda e: (_id_sort_key(e[0]), _id_sort_key(e[1])))
    initiative_edges = [(waiter, dep) for waiter, targets in deps.items()
                        for dep in targets]
    violations = initiative_violations(initiative_edges, epic_edges, initiative_of, known)

    out_rows = []
    for initiative in model.get('initiatives') or []:
        iid = initiative.get('id')
        out_rows.append({
            'id': iid,
            'dep_initiative_ids': list(deps.get(iid) or []),
            'holds_open_work': bool(open_by.get(iid)),
            'initiative_blocked_by': blocked_by.get(iid, []),
        })
    return {'blocked_by': blocked_by, 'rows': out_rows, 'violations': violations}


def derive_plan2(model, now=None, initiative_scoped=False):
    """Everything this requirement derives from one composed 2.0 payload:
    derive -> order -> check. Pure CPU over rows the composed read already
    fetched — zero additional gateway reads, matching design rule 5.

    Narrower than `pipeline_derive.derive_plan` in one respect: no batches —
    Batch does not exist in 2.0. `eligible`, `open_req_ids` (req #3750),
    `gate_open` / `launch_candidate` (req #3597),
    `pause` IS built here (DRV-005/006/016/017/018 — the verification
    register's boundary, not req #3345's stale docstring). `now` rides
    the payload for the same reason 1.0 carries it, and because
    `eligibility` above is one of this module's own consumers of it.

    `initiative_scoped` MUST be `True` when `model` came from
    `get_pipeline2_initiative_composed` — it changes only how `verify_order`
    reports a dependency it cannot see (an honest `out_of_scope_dep_ids`
    entry instead of a false `dangling-dependency` alarm; see that
    function's docstring for the defect this fixes). It does not change
    ordering or eligibility: an epic gated on an out-of-scope dependency is
    correctly, and unavoidably, `eligible: False` here either way — this
    payload cannot see whether that dependency holds open work, and the safe
    direction is not to guess. A caller that needs the true answer reads the
    whole-plan render instead.

    Every per-row field here is an id, an enum string, a boolean, or a short
    list of one of those — no re-embedded requirement or initiative rows, matching
    1.0's "compact block" discipline (`test_the_derived_block_is_compact_
    ids_and_enums_only`'s reason, req #3078's payload budget).
    """
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

    plan_rows = build_plan_rows(model)
    ordered = display_order(plan_rows, model.get('initiatives') or [])
    rows = ordered['rows']
    violations, out_of_scope_dep_ids = verify_order(rows, initiative_scoped=initiative_scoped)
    # AFTER `display_order`, so `suppressed_epic_ids` comes out in display
    # order, and it writes `launch_suppressed`/`suppressed_by` onto the same
    # row dicts the payload below projects — matching 1.0's ordering of the
    # two calls and its stated reason.
    pause = pause_state(model, rows)
    violations = violations + seat_violations(model)
    evidence = _evidence(model)
    reqs_by_id = _index_by_id(model.get('requirements'))

    by_id = {row['id']: row for row in rows}
    # The user's amendment to req #3597 — ONE checkpoint walk per row, cached
    # on the row, before any predicate reads it (`_checkpoint_blockers`).
    outside = plan_graph_outside(model, by_id)
    for row in rows:
        row['_checkpoint_blockers'] = open_checkpoints_upstream(row, by_id,
                                                                outside)
    # req #3823 — the initiative gate, one walk per initiative, cached on each
    # row before any predicate reads it (`_gates_open`, `launch_candidacy`).
    initiative_gate = _initiative_gate(model, rows, by_id)
    for row in rows:
        row['_initiative_blockers'] = initiative_gate['blocked_by'].get(
            row['initiative_id'], [])
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

    violations = violations + initiative_gate['violations']

    unresolved = []
    for row in rows:
        for rid in row.get('unresolved_req_ids') or []:
            if rid not in unresolved:
                unresolved.append(rid)

    return {
        'now': (now.isoformat(timespec='seconds') + 'Z'
                if isinstance(now, datetime) else now),
        'initiative_order': ordered['initiative_order'],
        'display_order': [row['id'] for row in rows],
        'rows': [{
            'id': row['id'],
            'run': row['run'],
            # req #3649 — the two stored flags, so a reader can say WHY a
            # epic holds its downstream (checkpoint) and draw the lock.
            'checkpoint': row['checkpoint'],
            'locked': row['locked'],
            'eligible': row['id'] in eligible_set,
            # req #3750 — the epic's OPEN WORK, the one fact every question
            # about an epic is asked through (an epic has no state).
            'open_req_ids': row['open_req_ids'],
            # req #3597. `gate_open` is the gate REPORTED (no dep holds open
            # work and the time gate passed) — the view's "gate satisfied / waiting".
            # `launch_candidate` is whether this epic's work may be announced
            # for launch, which no longer requires the gate.
            'gate_open': row['id'] in gate_open_set,
            'launch_candidate': row['id'] in candidate_set,
            # The amendment: checkpoint epics upstream that still hold open
            # work (req #3649: the flag, on by default). Non-empty means this
            # epic's work is NOT announced until they are.
            'checkpoint_blocked_by': row['_checkpoint_blockers'],
            # req #3823 — the initiatives this epic's initiative waits for
            # (transitively) that still hold open work. Non-empty means this
            # epic's work is NOT announced until they hold none. Kept apart
            # from `checkpoint_blocked_by`: a different gate, named apart.
            'initiative_blocked_by': row['_initiative_blockers'],
            'initiative_id': row['initiative_id'],
            'dep_ids': row['dep_ids'],
            # Which of THIS row's own deps are out of scope (a subset of
            # `dep_ids`, always empty unless `initiative_scoped`) — so a reader
            # deciding why a row is `eligible: False` does not have to
            # intersect `dep_ids` against the plan-level
            # `out_of_scope_dep_ids` by hand to find the honest reason.
            'out_of_scope_dep_ids': [d for d in row['dep_ids'] if d in out_of_scope_set],
            'req_ids': row['req_ids'],
            # req #3757 — the three facts Engine 2 reads instead of computing
            # them (rule R1): the gating set, the epic's own start time, and
            # the gating requirements nobody is working.
            'gating_req_ids': row['gating_req_ids'],
            'not_before': _public_time(row['_not_before']),
            'stall_req_ids': stall_requirement_ids(row, reqs_by_id, evidence, now),
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
        # req #3823 — one entry per initiative this read carries, in id
        # order: the initiatives it waits for, whether it holds
        # open work itself (so it holds its own dependents), and the ones
        # holding it now.
        'initiative_rows': initiative_gate['rows'],
        'eligible_epic_ids': eligible_ids,
        # req #3597 — every launch candidate, in launch PRIORITY order
        # (gate-open first, then display order), NOT display order.
        'launch_candidate_epic_ids': candidate_ids,
        # req #3649 — THE launch order, one entry per announceable
        # requirement (`launch_queue`): the engine ranks by position here.
        'launch_queue': queue,
        'violations': violations,
        # req #3757 — whether `stall_req_ids` could be answered: `complete`
        # when the work evidence was read, `unavailable` when it was not (every
        # row's `stall_req_ids` is then empty, which is NOT an all-clear).
        'stall_evidence': 'complete' if evidence is not None else 'unavailable',
        'cycle_detected': ordered['cycle_detected'],
        'cycle_epic_ids': ordered['cycle_epic_ids'],
        'duplicate_epic_ids': ordered['duplicate_epic_ids'],
        'unresolved_req_ids': unresolved,
        # Only ever non-empty when `initiative_scoped=True` — a dependency this
        # initiative-scoped payload never fetched, not a plan defect. See
        # `verify_order`'s docstring.
        'out_of_scope_dep_ids': out_of_scope_dep_ids,
        'requirement_counts': requirement_counts(model),
    }
