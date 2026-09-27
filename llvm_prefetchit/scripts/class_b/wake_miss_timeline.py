#!/usr/bin/env python3
"""Join timestamped PEBS retirement samples to complete sched_switch runs.

This estimates a distribution of FRONTEND_RETIRED.L2_MISS events; it does not
count speculative L2 requests or measure the instant of an instruction fetch.
One recorder uses the default perf clock, preserving PEBS hardware timestamps
on the native stable-TSC clock path (Linux 6.8 setup_pebs_time).
"""
import argparse
from bisect import bisect_right
from collections import Counter
import json
from pathlib import Path
import re
import statistics

EDGES_US = [0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000]
LINE = re.compile(r'^\s*(.*?)\s+(-?\d+)/(-?\d+)\s+\[(\d+)\]\s+(\d+)\.(\d{9}):\s+(\d+)\s+(\S+):\s+(.*)$')
SWITCH = re.compile(r'.*:(\d+) \[\d+\] (\S+) ==> .*:(\d+) \[\d+\]')
TASK = re.compile(r'^.*?\[(\d+)\]\s+(\d+)\.(\d{9}): PERF_RECORD_(FORK|EXIT)\((\d+):(\d+)\):\((\d+):(\d+)\)')


def parse(lines, target_pid=None):
    events = []
    for line in lines:
        if not line.strip() or line.startswith('#'):
            continue
        if re.search(r'PERF_RECORD_(LOST|LOST_SAMPLES|THROTTLE|UNTHROTTLE)', line):
            raise ValueError('lost or throttled records: '+line[:200])
        task = TASK.match(line)
        if task:
            cpu, sec, ns, kind, pid, tid, _, _ = task.groups()
            if target_pid is not None and int(pid) == target_pid:
                events.append(dict(event=kind.lower(), tid=int(tid), cpu=int(cpu),
                                   time=int(sec)*10**9+int(ns)))
            continue
        if 'PERF_RECORD_COMM' in line:
            continue
        match = LINE.match(line)
        if not match:
            raise ValueError('unparsed perf record: '+line[:200])
        comm, pid, tid, cpu, sec, ns, period, event, tail = match.groups()
        row = dict(comm=comm.strip(), pid=int(pid), tid=int(tid), cpu=int(cpu),
                   time=int(sec)*10**9+int(ns), period=int(period), event=event)
        if event == 'sched:sched_switch':
            switch = SWITCH.match(tail)
            if not switch:
                raise ValueError('invalid switch: '+line)
            prev, state, next_tid = switch.groups()
            row.update(prev=int(prev), state=state, next=int(next_tid))
        elif event == 'fe_l2':
            row['ip'] = int(tail.split()[0], 16)
        else:
            raise ValueError('unexpected event: '+event)
        events.append(row)
    order = {'fork':0, 'sched:sched_switch':1, 'fe_l2':2, 'exit':3}
    return sorted(events, key=lambda r: (r['time'], order[r['event']]))


