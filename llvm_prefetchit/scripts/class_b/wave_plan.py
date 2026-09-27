#!/usr/bin/env python3
"""Fit small periodic kernel batches to schedule-relative retired miss addresses.

This coarse process-wide policy observes only the selected next task at runtime.
It cannot predict its branch path; heldout address coverage is not fill accuracy.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import signal
import time

def mapped_images(pid):
    import fullset as h
    text = Path(f'/proc/{pid}/maps').read_text()
    images = {}
    for line in text.splitlines():
        f = line.split(None, 5)
        if len(f) < 6 or 'x' not in f[1] or 'w' in f[1] or not f[5].startswith('/'):
            continue
        low, high = (int(v, 16) for v in f[0].split('-'))
        path = f[5]
        if path not in images:
            binary = Path(f'/proc/{pid}/root')/path.lstrip('/')
            data = binary.read_bytes()
            images[path] = dict(sha256=h.c.sha(binary),
                segments=h.old.control.executable_segments(data), mappings=[])
        images[path]['mappings'].append([low, high, int(f[2], 16)])
    return images


def resolve_ip(ip, images):
    if ip is None: return None
    found = []
    for path, image in images.items():
        for low, high, offset in image['mappings']:
            if low <= ip < high:
                file_offset = offset+ip-low
                for off, va, size in image['segments']:
                    if off <= file_offset < off+size:
                        found.append((path, (va+file_offset-off) & ~63))
    if len(found) > 1: raise ValueError('ambiguous sampled instruction mapping')
    return found[0] if found else None


def fit(rows, interval_us, batch, stages):
    chosen = []; used = set()
    for stage in range(stages):
        issue_us = stage*interval_us
        # One microsecond of nominal lead; retirement is only a time proxy.
        scores = Counter()
        for r in rows:
            if issue_us+1 <= r['age_us'] < issue_us+interval_us+1:
                scores[(r['path'], r['va'])] += r['samples']
        candidates = sorted(scores, key=lambda k:(-scores[k], k))
        picked = [k for k in candidates if k not in used][:batch]
        if len(picked) < batch:
            break  # never fill a sparse future stage with unrelated hot lines
        for key in picked:
            chosen.append(dict(path=key[0], va=key[1], issue_us=issue_us,
                               training_samples=scores[key]))
            used.add(key)
    return chosen


def evaluate(chosen, rows):
    policy = {(r['path'], r['va']):r['issue_us'] for r in chosen}
    total = sum(r['samples'] for r in rows)
    any_age = early = 0
    for row in rows:
        issue = policy.get((row['path'], row['va']))
        if issue is not None:
            any_age += row['samples']
            early += row['samples'] * (issue+1 <= row['age_us'])
    return dict(mapped_samples=total, selected_address_samples=any_age,
                nominally_early_samples=early, address_coverage_pct=100*any_age/total,
                nominally_early_coverage_pct=100*early/total,
                limitation='Address/retirement-time association only; no proof of a cold fill, branch accuracy, actual timer arrival, or speedup')


def run(spec):
    import fullset as h
    from capture_miss_timeline import capture, decode_capture
    out = Path(spec['out']); out.mkdir(parents=True, exist_ok=False); h.c.space()
    h.c.save(out/'protocol.json', dict(**spec, purpose='Independent training and heldout windows; never timing evidence',
        classifier='Process identity and user-mode selected next task; no inferred syscall or future branch label',
        variants=[dict(interval_us=i, batch=b, stages=s) for i,b,s in ((2,4,16),(4,4,8),(4,8,8))]))
    stack = client = None
    try:
        stack = h.start(out, 'media', {}, 8)
        pid = stack.states['movie-id-service']['State']['Pid']
        images = mapped_images(pid); h.c.save(out/'images.json', images)
        client = h.load(out/'load', 'media', spec['rate'], spec['seed'], 100)
        time.sleep(50)
        for phase in ('train', 'heldout'):
            capture(out/phase, pid, 257)
            assert client.poll() is None
            time.sleep(2)
        rc = client.wait(timeout=100); client = None; stack.check()
        info = json.loads((out/'load/load.json').read_text())
        h.c.save(out/'load_validation.json', dict(valid=rc == 0, load=info))
        assert rc == 0 and not info['steady_errors'] and not info['steady_drops']
    finally:
        h.c.stop(client)
        if stack is not None: stack.close()
        h.old.compact(out)
    tables = {}
    for phase in ('train', 'heldout'):
        hist = Counter(); quality = Counter()
        def sample(age, ip, period, origin):
            key = resolve_ip(ip, images)
            quality['all_complete_samples'] += 1
            if key is None:
                quality['unmapped_samples'] += 1
            else:
                hist[(*key, int(age))] += 1
        def retain():
            rows = [dict(path=k[0], va=k[1], age_us=k[2], samples=n) for k,n in sorted(hist.items())]
            h.c.save(out/phase/'line_age_counts.json', dict(rows=rows, quality=dict(quality)))
            tables[phase] = rows
        decode_capture(out/phase, sample, retain)
        assert quality['unmapped_samples'] <= .01 * quality['all_complete_samples'], quality
    variants = {}
    for interval, batch, stages in ((2,4,16),(4,4,8),(4,8,8)):
        chosen = fit(tables['train'], interval, batch, stages)
        assert len(chosen) >= 4*batch
        name = f'wave{interval}us_b{batch}'
        plan = dict(profiles=[dict(syscall_nr=-1, targets=[dict(path=r['path'],
            sha256=images[r['path']]['sha256'], elf_va=hex(r['va'])) for r in chosen])])
        h.c.save(out/(name+'.json'), plan)
        variants[name] = dict(plan=str(out/(name+'.json')),
            options=dict(interval_ns=interval*1000, batch=batch, max_age_us=40),
            targets=chosen, training=evaluate(chosen,tables['train']),
            heldout=evaluate(chosen,tables['heldout']))
    h.c.save(out/'variants.json', variants)
    h.c.save(out/'complete.json', dict(variants=list(variants)))


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('manifest', type=Path); a=p.parse_args()
    def interrupt(signum, frame): raise KeyboardInterrupt(signum)
    signal.signal(signal.SIGTERM, interrupt)
    run(json.loads(a.manifest.read_text()))


if __name__ == '__main__': main()
