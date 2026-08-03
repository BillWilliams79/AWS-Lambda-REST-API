"""
The batched GET /map_coordinates read path — req #3166.

Darwin's frontend now fetches coordinates for MANY runs per request
(`Darwin/src/services/mapCoordinatesBatch.js`) instead of one request per run.
It does that entirely with query-string grammar `rest_get_table.py` already
supported — which is the point: req #3166 was written believing no IN filter
existed, and it did. Nothing in Lambda-Rest changed, so what needs locking down
is that the THREE features the batched client leans on keep behaving the way it
assumes, on this table:

  1. `?map_run_fk=(1,2,3)`      the IN filter, so N runs come back in one call
  2. `&sort=map_run_fk:asc,seq:asc`
                                a TWO-column sort — `seq:asc` alone interleaves
                                runs and the client's per-run split would then
                                have to re-sort every track
  3. `&fields=count(*),map_run_fk`
                                the grouped count that SIZES each batch, and
                                whose empty-set answer is 404 (not the 503 that
                                memory/lambda-patterns.md claimed until #3166)

Plus the property none of them may cost: a batched read is still scoped to its
caller. `map_coordinates` carries no `creator_fk` and is authorized by joining
through `map_run_fk` -> `map_runs.creator_fk` (req #3122), and an IN list is
exactly the shape that would leak if that join were skipped.

Integration tests — need `. ./exports.sh`.
"""
import json

import pytest

from conftest import extract_id


# Coordinate counts per fixture run. Deliberately uneven and deliberately NOT in
# id order, so an assertion about ordering cannot pass by accident.
_RUN_COORD_COUNTS = (3, 1, 4)


@pytest.fixture(scope='module')
def coord_runs(invoke, creator_fk, db_connection):
    """Three runs owned by the session creator, with coordinates.

    Coordinates are POSTed seq-DESCENDING on purpose: insertion order then
    disagrees with `seq`, so any test that sees seq-ascending output is seeing
    the ORDER BY work rather than the physical row order.
    """
    run_ids = []
    for index, count in enumerate(_RUN_COORD_COUNTS):
        response = invoke('POST', '/darwin_dev/map_runs', body={
            'run_id': 990_000 + index,
            'activity_id': 4,
            'activity_name': 'Ride',
            'start_time': '2026-01-01 08:00:00',
            'run_time_sec': 3600,
            'distance_mi': '10.0',
            'source': 'pytest',
        })
        assert response['statusCode'] in (200, 201), response
        run_id = int(extract_id(response))
        run_ids.append(run_id)

        for seq in range(count, 0, -1):
            coord = invoke('POST', '/darwin_dev/map_coordinates', body={
                'map_run_fk': run_id,
                'seq': seq,
                'latitude': f'37.{100 + seq}',
                'longitude': f'-122.{100 + seq}',
                'altitude': '10.0',
            })
            assert coord['statusCode'] in (200, 201), coord

    yield run_ids

    with db_connection.cursor() as cur:
        cur.execute('DELETE FROM map_coordinates WHERE map_run_fk IN (%s, %s, %s)', tuple(run_ids))
        cur.execute('DELETE FROM map_runs WHERE creator_fk = %s', (creator_fk,))
    db_connection.commit()


def _get(invoke, query):
    response = invoke('GET', '/darwin_dev/map_coordinates', query=query)
    return response, json.loads(response['body']) if response['body'] else None


def test_in_filter_returns_every_requested_run_in_one_call(invoke, coord_runs):
    """The whole premise of the batched read: N runs, ONE request."""
    ids = ','.join(str(r) for r in coord_runs)
    response, body = _get(invoke, {
        'map_run_fk': f'({ids})',
        'fields': 'map_run_fk,latitude,longitude,altitude',
        'sort': 'map_run_fk:asc,seq:asc',
    })

    assert response['statusCode'] == 200
    assert len(body) == sum(_RUN_COORD_COUNTS)
    assert {row['map_run_fk'] for row in body} == set(coord_runs)


def test_batched_rows_are_grouped_by_run_and_ordered_by_seq(invoke, coord_runs):
    """`map_run_fk:asc,seq:asc` — the split the client does depends on both halves.

    Contiguity lets the client group with a single pass; seq order inside each
    run is the track itself, and it must not come back in insertion order (the
    fixture inserted seq descending).
    """
    ids = ','.join(str(r) for r in coord_runs)
    _, body = _get(invoke, {
        'map_run_fk': f'({ids})',
        'fields': 'map_run_fk,latitude',
        'sort': 'map_run_fk:asc,seq:asc',
    })

    run_order = [row['map_run_fk'] for row in body]
    # Each run appears as ONE contiguous block, blocks in ascending id order.
    blocks = [run_order[0]]
    for run_fk in run_order[1:]:
        if run_fk != blocks[-1]:
            blocks.append(run_fk)
    assert blocks == sorted(coord_runs), 'runs interleaved — the per-run split would break'
    assert len(blocks) == len(set(blocks))

    # `latitude` encodes seq in the fixture (37.10<seq>), so ascending latitude
    # within a block is ascending seq.
    for run_id in coord_runs:
        lats = [float(row['latitude']) for row in body if row['map_run_fk'] == run_id]
        assert lats == sorted(lats), f'run {run_id} came back out of seq order'


