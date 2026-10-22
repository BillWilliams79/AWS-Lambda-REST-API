"""Pipeline 2.0 derivation — the unit tier (req #3349; MOVED HERE by req #3367
along with the module itself — `memory/pipeline-2-orchestration-algorithm.md`
§ 8, remediation B composing form).

Pure-function tests: `pipeline2_derive.py` performs no I/O, so unlike
`test_pipeline2_compose.py` there is no fake gateway here — every test builds
a composed-read-shaped `model` dict directly (`{pipeline, epics, steps,
step_requirements, step_deps, requirements}`) and calls the module's
functions against it. No database, no `exports.sh` needed.

Two things this tier is uniquely able to prove:

  * **A deleted field never reappears.** A field that silently survives on a
    derived row is req #3349's own stated failure mode — see the
    "deleted fields" block below.
  * **A step has no state** (req #3750): every question about a step is
    asked of its requirements through `open_req_ids`.

## The corpus, re-pointed at one target (req #3367 deliverable 6)

`darwin-mcp/tests/conformance/pipeline_conformance.json` (52 cases, checked
2026-08-09 — the "34" some earlier prose cites is stale) is 1.0's drift
control between two implementations. Under remediation B there is only ONE
2.0 implementation and there has never been a second — `pipelineModel.js` has
no 2.0 counterpart and, per this module's own docstring item 5, never will —
so re-pointing the corpus "at one target" means what it says: every case
whose BEHAVIOUR still exists in 2.0 is re-expressed as a test THIS FILE runs
against `derive_plan2` directly, and "retire the second harness" is satisfied
by there being nothing to retire (no `test_pipeline2_model.test.js` was ever
built). The 1.0 corpus file and its two harnesses are UNTOUCHED — 1.0 keeps
operating and its own drift control stays exactly as it was.

**Mapping, by 1.0 case name.** Cases are grouped by what they test, not by
file order, so the N/A reasons read as one structural argument rather than 52
one-line verdicts.

Translated and covered by a test in this file:
  `empty-plan` → `test_empty_plan_derives_cleanly`;
  `single-step-linkless-unstamped`, `single-step-linkless-stamped`,
    `rule1-terminal-status-matrix` →
    `test_open_requirement_ids_is_gating_work_not_yet_terminal`,
    `test_a_step_holding_nothing_has_no_open_work_and_no_state` (req #3750:
    there is no stamp and no step state — the stamped case is gone);
  `tracking-container-exemption` → `test_tracking_requirement_is_never_open_work`;
  `tracking-flag-coercion` → `test_tracking_flag_coercion_matrix`;
  `requirement-counts-tracking-and-terminal-statuses`,
    `requirement-counts-deferred-completes-epic`,
    `requirement-counts-wontfix-completes-epic` →
    `test_requirement_counts_groups_by_the_seated_epic_not_a_retired_middle_tier_chain`,
    `test_requirement_counts_excludes_tracking_containers`,
    `test_requirement_with_no_step_link_counts_overall_not_by_epic`
    (`met`/`deferred`/`wontfix` are one TERMINAL_REQUIREMENT_STATUSES tuple,
    not three branches — a case per status is not a case per behaviour);
  `eligibility-step-gates`, `eligibility-time-gate-passed`,
    `eligibility-time-gate-pending`, `time-gate-timestamp-formats`,
    `time-gate-with-no-clock`, `time-gate-non-canonical-spellings-are-not-passed` →
    `test_eligibility_requires_every_dependency_clear`,
    `test_eligibility_consults_not_before_against_the_payload_clock`,
    `test_eligibility_requires_launch_ready_work` (the timestamp-grammar
    hazards themselves are `_to_epoch`'s, restated verbatim from 1.0's
    already-tested `_TIMESTAMP_RE` — module docstring "changed" item 3);
  `topological-order-diamond` → `test_display_order_has_no_state_band` and
    the `display_order`/`verify_order` tests around it
    (`state-bands-outrank-stored-order` and
    `banding-inversion-forced-by-topology-is-not-a-violation` are retired with
    step state, req #3750);
  `cycle-detection` → `test_cycle_within_one_epic_is_detected_and_falls_back_to_stored_order`;
  `duplicate-step-ids` → `test_duplicate_step_id_is_reported`;
  `dangling-dependency` →
    `test_dangling_dependency_is_detected_and_reported`,
    `test_epic_scoped_read_reports_out_of_scope_not_dangling`,
    `test_whole_plan_read_still_reports_a_genuinely_dangling_dependency`;
  `unresolved-requirement-ids` →
    `test_derive_plan2_unresolved_requirement_is_reported_not_silently_dropped`;
  `pause-suppresses-whole-plan`, `pause-suppresses-one-epic-not-its-neighbour` →
    `test_epic_pause_suppresses_only_that_epics_steps`,
    `test_whole_plan_pause_suppresses_every_epics_steps`,
    `test_suppressed_by_names_both_reasons_when_both_fire`;
  `serial-holds-every-epic-but-the-live-one`,
    `serial-advances-when-the-live-epic-closes`,
    `serial-terminal-statuses-close-an-epic-like-met`,
    `serial-and-pause-both-name-themselves`,
    `serial-never-holds-a-step-with-no-epic-label` (N/A half: no step can
    have no epic label — folds into the epic_fk-is-a-column argument below),
    `serial-all-epics-closed-holds-nothing`,
    `parallel-is-the-default-and-suppresses-nothing`,
    `absent-execution-mode-reads-as-parallel` → the whole serial-state block,
    `test_serial_state_parallel_mode_holds_nothing` through
    `test_backward_edge_under_parallel_mode_is_not_a_deadlock`;
  `launchable-status-matrix`, `launch-args-drop-met-requirements`,
    `unresolved-requirement-is-not-launchable` (their PER-STEP half; the
    BATCH half is N/A below) →
    `test_launch_req_ids_only_swarm_ready_minus_containers`,
    `test_no_launch_reason_distinguishes_no_links_from_containers`;
  `epic-sort-order-outranks-first-appearance`,
    `epic-sort-order-absent-falls-back-to-first-appearance`,
    `epic-sort-order-null-sorts-after-every-ordered-epic` →
    `test_manual_sort_order_orders_the_epic_blocks`,
    `test_manual_sort_order_wins_over_derived_order`,
    `test_started_epics_order_by_earliest_activity_ahead_of_unstarted`;
  `serial-turn-follows-the-epic-sort-order` → `test_turn_suppression_appends_to_pause_suppression`
    plus the sort-order tests above (both mechanisms read the same `epic_order`);
  `epic-sort-order-does-not-outrank-a-state-band` — retired with step state
    (req #3750): there is no state band for sort order to outrank.

Structurally N/A — the SCENARIO cannot occur in 2.0, not merely untested:
  `batch-splits-on-machine`, `batch-splits-on-run-mode-and-gate`,
    `batch-splits-on-epic`, `batch-groups-on-remaining-gate`,
    `batch-no-launch-reason-no-links`, `batch-contiguity-avoidable-split-still-reports`,
    `machines-sharing-a-title`, `batch-no-launch-reason-nothing-launchable`
    (its batch half) — Batch does not exist in 2.0; the Step is the launch
    unit (first-principles record § 6, docstring item 1's "no `batches` key");
  `label-inheritance-chain`, `dominant-label-majority-and-tie`,
    `epic-sort-order-rides-an-inherited-label` — `epic_fk` is a NOT NULL
    column read directly; there is no tally, no majority vote, and no
    inheritance walk to have a tie or a chain (docstring item 1);
  `substrate-rebuild-34-rows` — a whole-plan integration fixture built from
    1.0's batch+label machinery end to end; its individual RULES are each
    covered above, and a 2.0-shaped equivalent integration case exists as
    `Lambda-Rest/tests/test_pipeline2_compose.py`'s `plan` /
    `two_epic_plan` fixtures, run against real `darwin_dev` rather than a
    hand-built model.

Verified rather than redone (module docstring item 6's own claim, checked
against this mapping): every 1.0 case whose behaviour survives in 2.0 now has
a 2.0-shaped test above it; the gaps the check surfaced —
`test_empty_plan_derives_cleanly`, `test_tracking_flag_coercion_matrix` — are added
at the end of this file rather than left as a silent hole.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pipeline2_derive as deriv                        # noqa: E402

_SUB = 'test-creator'


# ---------------------------------------------------------------------------
# Fixtures — built by hand, not through a fake REST client
# ---------------------------------------------------------------------------

def _req(id, status='met', tracking=0, machine_fk=None):
    return {'id': id, 'title': f'req {id}', 'requirement_status': status,
            'coordination_type': 'deployed', 'ai_model': 'sonnet',
            'effort': 'high', 'machine_fk': machine_fk, 'tracking': tracking}


def _epic(id, pipeline_fk=900, sort_order=None, title=None):
    return {'id': id, 'pipeline_fk': pipeline_fk, 'title': title or f'epic {id}',
            'description': None, 'epic_status': 'active', 'category_fk': 1,
            'sort_order': sort_order, 'closed': 0}


def _step(id, epic_fk, title=None, run='auto', not_before=None, notes=None,
         create_ts='2026-08-01 00:00:00', checkpoint=0, locked=0):
    # `checkpoint=0` here, against the column's DEFAULT 1 (req #3649): these
    # fixtures were written for steps that are launch PRIORITIES, and the
    # checkpoint tests below say `checkpoint=1` where they mean it.
    return {'id': id, 'epic_fk': epic_fk, 'title': title or f'step {id}',
            'run': run, 'checkpoint': checkpoint, 'locked': locked,
            'not_before': not_before, 'notes': notes, 'creator_fk': _SUB,
            'create_ts': create_ts, 'update_ts': create_ts}


def _basic_model():
    """One epic, three steps (two requirement-backed, one gate depending on
    both) — the same shape as `test_pipelines2.py`'s `plan2` fixture."""
    return {
        'pipeline': {'id': 900, 'title': 'Pipeline 2.0 Build',
                     'pipeline_status': 'active', 'execution_mode': 'parallel'},
        'epics': [_epic(90)],
        'steps': [
            _step(9001, 90, title='read service'),
            _step(9002, 90, title='tools'),
            _step(9003, 90, title='gate', run='manual'),
        ],
        'step_requirements': [
            {'step_fk': 9001, 'requirement_fk': 5010},
            {'step_fk': 9002, 'requirement_fk': 5011},
        ],
        'step_deps': [
            {'id': 1, 'step_fk': 9003, 'dep_step_fk': 9001},
            {'id': 2, 'step_fk': 9003, 'dep_step_fk': 9002},
        ],
        'requirements': [_req(5010), _req(5011)],
    }


