from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
from lean_profile import attribute


def test_line_boundary_and_aliases_do_not_duplicate_sample_weight():
    ranges=[dict(start=32,end=96,names=['a','a_alias']),
            dict(start=96,end=128,names=['b'])]
    lines=[dict(dso='main',va='0x40',samples=10),
           dict(dso='main',va='0x100',samples=3),
           dict(dso='other',va='0x40',samples=20)]
    result=attribute(lines,ranges,'main')
    assert result['total_main_samples']==13
    assert result['unmapped_samples']==3
    assert result['ambiguous_line_samples']==10
    assert sum(x['score'] for x in result['ranked'])==pytest.approx(10)
    assert [x['score'] for x in result['ranked']]==[5,5]
