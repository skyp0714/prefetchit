"""Normal-path dominance, bounded LBR ages and coverage cost must stay distinct."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

DIRECTORY=Path(__file__).resolve().parents[1]/'scripts/class_b'
sys.path.insert(0,str(DIRECTORY))
SPEC=importlib.util.spec_from_file_location('temporal_analysis_test',DIRECTORY/'temporal_path_analysis.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)


def image(instructions):
    result=m.Image.__new__(m.Image)
    result.code=SimpleNamespace(instructions=instructions,get=lambda ip:instructions.get(ip,(0,'unknown','unknown')))
    result.functions={0x100:dict(name='f',ips=sorted(instructions))}
    result.function_for={ip:0x100 for ip in instructions};result.cfgs={}
    return result


def test_conditional_path_call_is_not_promoted_to_dominator():
    code={0x100:(5,'call 200 <g>','f'),0x105:(2,'test %eax,%eax','f'),
        0x107:(2,'jne 118 <f+0x18>','f'),0x109:(5,'call 200 <g>','f'),
        0x10e:(2,'jmp 11a <f+0x1a>','f'),0x118:(2,'nop','f'),0x11a:(1,'ret','f')}
    obj=image(code)
    assert obj.dominance(0x100,0x11a)=='same_function_normal_cfg_dominator'
    assert obj.dominance(0x109,0x11a)=='same_function_observed_path'
    code[0x10e]=(2,'jmp *%rax','f');obj=image(code)
    assert obj.dominance(0x100,0x11a)=='same_function_unresolved_cfg'


def test_sampled_call_itself_and_saturated_history_are_excluded():
    images={'a':SimpleNamespace(calls={10:{},20:{},30:{},40:{}})}
    row=dict(dso=0,ip=10,edges=[[0,10,0,15,'P',25,'CALL'],[0,20,0,25,'P',100,'CALL'],
        [0,30,0,35,'P',65535,'CALL'],[0,40,0,45,'P',100,'CALL']])
    assert m.observed_calls(row,['a'],images,64,8192)=={('a',30):100}


def test_cost_selection_accounts_for_cross_dso_issue_work():
    rows=[dict(target_sha='b',line=10,weight=1,sites={('a',1):dict(kind='cross',target=640,got=100,addend=0),
        ('b',2):dict(kind='local',target=640)}) for _ in range(8)]
    chosen=m.choose(rows,{('a',1):1,('b',2):1},{'a':.1,'b':.1},min_gain=2,goal=1)
    assert chosen['covered']==8 and chosen['hints']==1
    assert chosen['choices'][0]['site']==2


def test_opening_a_stub_refreshes_other_targets_before_choosing_new_sites():
    rows=[]
    for site,line,count in [(1,10,10),(1,11,8),(2,12,9)]:
        rows += [dict(target_sha='a',line=line,weight=1,
            sites={('a',site):dict(kind='local',target=64*line)}) for _ in range(count)]
    rates={('a',1):1,('a',2):1}
    chosen=m.choose(rows,rates,{'a':.1},min_gain=1,goal=1,max_hints=2,site_overhead=4)
    assert [c['site'] for c in chosen['choices']]==[1,1]
    assert chosen['sites']==1 and chosen['covered']==18
    ordinary=m.choose(rows,rates,{'a':.1},min_gain=1,goal=1,max_hints=2)
    assert [c['site'] for c in ordinary['choices']]==[1,2]
    complete=m.choose(rows,rates,{'a':.1},min_gain=1,goal=1,max_hints=9,site_overhead=4)
    assert complete['hints']==3 and complete['covered']==27
    capped=m.choose(rows,rates,{'a':.1},min_gain=1,goal=1,max_hints=2,
        site_overhead=4,site_caps={('a',1):1})
    assert [c['site'] for c in capped['choices']]==[1,2]
    assert capped['covered']==19


def test_retained_mongo_stub_is_already_open_for_cost_accounting():
    rows=[dict(target_sha='a',line=10,weight=1,sites={
        ('a',1):dict(kind='local',target=640),('a',2):dict(kind='local',target=640)}) for _ in range(8)]
    chosen=m.choose(rows,{('a',1):1,('a',2):1},{'a':.1},min_gain=1,goal=1,
        site_overhead=4,opened_sites={('a',2)})
    assert chosen['choices'][0]['site']==2 and chosen['hints']==1