# ---------------------------------------------------------------------------
# Item 1 — epic_id is a column read; the deleted fields never appear
# ---------------------------------------------------------------------------

# COVERS: DRV-001
def test_epic_id_is_read_from_the_step_column_no_tally_no_tiebreak():
    model = _basic_model()
    rows = deriv.build_plan_rows(model)
    assert all(row['epic_id'] == 90 for row in rows)


# COVERS: DRV-001, DRV-002
def test_epic_id_follows_the_step_even_when_its_requirement_implies_nothing():
    """A req-less gate step still carries its OWN epic_fk — there is no
    inheritance walk to fall back on, because an unlabelled step cannot exist
    once epic_fk is NOT NULL."""
    model = _basic_model()
    rows = {row['id']: row for row in deriv.build_plan_rows(model)}
    assert rows[9003]['epic_id'] == 90


# COVERS: DRV-002, DRV-003
def test_build_plan_rows_has_no_legacy_or_leaked_fields():
    """Req #3349 item 6: a field that silently survives from the 1.0 shape
    (or from the retired middle tier) is the failure this requirement exists
    to prevent. An exhaustive POSITIVE assertion on the internal, pre-
    projection `build_plan_rows` shape catches that categorically — anything
    not on this list fails, named or not — the same technique
    `test_derive_plan2_shape_is_compact_ids_and_enums_only` below already uses
    for the projected `plan['rows']` shape."""
    model = _basic_model()
    for row in deriv.build_plan_rows(model):
        assert set(row) == {
            'id', 'title', 'run', 'checkpoint', 'locked', 'notes',
            'open_req_ids', 'epic_id',
            'req_ids', 'tracking_req_ids', 'unresolved_req_ids',
            'launch_req_ids', 'launch_excluded', 'launch_block',
            'swarm_start_command', 'no_launch_reason', 'dep_ids',
            '_create_ts', '_started', '_not_before'}


# COVERS: DRV-021
def test_no_batches_key_but_pause_serial_and_eligibility_are_present():
    """Batch does not exist in 2.0 (Step is the launch unit) — but `pause`,
    `serial` and `eligible_step_ids` ARE this requirement's: the first two
    per the verification register (DRV-005/006/016/017/018), `serial` per
    req #3349's own gate delta naming req #3388 (the register has no DRV
    entry for it at all, which is a gap in the register, not a scope
    exclusion — see the module docstring)."""
    model = _basic_model()
    plan = deriv.derive_plan2(model, now='2026-08-09T00:00:00Z')
    assert 'batches' not in plan
    for key in ('pause', 'serial', 'eligible_step_ids'):
        assert key in plan


# ---------------------------------------------------------------------------
# Item 2 — requirement_counts re-points at the step's seated epic
# ---------------------------------------------------------------------------

# COVERS: DRV-008
def test_requirement_counts_groups_by_the_seated_epic_not_a_retired_middle_tier_chain():
    model = {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': 'parallel'},
        'epics': [_epic(90), _epic(91)],
        'steps': [_step(9001, 90), _step(9101, 91)],
        'step_requirements': [
            {'step_fk': 9001, 'requirement_fk': 5010},
            {'step_fk': 9101, 'requirement_fk': 5011},
            {'step_fk': 9101, 'requirement_fk': 5012},
        ],
        'step_deps': [],
        'requirements': [
            _req(5010, status='met'), _req(5011, status='met'),
            _req(5012, status='authoring'),
        ],
    }
    counts = deriv.requirement_counts(model)
    assert counts['overall'] == {'met': 2, 'total': 3}
    by_epic = {b['epic_id']: b for b in counts['by_epic']}
    assert by_epic[90] == {'epic_id': 90, 'met': 1, 'total': 1}
    assert by_epic[91] == {'epic_id': 91, 'met': 1, 'total': 2}


def test_requirement_counts_excludes_tracking_containers():
    model = _basic_model()
    model['requirements'].append(_req(5012, status='development', tracking=1))
    model['step_requirements'].append({'step_fk': 9002, 'requirement_fk': 5012})
    counts = deriv.requirement_counts(model)
    assert counts['overall']['total'] == 2      # the container is not counted


def test_requirement_with_no_step_link_counts_overall_not_by_epic():
    model = _basic_model()
    model['requirements'].append(_req(5099, status='authoring'))
    counts = deriv.requirement_counts(model)
    assert counts['overall']['total'] == 3
    assert sum(b['total'] for b in counts['by_epic']) == 2


def test_overall_population_follows_model_requirements_not_the_whole_plan():
    """Documented residue (a code-review NOTE): on an EPIC-SCOPED `model`
    (only that epic's own requirements present, matching what
    `get_pipeline2_epic_composed` actually builds), `overall` is
    indistinguishable from that epic's own `by_epic` entry — never the
    plan's true total. A caller must label it as the epic's number, not the
    plan's, on that resource."""
    model = {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': 'parallel'},
        'epics': [_epic(90)],                    # ONE epic, as an epic-scoped
        'steps': [_step(9001, 90)],               # composed read narrows to
        'step_requirements': [{'step_fk': 9001, 'requirement_fk': 5010}],
        'step_deps': [],
        'requirements': [_req(5010, status='met')],
    }
    counts = deriv.requirement_counts(model)
    assert counts['overall'] == {'met': 1, 'total': 1}
    assert counts['by_epic'] == [{'epic_id': 90, 'met': 1, 'total': 1}]
    epic_entry = {k: v for k, v in counts['by_epic'][0].items() if k != 'epic_id'}
    assert counts['overall'] == epic_entry


# ---------------------------------------------------------------------------
# Item 3 — no time-gate branch: step_deps rows are plain edges
# ---------------------------------------------------------------------------

# COVERS: DRV-004
def test_step_deps_are_plain_edges_with_no_condition_kind():
    model = _basic_model()
    rows = {row['id']: row for row in deriv.build_plan_rows(model)}
    assert set(rows[9003]['dep_ids']) == {9001, 9002}
    assert 'time_deps' not in rows[9003]


# ---------------------------------------------------------------------------
# Item 4 — display order is a tree walk (no state band, req #3750)
# ---------------------------------------------------------------------------

# COVERS: DRV-007
def test_manual_sort_order_orders_the_epic_blocks():
    """`epic_order` and the resulting row order both follow `sort_order` —
    NOT a claim that epic blocks stay contiguous once a cross-epic edge
    exists (they are not guaranteed to; see `test_cross_epic_dependency_
    edge_is_legal_and_respected_topologically` below and the module
    docstring's item 4)."""
    model = {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': 'parallel'},
        'epics': [_epic(90, sort_order=2), _epic(91, sort_order=1)],
        'steps': [_step(9001, 90), _step(9101, 91)],
        'step_requirements': [], 'step_deps': [], 'requirements': [],
    }
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    assert ordered['epic_order'] == [91, 90]              # sort_order wins
    assert [r['id'] for r in ordered['rows']] == [9101, 9001]


def test_manual_sort_order_wins_over_derived_order():
    model = {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': 'parallel'},
        # epic 90 started (its step's work is met) so would derive FIRST;
        # epic 91 is unstarted and would derive LAST. A manual order on 91
        # overrides that.
        'epics': [_epic(90), _epic(91, sort_order=1)],
        'steps': [_step(9001, 90), _step(9101, 91)],
        'step_requirements': [{'step_fk': 9001, 'requirement_fk': 1}],
        'step_deps': [], 'requirements': [_req(1, status='met')],
    }
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    assert ordered['epic_order'] == [91, 90]


