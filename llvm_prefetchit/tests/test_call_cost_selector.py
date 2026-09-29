"""Selection must price dynamic issue and retain unique miss accounting."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
from call_cost_selector import select


def test_frequent_anchor_is_not_free_and_unseen_anchor_is_not_zero_cost():
    rows=[dict(line=10,target=640,sites=[100,200] if i<4 else [100]) for i in range(10)]
    out=select(rows,{100:100,200:1},floor=.5,max_sites=1,max_hints=1,min_gain=1,goal=1)
    assert out['choices'][0]['site']==200 and out['covered']==4
    # Missing frequency data must not turn a site into a zero-cost candidate.
    out=select(rows,{100:1},floor=100,max_sites=1,max_hints=1,min_gain=1,goal=1)
    assert out['choices'][0]['site']==100 and out['covered']==10


def test_overlap_weighting_and_site_budget():
    rows=[dict(line=10,target=640,sites=[100,200],miss_weight=.1) for _ in range(6)]
    rows += [dict(line=20,target=1280,sites=[200],miss_weight=1.) for _ in range(4)]
    out=select(rows,{100:1,200:2},floor=.1,max_sites=1,max_hints=2,min_gain=1,goal=1)
    assert [c['target'] for c in out['choices']]==[1280,640]
    assert out['sites']==1 and out['covered']==10
    assert abs(out['estimated_covered_misses_per_request']-4.6)<1e-9
    assert out['estimated_hint_executions_per_request']==4
    assert out['estimated_extra_jumps_per_request']==2