def test_grouped_count_sizes_the_batches(invoke, coord_runs):
    """`fields=count(*),map_run_fk` — the probe that bounds response size.

    Without a real per-run row count the client would have to guess how many
    runs fit under Lambda's 6 MB ceiling, and run sizes vary ~7x in production.
    """
    ids = ','.join(str(r) for r in coord_runs)
    response, body = _get(invoke, {
        'map_run_fk': f'({ids})',
        'fields': 'count(*),map_run_fk',
    })

    assert response['statusCode'] == 200
    counts = {row['map_run_fk']: row['count(*)'] for row in body}
    assert counts == dict(zip(coord_runs, _RUN_COORD_COUNTS))


def test_grouped_count_on_an_empty_set_is_404_not_503(invoke, coord_runs):
    """Corrects the claim memory/lambda-patterns.md carried until req #3166.

    A run with no GPS at all is a real case (a manually entered ride), and the
    batched client maps 404 to an empty result. If this were still the 503 the
    doc described, opening the aggregator on a filter of non-GPS rides would
    fail the whole card.
    """
    absent = max(coord_runs) + 10_000_000
    response, _ = _get(invoke, {
        'map_run_fk': f'({absent})',
        'fields': 'count(*),map_run_fk',
    })

    assert response['statusCode'] == 404


def test_in_filter_does_not_leak_another_creators_run(invoke, coord_runs, db_connection,
                                                      creator_fk):
    """Junction scoping (req #3122) holds through the IN filter.

    `map_coordinates` has no `creator_fk`; it is scoped by joining through to
    `map_runs`. A caller naming someone else's run id in the list must get their
    OWN rows and nothing more — the IN list must not become a way to enumerate.
    """
    other_creator = f'{creator_fk}-intruder'
    with db_connection.cursor() as cur:
        cur.execute('INSERT INTO profiles (id, name, email) VALUES (%s, %s, %s)',
                    (other_creator, 'pytest Other', 'other@test.com'))
        cur.execute(
            'INSERT INTO map_runs (run_id, activity_id, activity_name, start_time, '
            'run_time_sec, distance_mi, source, creator_fk) '
            "VALUES (995001, 4, 'Ride', '2026-01-01 08:00:00', 3600, 10.0, 'pytest', %s)",
            (other_creator,))
        other_run = cur.lastrowid
        cur.execute(
            'INSERT INTO map_coordinates (map_run_fk, seq, latitude, longitude) '
            'VALUES (%s, 1, 47.0, -121.0)', (other_run,))
    db_connection.commit()

    try:
        ids = ','.join(str(r) for r in (*coord_runs, other_run))
        response, body = _get(invoke, {
            'map_run_fk': f'({ids})',
            'fields': 'map_run_fk,latitude',
            'sort': 'map_run_fk:asc,seq:asc',
        })

        assert response['statusCode'] == 200
        assert {row['map_run_fk'] for row in body} == set(coord_runs)
        assert other_run not in {row['map_run_fk'] for row in body}
        assert len(body) == sum(_RUN_COORD_COUNTS)
    finally:
        with db_connection.cursor() as cur:
            cur.execute('DELETE FROM map_coordinates WHERE map_run_fk = %s', (other_run,))
            cur.execute('DELETE FROM map_runs WHERE id = %s', (other_run,))
            cur.execute('DELETE FROM profiles WHERE id = %s', (other_creator,))
        db_connection.commit()


def test_group_concat_max_len_can_hold_a_full_batch(db_connection):
    """The silent dependency the whole batching design rests on.

    Every GET on this stack is assembled as
    `CONCAT('[', GROUP_CONCAT(JSON_OBJECT(...)), ']')`, and MySQL TRUNCATES a
    GROUP_CONCAT that exceeds `group_concat_max_len` — to a WARNING, not an
    error. The client would receive a short, invalid-JSON array with a 200.

    The server default is 1024 bytes. RDS parameter group `mysql84-darwin` sets
    10 MB, and nothing in `rest_get_table.py` sets it per session, so the value
    is pure infrastructure configuration with no code guarding it. That was
    tolerable while a coordinate read was one run (~55 KB); req #3166's batch
    raises a single response to ~1.8 MB, roughly 33x. If someone resets the
    parameter group, this test fails instead of the map silently going blank.
    """
    with db_connection.cursor() as cur:
        cur.execute("SELECT @@SESSION.group_concat_max_len AS n")
        limit = cur.fetchone()['n']

    # COORD_ROW_BUDGET (20,000) x the 92 bytes/row measured on production.
    assert limit >= 20_000 * 92, (
        f'group_concat_max_len={limit} cannot hold one batched coordinate read; '
        'a full batch would be silently truncated into invalid JSON'
    )


def test_single_run_read_still_works_unchanged(invoke, coord_runs):
    """RouteMapThumbnail / RouteDetailView still read one run at a time.

    The batched path is additive; the per-run URI shape it did NOT replace has
    to keep working, including the `seq:asc` sort the composite index now serves
    without a filesort.
    """
    run_id = coord_runs[0]
    response, body = _get(invoke, {
        'map_run_fk': str(run_id),
        'fields': 'latitude,longitude,altitude',
        'sort': 'seq:asc',
    })

    assert response['statusCode'] == 200
    assert len(body) == _RUN_COORD_COUNTS[0]
    # The per-run projection carries NO map_run_fk — the batched client strips it
    # before writing into the same cache entries, and these two shapes have to
    # match for that sharing to be correct.
    assert all('map_run_fk' not in row for row in body)
