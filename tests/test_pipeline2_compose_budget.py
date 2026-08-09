"""The Pipeline 2.0 composing route's budget ladder — unit tier (req #3367).

Pure-function tests, no database: `pipeline2_compose._bounded` is the ONE
place this now runs (moved from darwin-mcp's `server._bounded_plan2`, which
this route obsoletes — the daemon no longer bounds anything, because what it
receives from here is already bounded). Byte-identical algorithm; these tests
mirror darwin-mcp's `tests/unit/test_pipelines2.py` budget-ladder section so
the same three regimes stay provably covered after the move.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pipeline2_compose as pc                          # noqa: E402


def _fake_composed(step_count=3, notes_len=10, derived_bytes=200):
    steps = [{'id': i, 'epic_fk': 1, 'title': f's{i}', 'run': 'auto',
             'not_before': None, 'notes': 'x' * notes_len,
             'completed_at': None} for i in range(1, step_count + 1)]
    return {
        'pipeline': {'id': 1, 'title': 'p', 'step_count': step_count},
        'epics': [{'id': 1, 'pipeline_fk': 1, 'title': 'e'}],
        'steps': steps,
        'step_requirements': [],
        'step_deps': [],
        'requirements': [],
        'derived': {'withheld': True, 'reason': 'x' * derived_bytes,
                   'withheld_reason': 'derivation_failed', 'rows_complete': True},
    }


def _bounded(composed, budget, monkeypatch, **kwargs):
    monkeypatch.setattr(pc, 'PAYLOAD_BUDGET_BYTES', budget)
    return pc._bounded('pipeline2_compose/1', composed, **kwargs)


def test_a_plan_under_budget_ships_regime_a_unchanged(monkeypatch):
    composed = _fake_composed()
    result = _bounded(composed, 1_000_000, monkeypatch)
    assert result is composed
    assert result['derived']['withheld_reason'] == 'derivation_failed'


def test_an_empty_plan_is_never_bounded(monkeypatch):
    composed = _fake_composed(step_count=0)
    result = _bounded(composed, 1, monkeypatch)
    assert result is composed


def test_regime_b_withholds_derived_and_keeps_every_row(monkeypatch):
    """A LARGE `derived` block pushes the payload over budget on its own;
    withholding it alone is enough."""
    composed = _fake_composed(step_count=5, notes_len=20, derived_bytes=50_000)
    budget = pc.payload_bytes(composed) - 1
    assert budget < pc.payload_bytes(composed)

    result = _bounded(composed, budget, monkeypatch)

    assert len(result['steps']) == 5
    assert not any(pc.TRUNCATION_KEY in s for s in result['steps'])
    assert pc.TRUNCATION_KEY not in result
    assert result['derived']['withheld_reason'] == pc.WITHHELD_BUDGET_DERIVED_ONLY
    assert result['derived']['rows_complete'] is True
    # THE OVER-BUDGET TRAP: the naive "swap stub in, then measure" fix ships
    # over budget because it forgets to re-check. Assert the shipped payload
    # actually fits.
    assert pc.payload_bytes(result) <= budget


def test_regime_c_truncates_steps_and_prunes_dependents(monkeypatch):
    composed = _fake_composed(step_count=50, notes_len=2000, derived_bytes=50_000)
    composed['step_requirements'] = [
        {'step_fk': i, 'requirement_fk': 100 + i} for i in range(1, 51)]
    composed['step_deps'] = [
        {'step_fk': i, 'dep_step_fk': i - 1} for i in range(2, 51)]

    budget = 10_000
    result = _bounded(composed, budget, monkeypatch)

    assert pc.TRUNCATION_KEY in result
    kept = {s['id'] for s in result['steps'] if pc.TRUNCATION_KEY not in s}
    assert 0 < len(kept) < 50, 'the budget must actually bite for this test to mean anything'
    for row in result['step_requirements']:
        assert row['step_fk'] in kept
    for row in result['step_deps']:
        assert row['step_fk'] in kept and row['dep_step_fk'] in kept

    assert result['derived']['withheld_reason'] == pc.WITHHELD_BUDGET_ROWS_TRUNCATED
    assert result['derived']['rows_complete'] is False
    assert result['pipeline']['step_count'] == 50
    assert pc.payload_bytes(result) <= budget


def test_regime_c_never_ships_over_budget_across_a_sweep(monkeypatch):
    """`remaining` (the allowance regime C's own truncation pass gets) must be
    measured against the REGIME-C `derived` stub that actually ships, never
    against regime B's — the two messages are different lengths with no
    reason to stay in a particular order, and measuring the wrong one is a
    latent over-budget bug that only shows up once someone edits either
    message's wording (found in review, req #3367)."""
    for step_count in (1, 4, 7, 13, 25, 40):
        for notes_len in (0, 50, 500, 2000):
            for derived_bytes in (0, 1000, 20_000, 80_000):
                for budget in (5_000, 8_000, 10_000, 20_000):
                    composed = _fake_composed(step_count=step_count, notes_len=notes_len,
                                              derived_bytes=derived_bytes)
                    composed['step_requirements'] = [
                        {'step_fk': i, 'requirement_fk': 100 + i}
                        for i in range(1, step_count + 1)]
                    composed['step_deps'] = [
                        {'step_fk': i, 'dep_step_fk': i - 1}
                        for i in range(2, step_count + 1)]
                    result = _bounded(composed, budget, monkeypatch)
                    size = pc.payload_bytes(result)
                    assert size <= budget, (
                        f"over budget by {size - budget}B: step_count={step_count} "
                        f"notes_len={notes_len} derived_bytes={derived_bytes} "
                        f"budget={budget}")


def test_regime_c_never_ships_the_real_derived_block(monkeypatch):
    composed = _fake_composed(step_count=40, notes_len=1500, derived_bytes=80_000)
    result = _bounded(composed, 8_000, monkeypatch)
    assert result['derived'] != composed['derived']
    assert result['derived']['withheld'] is True


def test_deriver_exception_degrades_to_a_withheld_stub_without_losing_rows(monkeypatch):
    """`_derive`'s guard: a `derive_plan2` exception must never take the real
    rows down with it."""
    def boom(model, now=None, epic_scoped=False):
        raise RuntimeError('synthetic failure')

    monkeypatch.setattr(pc.pipeline2_derive, 'derive_plan2', boom)
    model = {'pipeline': {'id': 1}, 'epics': [], 'steps': [],
             'step_requirements': [], 'step_deps': [], 'requirements': []}
    derived = pc._derive(model)
    assert derived['withheld'] is True
    assert derived['withheld_reason'] == pc.WITHHELD_DERIVATION_FAILED
    assert derived['rows_complete'] is True
