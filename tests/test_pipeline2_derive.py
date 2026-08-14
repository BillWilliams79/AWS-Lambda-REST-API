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
  * **The epic-scoped state-banding self-check**, including the amended
    three-step case (`memory/pipeline-2-visualizer-design.md` § 5.3) that a
    global-vs-scoped confusion would otherwise hide.

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
    `test_derive_step_state_done_running_pending`,
    `test_derive_step_state_with_no_gating_requirements_reads_completed_at`,
    `test_all_container_links_derive_from_completion_stamp_never_running`;
  `tracking-container-exemption` → `test_tracking_requirement_never_gates`,
    `test_all_container_links_derive_from_completion_stamp_never_running`;
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
    `test_eligibility_requires_every_dependency_done`,
    `test_eligibility_consults_not_before_against_the_payload_clock`,
    `test_eligibility_is_false_for_a_non_pending_row` (the timestamp-grammar
    hazards themselves are `_to_epoch`'s, restated verbatim from 1.0's
    already-tested `_TIMESTAMP_RE` — module docstring "changed" item 3);
  `topological-order-diamond`, `state-bands-outrank-stored-order`,
    `banding-inversion-forced-by-topology-is-not-a-violation` →
    `test_three_step_single_epic_case_still_reports_amended_acceptance` and
    the `display_order`/`verify_order` tests around it;
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
  `epic-sort-order-does-not-outrank-a-state-band` →
    `test_epic_sort_order_does_not_outrank_a_within_epic_state_band`.

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
a 2.0-shaped test above it; three gaps the check surfaced —
`test_empty_plan_derives_cleanly`, `test_tracking_flag_coercion_matrix`,
`test_epic_sort_order_does_not_outrank_a_within_epic_state_band` — are added
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
         completed_at=None, create_ts='2026-08-01 00:00:00'):
    return {'id': id, 'epic_fk': epic_fk, 'title': title or f'step {id}',
            'run': run, 'not_before': not_before, 'notes': notes,
            'completed_at': completed_at, 'creator_fk': _SUB,
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
            'id', 'title', 'run', 'notes', 'completed_at', 'state', 'epic_id',
            'req_ids', 'tracking_req_ids', 'unresolved_req_ids',
            'launch_req_ids', 'launch_excluded', 'launch_block',
            'swarm_start_command', 'no_launch_reason', 'dep_ids',
            '_create_ts', '_not_before'}


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
# Item 4 — display order is a tree walk, epic-scoped state-banding
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
        # epic 90 started (a done step) so would derive FIRST; epic 91 is
        # unstarted and would derive LAST. A manual order on 91 overrides that.
        'epics': [_epic(90), _epic(91, sort_order=1)],
        'steps': [
            _step(9001, 90, completed_at='2026-08-01 00:00:00'),
            _step(9101, 91),
        ],
        'step_requirements': [], 'step_deps': [], 'requirements': [],
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
            # epic 90: unstarted (all pending) -> creation order (id)
            _step(9001, 90),
            # epic 91: started later
            _step(9101, 91, completed_at='2026-08-05 00:00:00',
                 create_ts='2026-08-02 00:00:00'),
            # epic 92: started earliest
            _step(9201, 92, completed_at='2026-08-05 00:00:00',
                 create_ts='2026-08-01 00:00:00'),
        ],
        'step_requirements': [], 'step_deps': [], 'requirements': [],
    }
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    # started epics (92 earliest, then 91) precede the unstarted one (90).
    assert ordered['epic_order'] == [92, 91, 90]


# COVERS: DRV-020
def test_three_step_single_epic_case_still_reports_amended_acceptance():
    """The amended acceptance criterion, verbatim:
    `1 pending, 2 pending, 3 done depending on 2` in ONE epic must still
    report a state-banding violation
    (memory/pipeline-2-visualizer-design.md § 5.3)."""
    model = {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': 'parallel'},
        'epics': [_epic(90)],
        'steps': [
            _step(1, 90),
            _step(2, 90),
            _step(3, 90, completed_at='2026-08-01 00:00:00'),
        ],
        'step_requirements': [], 'requirements': [],
        'step_deps': [{'id': 1, 'step_fk': 3, 'dep_step_fk': 2}],
    }
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    violations, _ = deriv.verify_order(ordered['rows'])
    banding = [v for v in violations if v['invariant'] == 'state-banding']
    assert banding, ('the amended acceptance criterion requires this case to '
                     'still report — see visualizer-design.md § 5.3')
    assert set(banding[0]['step_ids']) == {3, 1}


