"""Preserve compact evidence and a current report; never infer unfinished gains."""
from common import *
import tarfile,math,statistics

def secondary_metrics(rows):
 out={};blocks=sorted({r['block'] for r in rows})
 for arm in sorted({r['arm'] for r in rows if r['arm']!='base' and not r['arm'].endswith('_nop')}):
  out[arm]={}
  for control in ['base',arm+'_nop']:
   values={}
   for metric in ['user_us_per_request','user_cycles_per_request','code_misses_per_request','mpki','whole_stack_cpu_us_per_request','p99_ms']:
    logs=[]
    for block in blocks:
     pair={r['arm']:r for r in rows if r['block']==block}
     if arm in pair and control in pair and pair[arm]['valid'] and pair[control]['valid'] and isinstance(pair[arm].get(metric),(float,int)) and isinstance(pair[control].get(metric),(float,int)) and pair[arm][metric]>0 and pair[control][metric]>0:logs.append(math.log(pair[control][metric]/pair[arm][metric]))
    if logs:values[metric]=dict(valid_pairs=len(logs),geometric_reduction_pct=100*(1-math.exp(-statistics.mean(logs))),role='Secondary descriptive metric, not an additional independently confirmed endpoint')
   out[arm][control]=values
 return out

def main():
 out=EVIDENCE;out.mkdir(parents=True,exist_ok=True)
 report={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'families':{},'metric':'Target cgroup user+kernel CPU per exactly completed external request, fixed arrival rate; not maximum throughput','warmup_policy':json.loads((B/'warmup_protocol_amendment.json').read_text())};measurements=[]
 report['sampling_policy']={'media_sample_rate':os.environ.get('CLASS_B_MEDIA_SAMPLE_RATE','upstream const1'),'social_sample_rate':os.environ.get('CLASS_B_SOCIAL_SAMPLE_RATE','.1')}
 report['confirmation_policy']=json.loads((B/'confirmation_policy.json').read_text())
 lines=['# Class B 확장 결과','', 'MovieId의 trace 기반 wake-stream을 다른 서비스에 적용한 결과다. Media와 SocialNetwork는 서로 다른 두 애플리케이션이며, 같은 애플리케이션 내 서비스 수를 독립 workload 성공 수로 세지 않는다. 표의 주 지표는 고정 요청률에서 타깃 서비스의 user+kernel CPU/완료 요청 절감률이다. 애플리케이션 전체의 최대 처리량 증가율은 측정하지 않았다.','', '| 애플리케이션 / 서비스 | 정상 RPS | 단독→공유 L2 code MPKI | 비교 결과 |','|---|---:|---:|---|']
 media_rate=f"{100*float(os.environ['CLASS_B_MEDIA_SAMPLE_RATE']):g}%" if 'CLASS_B_MEDIA_SAMPLE_RATE' in os.environ else '100% (upstream const1)'
 social_rate=f"{100*float(os.environ.get('CLASS_B_SOCIAL_SAMPLE_RATE','.1')):g}%"
 lines[3:3]=['','Tracing 조건: Media native/nginx '+media_rate+'; SocialNetwork native/nginx '+social_rate+'. 100% Media 결과와 10%에서 새로 학습한 결과는 별도로 보고한다.']
 if REPORT_SUFFIX=='_sampling10':lines[5:5]=['','주의: 10% Media는 같은 선별 규칙으로 선택된300RPS이며, 기존100% 캠페인의600RPS와 다르다. 두 캠페인의 개선 폭 차이를 tracing 비율만의 인과 효과로 해석하지 않는다.']
 for family in os.environ.get('CLASS_B_FAMILIES','media,social').split(','):
  q=S/('media_qualification_v2' if family=='media' else 'social_qualification')
  selected=q/'audited_selected.json';results=S/(family+'_results.json')
  entry={};report['families'][family]=entry
  if selected.exists():entry['selection']=json.loads(selected.read_text())
  if results.exists():entry['results']=json.loads(results.read_text())
  entry['secondary_metrics']={}
  for path in (S/(family+'_evaluation')).glob('*/*/rows.json'):
   entry['secondary_metrics'][str(path.parent.relative_to(S/(family+'_evaluation')))]=secondary_metrics(json.loads(path.read_text()))
  for key in entry.get('selection',{}):
   screen=S/(family+'_evaluation')/key/'screen'
   if key not in entry.get('results',{}) and (screen/'rows.json').exists() and len(json.loads((screen/'rows.json').read_text()))==len(json.loads((screen/'protocol.json').read_text())['arms'])*3:
    entry.setdefault('results',{})[key]=dict(screen=json.loads((screen/'paired_summary.json').read_text()),state='screen_complete_confirmation_pending')
  for key,sel in entry.get('selection',{}).items():
   if 'rate' not in sel:lines.append(f'| {family} / {key} | — | — | 정상 조건의 interleaving 증가 기준 미충족 |');continue
   result=entry.get('results',{}).get(key);status='삽입·비교 진행 중'
   if result:
    candidates=result.get('confirmation',result['screen']);parts=[]
    for candidate in candidates:
     values=[]
     for control in ['base',candidate['arm']+'_nop']:
      c=candidate['comparisons'][control]
      if 'cpu_cost_reduction_pct' not in c:values.append(f'{control}: 유효 쌍 {c["pairs"]}개');continue
      lo,hi=c['ci95_pct'];values.append(f'{control} 대비 {c["cpu_cost_reduction_pct"]:+.2f}% [{lo:+.2f}, {hi:+.2f}] (n={c["pairs"]})')
     parts.append(candidate['arm']+': '+', '.join(values))
    status=('탐색 완료·독립 확인 중. ' if result.get('state')=='screen_complete_confirmation_pending' else '독립 확인 채택 기준 통과. ' if result.get('confirmed_gain') else '독립 확인 채택 기준 미충족. ' if 'confirmation' in result else '탐색 채택 기준 미충족·독립 확인 미수행. ')+'; '.join(parts)
   lines.append(f'| {family} / {key} | {sel["rate"]} | {sel["alone_mpki"]:.2f} → {sel["mpki"]:.2f} | {status} |')
  for path in [q/'audited_summary.json',q/'audited_selected.json',q/'counter_format_audit.json',results,S/(family+'_completed.json')]:
   if path.exists():measurements.append(path)
  evaluations=S/(family+'_evaluation')
  if evaluations.exists():
   for path in evaluations.rglob('*.json'):
    # Compact measured outcomes, operating settings, exact commands and cleanup receipts.
    if path.name not in ['rows.json','paired_summary.json','protocol.json','summary.json','result.json','load.json','dataset_validation.json','binary_hashes.json','harness_hashes.json','cleanup.json','volume_cleanup.json','measurement_policy.json','tracing_configuration.json']:continue
    measurements.append(path)
 lines+=['','CPU 절감률은 paired log ratio와 개별95% t 신뢰구간으로 계산했다. 탐색3쌍과 독립 확인7쌍을 합치지 않으며, 여러 후보 전체에 대한 다중비교 보정은 적용하지 않았다. NOP는 삽입 명령을 동일 길이로 치환한다.','', '8코어 공유, 고정2GHz, C6 off, 완전한 서비스 스택 및 표준 입력을 사용했다. 매 arm은 새 프로세스·초기 데이터에서 시작한다. 첫50초 워밍업의 오류도 보존하고 보고하며, 그 이후 오류·drop은0건을 요구한다. 초기 Media qualification에서 제외한 표본은 재분류하지 않았다.','', 'Intel PT의 run별 첫 접근 순서는 실제 miss oracle가 아니다. 이번 정책은 service object 진입 및 post-call 사이트에 삽입하며, dependency archive 내부까지 삽입했던 기존 MovieId 결과와 coverage가 다르다. 기존 MovieId +5.4%는 user cycles/request 기준이므로 여기의 전체 CPU/요청 절감률과 직접 비교하지 않는다.','', '방법·진행 기록: [class_b_extension_20260926.md](class_b_extension_20260926.md). 실패 바이너리·생성 DB·decoded trace는 결과·해시·소스·계획을 남기고 정리한다.']
 save(out/'results.json',report)
 lines+=['','원본·PF·NOP 타깃 모두 동일한 fat-static 재빌드 및 info 로그 설정을 사용했다. 수치는 이 링크 설정에서의 삽입 효과다.']
 lines+=['','독립 확인은 탐색과 동일한 워밍업50초 및 순수 CPU 측정30초를 사용하고, 이후 PMU 수집만 생략하여 부하를95초에 종료한다. 확인은7쌍을 그대로 유지하며, user cycles·miss·top-down은 탐색3회의 별도 PMU 구간에서 보고한다. 확인 단계의 PMU 값은 추정하거나 보간하지 않는다.']
 archive_measurements=out/'measurements.tar.gz';manifest=[]
 with tarfile.open(archive_measurements,'w:gz') as tf:
  for path in sorted(set(measurements)):
   name=str(path.relative_to(S));tf.add(path,arcname=name);manifest.append(dict(name=name,bytes=path.stat().st_size,sha256=sha(path)))
 with tarfile.open(archive_measurements,'r:gz') as tf:
  for entry in manifest:
   assert hashlib.sha256(tf.extractfile(entry['name']).read()).hexdigest()==entry['sha256']
 save(out/'measurements_manifest.json',dict(archive_sha256=sha(archive_measurements),archive_bytes=archive_measurements.stat().st_size,files=manifest))
 # Remove only this reporter's previous loose mirrors after verified archival.
 removed=[]
 for family in ['media','social']:
  for path in sorted((out/(family+'_evaluation')).rglob('*')):
   if path.is_file() and not path.is_symlink():removed.append(dict(path=str(path),bytes=path.stat().st_size));path.unlink()
  root=out/(family+'_evaluation')
  if root.exists():shutil.rmtree(root)
  for path in out.glob(family+'_*.json'):
   assert (S/path.name).exists() or path.name in [family+'_'+x for x in ['audited_summary.json','audited_selected.json','counter_format_audit.json',family+'_results.json',family+'_completed.json']]
   removed.append(dict(path=str(path),bytes=path.stat().st_size));path.unlink()
 if removed:save(out/'loose_mirror_cleanup.json',dict(removed=removed,bytes_removed=sum(x['bytes'] for x in removed),reason='Replaced by verified compact measurements archive; original results remain on storage'))
 RESULT_DOC.write_text('\n'.join(lines)+'\n')
 # Reproduction sources and plans are small; bulk executables/traces are excluded.
 archive=out/'reproduction.tar.gz'
 with tarfile.open(archive,'w:gz') as tf:
  for path in sorted(B.glob('*.py')):tf.add(path,arcname='drivers/'+path.name)
  for path in sorted(B.glob('*.json')):tf.add(path,arcname='drivers/'+path.name)
  for relative in ['flat_codegen/dsb_build/media/ws/ws_plan_pass.py','flat_codegen/dsb_build/build_service.sh','llvm_prefetchit/tools/make_nop_control_binary.py']:
   path=REPO/relative;tf.add(path,arcname='helpers/'+path.name)
  for family in ['media','social']:
   root=S/(family+'_build')
   if root.exists():
    for path in root.rglob('*'):
     if path.is_file() and not path.is_symlink() and (path.name.endswith('.plan.json') or path.name in ['source.json','cmake_flags.json','binary.json','nop.json','insertion_audit.json','instrumentable.txt','screen_cleanup.json','confirmation_cleanup.json']):tf.add(path,arcname=str(path.relative_to(S)))
  for key in ['compose','rating','composepost','usertimeline']:
   root=T/key
   if root.exists():
    for path in root.rglob('*'):
     if path.is_file() and not path.is_symlink() and (path.name.endswith('.tsv') or path.name in ['maps.txt','capture.json','trace_quality.json','decoder_errors.txt','run_paths.log','decode_cleanup.json','raw_decode_cleanup.json']):tf.add(path,arcname='trace_summary/'+str(path.relative_to(T)))
 save(out/'archive.json',dict(path=str(archive),bytes=archive.stat().st_size,sha256=sha(archive)))
 print(json.dumps(dict(report=str(out/'results.json'),document=str(RESULT_DOC))),flush=True)

if __name__=='__main__':main()
