"""Selection should cover distinct misses without exceeding dispatch budgets."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
import callpath_prefetch as m


def test_budget_overlap_and_independent_coverage():
    rows=[dict(line=10,target=640,sites=[100,200]) for _ in range(10)]
    rows += [dict(line=11,target=704,sites=[100]) for _ in range(9)]
    rows += [dict(line=12,target=768,sites=[300]) for _ in range(8)]
    rows += [dict(line=13,target=832,sites=[]) for _ in range(4)]
    result=m.select(rows,max_sites=1,max_hints=2,per_site=2,min_gain=2,goal=1)
    assert result['sites']==1 and result['hints']==2 and result['covered']==19
    assert [r['site'] for r in result['choices']]==[100,100]
    heldout=[dict(line=10,target=640,sites=[200]),dict(line=11,target=704,sites=[100]),dict(line=11,target=704,sites=[])]
    assert m.coverage(heldout,result['choices'])==dict(samples=3,covered=1,eligible=2)
    smaller=m.select(rows,max_sites=8,max_hints=8,per_site=4,min_gain=2,goal=.3)
    assert smaller['hints']==1 and smaller['covered']==10


def test_empty_history_stays_in_goal_denominator_and_no_duplicate_targets():
    rows=[dict(line=1,target=64,sites=[100,200]) for _ in range(10)]
    rows += [dict(line=2,target=128,sites=[]) for _ in range(90)]
    result=m.select(rows,max_sites=2,max_hints=8,per_site=4,min_gain=1,goal=.5)
    assert result['samples']==100 and result['covered']==10 and result['hints']==1
