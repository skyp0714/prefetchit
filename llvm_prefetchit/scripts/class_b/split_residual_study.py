#!/usr/bin/env python3
"""Separate residual-miss diagnostics; never overlap clean E2E measurement."""
import argparse
import gzip
import json
from pathlib import Path
import signal
import backend_prefetch as capture
import balanced_backend
import dense_build as b
import fullset as h
from callpath_prefetch import residual_counts, residual_locations, fetch_spans
from dense_cause_analysis import Code
from e2e_lbr import remove_generated


def profile(spec):
    capture.start_client = balanced_backend.start_client
    capture.profile(spec)


def analyze(folder, binary):
    assert json.loads((folder/'complete.json').read_text())['valid']; b.space(folder)
    code = Code(binary); audit = json.loads(Path(str(binary)+'.json').read_text())
    assert b.sha(binary) == audit['sha256']
    hints = {row['va']:row['target'] for row in audit['hints']}
    assert all(code.raw_targets[s] == t for s,t in hints.items())
    records = {}
    for service in capture.BACKENDS:
        source = folder/service
        rows, quality = capture.observed_rows(source, code, hints, minimum=0)
        assert json.loads((source/'record_types.json').read_text())['SAMPLE'] == quality['all_samples'] > 100
        raw_counts, raw_nearest, raw_earliest = residual_counts(rows, hints)
        spans = fetch_spans(rows, hints, code)
        for row in rows:
            length = code.get(row['ip'])[0]; assert length
            if row['ip']//64 != (row['ip']+length-1)//64:
                row['sample_start_line'] = row['line']; row['line'] = (row['ip']+length)//64
                row['target'] = row['ip']+length
        dest = folder/(service+'_observations.json.gz')
        with gzip.open(dest,'wt') as stream: json.dump(rows,stream,separators=(',',':'))
        counts, nearest, earliest = residual_counts(rows,hints)
        requests = json.loads((source/'request_window.json').read_text())
        records[service] = dict(quality=quality, modeled_counts=counts,
            modeled_nearest_retired_age=nearest, modeled_earliest_retired_age=earliest,
            raw_start_line_counts=raw_counts, raw_nearest_retired_age=raw_nearest, raw_earliest_retired_age=raw_earliest,
            spans=spans, locations=residual_locations(rows,hints,code), request_window=requests,
            modeled_events_per_request={key:value*257/requests['completed_requests'] for key,value in counts.items()},
            observations_sha256=b.sha(dest), decoded_sha256=b.sha(source/'samples.txt'))
        b.save(folder/'analysis.json', dict(complete=len(records)==len(capture.BACKENDS),records=records,
            source_sha256=b.sha(__file__), binary_sha256=audit['sha256'],
            limitation='Post-selection diagnostic only, no E2E inference. Continuation-line correction is a model: PEBS does not identify which byte line missed. Missing hints can fall outside finite LBR history. Accumulated retired branch cycles do not measure prefetch issue-to-fetch lead. Matching old hints cannot distinguish ignored requests from eviction or lateness. Nearest branch type does not reveal BTB occupancy.'))
        remove_generated([source/'samples.txt'],source/'residual_cleanup.json',
            'Compact raw/modeled miss counts, request denominators, sparse observations, source and hashes retained; remove decoded trace immediately.')


def run(root):
    initial = json.loads((root/'prepared_complete.json').read_text())
    lead = json.loads((root/'lead512/prepared.json').read_text())
    base = initial['arms']['split75']
    out = root/'residual_diagnostics'; out.mkdir(exist_ok=False)
    b.save(out/'protocol.json', dict(source_sha256=b.sha(__file__),
        client_sha256=b.sha(Path(balanced_backend.__file__).with_name('balanced_load.py')),
        seed=89101, services=capture.BACKENDS,
        rule='Fresh full Media C4 with balanced persistent connections; 50s warmup then separate 8s PEBS/LBR windows for the two review MongoDBs. Training choices already frozen. Serial diagnostics only.'))
    for name,binary in [('split75',Path(base['mongo_binary'])),('lead512',Path(lead['binary']))]:
        folder = out/name; manifest = out/(name+'.json'); b.space(out)
        b.save(manifest,dict(out=str(folder),mongo_binary=str(binary),reference=str(binary),
            seed=89101,overrides=base['overrides'],capture_kind='miss'))
        h.platform(folder,['python3',Path(__file__),'profile',manifest])
        analyze(folder,binary)
    b.save(out/'complete.json',dict(valid=True,diagnostic_policies=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['profile','run']);parser.add_argument('path',type=Path)
    args=parser.parse_args()
    def interrupted(sig,frame): raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted)
    if args.action=='profile': profile(json.loads(args.path.read_text()))
    else: run(args.path)