def test_started_epics_order_by_earliest_activity_ahead_of_unstarted():
    model = {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': 'parallel'},
        'epics': [_epic(90), _epic(91), _epic(92)],
        'steps': [
            # epic 90: unstarted (no work begun) -> creation order (id)
            _step(9001, 90),
            # epic 91: started later (work in development)
            _step(9101, 91, create_ts='2026-08-02 00:00:00'),
            # epic 92: started earliest (work met)
            _step(9201, 92, create_ts='2026-08-01 00:00:00'),
        ],
        'step_requirements': [{'step_fk': 9001, 'requirement_fk': 1},
                              {'step_fk': 9101, 'requirement_fk': 2},
                              {'step_fk': 9201, 'requirement_fk': 3}],
        'step_deps': [],
        'requirements': [_req(1, status='swarm_ready'),
                         _req(2, status='development'), _req(3, status='met')],
    }
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    # started epics (92 earliest, then 91) precede the unstarted one (90).
    assert ordered['epic_order'] == [92, 91, 90]


# COVERS: DRV-020
def test_display_order_has_no_state_band():
    """Req #3750: a step has no state, so finished work does not float above
    unfinished work. Among rows whose dependencies have rendered, the order is
    the latest dependency's position, then epic, then run mode, then id."""
    model = {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': 'parallel'},
        'epics': [_epic(90)],
        'steps': [_step(1, 90), _step(2, 90), _step(3, 90, run='manual'),
                  _step(4, 90)],
        'step_requirements': [{'step_fk': 1, 'requirement_fk': 10},
                              {'step_fk': 4, 'requirement_fk': 40}],
        'requirements': [_req(10, status='swarm_ready'), _req(40, status='met')],
        'step_deps': [{'id': 1, 'step_fk': 2, 'dep_step_fk': 1}],
    }
    ordered = deriv.display_order(deriv.build_plan_rows(model), model['epics'])
    # 4 (all work met) does NOT jump ahead; 3 (manual) after the auto roots.
    assert [r['id'] for r in ordered['rows']] == [1, 4, 3, 2]
    assert 'banding_settled' not in ordered


def test_verify_order_has_no_banding_invariant():
    """The state-banding and banding-unsettled invariants went with step state
    (req #3750); topology is still checked."""
    model = _basic_model()
    by_id = {r['id']: r for r in deriv.build_plan_rows(model)}
    violations, _ = deriv.verify_order([by_id[9003], by_id[9001], by_id[9002]])
    kinds = {v['invariant'] for v in violations}
    assert kinds == {'topology'}
    assert not deriv.derive_plan2(model, now='2026-08-09T00:00:00Z')['violations']


def test_cycle_within_one_epic_is_detected_and_falls_back_to_stored_order():
    model = {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': 'parallel'},
        'epics': [_epic(90)],
        'steps': [_step(1, 90), _step(2, 90)],
        'step_requirements': [], 'requirements': [],
        'step_deps': [
            {'id': 1, 'step_fk': 1, 'dep_step_fk': 2},
            {'id': 2, 'step_fk': 2, 'dep_step_fk': 1},
        ],
    }
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    assert ordered['cycle_detected'] is True
    assert set(ordered['cycle_step_ids']) == {1, 2}


# COVERS: DRV-013
def test_duplicate_step_id_is_reported():
    model = _basic_model()
    model['steps'].append(_step(9001, 90, title='duplicate'))
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    assert 9001 in ordered['duplicate_step_ids']


# COVERS: DRV-014
def test_dangling_dependency_is_detected_and_reported():
    """A dep row pointing at a step id absent from the composed read's own
    `steps` tier — a truncated read, or a stale FK — must be reported, not
    silently swallowed."""
    model = _basic_model()
    model['step_deps'].append({'id': 3, 'step_fk': 9003, 'dep_step_fk': 424242})
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    violations, _ = deriv.verify_order(ordered['rows'])
    dangling = [v for v in violations if v['invariant'] == 'dangling-dependency']
    assert dangling and set(dangling[0]['step_ids']) == {9003, 424242}


# COVERS: DRV-020
def test_cross_epic_dependency_edge_is_legal_and_respected_topologically():
    """Stage-2 gate delta (req #3336, 2026-08-08): cross-epic edges are
    LEGAL, reversing the original body text. A step in epic 91 gated on a
    step in epic 90 must never render before it."""
    model = {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': 'parallel'},
        'epics': [_epic(90, sort_order=1), _epic(91, sort_order=2)],
        'steps': [
            _step(9001, 90),                    # gates 9101
            _step(9101, 91),                     # depends on 9001
        ],
        'step_requirements': [], 'requirements': [],
        'step_deps': [{'id': 1, 'step_fk': 9101, 'dep_step_fk': 9001}],
    }
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    positions = {row['id']: i for i, row in enumerate(ordered['rows'])}
    assert positions[9001] < positions[9101], \
        'a row must never render before a dependency, even across an epic'
    violations, _ = deriv.verify_order(ordered['rows'])
    assert [v for v in violations if v['invariant'] == 'topology'] == []


# ---------------------------------------------------------------------------
# open_requirement_ids — a step has no state, only open work (req #3750)
# ---------------------------------------------------------------------------

# COVERS: DRV-009
def test_open_requirement_ids_is_gating_work_not_yet_terminal():
    reqs = {r['id']: r for r in (
        _req(1, status='development'), _req(2, status='swarm_ready'),
        _req(3, status='authoring'), _req(4, status='met'),
        _req(5, status='deferred'), _req(6, status='wontfix'))}
    assert deriv.open_requirement_ids([1, 2, 3, 4, 5, 6], [], reqs) == [1, 2, 3]


# COVERS: DRV-009, DRV-010
def test_tracking_requirement_is_never_open_work():
    reqs = {1: _req(1, status='development', tracking=1)}
    assert deriv.open_requirement_ids([1], [1], reqs) == []


# COVERS: DRV-011
def test_a_step_holding_nothing_has_no_open_work_and_no_state():
    model = _basic_model()
    model['requirements'] = [_req(5010, status='development'), _req(5011, status='met')]
    rows = {r['id']: r for r in deriv.build_plan_rows(model)}
    assert rows[9001]['open_req_ids'] == [5010]
    assert rows[9002]['open_req_ids'] == []
    assert rows[9003]['open_req_ids'] == []          # holds nothing
    for row in rows.values():
        assert 'state' not in row and 'completed_at' not in row


def test_an_unresolved_requirement_counts_as_open_work():
    """Holding is the safe direction: a checkpoint that cannot see its work
    keeps holding."""
    assert deriv.open_requirement_ids([77], [], {}) == [77]


# ---------------------------------------------------------------------------
# Gate delta F9 — launch_req_ids / swarm_start_command / no_launch_reason
# ---------------------------------------------------------------------------

def test_launch_req_ids_only_swarm_ready_minus_containers():
    model = _basic_model()
    model['requirements'] = [
        _req(5010, status='swarm_ready'),
        _req(5011, status='met'),
    ]
    rows = {r['id']: r for r in deriv.build_plan_rows(model)}
    assert rows[9001]['launch_req_ids'] == [5010]
    assert rows[9001]['swarm_start_command'] == '/swarm-start 5010'
    assert rows[9001]['no_launch_reason'] is None
    assert rows[9002]['launch_req_ids'] == []
    assert rows[9002]['swarm_start_command'] is None
    assert '5011 met' in rows[9002]['launch_excluded']
    assert rows[9002]['no_launch_reason'] is not None


def test_no_launch_reason_distinguishes_no_links_from_containers():
    model = _basic_model()
    model['step_requirements'] = []
    model['requirements'] = []
    rows = {r['id']: r for r in deriv.build_plan_rows(model)}
    assert rows[9001]['launch_block'] == deriv.BLOCK_NO_LINKS

    model2 = _basic_model()
    model2['requirements'] = [_req(5010, status='met', tracking=1),
                              _req(5011, status='met')]
    rows2 = {r['id']: r for r in deriv.build_plan_rows(model2)}
    assert rows2[9001]['launch_block'] == deriv.BLOCK_CONTAINERS


# ---------------------------------------------------------------------------
# The whole derivation
# ---------------------------------------------------------------------------

