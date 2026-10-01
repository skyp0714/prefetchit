#!/usr/bin/env python3
"""Resume frozen diagnostic conditions after an explicitly recorded validity failure."""
import argparse
import json
from pathlib import Path
import signal
import time

import dense_build as b
import fullset as h
import rpc_future_diagnostics as diagnostic


def resume(root):
    spec = json.loads((root / 'diagnostics_spec.json').read_text())
    out = Path(spec['out'])
    protocol = json.loads((out / 'protocol.json').read_text())
    hashes = protocol['source_hashes']
    assert all(b.sha(path) == digest for path, digest in hashes.items())
    assert not (out / 'complete.json').exists()
    failed = out / '01_no_dso'
    failure = json.loads((failed / 'failure.json').read_text())
    assert not (failed / 'result.json').exists()
    assert failure['error'] == 'AssertionError((18458621304.0, 18843501319.0))'
    record = dict(epoch=time.time(), status='invalid_diagnostic_attempt', original_path=str(failed),
        error=failure['error'], topdown_closure_error_pct=100 * (18843501319 / 18458621304 - 1),
        reason='Top-down group sum exceeded frozen 2% closure gate; exclude entire incomplete diagnostic attempt. '
               'Keep partial counters, commands, binary hashes and restoration/cleanup records. No endpoint exclusion.',
        replay=dict(block=1, arm='no_dso', seed=spec['seedbase'] + 1, reverse_pmu=True),
        unchanged_source_hashes=hashes, resumer_sha256=b.sha(__file__))
    rejected = out / 'rejected' / '01_no_dso_attempt0'
    rejected.mkdir(parents=True, exist_ok=False)
    moved = []
    for path in sorted(out.glob('01_no_dso*')):
        target = rejected / path.name
        path.rename(target)
        moved.append(dict(original=str(path), retained=str(target)))
    record['moved_local_records'] = moved
    b.save(root / 'diagnostic_validity_retry.json', record)
    for block, order in enumerate(spec['orders']):
        for name in order:
            dest = out / f'{block:02d}_{name}'
            result = dest / 'result.json'
            if result.exists():
                assert json.loads(result.read_text())['valid']
                continue
            assert not dest.exists(), dest
            assert all(b.sha(path) == digest for path, digest in hashes.items()), 'Frozen diagnostic sources changed'
            b.space(root)
            manifest = dest.with_suffix('.json')
            b.save(manifest, dict(spec['arms'][name], out=str(dest), seed=spec['seedbase'] + block,
                                 reverse_pmu=bool(block % 2)))
            h.platform(dest, ['python3', diagnostic.__file__, 'trial', manifest])
            assert json.loads(result.read_text())['valid']
            print(json.dumps(dict(stage='diagnostic_complete', block=block, arm=name)), flush=True)
    b.save(out / 'complete.json', dict(valid=True, trials=8, invalid_attempts=1,
                                     retry_record=str(root / 'diagnostic_validity_retry.json')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    signal.signal(signal.SIGTERM, lambda sig, frame: (_ for _ in ()).throw(KeyboardInterrupt(sig)))
    resume(parser.parse_args().root)
