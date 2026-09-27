"""Check schedule boundaries, migration and exposure normalization."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1]/'scripts/class_b/wake_miss_timeline.py'
SPEC = importlib.util.spec_from_file_location('wake_miss_timeline', SCRIPT)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def switch(time, cpu, prev, next_tid):
    return dict(event='sched:sched_switch', time=time, cpu=cpu, prev=prev, next=next_tid, state='S')


def sample(time, cpu, tid=7, period=257):
    return dict(event='fe_l2', time=time, cpu=cpu, tid=tid, period=period)


def test_migration_exposure_and_boundary_exclusion():
    events = [sample(0, 0), switch(1000, 0, 0, 7), sample(1500, 0),
              sample(2000, 0), switch(4000, 0, 7, 0),
              switch(8000, 1, 0, 7), sample(9000, 1), switch(18000, 1, 7, 0),
              switch(20000, 0, 0, 7), sample(20100, 0)]
    r = m.analyze(events, {7})
    assert r['quality']['complete_runs'] == 2
    assert r['quality']['complete_samples'] == 3
    assert r['quality']['unmatched_samples'] == 1
    assert r['quality']['right_censored_samples'] == 1
    assert r['migrated_pct'] == 100
    assert r['median_off_us'] == 4
    assert r['bins'][0]['samples'] == 1
    assert r['bins'][1]['samples'] == 2
    assert r['bins'][0]['exposure_us'] == 2
    assert sum(b['exposure_us'] for b in r['bins']) == 13
    assert r['bins'][-1]['cumulative_pct'] == 100


def test_reject_scheduler_discontinuity():
    with pytest.raises(ValueError, match='discontinuity'):
        m.analyze([switch(0, 0, 0, 7), switch(1000, 0, 99, 0)], {7})


def test_parse_ns_and_colons_in_comm():
    r = m.parse(['  worker 7/7 [032] 132159.123456789: 1 sched:sched_switch: worker:7 [120] R+ ==> kworker/32:1:88 [120] ffffffff',
                 '  worker 7/7 [032] 132159.123456788: 257 fe_l2: 123456'])
    assert r[0]['time'] == 132159123456788
    assert r[1]['next'] == 88
    assert r[1]['state'] == 'R+'


def test_reject_loss_and_unparsed_lines():
    for text in ('PERF_RECORD_LOST 17', 'unparsed output'):
        with pytest.raises(ValueError):
            m.parse([text])


def test_new_thread_lifetime_and_first_run_are_tracked():
    events = [dict(event='fork', tid=8, time=100, cpu=0),
              switch(1000, 0, 0, 8), sample(1500, 0, tid=8), switch(4000, 0, 8, 0),
              switch(8000, 1, 0, 8), sample(9000, 1, tid=8),
              dict(event='exit', tid=8, time=10000, cpu=1), switch(11000, 1, 8, 0),
              switch(12000, 0, 0, 8), switch(13000, 0, 8, 0)]
    r = m.analyze(events, {7})
    assert r['quality']['complete_runs'] == 2  # Reused non-target TID excluded.
    assert r['origins']['new_thread_first_run']['samples'] == 1
    assert r['origins']['resume']['samples'] == 1


def test_parse_fork_pid_filters_and_exit():
    r = m.parse(['  worker 7/7 [032] 132159.123456780: PERF_RECORD_FORK(7:8):(7:7)',
                 '  worker 7/8 [032] 132159.123456790: PERF_RECORD_EXIT(7:8):(1:1)',
                 '  other 9/9 [032] 132159.123456791: PERF_RECORD_FORK(9:10):(9:9)',
                 '  worker 7/8 [032] 132159.123456781: PERF_RECORD_COMM: worker:7/8'], 7)
    assert [x['event'] for x in r] == ['fork', 'exit']
    assert [x['tid'] for x in r] == [8, 8]


def test_dying_thread_unknown_header_tid_uses_scheduler_payload():
    r = m.parse(['  :-1 40563/-1 [033] 132803.444292837: 1 sched:sched_switch: RatingService:287950 [120] X ==> swapper/33:0 [120] ffffffff'])
    assert r[0]['tid'] == -1
    assert r[0]['prev'] == 287950


def test_missing_sample_tid_requires_exact_target_cpu_interval():
    unknown = dict(event='fe_l2', time=1500, cpu=0, pid=7, tid=-1, period=257)
    events = [switch(1000, 0, 0, 7), unknown, switch(3000, 0, 7, 0),
              dict(unknown, time=4000)]
    r = m.analyze(events, {7}, target_pid=7)
    assert r['quality']['target_samples'] == 2
    assert r['quality']['unknown_tid_resolved_by_cpu_interval'] == 1
    assert r['quality']['unmatched_samples'] == 1
    assert r['quality']['complete_samples'] == 1
    assert sum(b['known_tid_samples'] for b in r['bins']) == 0


def test_exact_duplicate_switch_is_audited_without_dropping_real_intervals():
    events = [switch(1000, 0, 0, 7), switch(1000, 0, 0, 7), sample(1500, 0),
              switch(3000, 0, 7, 0)]
    r = m.analyze(events, {7})
    assert r['quality']['duplicate_scheduler_records'] == 1
    assert r['quality']['complete_runs'] == 1
    assert r['quality']['complete_samples'] == 1
    assert len(r['duplicate_scheduler_examples']) == 1