def test_derive_plan2_shape_is_compact_ids_and_enums_only():
    model = _basic_model()
    plan = deriv.derive_plan2(model, now='2026-08-09T00:00:00Z')
    assert set(plan) == {
        'now', 'epic_order', 'display_order', 'rows', 'pause', 'serial',
        'eligible_step_ids', 'launch_candidate_step_ids',
        'launch_queue',
        'violations', 'cycle_detected', 'cycle_step_ids',
        'duplicate_step_ids', 'unresolved_req_ids', 'out_of_scope_dep_ids',
        'requirement_counts'}
    for entry in plan['launch_queue']:
        assert set(entry) == {'step_id', 'requirement_id'}
    for row in plan['rows']:
        assert set(row) == {
            'id', 'run', 'checkpoint', 'locked', 'eligible', 'open_req_ids',
            'gate_open', 'launch_candidate', 'checkpoint_blocked_by',
            'epic_id', 'dep_ids',
            'out_of_scope_dep_ids', 'req_ids',
            'tracking_req_ids', 'unresolved_req_ids', 'launch_req_ids',
            'launch_excluded', 'launch_block', 'swarm_start_command',
            'no_launch_reason', 'launch_suppressed', 'suppressed_by'}


# COVERS: DRV-006
def test_derive_plan2_now_is_carried_for_a_later_eligibility_consumer():
    model = _basic_model()
    plan = deriv.derive_plan2(model, now='2026-08-09T00:00:00Z')
    assert plan['now'] == '2026-08-09T00:00:00Z'


# COVERS: DRV-015
def test_derive_plan2_unresolved_requirement_is_reported_not_silently_dropped():
    model = _basic_model()
    model['step_requirements'].append({'step_fk': 9002, 'requirement_fk': 99999})
    plan = deriv.derive_plan2(model, now='2026-08-09T00:00:00Z')
    assert 99999 in plan['unresolved_req_ids']
    row = next(r for r in plan['rows'] if r['id'] == 9002)
    assert 99999 in row['unresolved_req_ids']


# ---------------------------------------------------------------------------
# Eligibility (DRV-005/006) — a plain per-step predicate, no batch term
# ---------------------------------------------------------------------------

def _row(id, epic_id=90, dep_ids=None, not_before=None, launch_req_ids=(42,),
         open_req_ids=None):
    """A derived-row-shaped dict. `open_req_ids` defaults to the launch ids —
    launch-ready work is open work."""
    launch = list(launch_req_ids)
    return {'id': id, 'dep_ids': dep_ids or [], 'epic_id': epic_id,
            '_not_before': not_before, 'launch_req_ids': launch,
            'open_req_ids': list(open_req_ids) if open_req_ids is not None else launch}


NOW = '2026-08-09T00:00:00Z'


# COVERS: DRV-005
def test_eligibility_requires_every_dependency_clear():
    """A dependency is CLEAR when it holds no open work (req #3750)."""
    dep = _row(1)                                   # holds open work
    row = _row(2, dep_ids=[1])
    by_id = {1: dep, 2: row}
    assert deriv.eligibility(row, by_id, now=NOW) is False
    by_id[1] = _row(1, launch_req_ids=(), open_req_ids=())
    assert deriv.eligibility(row, by_id, now=NOW) is True
    # An unknown dependency is never clear.
    assert deriv.eligibility(_row(3, dep_ids=[99]), by_id, now=NOW) is False


# COVERS: DRV-005, DRV-006
def test_eligibility_consults_not_before_against_the_payload_clock():
    row = _row(1, not_before='2026-08-10T00:00:00Z')
    by_id = {1: row}
    # the gate has not passed yet relative to this `now`
    assert deriv.eligibility(row, by_id, now='2026-08-09T00:00:00Z') is False
    # the gate has passed relative to a later `now`
    assert deriv.eligibility(row, by_id, now='2026-08-11T00:00:00Z') is True
    # no `now` at all while a gate exists means NOT eligible, never passed
    assert deriv.eligibility(row, by_id, now=None) is False


def test_eligibility_requires_launch_ready_work():
    """No state to test — the requirements decide. A step with nothing
    launch-ready is never eligible, whatever its gate says."""
    row = _row(1, launch_req_ids=(), open_req_ids=(7,))
    assert deriv.eligibility(row, {1: row}, now=NOW) is False


def test_derive_plan2_eligible_step_ids_reflects_the_dep_graph():
    model = _basic_model()
    model['step_requirements'].append({'step_fk': 9003, 'requirement_fk': 5012})
    model['requirements'] = [_req(5010, status='met'), _req(5011, status='met'),
                             _req(5012, status='swarm_ready')]
    plan = deriv.derive_plan2(model, now=NOW)
    # 9001/9002 hold no open work, so 9003's gate is open and it has work.
    assert plan['eligible_step_ids'] == [9003]
    # Reopen work on 9002: the gate closes again — nothing was stored.
    model['requirements'][1]['requirement_status'] = 'development'
    plan = deriv.derive_plan2(model, now=NOW)
    assert plan['eligible_step_ids'] == []


# ---------------------------------------------------------------------------
# The old "top-up" case (DRV-026, req #3507) — now just `eligible`
# ---------------------------------------------------------------------------
#
# THE MEASURED CASE, 2026-08-14: plan 7 step 310 had requirement #3503 in
# `development` when #3506 was linked onto it, and #3506 sat `swarm_ready`
# for over 24 h because only a PENDING step could be `eligible`. With no step
# state (req #3750) there is nothing to split on: the step holds launch-ready
# work and its gate is open, so it is eligible.

# COVERS: DRV-026
def test_work_in_flight_beside_launch_ready_work_is_eligible():
    model = _basic_model()
    model['step_requirements'].append({'step_fk': 9001, 'requirement_fk': 5012})
    model['requirements'] = [_req(5010, status='development'),
                             _req(5011, status='met'),
                             _req(5012, status='swarm_ready')]
    plan = deriv.derive_plan2(model, now=NOW)
    row = next(r for r in plan['rows'] if r['id'] == 9001)
    assert row['eligible'] is True
    assert row['launch_req_ids'] == [5012]
    assert row['open_req_ids'] == [5010, 5012]
    assert row['swarm_start_command'] == '/swarm-start 5012'
    assert 'top_up_eligible' not in row and 'top_up_step_ids' not in plan


# COVERS: DRV-026
def test_work_in_flight_alone_is_not_eligible():
    """The steady state of every plan, and the volume guarantee: a step whose
    only requirement IS the one being worked has nothing to command."""
    model = _basic_model()
    model['requirements'] = [_req(5010, status='development'),
                             _req(5011, status='met')]
    plan = deriv.derive_plan2(model, now=NOW)
    assert plan['eligible_step_ids'] == []


# ---------------------------------------------------------------------------
# Launch candidacy (DRV-027, req #3597) — dependencies are a PRIORITY, not a gate
# ---------------------------------------------------------------------------
#
# THE USER RULE, 2026-10-17 (plan 10): whenever the machine has a free slot,
# launch-ready work is started even when its step's dependency gate is not
# satisfied. Measured trigger: #3594/#3595 seated on step 315 while dependent
# step 316 was running — held, with two slots free, and launched by hand.

def _plan10_model():
    """Plan 10's shape on 2026-10-17: 313's work is met; 315 depends on 313
    and gained new work while its dependent 316 has work in development; 314 depends on 316
    (gate closed) and carries launch-ready work; 317 depends on 314 — a
    further-downstream gated step, also carrying launch-ready work."""
    return {
        'pipeline': {'id': 10, 'title': 'Tip of the Spear',
                     'pipeline_status': 'active', 'execution_mode': 'parallel'},
        'epics': [_epic(100, pipeline_fk=10)],
        'steps': [_step(313, 100), _step(315, 100), _step(316, 100),
                  _step(314, 100), _step(317, 100)],
        'step_requirements': [
            {'step_fk': 313, 'requirement_fk': 3580},
            {'step_fk': 315, 'requirement_fk': 3581},
            {'step_fk': 315, 'requirement_fk': 3594},
            {'step_fk': 315, 'requirement_fk': 3595},
            {'step_fk': 316, 'requirement_fk': 3590},
            {'step_fk': 314, 'requirement_fk': 3586},
            {'step_fk': 317, 'requirement_fk': 3599},
            {'step_fk': 317, 'requirement_fk': 3598},
        ],
        'step_deps': [
            {'id': 1, 'step_fk': 315, 'dep_step_fk': 313},
            {'id': 2, 'step_fk': 316, 'dep_step_fk': 315},
            {'id': 3, 'step_fk': 314, 'dep_step_fk': 316},
            {'id': 4, 'step_fk': 317, 'dep_step_fk': 314},
        ],
        'requirements': [
            _req(3580, status='met'), _req(3581, status='met'),
            _req(3594, status='swarm_ready'), _req(3595, status='swarm_ready'),
            _req(3590, status='development'),
            _req(3586, status='swarm_ready'),
            _req(3599, status='swarm_ready'), _req(3598, status='swarm_ready'),
        ],
    }


# COVERS: DRV-027
def test_launch_candidacy_ignores_dependencies():
    dep = _row(1)                                   # holds open work
    row = _row(2, dep_ids=[1])
    assert deriv.eligibility(row, {1: dep, 2: row}, now=NOW) is False
    assert deriv.launch_candidacy(row, now=NOW) is True


