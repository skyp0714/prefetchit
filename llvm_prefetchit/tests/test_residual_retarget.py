"""Retargeting must trade observed coverage, not just chase raw frequency."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/class_b'))
from residual_retarget import plan,lead_rows,thin_plan,thin_by_age

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

def test_protect_short_lead_coverage():
    old=[dict(target=64,line=1,sites=[10]) for _ in range(20)]
    old += [dict(target=128,line=2,sites=[10]) for _ in range(24)]
    future=[dict(row,sites=[] if row['line']==1 else [10]) for row in old]
    assert len(plan(future,{10:64},max_fraction=1,min_gain=8)['changes'])==1
    assert plan(future,{10:64},max_fraction=1,min_gain=8,protected_rows=old)['changes']==[]

def test_older_occurrence_survives_lead_filter():
    rows=[dict(target=128,line=2,sites=[10,20],ages=[(10,[0,256]),(20,[32])])]
    assert lead_rows(rows,128,512)[0]['sites']==[10]

def test_thinning_preserves_observed_coverage():
    rows=[dict(target=64,line=1,sites=[10,20]) for _ in range(20)]
    rows += [dict(target=128,line=2,sites=[30]) for _ in range(12)]
    result=thin_plan(rows,{10:64,20:64,30:128,40:256})
    assert result['keep']==[10,30] and result['drop']==[20,40]
    assert result['retained_covered']==result['original_covered']==32

def test_age_thinning_does_not_replace_early_with_late_coverage():
    rows=[dict(target=64,line=1,sites=[10,20],ages=[(10,[0]),(20,[512])]) for _ in range(20)]
    assert thin_plan(rows,{10:64,20:64})['keep']==[10]
    result=thin_by_age(rows,{10:64,20:64,30:128})
    assert result['keep']==[10,20] and result['drop']==[30]
    assert all(b['original_covered']==b['retained_covered'] for b in result['bands'])

def test_native_retarget_and_thin_metadata(tmp_path):
    import subprocess
    import dense_build as b
    from lean_plan import RECORD,SECTION,read_image
    from residual_retarget import patch,thin_patch
    source=tmp_path/'metadata.c'
    source.write_text(r'''
__attribute__((noinline)) int leaf(int x){volatile int v=x;return v*3;}
__attribute__((noinline)) int other(int x){volatile int v=x;return v*5;}
int main(void){__asm__ volatile(".globl hint_site\nhint_site:\nprefetcht1 leaf(%%rip)":::"memory");return leaf(2)+other(3)!=21;}
''')
    raw=tmp_path/'raw'
    subprocess.run(['gcc','-O2','-fno-pie','-no-pie',str(source),'-o',str(raw)],check=True)
    syms={p[2]:int(p[0],16) for line in subprocess.check_output(['nm','-n',str(raw)],text=True).splitlines() if len(p:=line.split())==3}
    meta=tmp_path/'meta';meta.write_bytes(RECORD.pack(syms['hint_site'],syms['leaf'],1,2,3,4,5,3))
    binary=tmp_path/'original'
    subprocess.run(['objcopy','--add-section',f'{SECTION}={meta}',str(raw),str(binary)],check=True)
    dest=tmp_path/'retarget'
    patch(binary,dest,[dict(site=syms['hint_site'],old_target=syms['leaf'],target=syms['other'])],b.sha(binary))
    assert read_image(dest)['records'][0]['target']==syms['other']
    thin=tmp_path/'thin';thin_patch(dest,thin,[syms['hint_site']],b.sha(dest))
    after=read_image(thin)
    assert not after['records'][0]['active'] and after['records'][0]['site']==0
    assert after['records'][0]['target']==syms['other']
    assert after['executable_bytes']==read_image(binary)['executable_bytes']
    for path in [binary,dest,thin]:subprocess.run([str(path)],check=True)
