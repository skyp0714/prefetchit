"""Exit-only empty perf records must not hide missing or multiplexed intervals."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/static'))
from perf_intervals import read_intervals

def test_empty_exit_footer(tmp_path):
    p=tmp_path/'perf.csv';p.write_text('1,100,,instructions:u,1000000,100.00,,\n1,10,msec,task-clock,1000000,100.00,,\n1.02,<not counted>,,instructions:u,0,100.00,,\n1.02,<not counted>,msec,task-clock,0,100.00,,\n')
    counts,meta=read_intervals(p)
    assert counts=={'instructions:u':100,'task-clock':10}
    assert meta['empty_exit_footer'][0]['events']==2 and meta['numeric_records']==2

@pytest.mark.parametrize('text',[
 '1,<not counted>,,instructions:u,0,100,,\n2,100,,instructions:u,1000000,100,,\n',
 '1,100,,instructions:u,1000000,100,,\n2,<not counted>,,instructions:u,1,100,,\n',
 '1,100,,instructions:u,1000000,99.5,,\n',
 '1,100,,instructions:u,1000000,100,,\n2,4,msec,task-clock,1000000,100,,\n2,<not counted>,,instructions:u,0,100,,\n'])
def test_invalid_interval_rejected(tmp_path,text):
    p=tmp_path/'perf.csv';p.write_text(text)
    with pytest.raises(AssertionError):read_intervals(p)