# COVERS: DRV-027
def test_launch_candidacy_keeps_the_unchanged_conjuncts():
    """No launchable work, or an unpassed TIME gate: not a candidate. A time
    gate is a person's "not before", not a dependency."""
    empty = _row(1, launch_req_ids=())
    assert deriv.launch_candidacy(empty, now=NOW) is False
    timed = _row(3, not_before='2026-08-10T00:00:00Z')
    assert deriv.launch_candidacy(timed, now=NOW) is False
    assert deriv.launch_candidacy(timed, now=None) is False
    assert deriv.launch_candidacy(timed, now='2026-08-11T00:00:00Z') is True


def test_derive_plan2_plan10_every_launch_ready_step_is_a_candidate():
    plan = deriv.derive_plan2(_plan10_model(), now=NOW)
    rows = {r['id']: r for r in plan['rows']}
    assert rows[313]['open_req_ids'] == []          # its work is met
    # The gate is still REPORTED, and still draws the eligible-now ring.
    assert rows[315]['gate_open'] is True and rows[315]['eligible'] is True
    assert rows[314]['gate_open'] is False and rows[314]['eligible'] is False
    assert rows[317]['gate_open'] is False and rows[317]['eligible'] is False
    # ...but it no longer decides candidacy.
    assert {i for i, r in rows.items() if r['launch_candidate']} == {315, 314, 317}
    assert rows[316]['launch_candidate'] is False   # nothing launch-ready
    assert rows[313]['launch_candidate'] is False   # nothing launch-ready


# COVERS: DRV-027
def test_launch_candidate_step_ids_is_gate_open_first_then_display_order():
    plan = deriv.derive_plan2(_plan10_model(), now=NOW)
    order = plan['display_order']
    assert order.index(314) < order.index(317)
    # 315's gate is open, so it leads; then the gated steps down the chain.
    assert plan['launch_candidate_step_ids'] == [315, 314, 317]


def test_launch_candidate_step_ids_puts_gate_open_ahead_of_display_order():
    """A gate-open candidate that DISPLAYS after a gated one still leads."""
    model = _plan10_model()
    # A second root step, displayed last, whose (empty) gate is open.
    model['steps'].append(_step(318, 100))
    model['step_requirements'].append({'step_fk': 318, 'requirement_fk': 3600})
    model['requirements'].append(_req(3600, status='swarm_ready'))
    plan = deriv.derive_plan2(model, now=NOW)
    ids = plan['launch_candidate_step_ids']
    gate_open = [i for i in ids if next(r for r in plan['rows']
                                        if r['id'] == i)['gate_open']]
    assert ids[:len(gate_open)] == gate_open
    assert set(gate_open) == {315, 318}
    assert ids[len(gate_open):] == [314, 317]


# The user's amendment (2026-10-17): a CHECKPOINT blocks everything downstream
# of it. Since req #3649 a checkpoint is the step's own `checkpoint` column
# (default ON); since req #3750 it holds while it holds OPEN WORK — a step has
# no state and is never completed by hand.

def _checkpoint_model(checkpoint_open=True):
    """Step 1 is a CHECKPOINT (flag on) holding requirement 10. Step 2 (work in
    development) and step 4 (launch-ready) depend on it directly; step 3
    (launch-ready) depends on 2, two edges below the checkpoint. Step 5 is
    unrelated."""
    return {
        'pipeline': {'id': 11, 'title': 'Checkpoints',
                     'pipeline_status': 'active', 'execution_mode': 'parallel'},
        'epics': [_epic(110, pipeline_fk=11)],
        'steps': [_step(1, 110, title='checkpoint', checkpoint=1),
                  _step(2, 110), _step(3, 110), _step(4, 110), _step(5, 110)],
        'step_requirements': [
            {'step_fk': 1, 'requirement_fk': 10},
            {'step_fk': 2, 'requirement_fk': 20},
            {'step_fk': 3, 'requirement_fk': 30},
            {'step_fk': 4, 'requirement_fk': 40},
            {'step_fk': 5, 'requirement_fk': 50},
        ],
        'step_deps': [
            {'id': 1, 'step_fk': 2, 'dep_step_fk': 1},
            {'id': 2, 'step_fk': 3, 'dep_step_fk': 2},
            {'id': 3, 'step_fk': 4, 'dep_step_fk': 1},
        ],
        'requirements': [_req(20, status='development'),
                         _req(30, status='swarm_ready'),
                         _req(40, status='swarm_ready'),
                         _req(50, status='swarm_ready'),
                         _req(10, status='development' if checkpoint_open else 'met')],
    }


# COVERS: DRV-028
def test_an_open_checkpoint_blocks_everything_downstream_transitively():
    plan = deriv.derive_plan2(_checkpoint_model(), now=NOW)
    rows = {r['id']: r for r in plan['rows']}
    assert rows[1]['open_req_ids'] == [10]             # the checkpoint holds
    assert rows[4]['launch_candidate'] is False         # one edge below it
    assert rows[4]['checkpoint_blocked_by'] == [1]
    assert rows[3]['launch_candidate'] is False         # two edges below it
    assert rows[3]['checkpoint_blocked_by'] == [1]
    assert rows[5]['launch_candidate'] is True          # not downstream
    assert rows[5]['checkpoint_blocked_by'] == []
    assert plan['launch_candidate_step_ids'] == [5]


# COVERS: DRV-028
def test_a_checkpoint_whose_work_is_closed_blocks_nothing():
    plan = deriv.derive_plan2(_checkpoint_model(checkpoint_open=False), now=NOW)
    rows = {r['id']: r for r in plan['rows']}
    assert rows[1]['open_req_ids'] == []
    assert rows[4]['launch_candidate'] is True
    assert rows[4]['gate_open'] is True                 # its only dep is clear
    # 3 sits behind step 2's open work — an ordinary dependency, a PRIORITY.
    assert rows[3]['launch_candidate'] is True
    assert rows[3]['gate_open'] is False
    assert all(r['checkpoint_blocked_by'] == [] for r in plan['rows'])


# COVERS: DRV-028
def test_an_empty_checkpoint_holds_nothing():
    """Req #3750: a step holding no requirements has no open work, so even
    with the flag on it holds nothing — nobody has to close it by hand."""
    model = _checkpoint_model()
    model['step_requirements'] = [l for l in model['step_requirements']
                                  if l['step_fk'] != 1]
    plan = deriv.derive_plan2(model, now=NOW)
    rows = {r['id']: r for r in plan['rows']}
    assert rows[1]['checkpoint'] is True and rows[1]['open_req_ids'] == []
    assert rows[4]['checkpoint_blocked_by'] == []
    assert rows[4]['launch_candidate'] is True and rows[4]['gate_open'] is True
    # Seat work on it later and it holds again — on the very next read.
    model['step_requirements'].append({'step_fk': 1, 'requirement_fk': 10})
    plan = deriv.derive_plan2(model, now=NOW)
    rows = {r['id']: r for r in plan['rows']}
    assert rows[4]['checkpoint_blocked_by'] == [1]


def test_a_checkpoint_is_the_column_not_the_link_shape():
    """req #3649: the flag decides, default ON; link shape says nothing."""
    assert deriv.is_checkpoint({'checkpoint': 1}) is True
    assert deriv.is_checkpoint({'checkpoint': '1'}) is True
    assert deriv.is_checkpoint({'checkpoint': True}) is True
    assert deriv.is_checkpoint({'checkpoint': 0}) is False
    assert deriv.is_checkpoint({'checkpoint': '0'}) is False
    assert deriv.is_checkpoint({'checkpoint': False}) is False
    # Absent or blank = the column's DEFAULT, which is on.
    assert deriv.is_checkpoint({}) is True
    assert deriv.is_checkpoint({'checkpoint': None}) is True
    assert deriv.is_checkpoint({'checkpoint': ''}) is True
    # A no-work step with the flag off is NOT a checkpoint any more.
    assert deriv.is_checkpoint({'checkpoint': 0, 'launch_block': 'no-links'}) is False


# COVERS: DRV-028
def test_a_checkpoint_with_work_holds_downstream_until_its_requirements_are_terminal():
    """A step with the flag on holds its transitive downstream while any
    gating requirement is open — then it holds nothing."""
    model = _checkpoint_model()
    # Step 2 (work in development, one edge under the checkpoint) becomes a
    # checkpoint itself; step 3 depends on it.
    model['steps'][1]['checkpoint'] = 1
    plan = deriv.derive_plan2(model, now=NOW)
    rows = {r['id']: r for r in plan['rows']}
    assert rows[2]['checkpoint'] is True and rows[2]['open_req_ids'] == [20]
    assert rows[3]['checkpoint_blocked_by'] == [1, 2]
    assert rows[3]['launch_candidate'] is False
    # Close the first checkpoint's work; step 2 still holds step 3...
    model['requirements'][4]['requirement_status'] = 'met'
    plan = deriv.derive_plan2(model, now=NOW)
    rows = {r['id']: r for r in plan['rows']}
    assert rows[3]['checkpoint_blocked_by'] == [2]
    assert rows[3]['launch_candidate'] is False
    # ...until its work is terminal.
    model['requirements'][0]['requirement_status'] = 'met'
    plan = deriv.derive_plan2(model, now=NOW)
    rows = {r['id']: r for r in plan['rows']}
    assert rows[2]['open_req_ids'] == []
    assert rows[3]['checkpoint_blocked_by'] == []
    assert rows[3]['launch_candidate'] is True
    assert rows[3]['gate_open'] is True


