"""Compact complete AsmDB evidence and remove obsolete generated analysis artifacts."""
from pathlib import Path
import csv,hashlib,json,os,shutil,statistics,tarfile
B=Path(__file__).resolve().parent;REPO=B.parents[2];R=Path('/storage/prefetchit/class_a_expansion_20260925/asmdb_trace');E=REPO/'llvm_prefetchit/migration/evidence/asmdb_trace_20260926'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def main():
 os.sched_setaffinity(0,{84,85});assert (R/'broad_completed.json').exists();E.mkdir(exist_ok=True)
 full=R.parent/'asmdb_trace_full';assert (full/'completed.json').exists()
 tables=[]
 stages=[(R,n,n) for n in ['screen','confirmation','broad_screen','broad_confirmation']]+[(full,n,'full_'+n) for n in ['screen','confirmation']]
 for root,name,label in stages:
  if not (root/name/'paired_summary.json').exists():continue
  x=json.loads((root/name/'paired_summary.json').read_text());rows=list(csv.DictReader((root/name/'runs.csv').open()));groups={a:[r for r in rows if r['arm']==a] for a in {r['arm'] for r in rows}}
  def change(a,ref,key):return 100*(statistics.mean(float(r[key]) for r in groups[a])/statistics.mean(float(r[key]) for r in groups[ref])-1)
  for r in x['results']:
   p=json.loads((root/(r['arm']+'_plan.json')).read_text());tables.append(dict(stage=label,**r,sites=len(p['sites']),hints=sum(len(s['targets']) for s in p['sites']),code_misses_change_pct=change(r['arm'],'base','l2_code_misses'),instructions_change_pct=change(r['arm'],'base','instructions'),static_vs_base=x['static_vs_base']))
  for f in ['paired_summary.json','runs.csv','manifest.json','platform_before.json','platform_restored.json','hwp_before.json','hwp_restored.json']:
   shutil.copyfile(root/name/f,E/(label+'_'+f))
  for kind in ['platform','hwp']:assert json.loads((root/name/(kind+'_before.json')).read_text())==json.loads((root/name/(kind+'_restored.json')).read_text())
 save(E/'comparison.json',tables)
 small=['protocol.json','broad_protocol.json','image.json','aux_audit.json','calibration.json','decode_summary.json','rewrite_test.json','history_tests.json','format_probe.json','completed.json','broad_completed.json','pre_timing_cleanup.json','screen_cleanup.json','broad_index_cleanup.json','broad_screen_cleanup.json','failed_fixture_cleanup.json','denominator_correction.json']
 for name in small:
  if (R/name).exists():shutil.copyfile(R/name,E/name)
  if (full/name).exists():shutil.copyfile(full/name,E/('full_'+name))
 for root,prefix in [(R,''),(full,'full_')]:
  for p in root.glob('*cleanup.json'):shutil.copyfile(p,E/(prefix+p.name))
 sources=sorted(B.glob('asmdb_*.py'))+sorted(B.glob('asmdb_*.cc'));records=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in sources];save(E/'source_records.json',records)
 # Compressed plans/patches keep exact replay information without enormous text diffs.
 with tarfile.open(E/'sources_plans_patches.tar.gz','w:gz') as tar:
  for p in sources:tar.add(p,arcname='source/'+p.name,recursive=False)
  for root in [R,full]:
   for pattern in ['*_plan.json','*.patches.json','*_joint_coverage.json','*_command.json','window*_stats.json','window*_cleanup.json']:
    for p in sorted(root.glob(pattern)):tar.add(p,arcname='records/'+root.name+'/'+p.name,recursive=False)
 save(E/'bundle_sha256.json',dict(path='sources_plans_patches.tar.gz',sha256=sha(E/'sources_plans_patches.tar.gz')))
 removed=[]
 for pattern in ['*_pairs.tsv','history_test*.bin','history_test_mapping.tsv','history_test_targets.txt']:
  for p in sorted(R.glob(pattern)):
   assert p.parent==R and not p.is_symlink();removed.append(dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p),reason='placement/evaluation complete; exact plans, statistics, sources and original PT preserved'));p.unlink()
 save(R/'final_analysis_cleanup.json',dict(removed=removed,bytes_removed=sum(r['bytes'] for r in removed),free=shutil.disk_usage(R).free));shutil.copyfile(R/'final_analysis_cleanup.json',E/'final_analysis_cleanup.json')
 decoder=full/'stream_decoder_v1'
 if decoder.exists():
  receipt=dict(path=str(decoder),bytes=decoder.stat().st_size,sha256=sha(decoder),reason='Original decoder process finished; revised pair aggregation validated and complete');decoder.unlink();save(full/'old_decoder_cleanup.json',receipt);save(E/'full_old_decoder_cleanup.json',receipt)
 def fmt(c):return f"{c['speedup_pct']:+.2f}% [{c['ci95_pct'][0]:+.2f}, {c['ci95_pct'][1]:+.2f}]"
 text='\n\n## 실제 결과\n\n아래 CI는 paired log-ratio 95% 구간이다. `screen`은 각3쌍 탐색이며 확정 이득으로 채택하지 않는다. `confirmation`이 있는 경우에만 새 입력 seed의7쌍 독립 확인 결과다.\n\n| 단계 / 정책 | 위치 / 힌트 | baseline 대비 | 해당 NOP 대비 | 기존 static 대비 | L2 code miss 변화 |\n|---|---:|---:|---:|---:|---:|\n'
 for r in tables:
  c=r['comparisons'];text+=f"| {r['stage']} / {r['arm']} | {r['sites']} / {r['hints']} | {fmt(c['base'])} | {fmt(c[r['arm']+'_nop'])} | {fmt(c['static'])} | {r['code_misses_change_pct']:+.2f}% |\n"
 text+='\n고정 작업당 L2 code miss 수를 비교했으며 MPKI 분모 증가를 miss 제거로 오인하지 않는다. 기존 static의 동시 대조 결과와 각 정책의 instructions 변화는 `migration/evidence/asmdb_trace_20260926/comparison.json`에 보존한다. 소스·정확한 계획·patch는 압축 bundle로 보존한다. 탈락 바이너리와 decoded trace/index 삭제 내역은 개별 cleanup 기록에 남겼다.\n'
 first=json.loads((R/'broad2048.patches.json').read_text());second=json.loads((R/'broad4096.patches.json').read_text())
 if first['prefetch_sha256']==second['prefetch_sha256']:text+='\n2,048/4,096 위치 상한은 모두 실제822개 위치로 수렴해 **byte-identical 정책**이 됐다. 두 arm의 반복은 보존하지만 서로 다른 두 방법의 성공/실패 사례로 세지 않는다.\n'
 doc=REPO/'docs/class_a_asmdb_trace_20260926.md';old=doc.read_text().replace('측정 진행 중이며 최종 이득 수치는 아직 판정하지 않았다.','계획한 trace 삽입 비교와 coverage 확장을 완료했다. 결과는 아래에 구분해 기록한다.');doc.write_text(old+text)
 (E/'STATUS.md').write_text('Completed FleetBench trace-based placement screens and predeclared follow-up. Read docs/class_a_asmdb_trace_20260926.md; screens are not confirmed gains. Exact selected plans and source are in the compressed bundle; original trace remains under /trace. Baseline and schema control artifacts are preserved.\n')
 if 'SUDO_UID' in os.environ:
  uid,gid=int(os.environ['SUDO_UID']),int(os.environ['SUDO_GID'])
  for p in [E,*E.rglob('*')]:os.chown(p,uid,gid,follow_symlinks=False)
 print(json.dumps(dict(evidence=str(E),comparisons=len(tables),removed_bytes=sum(r['bytes'] for r in removed))),flush=True)
if __name__=='__main__':main()
