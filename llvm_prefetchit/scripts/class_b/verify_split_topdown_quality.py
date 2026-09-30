#!/usr/bin/env python3
"""Check that rejecting a PMU window leaves clean endpoint evidence intact."""
import argparse
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import dense_build as b
import mechanism_report
import split_topdown_report
from split_l1_continue import annotate


def verify(root):
    checks=[]
    for error,expected in [(0,True),(.019,True),(.027529,False)]:
        fractions={'retiring':.13,'bad-spec':.1,'fe-bound':.67+error,'be-bound':.1,'fetch-lat':.58,'mem-bound':.04}
        row={'counters':{'slots:u':1e6,**{'topdown-'+k+':u':v*1e6 for k,v in fractions.items()}}}
        raw=copy.deepcopy(row['counters']);annotate(row)
        assert row['counters']==raw and row['topdown_valid']==expected
        assert abs(row['topdown_closure_error_pct']-100*error)<1e-10
        checks.append(dict(case='closure_annotation',input_error=error,valid=expected,raw_preserved=True))
    source=root/'l1_screen';rows=json.loads((source/'screen/rows.json').read_text())[:4]
    assert len(rows)==4 and len({row['arm'] for row in rows})==4
    inputs={str(Path(row['output'])/'result.json'):b.sha(Path(row['output'])/'result.json') for row in rows}
    with tempfile.TemporaryDirectory(prefix='prefetchit-td-quality-') as temp:
        stage=Path(temp);screen=stage/'screen';screen.mkdir();fixtures=[]
        (screen/'protocol.json').write_bytes((source/'protocol.json').read_bytes())
        for row in rows:
            dest=stage/row['arm'];dest.mkdir()
            (dest/'result.json').write_bytes((Path(row['output'])/'result.json').read_bytes())
            fixtures.append(dict(row,output=str(dest)))
        b.save(screen/'rows.json',fixtures);b.save(screen/'complete.json',{});b.save(stage/'complete.json',{})
        original=mechanism_report.evaluate(screen,stage/'before.json')
        path=stage/'extra_it0/result.json';value=json.loads(path.read_text())
        value['pmu_extra']['topdown']['mongo_storage']['topdown_valid']=False
        value['pmu_extra']['topdown']['mongo_storage']['topdown_quality_error']='Validation fixture only'
        b.save(path,value)
        after=mechanism_report.evaluate(screen,stage/'after.json')
        assert original['e2e']==after['e2e'] and original['service_cpu']==after['service_cpu']
        assert after['trials']==4 and after['complete'] and len(after['invalid_pmu_windows'])==1
        metrics=after['absolute']['extra_it0']['pmu']
        assert 'topdown:sum:slots:u' not in metrics and 'topdown:mongo_storage:slots:u' not in metrics
        assert 'topdown:mongo_user:slots:u' in metrics
        for key,value in original['absolute']['extra_it0']['pmu'].items():
            if not key.startswith('topdown:'):assert metrics[key]==value
        with contextlib.redirect_stdout(io.StringIO()):split_topdown_report.report(stage)
        top=json.loads((stage/'topdown.json').read_text())
        assert len(top['invalid_topdown_records'])==2
        assert top['valid_trials']['mongo3']['extra_it0']==0
        assert 'extra_it0' not in top['absolute']['mongo3'] and 'extra_it0' in top['absolute']['pool_u']
        checks.append(dict(case='single_bad_service_window',clean_e2e_unchanged=True,service_cpu_unchanged=True,
            unrelated_pmu_unchanged=True,bad_service_and_aggregate_excluded=True,raw_input_files_unchanged=True))
    assert all(b.sha(path)==sha for path,sha in inputs.items())
    result=dict(valid=True,checks=checks,inputs=inputs,command=sys.argv,
        source_hashes={str(path):b.sha(path) for path in [Path(__file__),Path(mechanism_report.__file__),
            Path(split_topdown_report.__file__),Path(__file__).with_name('split_l1_continue.py')]})
    b.save(root/'topdown_quality_validation.json',result)
    print(json.dumps(dict(valid=True,checks=len(checks))))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);verify(parser.parse_args().root)