# COVERS: DRV-028
def test_a_step_with_the_flag_off_is_a_priority_not_a_hold():
    """`checkpoint=0`: the step holds NOTHING even with open work — its
    dependants are past-gate launch candidates, like work behind any work."""
    model = _checkpoint_model()
    model['steps'][0]['checkpoint'] = 0
    plan = deriv.derive_plan2(model, now=NOW)
    rows = {r['id']: r for r in plan['rows']}
    assert rows[1]['open_req_ids'] == [10] and rows[1]['checkpoint'] is False
    for sid in (3, 4):
        assert rows[sid]['checkpoint_blocked_by'] == [], sid
        assert rows[sid]['launch_candidate'] is True, sid
        assert rows[sid]['gate_open'] is False, sid


# COVERS: DRV-028
def test_a_holding_checkpoint_above_a_clear_step_still_holds_its_downstream():
    """Review C1, measured: checkpoint 10 holding, step 11 under it with all
    its work met, 12 and 13 under 11. Their DIRECT deps are clear, so without
    the transitive walk they would read `eligible` and the engine would
    launch straight past the checkpoint."""
    model = {
        'pipeline': {'id': 12, 'title': 'C1', 'pipeline_status': 'active',
                     'execution_mode': 'parallel'},
        'epics': [_epic(120, pipeline_fk=12)],
        'steps': [_step(10, 120, checkpoint=1), _step(11, 120), _step(12, 120),
                  _step(13, 120), _step(14, 120, checkpoint=1)],
        'step_requirements': [
            {'step_fk': 10, 'requirement_fk': 100},
            {'step_fk': 11, 'requirement_fk': 101},
            {'step_fk': 12, 'requirement_fk': 102},
            {'step_fk': 13, 'requirement_fk': 103},
            {'step_fk': 13, 'requirement_fk': 104},
            {'step_fk': 14, 'requirement_fk': 105},
        ],
        'step_deps': [
            {'id': 1, 'step_fk': 11, 'dep_step_fk': 10},
            {'id': 2, 'step_fk': 12, 'dep_step_fk': 11},
            {'id': 3, 'step_fk': 13, 'dep_step_fk': 11},
            {'id': 4, 'step_fk': 14, 'dep_step_fk': 11},   # a 2nd checkpoint
        ],
        'requirements': [_req(100, status='development'),
                         _req(101, status='met'), _req(102, status='swarm_ready'),
                         _req(103, status='development'),
                         _req(104, status='swarm_ready'),
                         _req(105, status='swarm_ready')],
    }
    plan = deriv.derive_plan2(model, now=NOW)
    rows = {r['id']: r for r in plan['rows']}
    assert rows[11]['open_req_ids'] == []
    for sid in (12, 13, 14):
        assert rows[sid]['checkpoint_blocked_by'] == [10], sid
        assert rows[sid]['gate_open'] is False, sid
        assert rows[sid]['eligible'] is False, sid
        assert rows[sid]['launch_candidate'] is False, sid
    assert plan['eligible_step_ids'] == []


# COVERS: DRV-028
def test_an_epic_scoped_read_sees_a_checkpoint_in_another_epic():
    """Review I1: the epic-scoped compose supplies `plan_graph` (the rest of
    the plan's steps, edges, links and requirement statuses) so a checkpoint
    outside the epic holds this epic's step exactly as a whole-plan read does."""
    model = {
        'pipeline': {'id': 13, 'title': 'I1', 'pipeline_status': 'active',
                     'execution_mode': 'parallel'},
        'epics': [_epic(131, pipeline_fk=13)],
        'steps': [_step(2, 131)],
        'step_requirements': [{'step_fk': 2, 'requirement_fk': 20}],
        'step_deps': [{'id': 1, 'step_fk': 2, 'dep_step_fk': 5}],
        'requirements': [_req(20, status='swarm_ready')],
        # step 5 is a priority step (flag off) in epic 130, and it depends on
        # step 1 — a checkpoint holding work 900 (and a container, 901).
        'plan_graph': {
            'steps': [{'id': 1, 'checkpoint': 1}, {'id': 5, 'checkpoint': 0}],
            'step_deps': [{'step_fk': 5, 'dep_step_fk': 1}],
            'step_requirements': [{'step_fk': 1, 'requirement_fk': 900},
                                  {'step_fk': 1, 'requirement_fk': 901}],
            'requirements': [{'id': 900, 'requirement_status': 'development',
                              'tracking': 0},
                             {'id': 901, 'requirement_status': 'development',
                              'tracking': 1}],
        },
    }
    plan = deriv.derive_plan2(model, now=NOW, epic_scoped=True)
    row = plan['rows'][0]
    assert row['checkpoint_blocked_by'] == [1]
    assert row['launch_candidate'] is False
    # ...and once its work is terminal, the same read releases the step; the
    # container never counted.
    model['plan_graph']['requirements'][0]['requirement_status'] = 'met'
    plan = deriv.derive_plan2(model, now=NOW, epic_scoped=True)
    assert plan['rows'][0]['checkpoint_blocked_by'] == []
    assert plan['rows'][0]['launch_candidate'] is True


# COVERS: DRV-028
def test_an_epic_scoped_read_holds_behind_another_epics_checkpoint_with_work():
    """An outside checkpoint holds while any gating requirement is open."""
    model = {
        'pipeline': {'id': 14, 'title': 'I1b', 'pipeline_status': 'active',
                     'execution_mode': 'parallel'},
        'epics': [_epic(141, pipeline_fk=14)],
        'steps': [_step(2, 141)],
        'step_requirements': [{'step_fk': 2, 'requirement_fk': 20}],
        'step_deps': [{'id': 1, 'step_fk': 2, 'dep_step_fk': 1}],
        'requirements': [_req(20, status='swarm_ready')],
        'plan_graph': {
            'steps': [{'id': 1, 'checkpoint': 1}],
            'step_deps': [],
            'step_requirements': [{'step_fk': 1, 'requirement_fk': 10},
                                  {'step_fk': 1, 'requirement_fk': 11}],
            'requirements': [{'id': 10, 'requirement_status': 'met', 'tracking': 0},
                             {'id': 11, 'requirement_status': 'development',
                              'tracking': 0}],
        },
    }
    plan = deriv.derive_plan2(model, now=NOW, epic_scoped=True)
    assert plan['rows'][0]['checkpoint_blocked_by'] == [1]
    assert plan['rows'][0]['launch_candidate'] is False
    # Its last requirement going terminal releases it.
    model['plan_graph']['requirements'][1]['requirement_status'] = 'wontfix'
    plan = deriv.derive_plan2(model, now=NOW, epic_scoped=True)
    assert plan['rows'][0]['checkpoint_blocked_by'] == []
    assert plan['rows'][0]['launch_candidate'] is True
    # An outside step with the flag OFF never holds, whatever its links say.
    model['plan_graph']['steps'][0] = {'id': 1, 'checkpoint': 0}
    model['plan_graph']['requirements'][1]['requirement_status'] = 'development'
    plan = deriv.derive_plan2(model, now=NOW, epic_scoped=True)
    assert plan['rows'][0]['checkpoint_blocked_by'] == []
    # An outside checkpoint holding NOTHING never holds either.
    model['plan_graph']['steps'][0] = {'id': 1, 'checkpoint': 1}
    model['plan_graph']['step_requirements'] = []
    plan = deriv.derive_plan2(model, now=NOW, epic_scoped=True)
    assert plan['rows'][0]['checkpoint_blocked_by'] == []


def test_checkpoint_walk_survives_a_cycle_and_an_unseen_dependency():
    a = {'id': 1, 'dep_ids': [2, 99], 'checkpoint': 0, 'open_req_ids': [7]}
    b = {'id': 2, 'dep_ids': [1], 'checkpoint': 0, 'open_req_ids': [8]}
    assert deriv.open_checkpoints_upstream(a, {1: a, 2: b}) == []
    # ...and with the flag on, the cycle still terminates and names the hold.
    b['checkpoint'] = 1
    assert deriv.open_checkpoints_upstream(a, {1: a, 2: b}) == [2]


# ---------------------------------------------------------------------------
# req #3649 — `launch_queue`: THE launch order, stated once
# ---------------------------------------------------------------------------

