#!/usr/bin/env python3
"""Aggregate the independent precise-distribution sampling check."""
import gzip
import json
from pathlib import Path
import sys

import dense_build as b
from dense_cause_analysis import analyze_service
from dense_cause_report import sampling_summary
from e2e_lbr import remove_generated


def analyze(root):
    folder=root/'pdist_check';assert (folder/'complete.json').exists()
    result={'base':{}}
    for key in b.SERVICES:
        result['base'][key]=analyze_service(folder/key,kinds=('l2','l2_pdist','instructions_pdist'))
    with gzip.open(folder/'analysis.json.gz','wt') as output:json.dump(result,output,separators=(',',':'))
    b.save(root/'pdist_sample_summary.json',sampling_summary(result)['base'])
    quality=[]
    for path in folder.glob('*/*/record_types.json'):
        record=json.loads(path.read_text());assert not any(record.get(k,0) for k in ('LOST','LOST_SAMPLES','THROTTLE','UNTHROTTLE'))
        quality.append(dict(path=str(path),record_types=record))
    assert len(quality)==9
    b.save(root/'pdist_quality.json',dict(captures=quality,valid=True,source_sha256=b.sha(__file__)))
    remove_generated(list(folder.glob('*/*/samples.txt'))+list(folder.glob('*/dsos/*')),
        root/'pdist_analysis_cleanup.json','PDIR/PDist comparison fully aggregated; counts, source/IP/line/branch tables, hashes and capture quality retained')

if __name__=='__main__':analyze(Path(sys.argv[1]))
