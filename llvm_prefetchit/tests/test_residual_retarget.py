"""Retargeting must trade observed coverage, not just chase raw frequency."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
from residual_retarget import plan

def test_redundant_slot_reuse_without_instruction_growth():
    rows=[dict(target=64,line=1,sites=[10,20]) for _ in range(20)]
    rows += [dict(target=128,line=2,sites=[10,20]) for _ in range(12)]
    result=plan(rows,{10:64,20:64},max_fraction=.5,min_gain=8)
    assert len(result['changes'])==1 and result['changes'][0]['target']==128
    assert result['initial_covered']==20 and result['final_covered']==32

def test_lost_existing_coverage_is_charged():
    rows=[dict(target=64,line=1,sites=[10]) for _ in range(20)]
    rows += [dict(target=128,line=2,sites=[10]) for _ in range(24)]
    result=plan(rows,{10:64},max_fraction=1,min_gain=8)
    assert result['changes']==[] and result['final_covered']==20

def test_no_eligible_lbr_sites_does_not_invent_a_target():
    rows=[dict(target=128,line=2,sites=[]) for _ in range(30)]
    result=plan(rows,{10:64},max_fraction=1,min_gain=8)
    assert result['changes']==[] and result['samples']==30