def _queue_model():
    """Two gate-open roots (A displays before B), C past its gate behind A.
    A carries implemented 31, deployed 32, implemented 30 (junction order);
    B carries deployed 41; C carries 51. A `run=manual` root M carries 61."""
    model = {
        'pipeline': {'id': 15, 'title': 'Queue', 'pipeline_status': 'active',
                     'execution_mode': 'parallel'},
        'epics': [_epic(150, pipeline_fk=15)],
        'steps': [_step(1, 150, title='A'), _step(2, 150, title='B'),
                  _step(3, 150, title='C'), _step(4, 150, title='M', run='manual')],
        'step_requirements': [
            {'step_fk': 1, 'requirement_fk': 31},
            {'step_fk': 1, 'requirement_fk': 32},
            {'step_fk': 1, 'requirement_fk': 30},
            {'step_fk': 2, 'requirement_fk': 41},
            {'step_fk': 3, 'requirement_fk': 51},
            {'step_fk': 4, 'requirement_fk': 61},
        ],
        'step_deps': [{'id': 1, 'step_fk': 3, 'dep_step_fk': 1}],
        'requirements': [
            {**_req(31, status='swarm_ready'), 'coordination_type': 'implemented'},
            {**_req(32, status='swarm_ready'), 'coordination_type': 'deployed'},
            {**_req(30, status='swarm_ready'), 'coordination_type': 'implemented'},
            {**_req(41, status='swarm_ready'), 'coordination_type': 'deployed'},
            {**_req(51, status='swarm_ready'), 'coordination_type': 'deployed'},
            {**_req(61, status='swarm_ready'), 'coordination_type': 'implemented'},
        ],
    }
    return model


def _pairs(plan):
    return [(e['step_id'], e['requirement_id']) for e in plan['launch_queue']]


# COVERS: DRV-029
def test_launch_queue_is_gate_open_steps_then_past_gate_in_display_order():
    plan = deriv.derive_plan2(_queue_model(), now=NOW)
    steps = [s for s, _ in _pairs(plan)]
    # Every gate-open step's work precedes every past-gate step's work.
    assert steps.index(3) > max(steps.index(1), steps.index(2), steps.index(4))
    assert plan['launch_candidate_step_ids'][-1] == 3


# COVERS: DRV-029
def test_launch_queue_within_a_step_is_deployed_first_then_fifo_by_id():
    plan = deriv.derive_plan2(_queue_model(), now=NOW)
    a = [r for s, r in _pairs(plan) if s == 1]
    assert a == [32, 30, 31]          # deployed 32 first, then ids ascending


# COVERS: DRV-029
def test_launch_queue_a_later_steps_deployed_work_never_jumps_an_earlier_step():
    """The user's ruling (2026-10-19), superseding req #3623's scope-wide
    preference: B's deployed 41 and C's deployed 51 rank AFTER every one of
    A's requirements, implemented included."""
    plan = deriv.derive_plan2(_queue_model(), now=NOW)
    pairs = _pairs(plan)
    last_of_a = max(i for i, (s, _) in enumerate(pairs) if s == 1)
    assert pairs.index((2, 41)) > last_of_a
    assert pairs.index((3, 51)) > pairs.index((2, 41))


# COVERS: DRV-029
def test_launch_queue_includes_manual_steps_and_excludes_suppressed_ones():
    model = _queue_model()
    plan = deriv.derive_plan2(model, now=NOW)
    assert (4, 61) in _pairs(plan)                    # run=manual is IN
    model['epics'][0]['epic_status'] = 'paused'
    plan = deriv.derive_plan2(model, now=NOW)
    assert plan['launch_queue'] == []                 # suppressed is OUT...
    assert plan['launch_candidate_step_ids'] == [1, 2, 4, 3]   # ...but still a candidate


# COVERS: DRV-029
def test_launch_queue_omits_a_step_held_by_a_checkpoint_and_non_launchable_work():
    plan = deriv.derive_plan2(_checkpoint_model(), now=NOW)
    assert _pairs(plan) == [(5, 50)]
    model = _queue_model()
    model['requirements'][0]['requirement_status'] = 'development'   # 31
    plan = deriv.derive_plan2(model, now=NOW)
    assert 31 not in [r for _, r in _pairs(plan)]


# COVERS: DRV-029
def test_launch_queue_is_a_pure_function_of_candidates_rows_and_requirements():
    rows = {7: {'id': 7, 'launch_req_ids': [3, 1, 2], 'launch_suppressed': False},
            8: {'id': 8, 'launch_req_ids': [9], 'launch_suppressed': True}}
    reqs = {1: {'coordination_type': 'implemented'},
            2: {'coordination_type': 'deployed'}}       # 3 unknown -> not deployed
    assert deriv.launch_queue([7, 8], rows, reqs) == [
        {'step_id': 7, 'requirement_id': 2},
        {'step_id': 7, 'requirement_id': 1},
        {'step_id': 7, 'requirement_id': 3}]
    assert deriv.launch_queue([], rows, reqs) == []


# ---------------------------------------------------------------------------
# Pause (DRV-016/017/018) — launch suppression, epic-scoped
# ---------------------------------------------------------------------------

def _paused_model(pipeline_status='active', epic_statuses=(None, None)):
    return {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': pipeline_status,
                    'execution_mode': 'parallel'},
        'epics': [
            {**_epic(90), 'epic_status': epic_statuses[0] or 'active'},
            {**_epic(91), 'epic_status': epic_statuses[1] or 'active'},
        ],
        'steps': [_step(9001, 90), _step(9101, 91)],
        'step_requirements': [{'step_fk': 9001, 'requirement_fk': 71},
                              {'step_fk': 9101, 'requirement_fk': 72}],
        'step_deps': [],
        'requirements': [_req(71, status='swarm_ready'),
                         _req(72, status='swarm_ready')],
    }


# COVERS: DRV-017
def test_epic_pause_suppresses_only_that_epics_steps():
    model = _paused_model(epic_statuses=('paused', 'active'))
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    pause = deriv.pause_state(model, ordered['rows'])
    by_id = {r['id']: r for r in ordered['rows']}
    assert by_id[9001]['launch_suppressed'] is True
    assert by_id[9001]['suppressed_by'] == ['epic']
    assert by_id[9101]['launch_suppressed'] is False
    assert pause['paused_epic_ids'] == [90]
    assert pause['suppressed_step_ids'] == [9001]


# COVERS: DRV-016
def test_launch_suppression_leaves_eligible_unchanged():
    """`eligible` and `launch_suppressed` are independent — an
    eligible-and-suppressed step must stay distinguishable from a
    not-eligible one (DRV-016)."""
    model = _paused_model(epic_statuses=('paused', 'active'))
    plan = deriv.derive_plan2(model, now='2026-08-09T00:00:00Z')
    row = next(r for r in plan['rows'] if r['id'] == 9001)
    assert row['eligible'] is True                 # work, no deps, no time gate
    assert row['launch_suppressed'] is True         # but its epic is paused
    assert 9001 in plan['eligible_step_ids']         # eligibility is untouched


# COVERS: DRV-018
def test_whole_plan_pause_suppresses_every_epics_steps():
    """A whole-plan pause binds a whole-plan orchestrator's every epic —
    suppression is a property of the STEP regardless of which scope asks."""
    model = _paused_model(pipeline_status='paused')
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    pause = deriv.pause_state(model, ordered['rows'])
    assert pause['pipeline_paused'] is True
    assert set(pause['suppressed_step_ids']) == {9001, 9101}
    by_id = {r['id']: r for r in ordered['rows']}
    assert by_id[9001]['suppressed_by'] == ['pipeline']
    assert by_id[9101]['suppressed_by'] == ['pipeline']


def test_suppressed_by_names_both_reasons_when_both_fire():
    model = _paused_model(pipeline_status='paused', epic_statuses=('paused', 'active'))
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    pause = deriv.pause_state(model, ordered['rows'])
    by_id = {r['id']: r for r in ordered['rows']}
    assert by_id[9001]['suppressed_by'] == ['pipeline', 'epic']


# ---------------------------------------------------------------------------
# Epic-scoped reads and out-of-scope cross-epic dependencies
#
# Regression coverage for a code-review finding: `get_pipeline2_epic_composed`
# narrows `steps` at the gateway but fetches `step_deps` by `step_fk`, so an
# OUTGOING cross-epic edge names a `dep_step_fk` this payload never fetched.
# `eligibility` correctly, permanently refuses to launch such a step (it
# cannot know whether the dependency is done) — the defect was that
# `verify_order` reported this as `dangling-dependency`, which reads as data
# corruption rather than "read the whole-plan render for the true state".
# ---------------------------------------------------------------------------

def _epic_scoped_model_with_outgoing_edge():
    return {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': 'parallel'},
        'epics': [_epic(90)],                    # ONLY the requested epic
        'steps': [_step(9001, 90)],               # ONLY that epic's own steps
        'step_requirements': [], 'requirements': [],
        # names a step in a DIFFERENT epic this payload never fetched
        'step_deps': [{'id': 1, 'step_fk': 9001, 'dep_step_fk': 8888}],
    }


