import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
from temporal_path_trial import retain_windows


def test_windows_preserve_roi_boundaries_and_do_not_count_warmup(tmp_path):
    (tmp_path/'load').mkdir()
    samples=[(9.99,10),(19.98,20),(29.97,30),(39.96,40),(9,9.5),(40,40.1)]
    with gzip.open(tmp_path/'load/requests.json.gz','wt') as stream:json.dump(samples,stream)
    (tmp_path/'result.json').write_text(json.dumps(dict(pool=dict(start=10,end=40,completed=3))))
    retain_windows(tmp_path)
    result=json.loads((tmp_path/'endpoint_windows.json').read_text())
    assert result['valid']
    assert [row['completed'] for row in result['windows']]==[1,1,1]
    assert abs(sum(row['mean_ms'] for row in result['windows'])-60)<1e-8


def test_windows_avoid_a_nearly_empty_tail_from_clock_roundoff(tmp_path):
    (tmp_path/'load').mkdir()
    with gzip.open(tmp_path/'load/requests.json.gz','wt') as stream:json.dump([(60,60.000001)],stream)
    (tmp_path/'result.json').write_text(json.dumps(dict(pool=dict(start=0,end=60.00001,completed=1))))
    retain_windows(tmp_path)
    rows=json.loads((tmp_path/'endpoint_windows.json').read_text())['windows']
    assert len(rows)==6 and rows[-1]['completed']==1
    assert all(9.99<row['seconds']<10.01 for row in rows)
