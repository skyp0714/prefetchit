from pathlib import Path
import gzip, hashlib, json, math
r=Path('/storage/prefetchit/class_b_coverage_20260928')
read=lambda p:json.loads(p.read_text())
old=Path('/storage/prefetchit/class_b_lean_20260928/v5_build.json')
snapshot=r/'v5_reference_build.json'
if not snapshot.exists():snapshot.write_bytes(old.read_bytes())
assert snapshot.read_bytes()==old.read_bytes()
files=dict(v5=snapshot,v6=r/'coverage_callees_build.json',
           v7=r/'coverage_indirect_build.json',v8=r/'coverage_indirect_lift_build.json')
with gzip.open(r/'indirect_profile/aggregates.json.gz','rt') as f:population=json.load(f)
expected=read(r/'coverage_progression.json')['rows'];checks=[]
for row in expected:
    profile=population[row['service']]
    names=set(read(files[row['policy']])['targets'][row['service']]['target_names'])
    lines={s['start']//64 for s in profile['symbol_ranges'] if names.intersection(s['names'])}
    ips=profile['phases']['heldout']['main_ips'];total=sum(x['samples'] for x in ips)
    targeted=sum(x['samples'] for x in ips if int(x['va'],16)//64 in lines)
    assert total==row['total_main_samples'] and targeted==row['target_line_samples']
    assert len(names)==row['target_function_names']
    assert math.isclose(100*targeted/total,row['coverage_pct'],abs_tol=1e-10)
    checks.append(dict(policy=row['policy'],service=row['service'],verified=True))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
inputs=[*files.values(),r/'indirect_profile/aggregates.json.gz',r/'coverage_progression.json']
out=dict(checks=checks,source_sha256=sha(Path(__file__)),
         inputs=[dict(path=str(p),sha256=sha(p)) for p in inputs],
         method='Replay static target-line overlap from audited target names and identical heldout original main-image IP counts. No binary disassembly or timing rerun.')
(r/'coverage_progression_verification.json').write_text(json.dumps(out,indent=2)+'\n')
print('Verified',len(checks),'static coverage rows from retained inputs.')