def test_epic_scoped_read_reports_out_of_scope_not_dangling():
    model = _epic_scoped_model_with_outgoing_edge()
    plan = deriv.derive_plan2(model, now='2026-08-09T00:00:00Z', epic_scoped=True)
    assert plan['out_of_scope_dep_ids'] == [8888]
    assert [v for v in plan['violations'] if v['invariant'] == 'dangling-dependency'] == []
    # Still correctly NOT eligible — this payload cannot see whether 8888 is
    # done, and the safe direction is not to guess.
    row = next(r for r in plan['rows'] if r['id'] == 9001)
    assert row['eligible'] is False
    assert 9001 not in plan['eligible_step_ids']
    # The reason is discoverable ON THE ROW, not just at plan level.
    assert row['out_of_scope_dep_ids'] == [8888]


def test_whole_plan_read_still_reports_a_genuinely_dangling_dependency():
    """The SAME shape, read as a whole-plan payload (`epic_scoped=False`,
    the default) — every epic is supposed to be present, so a missing dep
    is a real defect (truncation or corruption) and must stay a loud
    violation, unlike the epic-scoped case above."""
    model = _epic_scoped_model_with_outgoing_edge()
    plan = deriv.derive_plan2(model, now='2026-08-09T00:00:00Z')
    assert plan['out_of_scope_dep_ids'] == []
    dangling = [v for v in plan['violations'] if v['invariant'] == 'dangling-dependency']
    assert dangling and set(dangling[0]['step_ids']) == {9001, 8888}


# ---------------------------------------------------------------------------
# Serial execution (gate delta, req #3388) — restated for 2.0
#
# The verification register has NO DRV-* entry for this at all (on any
# requirement), which is a gap in the register, not evidence the work
# belongs elsewhere — req #3349's own GATE DELTAS section names it
# explicitly. See the module docstring's Scope section.
# ---------------------------------------------------------------------------

def _serial_model(execution_mode='serial'):
    """Three epics in turn order 90 -> 91 -> 92. Epic 90 holds no open work
    (its turn is over), epic 91 holds open work (live), epic 92 too (waiting)."""
    return {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': execution_mode},
        'epics': [_epic(90, sort_order=1), _epic(91, sort_order=2),
                 _epic(92, sort_order=3)],
        'steps': [_step(9001, 90), _step(9101, 91), _step(9201, 92)],
        'step_requirements': [{'step_fk': 9001, 'requirement_fk': 1},
                              {'step_fk': 9101, 'requirement_fk': 2},
                              {'step_fk': 9201, 'requirement_fk': 3}],
        'step_deps': [],
        'requirements': [_req(1, status='met'), _req(2, status='swarm_ready'),
                         _req(3, status='swarm_ready')],
    }


def test_serial_state_parallel_mode_holds_nothing():
    model = _serial_model(execution_mode='parallel')
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    deriv.pause_state(model, ordered['rows'])
    serial = deriv.serial_state(model, ordered['rows'], ordered['epic_order'])
    assert serial == {
        'execution_mode': 'parallel', 'serial': False,
        'epic_order': [90, 91, 92], 'closed_epic_ids': [90],
        'live_epic_id': 91, 'waiting_epic_ids': [92], 'held_step_ids': []}
    by_id = {r['id']: r for r in ordered['rows']}
    assert by_id[9201]['launch_suppressed'] is False


def test_serial_state_serial_mode_holds_the_waiting_epic():
    model = _serial_model(execution_mode='serial')
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    deriv.pause_state(model, ordered['rows'])
    serial = deriv.serial_state(model, ordered['rows'], ordered['epic_order'])
    assert serial['serial'] is True
    assert serial['live_epic_id'] == 91
    assert serial['waiting_epic_ids'] == [92]
    assert serial['held_step_ids'] == [9201]
    by_id = {r['id']: r for r in ordered['rows']}
    assert by_id[9201]['launch_suppressed'] is True
    assert by_id[9201]['suppressed_by'] == ['turn']
    # The LIVE epic's own step is untouched.
    assert by_id[9101]['launch_suppressed'] is False
    # A closed epic's step is never held either (it is behind, not ahead).
    assert by_id[9001]['launch_suppressed'] is False


def test_serial_state_absent_execution_mode_reads_as_parallel():
    model = _serial_model(execution_mode=None)
    del model['pipeline']['execution_mode']
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    serial = deriv.serial_state(model, ordered['rows'], ordered['epic_order'])
    assert serial['execution_mode'] == deriv.MODE_PARALLEL
    assert serial['serial'] is False


def test_turn_suppression_appends_to_pause_suppression():
    """A step held by BOTH a pause and a turn names both reasons — pause
    runs first and `serial_state` appends rather than replaces."""
    model = _serial_model(execution_mode='serial')
    model['epics'][2] = {**model['epics'][2], 'epic_status': 'paused'}   # epic 92
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    deriv.pause_state(model, ordered['rows'])
    deriv.serial_state(model, ordered['rows'], ordered['epic_order'])
    by_id = {r['id']: r for r in ordered['rows']}
    assert by_id[9201]['suppressed_by'] == ['epic', 'turn']


def test_derive_plan2_carries_the_serial_block():
    model = _serial_model(execution_mode='serial')
    plan = deriv.derive_plan2(model, now='2026-08-09T00:00:00Z')
    assert plan['serial']['serial'] is True
    assert plan['serial']['held_step_ids'] == [9201]
    row = next(r for r in plan['rows'] if r['id'] == 9201)
    assert row['launch_suppressed'] is True
    assert row['suppressed_by'] == ['turn']


def test_forward_cross_epic_edge_under_serial_is_not_a_deadlock():
    """The ORDINARY case: a later epic's step depends on an earlier epic's
    step. That is exactly how serial execution is meant to work and must
    NOT be reported."""
    model = _serial_model(execution_mode='serial')
    model['step_deps'] = [{'id': 1, 'step_fk': 9101, 'dep_step_fk': 9001}]
    plan = deriv.derive_plan2(model, now='2026-08-09T00:00:00Z')
    assert [v for v in plan['violations'] if v['invariant'] == 'serial-deadlock'] == []


def test_backward_cross_epic_edge_under_serial_is_a_loud_deadlock():
    """The live epic's step depends on the WAITING epic's step — that
    dependency can never be released (its epic never goes live while this
    one, blocked on it, never closes). Must be a LOUD violation."""
    model = _serial_model(execution_mode='serial')
    # 9101 (epic 91, live) depends on 9201 (epic 92, waiting) — backward.
    model['step_deps'] = [{'id': 1, 'step_fk': 9101, 'dep_step_fk': 9201}]
    plan = deriv.derive_plan2(model, now='2026-08-09T00:00:00Z')
    deadlocks = [v for v in plan['violations'] if v['invariant'] == 'serial-deadlock']
    assert deadlocks and set(deadlocks[0]['step_ids']) == {9101, 9201}
    # req #3597 — still LOUD, but no longer called a deadlock: the depending
    # step launches ahead of its dependency, so the plan runs.
    assert 'never be honoured as an ordering' in deadlocks[0]['message']
    assert 'can never open' not in deadlocks[0]['message']


def test_backward_edge_under_parallel_mode_is_not_a_deadlock():
    """The same backward edge under `parallel` execution is ordinary
    topology (already checked elsewhere) — serial-deadlock only applies
    when a turn order actually exists to violate."""
    model = _serial_model(execution_mode='parallel')
    model['step_deps'] = [{'id': 1, 'step_fk': 9101, 'dep_step_fk': 9201}]
    plan = deriv.derive_plan2(model, now='2026-08-09T00:00:00Z')
    assert [v for v in plan['violations'] if v['invariant'] == 'serial-deadlock'] == []


# ---------------------------------------------------------------------------
# Req #3367 deliverable 6 — three cases the corpus mapping below (module
# docstring) found genuinely UNCOVERED once every translatable 1.0 case was
# checked off against the tests above. Added here rather than left as a gap.
# ---------------------------------------------------------------------------

def test_empty_plan_derives_cleanly():
    """`pipeline_conformance.json` case `empty-plan`, translated: the
    degenerate input every loop here must survive. No epics, no steps — every
    collection comes back empty and nothing raises."""
    model = {'pipeline': {'id': 1, 'title': 'Empty', 'pipeline_status': 'draft'},
            'epics': [], 'steps': [], 'step_requirements': [], 'step_deps': [],
            'requirements': []}
    plan = deriv.derive_plan2(model, now='2026-08-09T00:00:00Z')
    assert plan['display_order'] == []
    assert plan['rows'] == []
    assert plan['violations'] == []
    assert plan['cycle_detected'] is False
    assert plan['requirement_counts']['overall'] == {'met': 0, 'total': 0}


def test_tracking_flag_coercion_matrix():
    """`pipeline_conformance.json` case `tracking-flag-coercion`, translated:
    `is_tracking_requirement` reads MySQL's own TINYINT truthiness, not
    Python's — a container link, once excluded from a step's GATING set, must
    stay excluded across every spelling `tracking` might arrive in."""
    truthy = (1, True, 2, '1', '2', -1)
    falsy = (0, False, None, '', '0')
    for value in truthy:
        assert deriv.is_tracking_requirement({'tracking': value}) is True, value
    for value in falsy:
        assert deriv.is_tracking_requirement({'tracking': value}) is False, value


