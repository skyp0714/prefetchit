#!/usr/bin/env python3
"""Publish E2E confidence intervals, kernel wave timing, and compact evidence."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import tarfile

import fullset as h


def read(path): return json.loads(path.read_text())


def estimate(value):
    ci = value['ci95_pct']
    return f"{value['cost_reduction_pct']:+.2f}% [{ci[0]:+.2f}, {ci[1]:+.2f}]"


def figure(root, final, kernel):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(11.5,4.2),layout='constrained')
    for i,key in enumerate(('mean_ms','p99_ms')):
        r=final[key];value=r['cost_reduction_pct'];low,high=r['ci95_pct']
        axes[0].errorbar(value,i,xerr=[[value-low],[high-value]],fmt='o',capsize=5,color='#176b87')
    axes[0].axvline(0,color='#777',lw=1)
    axes[0].axvline(10,color='#b65c37',lw=1,ls='--',label='10% target')
    axes[0].set(yticks=[0,1],yticklabels=['Mean','p99'],xlabel='External request latency reduction (%)',
                title='LBR placement: 7 independent pairs')
    axes[0].legend(frameon=False)
    line_rows=read(root/'wave_training/train/line_age_counts.json')['rows']
    miss=[sum(r['samples'] for r in line_rows if r['age_us']==i) for i in range(40)]
    total=sum(r['samples'] for r in line_rows)
    axes[1].fill_between(range(40),[100*n/total for n in miss],step='mid',color='#999',alpha=.25,label='Baseline retired misses')
    for row in kernel['rows']:
        counts=row['waves']['age_2us_bins']
        # The last overflow bin is excluded from the drawn density, but is
        # retained in the denominator and in the machine-readable report.
        axes[1].step([2*i+1 for i in range(15)],[50*n/sum(counts) for n in counts[:15]],
                     where='mid',label=row['arm'])
    axes[1].axvspan(10,20,color='#e4b96a',alpha=.16)
    axes[1].set(xlim=(0,40),xlabel='Age after next-task selection (us)',ylabel='Within-series share per us (%)',
                title='MovieId: delayed emissions and sampled miss ages')
    axes[1].legend(fontsize=8,frameon=False)
    fig.suptitle('Media full stack, 1,000 offered RPS; positive reduction is better',fontsize=12)
    path=h.REPO/'docs/figures/class_b_e2e_distributed_20260927.png';path.parent.mkdir(exist_ok=True)
    fig.savefig(path,dpi=170);plt.close(fig)
    return path


def kernel_summary(root):
    rows = read(root/'kernel_screen/rows.json')
    controls = [r for r in rows if r['arm'].startswith('off')]
    index = {r['arm']:i for i,r in enumerate(rows)}
    by_name = {r['arm']:r for r in rows}
    output = []
    for row in rows:
        name = row['arm']
        if name.startswith('off') or name.endswith(('_nop','_burst')): continue
        i = index[name]
        low = max((r for r in controls if index[r['arm']] < i),key=lambda r:index[r['arm']])
        high = min((r for r in controls if index[r['arm']] > i),key=lambda r:index[r['arm']])
        frac = (i-index[low['arm']])/(index[high['arm']]-index[low['arm']])
        baseline = {k:math.exp((1-frac)*math.log(low['metrics'][k])+frac*math.log(high['metrics'][k]))
                    for k in ('mean_ms','p99_ms')}
        comparisons = {}
        for label, metrics in [('off_bracket',baseline),('timer_nop',by_name[name+'_nop']['metrics']),
                               ('same_targets_burst',by_name[name+'_burst']['metrics'])]:
            comparisons[label] = {k:100*(1-row['metrics'][k]/metrics[k]) for k in baseline}
        result = read(Path(row['output'])/'result.json')['windows']
        before,after = result['waves_before'],result['waves_after']
        counters = {k:after[k]-before[k] for k in ('callbacks','emitted','lines','cancelled','expired','wrong_task')}
        age = [a-b for a,b in zip(after['age_2us_bins'],before['age_2us_bins'])]
        total = sum(age)
        counters.update(age_2us_bins=age, delayed_emissions=total,
            emission_age_10_to_20us_pct=100*sum(age[5:10])/total,
            emission_age_20_to_30us_pct=100*sum(age[10:15])/total,
            emission_age_at_least_30us_pct=100*age[15]/total)
        output.append(dict(arm=name,valid=row['valid'],metrics=row['metrics'],
            interpolated_off=baseline,reduction_pct=comparisons,waves=counters))
    return dict(rows=output,interpretation='Exploratory single temporal sequence; no CI. Off comparator interpolates log latencies between bracketing off phases by phase index. NOP/burst are direct phase ratios; none is independent confirmation.')


def report(root):
    assert (root/'e2e_complete.json').exists()
    h.c.space()
    evidence = h.REPO/'llvm_prefetchit/migration/evidence/class_b_e2e_20260927'
    evidence.mkdir(parents=True,exist_ok=False)
    selection = read(root/'selection.json'); winner = selection['winner']
    decision = read(root/'placement_decision.json')
    rows = read(root/'confirmation_media/rows.json'); final = decision['metrics']
    assert len(rows) == 14 and all(r['valid'] for r in rows), 'report requires seven valid independent pairs'
    assert all(final[key]['pairs'] == 7 for key in ('mean_ms','p99_ms'))
    means = {arm:{k:statistics.mean(r['metrics'][k] for r in rows if r['arm']==arm)
                  for k in ('mean_ms','p50_ms','p95_ms','p99_ms')} for arm in ('base',winner)}
    baseline_results = [read(Path(r['output'])/'result.json') for r in rows if r['arm']=='base']
    cpu_share = {key:statistics.mean(100*r['services'][key]['cpu']['cpu_us_per_request']/
                    r['whole_stack_cpu_us_per_request'] for r in baseline_results)
                 for key in ('movie','compose','rating')}
    kernel = kernel_summary(root); h.c.save(root/'kernel_analysis.json',kernel)
    figure(root,final,kernel)
    lines = ['# Distributed prefetch: external request latency and timed kernel waves','',
        'Media 전체 스택에서 외부 HTTP 요청의 예정 도착→완료 평균·p99를 주 지표로 검증했다. '
        '양수 절감률이 개선이다. CPU/request 절감을 응답시간 또는 최대 throughput 향상으로 대체하지 않는다.','',
        '## 독립 확인 결과','',
        f'분기 이력 배치의 두 block screen에서 `{winner}`를 평균 지연시간으로 선택한 뒤, '
        '새 시드 7쌍과 새 스택으로 확인했다. MovieId·ComposeReview·Rating에 함께 적용한 bundle 결과다. '
        '원본과 동일한 주소·크기의 NOP 공간을 치환했으므로 baseline이 정확한 NOP 대조군이다. '
        '절대값은 실행별 지표의 산술평균, 절감률은 paired log-ratio와 개별 95% t 구간이다. '
        '두 endpoint의 다중 비교 보정은 하지 않았으며 screen은 신뢰구간에 합치지 않았다.','',
        '| External request metric | Baseline | Selected policy | Reduction, 95% CI |',
        '|---|---:|---:|---:|']
    for key in ('mean_ms','p50_ms','p95_ms','p99_ms'):
        lines.append(f'| {key} | {means["base"][key]:.4f} ms | {means[winner][key]:.4f} ms | {estimate(final[key])} |')
    if all(final[key]['ci95_pct'][0] < 10 for key in ('mean_ms','p99_ms')):
        lines += ['', '**평균·p99의 10% E2E 개선은 입증하지 못했다.** '
            '지연시간 CI가 0을 포함하는 endpoint는 개선이 확인된 것으로 표현하지 않는다.']
    gates={arm:sum(r['qualified_20ms'] for r in rows if r['arm']==arm) for arm in ('base',winner)}
    lines += ['',f'1,000 RPS의 20 ms p99 gate 통과: baseline {gates["base"]}/7, 후보 {gates[winner]}/7.']
    lines += ['',f'고정된 E2E 보존 기준 통과: **{decision["promoted"]}**. '
        '평균 또는 p99의 95% 하한이 양수이며, 두 점추정치 모두 2%를 넘게 악화되지 않아야 한다. '
        '이는 연구 artifact의 보존 기준이며 서비스 기본 배포 설정을 바꾸지 않았다.','',
        '## 부하와 처리 용량의 범위','',
        'Media 8개 공유 코어(32–39), Poisson 1,000 RPS, upstream 입력·요청 분포, tracing 100%, '
        '2 GHz/C6 off. 각 스택 50초 워밍업 뒤 30초의 계측 없는 요청 구간이다. '
        '프리패치 선택 전에 baseline으로 1,000/1,100 RPS를 확인하고, p99 20 ms와 steady 오류·drop 0을 용량 gate로 고정했다.','',
        '| Baseline offered RPS | Mean | p99 | Pool utilization | 20 ms gate |','|---|---:|---:|---:|---|']
    for rate in (1000,1100):
        r=read(root/f'qualification/media_r{rate}/result.json');p=r['pool']
        lines.append(f'| {rate} | {p["mean_ms"]:.3f} ms | {p["p99_ms"]:.3f} ms | {r["pool_util_pct"]:.2f}% | {r["valid"] and p["p99_ms"]<=20} |')
    lines += ['', '이 두 탐색점은 비교 부하를 고르기 위한 것이다. 모든 arm의 고정 제공 부하가 같으므로 완료 RPS가 비슷한 것은 최대 처리량 향상의 증거가 아니다. '
        '반복 capacity search를 하지 않았으므로 최대 지속 처리량 또는 그 향상률을 확정하지 않는다.','',
        '## 구현 A: 실행 경로를 따라 분산하는 LBR 배치','',
        '실제 FRONTEND_RETIRED.L2_MISS 샘플의 이전 taken-branch 경로에서 실행된 NOP를 찾고, '
        '나중 미스 라인 하나를 RIP-relative T1/T0로 가져온다. 미스별 경로 조건을 사용하며 같은 삽입점 간 정적 거리는 64 code bytes 이상이다. '
        '고정 μs 타이머가 아니라 실행 진행에 따라 발행한다. LBR cycles는 은퇴 시각의 lead proxy이며 실제 fetch deadline이 아니다.','',
        '| Variant | Service | Sites | Heldout miss-address/path coverage |','|---|---|---:|---:|']
    for path in sorted((root/'placements_media').glob('*/*Service.json')):
        meta=read(path);v=meta['heldout']
        coverage=100*v.get('samples_with_correct_selected_target',0)/v['all_samples']
        lines.append(f'| {path.parent.name} | {path.stem} | {meta["sites"]} | {coverage:.2f}% |')
    lines += ['', '`near`: 64–512 retired LBR cycles/T1/128-site cap; `far`: 256–2048 cycles/T1/256 cap; '
        '`far_t0`: far와 동일 주소의 T0. 실제 사이트 수는 cap보다 훨씬 작다. '
        'NOP 공간과 관측된 경로의 교집합이 제한되어 커버리지가 낮다. '
        '검증 비율은 각 샘플을 한 번만 세며, 실제 실행마다 힌트가 맞는 비율이나 cache-fill 성공률이 아니다.','',
        '## 구현 B: 스케줄인 뒤 실제 μs 간격의 커널 발행','',
        'sched_switch에서 들어올 task가 선택된 뒤 첫 batch를 발행한다. 동일 CPU의 pinned hard hrtimer가 '
        '2/4 μs 간격으로 다음 batch를 발행한다. task가 바뀌면 취소하고 TGID/TID/mm/generation을 다시 확인한다. '
        '총 최대 64라인, callback당 최대 8라인(실험 설정), 40 μs 만료로 제한했다. '
        '커널 이미지 재부팅 대신 현재 커널에 적재한 scheduler probe 확장이다.','',
        '이번 대상 주소는 1,000 RPS의 새 PEBS+scheduler 학습 구간에서, 앞으로 실행될 시간 bin에 자주 나타난 실제 미스 IP로 정했다. '
        '별도 heldout 구간을 보존했다. coarse process-wide 분류이므로 미래 분기를 아는 것으로 간주하지 않는다. '
        '은퇴 시각과 실제 fetch 시각의 차이, IRQ 지연과 누적 지연은 남으며 실제 발행 나이를 별도로 기록했다.','',
        '| Kernel plan | Heldout address coverage | Nominally early coverage |','|---|---:|---:|']
    for name,v in read(root/'wave_training/variants.json').items():
        e=v['heldout'];lines.append(f'| {name} | {e["address_coverage_pct"]:.2f}% | {e["nominally_early_coverage_pct"]:.2f}% |')
    lines += ['', '다음은 한 temporal sequence의 탐색 결과이며 신뢰구간이나 확정 개선으로 해석하지 않는다. '
        'off는 앞뒤 off 구간의 log latency를 phase index로 보간했다. '
        'NOP는 타이머를 포함한 동일 경로의 모듈이고 prefetch opcode 6 bytes만 바뀐다. '
        'burst는 같은 주소 목록을 처음에 모두 발행한다. 인터럽트 비용을 포함한 외부 요청 지표다.','',
        '| Kernel plan | Mean / p99 | vs off mean / p99 reduction | vs timer NOP | vs same-target burst | Emissions aged 10–20 us |',
        '|---|---:|---:|---:|---:|---:|']
    for r in kernel['rows']:
        cells=[]
        for comparator in ('off_bracket','timer_nop','same_targets_burst'):
            v=r['reduction_pct'][comparator];cells.append(f'{v["mean_ms"]:+.2f}% / {v["p99_ms"]:+.2f}%')
        lines.append(f'| {r["arm"]} | {r["metrics"]["mean_ms"]:.3f} / {r["metrics"]["p99_ms"]:.3f} ms | '+
            ' | '.join(cells)+f' | {r["waves"]["emission_age_10_to_20us_pct"]:.2f}% |')
    lines += ['', '이 지표는 프리패치 **시도**다. fetch queue 점유나 성공한 fill을 직접 측정하지 않았다. '
        '커널 alias prefetch는 user instruction fetch/ITLB/branch predictor 훈련 자체가 아니다. '
        '[Intel GNR 이벤트 정의](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/)와 '
        '[Linux 6.8 hrtimer](https://github.com/torvalds/linux/blob/v6.8/kernel/time/hrtimer.c)를 기준으로 해석했다.','',
        '추가 CPUID 검사에서 leaf 7/subleaf 1 EDX=0xe4000, PREFETCHI bit 14=1을 확인했다. '
        'Linux cpuinfo에 flag가 보이지 않는 것만으로 지원 여부를 판정하지 않는다. 이번 새 성능 비교의 명령은 '
        'PREFETCHT1/T0이며, 기존 동일-plan PREFETCHIT1의 음성 결과는 '
        '[이전 MovieId 실험](prefetch_plan_classB_wakestream.md#7-12-round-7b--prefetchit1-vs-prefetcht1-같은-사이트같은-타깃-exe-모듈만-계측-direct-타깃-1296개-3회)에 있다. '
        '그 결과를 ISA 미지원이나 모든 배치에서의 no-op으로 일반화하지 않는다. '
        '[Intel ISA reference](https://cdrdv2-public.intel.com/819680/architecture-instruction-set-extensions-programming-reference.pdf)는 '
        'PREFETCHIT0/1의 64-bit RIP-relative 조건과 유효한 명령 시작 주소 사용을 설명한다.','',
        '![E2E latency and actual delayed emissions](figures/class_b_e2e_distributed_20260927.png)','',
        '왼쪽은 독립 요청 지연시간 신뢰구간이다. 오른쪽은 실제 지연 발행 나이와 학습용 미스의 은퇴 나이를 '
        '각 계열 내부에서 정규화한 밀도다. 초기 batch와 >=30 us overflow는 wave 곡선에서 생략되므로 '
        '주소 적중률이나 cache fill 비율로 해석하지 않는다. 완전한 카운트는 JSON에 보존했다.','',
        '## 높은 MPKI가 E2E 개선으로 이어지지 않은 범위','',
        f'확인 실험의 baseline 전체 stack CPU에서 MovieId가 차지한 비중은 평균 {cpu_share["movie"]:.2f}%, '
        f'MovieId·ComposeReview·Rating 합은 {sum(cpu_share.values()):.2f}%였다. '
        '이 비중은 CPU 비용의 범위이며 요청 critical path나 latency의 상한으로 해석하지 않는다. '
        '높은 MPKI만으로 전체 요청시간에서 제거 가능한 비용을 계산할 수 없다.','',
        '스케줄인 이후 frontend L2 miss는 관측됐고 주기 발행도 목표 시간대에 도달했다. '
        '이 관측만으로 compulsory/capacity/conflict miss를 분해하지는 않았다. 현재 LBR 배치는 삽입 가능한 실행 NOP의 부족으로 '
        '커버리지가 작고, 커널의 시간-bin 배치는 같은 process 내 서로 다른 thread의 미래 분기를 구별하지 않는다. '
        '후자의 heldout 주소 커버리지는 최대 약 25%, nominally early 커버리지는 약 20%이며 실제 fill 성공률은 측정하지 않았다. '
        '따라서 queue 한계 하나로 원인을 확정할 수 없고, 이번 구현은 타이머와 힌트 발행 비용을 포함한 순이득을 보이지 못했다.','',
        '## 보존 및 검증','',
        '각 실패·탈락·대체 정책의 측정값, 설정, 명령, source/patch, SHA-256을 남기고 사용하지 않는 바이너리·인덱스·raw/decoded trace는 정리했다. '
        '원본 benchmark/source/input과 보존 reference는 유지했다. NAS 전송은 사용하지 않았다. '
        '주파수/C-state 복원, 데이터셋·오류 gate, 모듈 unload와 parser/ABI/lifecycle 검사를 확인했다.', '',
        f'상세 결과: `{root}`. 재현 진입점: `e2e_lbr.py`, `wave_plan.py`, `e2e_finish.py`. '
        'Git evidence에는 compact 요약과 archive SHA-256을 보존한다.']
    checks=[]
    for before in root.rglob('*_before.json'):
        if before.name not in ('platform_before.json','hwp_before.json'):continue
        after=before.with_name(before.name.replace('_before','_restored'))
        checks.append(after.exists() and read(before)==read(after))
    assert checks and all(checks)
    h.c.save(root/'restoration.json',dict(all_restored=True,checks=len(checks)))
    for name in ('protocol.json','kernel_protocol.json','selection.json','placement_decision.json',
                 'kernel_analysis.json','kernel_decision.json','kernel_rejected_cleanup.json',
                 'restoration.json','source_hashes.json','kernel_nop_audit.json','prefetchi_cpuid.json'):
        (evidence/name).write_bytes((root/name).read_bytes())
    h.c.save(evidence/'confirmation_rows.json',rows)
    h.c.save(evidence/'baseline_cpu_share_pct.json',cpu_share)
    h.c.save(evidence/'wave_plans.json',read(root/'wave_training/variants.json'))
    h.c.save(evidence/'screen_rows.json',read(root/'screen_media/rows.json'))
    h.c.save(evidence/'kernel_screen_rows.json',read(root/'kernel_screen/rows.json'))
    for name in ('kernel_smoke','kernel_nop_smoke'):
        (evidence/(name+'.json')).write_bytes((root/name/'result.json').read_bytes())
    document=h.REPO/'docs/class_b_e2e_distributed_20260927.md'
    document.write_text('\n'.join(lines)+'\n')
    archive_dir=root/'evidence_archive';archive_dir.mkdir(exist_ok=False)
    archive=archive_dir/'compact_results.tar.gz';manifest=[]
    paths=[p for p in root.rglob('*') if p.is_file() and not p.is_symlink() and not p.is_relative_to(archive_dir)
           and (p.suffix in ('.json','.csv','.log','.txt','.tsv','.err','.py','.c','.h','.sh','.conf') or p.name=='Makefile')]
    with tarfile.open(archive,'w:gz') as tf:
        for path in sorted(paths):
            assert path.stat().st_size<8*2**20,(path,'unexpected bulk')
            rel=str(path.relative_to(root));manifest.append(dict(path=rel,bytes=path.stat().st_size,sha256=h.c.sha(path)))
            tf.add(path,arcname=rel,recursive=False)
    with tarfile.open(archive,'r:gz') as tf:
        for row in manifest:
            assert hashlib.sha256(tf.extractfile(row['path']).read()).hexdigest()==row['sha256']
    h.c.save(archive_dir/'manifest.json',manifest)
    h.c.save(evidence/'archive.json',dict(path=str(archive),sha256=h.c.sha(archive),bytes=archive.stat().st_size,
        members=len(manifest),all_members_verified=True,restoration_checks=len(checks)))
    print(json.dumps(dict(document=str(document),evidence=str(evidence),archive_members=len(manifest))))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root',type=Path)
    report(parser.parse_args().root)
