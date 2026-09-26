import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from static_prefetch_graph import descendants, code_lines


def test_exact_frontier_deduplicates_diamond_and_bounds_cycles():
    graph = {'a':['b','c'],'b':['d'],'c':['d'],'d':['a']}
    assert descendants(graph,'a',2,2) == ['d']
    assert descendants(graph,'a',1,3) == ['b','c','d','a']


def test_budget_covers_entries_before_later_lines():
    assert code_lines(['a','b','a'],{'a':200,'b':65},4,cap_to_size=True,
                      budget=3,order='round-robin') == [['a',0,0],['b',0,0],['a',64,0]]