# COVERS: DRV-020
def test_epic_scoping_produces_zero_false_violations_across_epics():
    """Measurement D (visualizer-design.md § 5.2): a finished epic's done
    steps rendering above an unrelated epic's still-pending work must NOT be
    reported — that is what containment asks for, and a global check would
    wrongly flag it (measurement C, 15 false violations on the live plan)."""
    model = {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': 'parallel'},
        'epics': [_epic(90, sort_order=1), _epic(91, sort_order=2)],
        'steps': [
            # epic 90: fully done
            _step(9001, 90, completed_at='2026-08-01 00:00:00'),
            _step(9002, 90, completed_at='2026-08-01 00:00:00'),
            # epic 91: still has pending work
            _step(9101, 91),
        ],
        'step_requirements': [], 'step_deps': [], 'requirements': [],
    }
    rows = deriv.build_plan_rows(model)
    ordered = deriv.display_order(rows, model['epics'])
    violations, _ = deriv.verify_order(ordered['rows'])
    assert [v for v in violations if v['invariant'] == 'state-banding'] == []


# COVERS: DRV-012
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
    still-pending step in epic 90 must never render before it, and the
    epic-scoped banding check must not false-positive on the crossing."""
    model = {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': 'parallel'},
        'epics': [_epic(90, sort_order=1), _epic(91, sort_order=2)],
        'steps': [
            _step(9001, 90),                    # pending, gates 9101
            _step(9101, 91),                     # pending, depends on 9001
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
    assert [v for v in violations if v['invariant'] == 'state-banding'] == []


# ---------------------------------------------------------------------------
# derive_step_state — unchanged rule, restated
# ---------------------------------------------------------------------------

# COVERS: DRV-009
def test_derive_step_state_done_running_pending():
    step = {'completed_at': None}
    assert deriv.derive_step_state(step, [_req(1, status='development')]) == deriv.STEP_RUNNING
    assert deriv.derive_step_state(step, [_req(1, status='met')]) == deriv.STEP_DONE
    assert deriv.derive_step_state(step, [_req(1, status='authoring')]) == deriv.STEP_PENDING


# COVERS: DRV-011
def test_derive_step_state_with_no_gating_requirements_reads_completed_at():
    assert deriv.derive_step_state({'completed_at': None}, []) == deriv.STEP_PENDING
    assert deriv.derive_step_state({'completed_at': '2026-08-01'}, []) == deriv.STEP_DONE


# COVERS: DRV-009
def test_tracking_requirement_never_gates():
    step = {'completed_at': None}
    reqs = [_req(1, status='development', tracking=1)]
    assert deriv.derive_step_state(step, reqs) == deriv.STEP_PENDING


# COVERS: DRV-010
def test_all_container_links_derive_from_completion_stamp_never_running():
    """A step whose links are ALL tracking containers falls through to its
    own `completed_at` stamp exactly as a link-less step does — Complete or
    Scheduled, NEVER Running, even though a container sits in `development`."""
    reqs = [_req(1, status='development', tracking=1)]
    assert deriv.derive_step_state({'completed_at': None}, reqs) == deriv.STEP_PENDING
    assert deriv.derive_step_state({'completed_at': '2026-08-01'}, reqs) == deriv.STEP_DONE


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
        'eligible_step_ids', 'violations', 'cycle_detected', 'cycle_step_ids',
        'duplicate_step_ids', 'unresolved_req_ids', 'out_of_scope_dep_ids',
        'requirement_counts'}
    for row in plan['rows']:
        assert set(row) == {
            'id', 'state', 'run', 'eligible', 'epic_id', 'dep_ids',
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

def _pending_row(id, epic_id=90, dep_ids=None, not_before=None):
    return {'id': id, 'state': deriv.STEP_PENDING, 'dep_ids': dep_ids or [],
            'epic_id': epic_id, '_not_before': not_before}


def _done_row(id, epic_id=90):
    return {'id': id, 'state': deriv.STEP_DONE, 'dep_ids': [], 'epic_id': epic_id,
            '_not_before': None}


# COVERS: DRV-005
def test_eligibility_requires_every_dependency_done():
    dep = _pending_row(1)
    row = _pending_row(2, dep_ids=[1])
    by_id = {1: dep, 2: row}
    assert deriv.eligibility(row, by_id, now='2026-08-09T00:00:00Z') is False
    by_id[1] = _done_row(1)
    assert deriv.eligibility(row, by_id, now='2026-08-09T00:00:00Z') is True


# COVERS: DRV-005, DRV-006
def test_eligibility_consults_not_before_against_the_payload_clock():
    row = _pending_row(1, not_before='2026-08-10T00:00:00Z')
    by_id = {1: row}
    # the gate has not passed yet relative to this `now`
    assert deriv.eligibility(row, by_id, now='2026-08-09T00:00:00Z') is False
    # the gate has passed relative to a later `now`
    assert deriv.eligibility(row, by_id, now='2026-08-11T00:00:00Z') is True
    # no `now` at all while a gate exists means NOT eligible, never passed
    assert deriv.eligibility(row, by_id, now=None) is False


def test_eligibility_is_false_for_a_non_pending_row():
    row = _done_row(1)
    assert deriv.eligibility(row, {1: row}, now='2026-08-09T00:00:00Z') is False


def test_derive_plan2_eligible_step_ids_reflects_the_dep_graph():
    model = _basic_model()
    model['requirements'] = [_req(5010, status='met'), _req(5011, status='met')]
    plan = deriv.derive_plan2(model, now='2026-08-09T00:00:00Z')
    # 9001/9002 are done (met requirements); 9003 gates on both -> eligible.
    assert plan['eligible_step_ids'] == [9003]
    row = next(r for r in plan['rows'] if r['id'] == 9003)
    assert row['eligible'] is True


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
        'step_requirements': [], 'step_deps': [], 'requirements': [],
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
    assert row['eligible'] is True                 # no deps, no time gate
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
# The state-banding closure must be GLOBAL even though the comparison is
# epic-scoped — regression coverage for a code-review finding: an earlier
# version computed `depends_on` per epic, which cannot see a transitive
# dependency path that leaves and re-enters an epic through another one.
# ---------------------------------------------------------------------------

def test_banding_closure_sees_a_transitive_path_through_another_epic():
    """1 depends on 2 (epic 91), which depends on 3 (epic 90, same epic as
    1). Topological order is [3, 2, 1]. Within epic 90's own two rows
    ([3, 1] in that relative order), 1 (done) renders below 3 (pending) —
    which LOOKS like an avoidable inversion unless the closure can see that
    1 transitively depends on 3 through 2, which lives in epic 91."""
    row1 = {'id': 1, 'state': deriv.STEP_DONE, 'epic_id': 90, 'dep_ids': [2]}
    row2 = {'id': 2, 'state': deriv.STEP_PENDING, 'epic_id': 91, 'dep_ids': [3]}
    row3 = {'id': 3, 'state': deriv.STEP_PENDING, 'epic_id': 90, 'dep_ids': []}
    rows = [row3, row2, row1]                     # the topological order
    violations, out_of_scope = deriv.verify_order(rows)
    assert out_of_scope == []
    assert [v for v in violations if v['invariant'] == 'state-banding'] == []


# ---------------------------------------------------------------------------
# Serial execution (gate delta, req #3388) — restated for 2.0
#
# The verification register has NO DRV-* entry for this at all (on any
# requirement), which is a gap in the register, not evidence the work
# belongs elsewhere — req #3349's own GATE DELTAS section names it
# explicitly. See the module docstring's Scope section.
# ---------------------------------------------------------------------------

def _serial_model(execution_mode='serial'):
    """Three epics in turn order 90 -> 91 -> 92. Epic 90 is fully done,
    epic 91 has pending work (live), epic 92 is untouched (waiting)."""
    return {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': execution_mode},
        'epics': [_epic(90, sort_order=1), _epic(91, sort_order=2),
                 _epic(92, sort_order=3)],
        'steps': [
            _step(9001, 90, completed_at='2026-08-01 00:00:00'),
            _step(9101, 91),
            _step(9201, 92),
        ],
        'step_requirements': [], 'step_deps': [], 'requirements': [],
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


def test_epic_sort_order_does_not_outrank_a_within_epic_state_band():
    """`pipeline_conformance.json` case
    `epic-sort-order-does-not-outrank-a-state-band`, translated: `sort_order`
    is a CLUSTERING signal between epics (`display_order`'s epic_order), never
    an override of the state-banding invariant WITHIN an epic. An epic given
    `sort_order=1` (so it renders first) whose own steps still violate banding
    must report that violation regardless of its position."""
    model = {
        'pipeline': {'id': 900, 'title': 'p', 'pipeline_status': 'active',
                    'execution_mode': 'parallel'},
        'epics': [_epic(90, sort_order=1), _epic(91, sort_order=2)],
        'steps': [
            _step(1, 90), _step(2, 90),
            _step(3, 90, completed_at='2026-08-01 00:00:00'),
            _step(9101, 91),
        ],
        'step_requirements': [], 'requirements': [],
        'step_deps': [{'id': 1, 'step_fk': 3, 'dep_step_fk': 2}],
    }
    plan = deriv.derive_plan2(model, now='2026-08-09T00:00:00Z')
    assert plan['epic_order'] == [90, 91], "sort_order still clusters the epics"
    banding = [v for v in plan['violations'] if v['invariant'] == 'state-banding']
    assert banding, ("sort_order must not suppress a genuine within-epic "
                     "banding violation")
    assert set(banding[0]['step_ids']) == {3, 1}