def analyze(events, tids, target_pid=None, sample_callback=None):
    active, last_out, runs = {}, {}, []
    live, known, births, scheduled = set(tids), set(tids), {}, set()
    last_switch, duplicate_examples = {}, []
    quality = Counter()
    for event in events:
        cpu, timestamp = event['cpu'], event['time']
        if event['event'] == 'fork':
            tid = event['tid']
            live.add(tid); known.add(tid); births[tid] = timestamp
            last_out.pop(tid, None); scheduled.discard(tid)
            quality['new_threads' if timestamp else 'initial_threads'] += 1
            continue
        if event['event'] == 'exit':
            live.discard(event['tid'])
            quality['thread_exits'] += 1
            continue
        if event['event'] == 'sched:sched_switch':
            signature = (timestamp, event['prev'], event['next'], event['state'])
            if last_switch.get(cpu) == signature:
                quality['duplicate_scheduler_records'] += 1
                if len(duplicate_examples) < 20:
                    duplicate_examples.append(event)
                continue
            last_switch[cpu] = signature
            run = active.pop(cpu, None)
            if run is not None:
                if run['tid'] != event['prev']:
                    raise ValueError(f'scheduler discontinuity on CPU {cpu}: active={run["tid"]} since {run["start"]}, next switch={event}')
                run['end'] = timestamp
                run['out_state'] = event['state']
                assert run['end'] >= run['start']
                runs.append(run)
            if event['prev'] in live:
                last_out[event['prev']] = (timestamp, cpu, event['state'])
            if event['next'] in live:
                previous = last_out.get(event['next'])
                active[cpu] = dict(tid=event['next'], cpu=cpu, start=timestamp, samples=[],
                    off_ns=timestamp-previous[0] if previous else None,
                    migrated=cpu != previous[1] if previous else None,
                    previous_state=previous[2] if previous else None,
                    origin='resume' if previous else ('new_thread_first_run' if births.get(event['next'], 0) > 0 and event['next'] not in scheduled else 'boundary_or_initial'))
                scheduled.add(event['next'])
        elif event['tid'] in known or (target_pid is not None and event.get('pid') == target_pid):
            quality['target_samples'] += 1
            run = active.get(cpu)
            resolved = event['tid'] == -1 and event.get('pid') == target_pid
            if resolved:
                quality['unknown_tid_samples'] += 1
            if run is None or (run['tid'] != event['tid'] and not resolved):
                quality['unmatched_samples'] += 1
            else:
                quality['unknown_tid_resolved_by_cpu_interval'] += int(resolved)
                run['samples'].append((timestamp, event['period'], resolved, event.get('ip')))
        else:
            quality['foreign_samples'] += 1
    quality['right_censored_runs'] = len(active)
    quality['right_censored_samples'] = sum(len(r['samples']) for r in active.values())
    quality['complete_runs'] = len(runs)
    if not runs:
        raise ValueError('no complete target scheduling intervals')
    bins = [dict(lo_us=lo, hi_us=EDGES_US[i+1] if i+1<len(EDGES_US) else None,
                 samples=0, known_tid_samples=0, estimated_events=0, exposure_us=0., runs_reaching_bin=0)
            for i, lo in enumerate(EDGES_US)]
    per_origin = {}
    for run in runs:
        elapsed_us = (run['end']-run['start'])/1000
        thread = per_origin.setdefault(run['origin'], dict(runs=0, samples=0, estimated_events=0,
            bins=[dict(lo_us=b['lo_us'], hi_us=b['hi_us'], samples=0, estimated_events=0, exposure_us=0.) for b in bins]))
        thread['runs'] += 1
        for i, b in enumerate(bins):
            hi = b['hi_us'] if b['hi_us'] is not None else elapsed_us
            exposure = max(0., min(elapsed_us, hi)-b['lo_us'])
            b['exposure_us'] += exposure
            b['runs_reaching_bin'] += int(exposure > 0)
            thread['bins'][i]['exposure_us'] += exposure
        for timestamp, period, resolved, ip in run['samples']:
            age = (timestamp-run['start'])/1000
            assert 0 <= age < elapsed_us
            if sample_callback is not None:
                sample_callback(age, ip, period, run['origin'])
            index = bisect_right(EDGES_US, age)-1
            b = bins[index]
            b['samples'] += 1
            b['known_tid_samples'] += int(not resolved)
            b['estimated_events'] += period
            thread['samples'] += 1
            thread['estimated_events'] += period
            thread['bins'][index]['samples'] += 1
            thread['bins'][index]['estimated_events'] += period
    total = sum(b['estimated_events'] for b in bins)
    assert total > 0
    cumulative = 0
    for b in bins:
        cumulative += b['estimated_events']
        b.update(event_share_pct=100*b['estimated_events']/total,
                 cumulative_pct=100*cumulative/total,
                 estimated_events_per_1000_switchins=1000*b['estimated_events']/len(runs),
                 estimated_events_per_scheduled_us=b['estimated_events']/b['exposure_us'] if b['exposure_us'] else None)
    matched = sum(b['samples'] for b in bins)
    quality['complete_samples'] = matched
    quality['complete_sample_pct'] = 100*matched/quality['target_samples']
    durations = sorted((r['end']-r['start'])/1000 for r in runs)
    with_history = [r for r in runs if r['off_ns'] is not None]
    return dict(quality=dict(quality), duplicate_scheduler_examples=duplicate_examples,
                bins=bins, origins=per_origin,
                median_run_us=statistics.median(durations),
                p90_run_us=durations[int(.9*(len(durations)-1))],
                runs_with_prior_out=len(with_history),
                migrated_pct=100*sum(r['migrated'] for r in with_history)/len(with_history) if with_history else None,
                median_off_us=statistics.median(r['off_ns']/1000 for r in with_history) if with_history else None,
                event='FRONTEND_RETIRED.L2_MISS, user mode, PEBS precise_ip=2',
                origin='sched_switch selection of this next TID, before switch completes; includes kernel return time',
                estimator='Sum of fixed sample periods, assigned at sampled retirement; counters are not reset at switches. Estimates, not exact per-bin miss counts.',
                exposure='Scheduled wall time of complete target runs, includes kernel/interrupt time; not user instructions or user-only time',
                limitations='Boundary runs excluded. PEBS retirement time differs from fetch time. Diagnostic sampling perturbs execution; not a clean latency/throughput result.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('decoded', type=Path)
    parser.add_argument('--tids', required=True, help='Comma-separated host thread IDs')
    parser.add_argument('--pid', type=int, help='Target TGID: admit dynamically created threads from task records')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = analyze(parse(args.decoded.read_text().splitlines(), args.pid), set(map(int, args.tids.split(','))), args.pid)
    args.out.write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
