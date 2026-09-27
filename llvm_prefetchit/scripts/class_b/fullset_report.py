#!/usr/bin/env python3
"""Archive completed compact evidence and report comparable CPU-cost results."""
import json
from pathlib import Path
import statistics
import tarfile
import fullset as h
from fullset_study import summarize


def read(path):return json.loads(path.read_text())


def estimate(value):
    ci=value.get('ci95_pct')
    return f"{value['cost_reduction_pct']:+.2f}%"+(f" [{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else ' (n=1)')


def cpu_breakdown(family):
    rows=read(h.OUT/'confirmation'/family/'rows.json')
    fractions={key:[] for key in h.TARGETS[family]};parsed=[]
    for row in rows:
        result=read(Path(row['output'])/'result.json');metrics={}
        for key,service in result['services'].items():
            cost=service['cpu']
            metrics[key+'_user_cpu']=cost['user_us']/cost['completed']
            metrics[key+'_system_cpu']=cost['system_us']/cost['completed']
            if row['valid'] and row['arm']=='base':fractions[key].append(100*cost['user_us']/cost['cpu_us'])
        parsed.append(dict(row,metrics=metrics))
    return dict(baseline_user_fraction_pct={k:statistics.mean(v) for k,v in fractions.items()},
        summary=summarize(parsed,{'new':dict(controls=['base','reference','new_nop'])})['new'],
        interpretation='Post-hoc secondary decomposition of the same seven clean CPU windows after the MovieId metric question. User CPU time is not the old user-cycle PMU metric. No promotion rule changed.')


def histogram_window(before,after,name):
    counts=[b-a for a,b in zip(before[name],after[name])]
    limits=h.old.control.HISTOGRAM_UPPER_TSC
    total=sum(counts)
    def quantile(q):
        cumulative=0;low=0
        for count,high in zip(counts,limits):
            cumulative+=count
            if cumulative>=total*q:return [low,high]
            low=high
        return None
    return dict(samples=total,counts=counts,median_bin=quantile(.5) if total else None,
        at_least_256_ticks_pct=100*sum(counts[5:])/total if total else None)


def main():
    assert (h.OUT/'all_measurements_complete.json').exists()
    h.c.space()
    evidence=h.REPO/'llvm_prefetchit/migration/evidence/class_b_fullset_20260926'
    evidence.mkdir(parents=True,exist_ok=False)
    document=h.REPO/'docs/class_b_fullset_20260926.md'
    lines=['# Class B: five-service policy and selected-next-task emission study',
        '', '모든 절감률은 `(1 - candidate cost / control cost) × 100`이며, 양수가 개선이다. '
        '주 지표는 완료된 외부 요청당 user+kernel CPU 비용이다. 고정 RPS 결과를 throughput 향상이나 응답시간 개선으로 바꾸어 해석하지 않는다.',
        '', '## 운영점과 방법', '',
        '| Family | Shared cores | RPS | Baseline target L2 code MPKI |', '|---|---:|---:|---|']
    for family in h.TARGETS:
        choice=read(h.OUT/(family+'_selection.json'))
        selected=next(x for x in choice['rows'] if x['pool']==choice['pool'])['result']
        mpki=', '.join(f"{k}: {v['pmu']['mpki']:.2f}" for k,v in selected['services'].items())
        lines.append(f"| {family} | {choice['pool']} | {choice['rate']} | {mpki} |")
    lines += ['', '운영점은 후보 성능을 보기 전에 baseline의 가족 내 기하평균 MPKI로 선택했다. '
        'Media tracing 100%, Social tracing 10%를 각 가족 내 모든 arm에 동일하게 유지했다. '
        'CPU는 2 GHz와 C6 off로 측정하고 매 실행 뒤 기존 상태로 복원했다. '
        '공식 입력과 초기화 검증, 정상 RPS/오류/지연시간 gate를 통과한 결과만 비교했다.',
        '', '## 사용자 공간 새 정책: 7개 독립 seed block', '',
        '각 block은 새 전체 스택을 사용한다. Media 3개 또는 Social 2개를 동시에 교체한 bundle의 효과다. '
        '대괄호는 개별 95% paired-log t 신뢰구간이며 다중 비교 보정은 하지 않았다. '
        '개별 적용 screen과 마지막 PMU 1회는 이 신뢰구간에 합치지 않았다.', '',
        '| Service | New vs baseline | New vs retained reference | New vs layout NOP | Target promotion |',
        '|---|---:|---:|---:|---|']
    family_results={}
    for family,targets in h.TARGETS.items():
        completed=read(h.OUT/(family+'_stream_complete.json'));family_results[family]=completed
        summary=completed['summary']['new']
        for key in targets:
            values=[estimate(summary[control][key+'_cpu']) for control in ('base','reference','new_nop')]
            lines.append('| '+ ' | '.join([key,*values,'yes' if completed['promoted'][key] else 'no'])+' |')
    lines += ['', 'MovieId의 retained reference는 이전 p11a 빌드이므로 artifact 비교다. '
        '동일 소스에서 하나의 설정만 바꾼 비교로 해석하지 않는다. Rating의 이전 후보는 실패 후 삭제됐으므로 '
        'retained reference는 baseline이다. 새 정책과 NOP 쌍은 동일 코드 배치를 유지한다.', '',
        'MovieId의 과거 p11a **약 5.1% 절감**은 당시 wsm baseline 대비 **user cycles/요청** '
        '(1.054× 효율, 5회 중앙값)이다. 이번의 baseline 대비 수치는 새 빌드의 **user+kernel CPU/요청** '
        '7쌍 결과이며 분모와 baseline이 다르다. 이번 새 정책과 보존 p11a의 전체 CPU 비교는 위 '
        'retained-reference 열이다. 과거 5.1%와 이번 절감률을 합산하지 않는다. '
        '[기존 MovieId 결과](dsb_results_summary_20260926.md#movieid-별도-지표의-과거-결과).', '',
        '| Family | Whole-stack CPU vs baseline | Whole-pool CPU vs baseline |', '|---|---:|---:|']
    for family,completed in family_results.items():
        s=completed['summary']['new']['base']
        lines.append(f"| {family} | {estimate(s['stack_cpu'])} | {estimate(s['pool_cpu'])} |")
    breakdown={family:cpu_breakdown(family) for family in h.TARGETS}
    h.c.save(h.OUT/'user_cpu_breakdown.json',breakdown)
    lines += ['', '## 같은 7쌍의 user/kernel CPU 분해', '',
        'MovieId의 과거 약 5% 결과에 대한 질문 후 동일 CPU 측정 구간을 사후 분해했다. '
        '아래 user CPU는 cgroup의 사용자 CPU **시간/요청**이며 과거 PMU user **cycles/요청**과 '
        '구분한다. 승격 기준은 변경하지 않았고, 신뢰구간은 개별 95% 구간이다. '
        '사용자 영역의 절감이 커도 전체 CPU에서 그 영역이 차지하는 비율과 커널 비용 변화에 따라 '
        '전체 절감률은 작아질 수 있다.', '',
        '| Service | Baseline user CPU share | User CPU vs baseline | Kernel CPU vs baseline | User CPU vs retained artifact |',
        '|---|---:|---:|---:|---:|']
    for family,targets in h.TARGETS.items():
        b=breakdown[family]
        for key in targets:
            s=b['summary']
            lines.append(f"| {key} | {b['baseline_user_fraction_pct'][key]:.2f}% | {estimate(s['base'][key+'_user_cpu'])} | {estimate(s['base'][key+'_system_cpu'])} | {estimate(s['reference'][key+'_user_cpu'])} |")
    lines += ['', 'retained-artifact 열은 동일한 단일 설정만 바꾼 비교가 아니다. 특히 MovieId의 '
        'p11a는 다른 역사적 빌드다. 이 열의 큰 user CPU 절감을 정책 단독의 이득이나 '
        '전체 CPU 10% 목표 달성으로 해석하지 않는다.']
    lines += ['', '## 트레이스의 시간 분리 검증', '',
        '별도 시점의 검증 trace에서 다음 값을 계산했다. touch precision은 해당 전환 후 실제 실행된 '
        '코드 라인의 비율이며, cache miss 예측 정확도나 성공한 prefetch fill 비율이 아니다. '
        '처음에는 오류가 하나라도 있는 capture batch를 전부 기각했다. 반복 오류를 진단한 뒤 '
        '서비스·시간 구간마다 3개 캡처 중 첫 무손실 캡처를 우선 선택했다. Rating에서 모두 실패할 때만 '
        '하나의 비동기 Redis I/O 스레드에 국한된 overflow를 ELF 심벌로 확인하고 해당 오류 캡처에서 '
        '그 스레드 전체를 제외하는 예외도 구현했다. __fdelt_chk와 __fdelt_warn의 동일 주소 '
        '별칭을 검증하며 다른 오류는 계속 기각한다. 이 변경은 후보 성능 측정 전에 고정했다. '
        '아래 실제 선택 기록의 제외 목록이 비어 있으면 이 예외를 사용하지 않은 전체 스레드 캡처다. '
        '실제 성능 측정은 항상 I/O 스레드를 '
        '포함한 전체 프로세스/스택/풀을 그대로 집계한다. '
        '[Linux 6.8 PT documentation](https://github.com/torvalds/linux/blob/v6.8/tools/perf/Documentation/perf-intel-pt.txt).', '',
        '| Service | Policy | Matched / admitted validation runs | Touch precision | Admitted first-touch coverage |',
        '|---|---|---:|---:|---:|']
    for targets in h.TARGETS.values():
        for key in targets:
            for policy,budget in [('strict','32'),('wide','64')]:
                v=read(h.OUT/'plans'/key/policy/'training_report.json')['policies'][budget]['validation']
                precision=f"{100*v['touch_precision']:.2f}%" if v['touch_precision'] is not None else 'unavailable'
                lines.append(f"| {key} | {policy}/{budget} | {v['matched_runs']} / {v['runs']} | {precision} | {v['all_first_touch_coverage_pct']:.2f}% |")
    lines += ['', '| Service | Phase | Selected capture | Excluded TIDs |', '|---|---|---|---|']
    for family in h.TARGETS:
        selection=read(h.OUT/(family+'_trace_selection.json'))
        for row in read(Path(selection['out'])/'selected_captures.json')['outputs']:
            trace=Path(row['selected_trace'])
            lines.append(f"| {trace.parent.name} | {trace.name} | {Path(row['original_trace']).name} | {row['excluded_tids']} |")
    lines += ['', '## 커널 발행 방식', '',
        '`sched_switch`에서 next task를 선택한 뒤 발행한다. 앞단의 wakeup/enqueue로 이동하지 않았다. '
        '분할 arm은 일부를 여기서 발행하고 나머지를 실제 전환 뒤 `finish_task_switch.isra.0` entry에서 발행한다. '
        '총 발행 수는 64 이하이며, 간격은 4/16개의 NOP 명령으로 제한했다. '
        '`__switch_to`에는 probe를 넣지 않는다. '
        '[Linux x86 switch source](https://github.com/torvalds/linux/blob/v6.8/arch/x86/kernel/process_64.c), '
        '[kprobe restrictions](https://docs.kernel.org/6.8/trace/kprobes.html).',
        '', 'MovieId와 UserTimeline에서 13개 방식(8/16/32/64 budget, 간격/묶음, 전후 분할, '
        '동일 대상의 첫 실행 순서, T0 hint, 넓은 경로 coverage)을 탐색했다. '
        '각 NOP 모듈은 발행 함수의 프리패치 3개만 같은 길이 NOP로 바꾼 복사본이다. '
        '파일 크기·전체 byte diff를 확인했고 양쪽 모두 config mode 1을 사용했다. '
        '따라서 같은 분기, 주소 로드, 카운터, 간격과 completion probe 경로가 실행된다.', '',
        '| Service | Pattern | Target CPU vs same-path NOP | Pool CPU vs module off | Code misses vs NOP |',
        '|---|---|---:|---:|---:|']
    diagnostics={}
    for key in ('movie','usertimeline'):
        root=h.OUT/'kernel_emission'/key
        summary=read(root/'screen_summary.json')
        for arm,comparisons in summary.items():
            if arm.endswith('_nop'):continue
            nop=comparisons.get(arm+'_nop',{});off=comparisons.get('off',{})
            if key+'_cpu' not in nop or 'pool_cpu' not in off:continue
            miss=nop.get(key+'_code_misses_per_request')
            lines.append(f"| {key} | {arm} | {estimate(nop[key+'_cpu'])} | {estimate(off['pool_cpu'])} | {estimate(miss) if miss else 'unavailable'} |")
        d={}
        for row in read(root/'diagnostic/rows.json'):
            result=read(Path(row['output'])/'result.json')['windows']
            before,after=result['detail_before'],result['detail_after']
            d[row['arm']]={name:histogram_window(before,after,name) for name in ('pre','post','lead')}
        diagnostics[key]=d
    completed=read(h.OUT/'kernel_emission/complete.json')
    key=completed['selected']['service']
    lines += ['', '위 표는 방법당 1개 exploratory block이다. off는 스택 초기의 한 구간이고 '
        '뒤의 정책은 순차 실행되므로 off 대비 차이에 시간에 따른 workload 변화가 섞일 수 있다. '
        '인접한 NOP 쌍과 독립 확인을 함께 보며, 이 표만으로 hook 비용이나 최고 이득을 확정하지 않는다. '
        'MovieId의 첫 block은 마지막 PMU 전에 부하 시간이 끝나 통째로 제외했다. '
        '종료 시간 검사를 추가하고 여유 시간을 늘려 같은 seed/순서의 새 스택으로 반복했다. '
        '제외한 block의 compact 측정과 사유도 보존했다. '
        '긴 탐색에서 NOP 비용도 구간에 따라 변하는 것을 확인해, 독립 확인 시작 전에 후보 순위 규칙을 '
        '초기 off/NOP 중 작은 이득에서 인접 NOP 대비 이득으로 수정했다. 원래 순위·후보·진단과 '
        '`selection_amendment.json`을 보존했다. off 대비 순이득 요건은 독립 확인에서 그대로 적용한다. '
        '선택 후 별도의 7개 새 baseline 프로세스에서 off/NOP/candidate 순서를 교대했다. '
        '각 arm은 10초 안정화, 30초 CPU 측정을 사용했고 PMU/진단은 이 구간에 실행하지 않았다.', '',
        f"확정 후보: **{key} / {completed['selected']['name']}**. 커널 승격: **{completed['promoted']}**.", '',
        '| Metric | vs module off | vs same-path NOP |', '|---|---:|---:|']
    summary=completed['summary']['candidate']
    for metric in (key+'_cpu','stack_cpu','pool_cpu'):
        lines.append(f"| {metric} | {estimate(summary['off'][metric])} | {estimate(summary['nop'][metric])} |")
    lines += ['', '커널 승격은 타깃 CPU가 off와 NOP 대비 모두 개선되고, 풀 CPU도 off 대비 '
        '개선된다는 95% 하한이 양수일 때만 인정한다. 타깃 비용만 낮아져도 outgoing task나 '
        '다른 서비스에 발행 비용이 전가될 수 있어 풀 비용을 함께 본다.', '',
        '이번 구현은 실행 중인 커널에 모듈과 probe를 추가한 것이다. 커널 이미지를 직접 '
        '패치해 재부팅한 결과는 아니므로 직접 삽입 시 줄어들 수 있는 hook 비용까지 배제하지 않는다.', '',
        '## Cold/timeliness 진단', '',
        '진단은 64번 match마다 첫 발행 구간의 한 라인을 순환 샘플링한다. '
        'pre와 post는 다른 실행 구간이므로 pre의 data load가 post 샘플을 데우지 않는다. '
        '아래 수치는 pinned physical alias의 **data 접근 지연과 전환 완료까지 시간**이다. '
        '실제 첫 명령어 fetch latency, L1I/ITLB 복구, 캐시 레벨 구분 또는 core cycle로 해석하지 않는다. '
        '진단 정책은 표에 명시하며, 원래 탐색 순위의 후보로 수행한 진단을 최종 확인 후보의 진단으로 바꾸어 부르지 않는다.', '',
        '| Service / diagnostic policy | Phase | Samples | Median TSC tick bin | >=256 ticks |', '|---|---|---:|---|---:|']
    for service,values in diagnostics.items():
        diagnostic_policy=read(h.OUT/'kernel_emission'/service/'selection.json')['best']['name']
        for arm,phase in [('d1_nop','pre'),('d2_nop','post'),('d2_t1','post'),('d2_t1','lead')]:
            record=values[arm][phase];fraction=record['at_least_256_ticks_pct']
            label=service+' / '+diagnostic_policy
            lines.append(f"| {label} | {arm}/{phase} | {record['samples']} | {record['median_bin']} | {fraction:.2f}% |" if fraction is not None else f"| {label} | {arm}/{phase} | 0 | unavailable | unavailable |")
    probe=read(h.OUT/'kernel_cache_probe/result.json')
    lines += ['', f"별도 flush/sleep 기능 검사의 평균 median TSC ticks: `{probe['mean_of_medians']}`. "
        '이 검사는 애플리케이션 성능 측정에서 제외했다.', '',
        '`L2_RQSTS.CODE_RD_MISS`는 speculative code-fetch miss 요청을 세고, 학습의 '
        '`FRONTEND_RETIRED.L2_MISS` PEBS는 retired instruction에 귀속된 이벤트를 샘플링한다. '
        '서로 같은 모집단이 아니므로 두 카운트로 직접 miss coverage를 계산하지 않는다. '
        '[Intel Granite Rapids event definitions](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).', '',
        '## 재현성과 보존', '',
        '원본 코드/입력은 보존했다. 오류가 난 트레이스, 실패·기각 후보의 결과와 source/명령/해시는 '
        '남기고 더 이상 쓰지 않는 raw/decoded trace, ELF 복사본, 실행 파일과 object는 즉시 정리했다. '
        '모든 플랫폼 복원과 제거 경로/바이트는 evidence에 기록했다.', '',
        '- [실행 드라이버](../llvm_prefetchit/scripts/class_b/README.md)',
        '- [공개 결과 요약](../llvm_prefetchit/migration/evidence/class_b_fullset_20260926/results.json)',
        '- [로컬 재현 아카이브 위치·해시](../llvm_prefetchit/migration/evidence/class_b_fullset_20260926/archive_reference.json)',
        '- [이전 DSB 결과](dsb_results_summary_20260926.md)', '']
    outcomes=[]
    for family,result in family_results.items():
        for service in h.TARGETS[family]:
            value=result['summary']['new']['base'][service+'_cpu']
            outcomes.append((service,value))
    target_met=[service for service,value in outcomes if value['ci95_pct'][0]>=10]
    kernel_value=completed['summary']['candidate']['off'][key+'_cpu']
    if completed['promoted'] and kernel_value['ci95_pct'][0]>=10:
        target_met.append('kernel '+key)
    headline=['', '## 확인 결과', '',
        '새 정책의 baseline 대비 타깃 CPU 절감: '+', '.join(f'{service} **{estimate(value)}**' for service,value in outcomes)+'.',
        '', f"커널 확인 후보 `{key}/{completed['selected']['name']}`의 off 대비 타깃 CPU 절감은 **{estimate(kernel_value)}**다. "
        f"타깃과 풀 비용을 함께 보는 승격 기준: **{'통과' if completed['promoted'] else '미통과'}**.",
        '', ('95% 하한까지 10%에 도달한 결과: '+', '.join(target_met)+'.') if target_met else
        '이번 확인 실험에서 95% 하한까지 10% 절감을 입증한 정책은 없다. 탐색 최고값이나 다른 지표의 과거 이득을 더해 목표 달성으로 보고하지 않는다.']
    lines[3:3]=headline
    h.c.save(h.OUT/'diagnostic_summary.json',diagnostics)
    document.write_text('\n'.join(lines))
    checks=[]
    for before in h.OUT.rglob('*_before.json'):
        if before.name not in ('platform_before.json','hwp_before.json'):continue
        after=before.with_name(before.name.replace('_before','_restored'))
        checks.append(dict(path=str(before),restored=after.exists() and read(before)==read(after)))
    assert checks and all(x['restored'] for x in checks)
    h.c.save(evidence/'platform_restoration.json',dict(all_restored=True,checks=len(checks),details=checks))
    files={}
    for root,prefix in [(h.OUT,'campaign'),(h.TRACE,'trace_summary')]:
        for p in root.rglob('*'):
            if not p.is_file() or p.is_symlink() or 'symfs' in p.parts:continue
            if p.name in ('branches.txt','syscall_context.txt','misses.txt','requests.json.gz'):continue
            if p.suffix not in ('.json','.csv','.log','.txt','.tsv','.err','.yaml','.yml','.conf','.c','.h','.py'):continue
            assert p.stat().st_size<5*2**20,p
            files[p]=prefix+'/'+str(p.relative_to(root))
    for family,targets in h.TARGETS.items():
        root=h.c.S/(family+'_build')
        for key in targets:
            for p in (root/key/'fullset_coverage').rglob('*'):
                if p.is_file() and not p.is_symlink() and p.suffix in ('.json','.log','.txt'):
                    files[p]='builds/'+family+'/'+str(p.relative_to(root))
        for name in ('source.json','cmake_flags.json','build_service.sh'):
            p=root/name
            if p.is_file():files[p]='builds/'+family+'/'+name
    # Publication follows the repository's compact-evidence convention. The
    # detailed reproduction archive, generated plans and run logs stay local.
    local=h.OUT/'evidence_archive';local.mkdir(exist_ok=False)
    archive=local/'campaign_results.tar.gz';manifest=[]
    with tarfile.open(archive,'w:gz') as tf:
        for p,name in sorted(files.items(),key=lambda x:x[1]):
            manifest.append(dict(path=str(p),archive_path=name,bytes=p.stat().st_size,sha256=h.c.sha(p)))
            tf.add(p,arcname=name,recursive=False)
    h.c.save(local/'archive_manifest.json',dict(files=manifest,archive_sha256=h.c.sha(archive),archive_bytes=archive.stat().st_size,
        excludes='Original inputs, executables, objects, build directories, raw/decoded PT and mapped ELF copies'))
    h.c.save(evidence/'archive_reference.json',dict(path=str(archive),sha256=h.c.sha(archive),bytes=archive.stat().st_size,
        members=len(manifest),manifest_path=str(local/'archive_manifest.json'),manifest_sha256=h.c.sha(local/'archive_manifest.json'),
        publication='Detailed local reproduction archive is not committed. Git contains curated summaries, protocols, hashes and exclusion reasons.'))
    h.c.save(evidence/'results.json',dict(families=family_results,kernel=completed,
        metric='user+kernel CPU per completed external request; positive is cost reduction',
        interval='Individual 95% paired-log t intervals, seven fresh seeded blocks; no multiplicity adjustment',
        deployment='Each family confirmation changes its target services simultaneously; effects are bundle-conditional, not additive or individually re-confirmed deployments'))
    h.c.save(evidence/'confirmation_rows.json',dict(
        **{family:read(h.OUT/'confirmation'/family/'rows.json') for family in h.TARGETS},
        kernel=read(h.OUT/'kernel_emission/confirmation_rows.json')))
    h.c.save(evidence/'protocols.json',{family:read(h.OUT/'confirmation'/family/'protocol.json') for family in h.TARGETS})
    h.c.save(evidence/'diagnostics.json',dict(application=diagnostics,synthetic=read(h.OUT/'kernel_cache_probe/result.json')))
    h.c.save(evidence/'user_cpu_breakdown.json',breakdown)
    h.c.save(evidence/'operating_points.json',{family:read(h.OUT/(family+'_selection.json')) for family in h.TARGETS})
    trace_summary={}
    for family,targets in h.TARGETS.items():
        selection=read(h.OUT/(family+'_trace_selection.json'))
        records=read(Path(selection['out'])/'selected_captures.json')
        for service in targets:
            trace_summary[service]=dict(
                captures=[v for v in records['outputs'] if Path(v['selected_trace']).parent.name==service],
                policies={policy:{budget:record['validation'] for budget,record in
                    read(h.OUT/'plans'/service/policy/'training_report.json')['policies'].items()} for policy in ('strict','wide')})
    h.c.save(evidence/'trace_validation.json',trace_summary)
    h.c.save(evidence/'kernel_screen.json',{service:read(h.OUT/'kernel_emission'/service/'screen_summary.json') for service in ('movie','usertimeline')})
    h.c.save(evidence/'selection_amendment.json',read(h.OUT/'kernel_emission/selection_amendment.json'))
    h.c.save(evidence/'builds.json',dict(candidates=read(h.OUT/'candidates.json'),module_nop_audit=read(h.OUT/'kernel_nop_audit.json')))
    h.c.save(evidence/'validation.json',dict(kernel_unit=(h.OUT/'kernel_unit_retry.log').read_text(),
        initial_unit_environment_failure=(h.OUT/'kernel_unit.log').read_text(),
        trace_admission_unit=(h.OUT/'trace_admission_unit.log').read_text(),
        original_module_runtime=json.loads((h.OUT/'kernel_smoke.log').read_text()),
        nop_module_runtime=json.loads((h.OUT/'kernel_nop_smoke.log').read_text())))
    exclusions={}
    for pattern in ('trace_rejection.json','attempt_exclusion.json','trace_admission_amendment.json'):
        for path in h.OUT.rglob(pattern):exclusions[str(path.relative_to(h.OUT))]=read(path)
    h.c.save(evidence/'exclusions.json',exclusions)
    import subprocess
    sources=[*Path(__file__).parent.glob('*.py'),*h.HARNESS.glob('*.py')]
    sources += [p for p in (h.REPO/'llvm_prefetchit/kernel/wake_prefetch').iterdir() if p.suffix in ('.c','.h','.py','.md') or p.name=='Makefile']
    sources += [h.REPO/'llvm_prefetchit/tests'/name for name in ('test_wake_kernel.py','test_wake_trace_admission.py')]
    h.c.save(evidence/'source_manifest.json',dict(git_head_before_result_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=h.REPO,text=True).strip(),
        files=[dict(path=str(p.relative_to(h.REPO)),sha256=h.c.sha(p)) for p in sorted(set(sources))]))
    print(json.dumps(dict(report=str(document),files=len(files),bytes=archive.stat().st_size)),flush=True)


if __name__=='__main__':main()
