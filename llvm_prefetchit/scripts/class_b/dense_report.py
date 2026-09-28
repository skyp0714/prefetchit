#!/usr/bin/env python3
"""Publish the dense-prefetch comparison and measured concurrency tradeoff."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import statistics as st
import tarfile

import dense_build as b


def read(path): return json.loads(path.read_text())


def plots(root,scaling,screen):
    import matplotlib
    matplotlib.use('Agg')
    matplotlib.rcParams['svg.hashsalt']='class-b-concurrency-20260927'
    import matplotlib.pyplot as plt
    folder=b.REPO/'docs/figures';folder.mkdir(exist_ok=True)
    scaling=[dict(row) for row in scaling]
    for row in scaling:
        scheduler=read(Path(row['output'])/'result.json')['scheduler']
        row['average_running_tasks']=scheduler['average_running_tasks']
        row['average_runnable_tasks']=scheduler['average_running_tasks']+scheduler['average_waiting_runnable_tasks']
    counts=sorted({r['concurrency'] for r in scaling})
    fig,axes=plt.subplots(1,3,figsize=(13,4.2),layout='constrained')
    series=[(0,'achieved_rps','Completed requests/s','#176b87'),
            (1,'mean_ms','Mean','#176b87'),(1,'p99_ms','p99','#bc5734'),
            (2,'average_runnable_tasks','Running + waiting','#755b9c'),
            (2,'average_running_tasks','Running','#57845a')]
    for index,key,label,color in series:
        means=[];lows=[];highs=[]
        for count in counts:
            rows=[r for r in scaling if r['concurrency']==count]
            values=[r['metrics'][key] if key in r['metrics'] else r[key] for r in rows]
            mean=st.mean(values);means.append(mean);lows.append(mean-min(values));highs.append(max(values)-mean)
            axes[index].scatter([count]*len(values),values,color=color,alpha=.3,s=18)
            for row,value in zip(rows,values):
                if not row['valid']:axes[index].scatter(count,value,marker='x',color='red',s=65)
        axes[index].errorbar(counts,means,yerr=[lows,highs],label=label,color=color,marker='o',capsize=4,lw=1.6)
    titles=['Throughput','Individual request latency','CPU scheduling contention']
    ylabels=['Successful requests / second','HTTP dispatch to completion (ms)','Average task count (schedstat)']
    for ax,title,ylabel in zip(axes,titles,ylabels):
        ax.set_xscale('log',base=2);ax.set_xticks(counts,[str(c) for c in counts])
        ax.set(xlabel='Concurrent requests (closed loop)',ylabel=ylabel,title=title,ylim=(0,None))
        ax.grid(axis='y',alpha=.2)
    axes[0].annotate('CPU 85.6%',xy=(4,1167.6),xytext=(2.1,900),arrowprops=dict(arrowstyle='-',color='#555'),fontsize=8)
    axes[0].annotate('Throughput plateau',xy=(16,1395.6),xytext=(6,1180),arrowprops=dict(arrowstyle='-',color='#555'),fontsize=8)
    axes[1].legend(frameon=False)
    axes[2].axhline(8,ls=':',color='#777',lw=1,label='8 CPU cores')
    axes[2].legend(frameon=False,fontsize=8)
    repetitions=sorted({sum(r['concurrency']==count for r in scaling) for count in counts})
    repeat_label='–'.join(map(str,repetitions))
    fig.suptitle('Media: one instance per service, fixed 8 CPU cores, no prefetch\n'
                 f'{repeat_label} fresh runs per point; bars = observed min–max',fontsize=12)
    path=folder/'class_b_concurrency_20260927.png';fig.savefig(path,dpi=180)
    svg=path.with_suffix('.svg');fig.savefig(svg,metadata={'Date':None});plt.close(fig)
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
    fig,axes=plt.subplots(1,2,figsize=(10,4),layout='constrained')
    arms=['callee8','seq4k','seq256'];labels=['Callee 8 lines','Periodic +4 KiB','Periodic +256 B']
    for index,key in enumerate(('stack_cpu','mean_ms')):
        for offset,control,color,label in [(-.16,'base','#176b87','vs rebuilt baseline'),(.16,'nop','#bc5734','vs identical-layout NOP')]:
            values=[screen[arm][arm+'_nop' if control=='nop' else control][key]['cost_reduction_pct'] for arm in arms]
            axes[index].barh([i+offset for i in range(3)],values,height=.3,color=color,label=label)
        axes[index].set(yticks=range(3),yticklabels=labels,xlabel='Reduction (%); positive is better',
                        title=['Whole-stack CPU / request','External mean latency'][index])
        axes[index].axvline(0,color='#555',lw=1);axes[index].grid(axis='x',alpha=.2)
    axes[1].legend(frameon=False,fontsize=8)
    fig.suptitle('Dense prefetch: two screening blocks at 1,000 offered RPS (exploratory)')
    path2=folder/'class_b_dense_20260927.png';fig.savefig(path2,dpi=180);plt.close(fig)
    return path,path2


def report(root):
    assert (root/'measurements_complete.json').exists()
    b.space(root)
    scaling=[r for r in read(root/'concurrency/rows.json') if r['block']<2];screen=read(root/'screen/summary.json')
    decision=read(root/'dense_decision.json');audit=read(root/'binary_audit.json')
    followup=None
    if (root/'latency_followup_complete.json').exists():
        followup=read(root/'latency_followup_decision.json')
    plots(root,scaling,screen)
    lines=['# 고밀도 프리패치와 동시 요청 수의 실측 비교','',
        'Media 전체 스택을 새로 띄워 측정했다. MovieId·ComposeReview·Rating 세 서비스에 같은 정책을 함께 적용한 bundle 비교다. '
        '고밀도 실험의 외부 요청 지연시간과 전체 stack CPU/request를 따로 보고한다. 절감률은 양수일 때 개선이다.','',
        '## 고밀도 구현과 대조군','',
        '| 구현 | MovieId / ComposeReview / Rating의 정적 PF 명령 수 | 방식 |','|---|---:|---|']
    lead=[]
    if followup:
        values=followup['metrics']['base']
        verdict='latency 개선을 확인했다' if followup['promoted'] else 'latency 개선을 입증하지 못했다'
        lead += [f'호출 대상 8라인 정책의 E2E 우선 독립 7묶음 확인에서 {verdict}. '
            f'원래 기준 대비 절감률은 평균 {values["mean_ms"]["cost_reduction_pct"]:+.2f}%, '
            f'p99 {values["p99_ms"]["cost_reduction_pct"]:+.2f}%, '
            f'전체 CPU/request {values["stack_cpu"]["cost_reduction_pct"]:+.2f}%다. '
            '음수 절감률은 악화이며, 신뢰구간과 NOP 대비 결과는 아래에 함께 제시한다.','']
    low=[r for r in scaling if r['concurrency']==1];high=[r for r in scaling if r['concurrency']==32]
    if low and high and all(r['valid'] for r in low+high):
        pairs={key:(st.mean(r['metrics'][key] for r in low),st.mean(r['metrics'][key] for r in high))
               for key in ('achieved_rps','mean_ms','p99_ms')}
        lead += [f'같은 8 CPU에서 동시 요청 1→32개로 늘리면 관측 처리량은 '
            f'{pairs["achieved_rps"][0]:.1f}→{pairs["achieved_rps"][1]:.1f} RPS, '
            f'평균 지연은 {pairs["mean_ms"][0]:.3f}→{pairs["mean_ms"][1]:.3f} ms, '
            f'p99는 {pairs["p99_ms"][0]:.3f}→{pairs["p99_ms"][1]:.3f} ms였다. '
            '각 지점의 독립 2회 평균이며, 서비스 인스턴스 수와 내부 threading 구현은 고정했다.','']
    lead += ['[코드 미스·ITLB·분기와 실제 PF 커버리지 상세 진단](class_b_dense_miss_causes_20260927.md)을 별도로 정리했다.','']
    lines[2:2]=lead
    descriptions={'callee8':'정의가 보이는 직접 호출 대상의 앞 8 cache lines',
        'seq4k':'eligible IR 명령 20개마다 RIP+4096, 호출 대상 4 lines',
        'seq256':'eligible IR 명령 20개마다 RIP+256, 호출 대상 4 lines'}
    for arm in descriptions:
        counts=[next(r['prefetch_instructions'] for r in audit if r['arm']==arm and r['service']==key) for key in b.SERVICES]
        lines.append(f'| {arm} | '+ ' / '.join(f'{n:,}' for n in counts)+f' | {descriptions[arm]} |')
    lines += ['', 'PREFETCHT1을 사용했다. 주기적 방식의 stride는 LLVM IR 기준이며, 일정 μs 간격이나 기계어 20개 간격을 보장하지 않는다. '
        '서비스와 mongo-c/BSON·Thrift·yaml-cpp·OpenTracing·Jaeger를 재빌드했다. 시스템 libstdc++·libc·libmemcached, Redis 계열 기존 라이브러리 및 다른 서비스는 '
        '재계측하지 않았다. 따라서 모든 실행 명령 또는 모든 미스의 커버리지를 주장하지 않는다.','',
        '프리패치 없는 baseline도 동일 소스·도구·옵션으로 재빌드했다. 기존 FATSTATIC=1 레시피를 모든 arm에 적용했으며, '
        '정적 libstdc++/libgcc를 포함한 이 링크 구성의 결과다. 각 PF 바이너리에는 같은 길이의 NOP로 PF만 바꾼 대조군을 만들었다. '
        '전체 파일 크기, 치환 바이트, 역치환 시 원본 일치, 남은 PF=0을 검사했다. 삽입 위치별 원본/NOP 바이트와 SHA-256을 보존했다.','',
        '8개 공유 CPU(32–39), 2 GHz/C6 off, tracing 100%, Poisson 1,000 RPS, 50초 warmup + 90초 ROI. '
        '각 실행마다 스택과 데이터를 새로 초기화했다. 컴파일·디스어셈블·PMU 수집은 주 지표 ROI와 겹치지 않는다. '
        '첫 screen block의 PMU는 ROI 뒤 별도 20초/서비스 구간이다.','',
        '## 기준 측정의 변동','',
        '동일 요청 seed와 같은 설정을 쓰는 네 번의 독립 스택 측정이다.','',
        '| 지표 | 평균 | 최소–최대 | 실행 간 CV |','|---|---:|---:|---:|']
    for key,v in read(root/'baseline_variation.json').items():
        lines.append(f'| {key} | {v["mean"]:.3f} | {v["minimum"]:.3f}–{v["maximum"]:.3f} | {v["cv_pct"]:.2f}% |')
    lines += ['', 'CPU 단위는 μs/request, 지연시간 단위는 ms다. 이전 30초·서로 다른 seed의 반복과는 '
        '측정 길이 및 입력 조건이 함께 달라졌으므로 변동 감소를 측정 길이 하나의 효과로 단정하지 않는다.','',
        '## 고밀도 탐색 결과','',
        '두 새 seed block의 paired log ratio다. 아래는 탐색 점추정치이며, 두 쌍만으로 확정 개선을 주장하지 않는다. '
        'base 대비 결과는 코드 배치·크기와 PF 비용을 포함한다. NOP 대비 결과는 같은 배치에서 힌트 명령의 순효과다.','',
        '| 구현 | 대조군 | 전체 CPU/request 절감 | 평균 latency 절감 | p99 절감 |','|---|---|---:|---:|---:|']
    for arm in descriptions:
        for control in ('base',arm+'_nop'):
            row=screen[arm][control]
            values=[row[key]['cost_reduction_pct'] for key in ('stack_cpu','mean_ms','p99_ms')]
            lines.append(f'| {arm} | {control} | '+' | '.join(f'{v:+.2f}%' for v in values)+' |')
    lines += ['', '추가 섹션 감사에서 seq4k와 seq256의 NOP 대조군은 세 서비스 모두 실행 가능 섹션의 주소·크기·바이트가 같았다. '
        '서로 다른 파일/매핑과 실행 시점은 유지된다. 첫 block의 서로 다른 NOP 성능을 prefetch 거리의 효과나 '
        '코드 삽입 비용의 확정값으로 해석하지 않는다. `periodic_nop_equivalence.json`에 섹션 SHA를 보존했다. '
        '같은 baseline 파일의 짧은 A/A 반복 CV만으로 모든 대조군의 변동을 설명할 수도 없다.']
    lines += ['', '![Dense comparison](figures/class_b_dense_20260927.png)','',
        f'CPU 절감도 동시에 요구한 초기 선택 규칙의 후보: **{decision["winner"] or "없음"}**, 이 규칙의 독립 확인 통과: **{decision["promoted"]}**. '
        '선택 및 보존 규칙은 `measurement_protocol.json`에 성능 측정 전에 기록했다. '
        'screen과 독립 확인 데이터는 합치지 않는다. 탈락 구현은 기본 실행에 적용하지 않았다.']
    if decision['confirmation']:
        lines += ['', '독립 새 seed 7 block의 확인 결과(개별 95% t 구간, 다중 endpoint 보정 없음):','',
            '| 대조군 | 지표 | 절감률 [95% CI] |','|---|---|---:|']
        for control,metrics in decision['confirmation'][decision['winner']].items():
            for key in ('stack_cpu','mean_ms','p99_ms'):
                v=metrics[key];lo,hi=v['ci95_pct']
                lines.append(f'| {control} | {key} | {v["cost_reduction_pct"]:+.2f}% [{lo:+.2f}, {hi:+.2f}] |')
    if followup:
        equality=read(root/'latency_followup_build_equivalence.json')
        lines += ['', '## E2E 우선 기준으로 8라인 정책 독립 확인','',
            '초기 선택은 전체 CPU point estimate가 원본·NOP 모두보다 좋아야 한다는 추가 조건을 두었다. '
            '그 때문에 latency 탐색값이 가장 좋았던 callee8이 NOP 대비 CPU −0.026%로 탈락했다. '
            '사용자가 요청한 E2E 우선 평가를 위해 그 초기 분석을 유지하면서 별도 확인을 등록했다. '
            '추가 정책의 선택 근거는 두 block screen의 평균 latency이며, 새 결과를 보고 후보를 바꾸지 않았다.','',
            '같은 소스·플러그인·이미지로 baseline과 callee8을 다시 빌드하고 NOP를 재감사했다. '
            f'원래 artifact와 전체 SHA가 일치한 실행 파일은 {sum(r["identical"] for r in equality)}/{len(equality)}개다. '
            '기준 바이너리 세 개가 모두 같으면 원래 기준을 재사용하고 중복 파일을 바로 정리했다. '
            '7개 새 seed(44001–44007), fresh stack, 50초 warmup·90초 ROI, 1,000 RPS, 8 CPU의 같은 설정이다. '
            '이 결과를 screen이나 seq4k 확인 데이터와 합치지 않았다.','',
            'CPU는 독립 보고 지표로 두었다. 평균 또는 p99 중 같은 endpoint가 원본과 NOP 양쪽에서 '
            '97.5% 구간의 하한이 양수여야 하며, 다른 latency point estimate가 2% 넘게 악화되지 않아야 한다. '
            '두 latency endpoint 선택에는 Bonferroni 보정을 적용했다. CPU의 표시 구간은 개별 95%다.','',
            '| 대조군 | 지표 | 절감률 | 구간 |','|---|---|---:|---:|']
        for control,metrics in followup['metrics'].items():
            for key in ('stack_cpu','mean_ms','p99_ms'):
                value=metrics[key];ci=value['ci95_pct'] if key=='stack_cpu' else value['ci97_5_pct']
                level='95%' if key=='stack_cpu' else '97.5%'
                lines.append(f'| {control} | {key} | {value["cost_reduction_pct"]:+.2f}% | {level}: [{ci[0]:+.2f}, {ci[1]:+.2f}] |')
        lines += ['',f'E2E 우선 보존 판정: **{followup["promoted"]}**. '
            f'확인된 latency endpoint: **{", ".join(followup["confirmed_latency_endpoints"]) or "없음"}**. '
            f'CPU 절감 별도 확인: **{followup["cpu_improved_95"]}**. '
            f'10% 절감을 양쪽 대조군에 대해 지지하는 latency 구간: **{followup["ten_percent_supported"]}**.']
    lines += ['', '## PMU 진단','',
        '별도 진단 구간 한 번의 값이다. 서비스별 user-mode 이벤트이며 전체 스택 CPU와 범위가 다르다.','',
        '| 구현 | 서비스 | instructions/request | L2 code misses/request | MPKI | SWPF miss / hit per request |','|---|---|---:|---:|---:|---:|']
    pmu_rows=[]
    for row in read(root/'screen/rows.json'):
        if row['block']!=0:continue
        result=read(Path(row['output'])/'result.json')
        for key,service in result['services'].items():
            v=service['pmu'];events=v['counters'];n=v['window']['completed']
            d=dict(arm=row['arm'],service=key,instructions_per_request=events['instructions:u']/n,
                code_misses_per_request=v['code_misses_per_request'],mpki=v['mpki'],
                swpf_miss_per_request=events['SWPF_MISS']/n,swpf_hit_per_request=events['SWPF_HIT']/n,
                fully_scheduled=v['fully_scheduled'])
            pmu_rows.append(d)
            lines.append(f'| {d["arm"]} | {key} | {d["instructions_per_request"]:,.0f} | {d["code_misses_per_request"]:,.1f} | {d["mpki"]:.2f} | {d["swpf_miss_per_request"]:,.1f} / {d["swpf_hit_per_request"]:,.1f} |')
    b.save(root/'pmu_summary.json',pmu_rows)
    near=[r for r in pmu_rows if r['arm']=='seq256']
    hits=[100*r['swpf_hit_per_request']/(r['swpf_hit_per_request']+r['swpf_miss_per_request']) for r in near]
    lines += ['',f'seq256의 집계된 SWPF 요청 중 L2 hit 비중은 세 서비스에서 {min(hits):.1f}–{max(hits):.1f}%였다. '
        '대부분 이미 L2에 있는 주소를 요청했다는 관측이며, 미래 실행 경로의 정확도나 실제 fill 성공률은 아니다. '
        '상태가 이미 hot인 힌트를 많이 발행해도 코드 미스나 E2E 비용이 같은 비율로 줄어들지는 않는다.']
    baseline=read(root/'screen/00_base/result.json')
    scope={key:dict(cpu_us_per_request=v['cpu']['cpu_us_per_request'],
                   user_us_per_request=v['cpu']['user_us_per_request'])
           for key,v in baseline['services'].items()}
    total=baseline['whole_stack_cpu_us_per_request']
    b.save(root/'baseline_cpu_scope.json',dict(services=scope,stack_cpu_us_per_request=total))
    lines += ['', 'MPKI는 instruction 수가 늘어도 떨어질 수 있으므로 miss/request를 함께 본다. '
        'L2_RQSTS.CODE_RD_MISS는 speculative code request의 L2 miss이며, retired miss 샘플과 같은 모집단이 아니다. '
        'SWPF_MISS/HIT는 fill buffer가 가득 차지 않았을 때의 요청을 세므로 실제 cache-fill 성공률·정확도 또는 queue 포화를 직접 측정한 값으로 해석하지 않는다. '
        '[Intel Granite Rapids 이벤트 정의](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).','',
        f'첫 screen baseline에서 세 대상 서비스의 전체 CPU 합은 스택 CPU의 '
        f'{100*sum(v["cpu_us_per_request"] for v in scope.values())/total:.2f}%, '
        f'그 서비스들의 user CPU 합은 {100*sum(v["user_us_per_request"] for v in scope.values())/total:.2f}%였다. '
        '이는 높은 user-space MPKI와 전체 요청 비용의 범위 차이를 보여준다. '
        'CPU 구성비를 latency critical path의 비중이나 프리패치 이득의 엄밀한 상한으로 사용하지 않는다.','',
        '## 동시 요청 수와 개별 요청 지연시간','',
        '![Throughput, latency and scheduling contention](figures/class_b_concurrency_20260927.png)','',
        '이 그래프의 기준은 **동시 요청 1개**다. 모든 점에서 서비스당 인스턴스는 하나이고, 기존 내부 server/async 스레드는 유지한다. '
        '따라서 순수 single-thread 실행이나 프로세스 수를 바꾼 실험은 아니다. 같은 8개 CPU에서 '
        '완료 즉시 다음 요청을 보내는 closed loop를 사용했다. 지연시간은 HTTP dispatch→완료이고, '
        '고정 RPS 실험의 예정 도착→완료 지연시간과 정의가 다르다. 오류가 있거나 단일 Python client CPU 사용량이 '
        '0.8 core 이상이면 invalid로 표시한다. 수직 막대는 두 실행의 관측 최소–최대이며 신뢰구간이 아니다.','',
        '| 동시 요청 | 성공 RPS | 평균 ms | p99 ms | CPU 사용률 | 평균 runnable 대기 수 | 오류율 | 유효 실행 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    scaling_summary=[]
    for count in sorted({r['concurrency'] for r in scaling}):
        rows=[r for r in scaling if r['concurrency']==count]
        d=dict(concurrency=count,valid_runs=sum(r['valid'] for r in rows),runs=len(rows),
            **{key:st.mean(r['metrics'][key] for r in rows) for key in ('achieved_rps','mean_ms','p99_ms')},
            **{key:st.mean(r[key] for r in rows) for key in ('pool_util_pct','average_waiting_runnable_tasks','runqueue_wait_us_per_request','error_fraction','client_cpu_cores')})
        results=[read(Path(r['output'])/'result.json') for r in rows]
        d['whole_stack_cpu_us_per_request']=st.mean(r['whole_stack_cpu_us_per_request'] for r in results)
        d['average_running_tasks']=st.mean(r['scheduler']['average_running_tasks'] for r in results)
        d['average_runnable_tasks']=d['average_running_tasks']+d['average_waiting_runnable_tasks']
        scaling_summary.append(d)
        lines.append(f'| {count} | {d["achieved_rps"]:.1f} | {d["mean_ms"]:.3f} | {d["p99_ms"]:.3f} | {d["pool_util_pct"]:.1f}% | {d["average_waiting_runnable_tasks"]:.3f} | {100*d["error_fraction"]:.3f}% | {d["valid_runs"]}/{len(rows)} |')
    b.save(root/'scaling_summary.json',scaling_summary)
    valid=[v for v in scaling_summary if v['valid_runs']==v['runs']]
    single=next((v for v in valid if v['concurrency']==1),None)
    if single and valid:
        best=max(valid,key=lambda v:v['achieved_rps'])
        highest=max(valid,key=lambda v:v['concurrency'])
        lines += ['',f'측정한 유효 지점 중 최대 평균 처리량은 동시 요청 {best["concurrency"]}개의 '
            f'{best["achieved_rps"]:.1f} RPS였다. 동시 요청 1개 대비 '
            f'{best["achieved_rps"]/single["achieved_rps"]:.2f}배이며, 같은 점의 평균/p99 지연시간은 각각 '
            f'{best["mean_ms"]/single["mean_ms"]:.2f}/{best["p99_ms"]/single["p99_ms"]:.2f}배다. '
            f'가장 높은 유효 동시성 {highest["concurrency"]}개에서는 {highest["achieved_rps"]:.1f} RPS, '
            f'평균 {highest["mean_ms"]:.3f} ms, p99 {highest["p99_ms"]:.3f} ms를 관측했다.']
    lines += ['', '동시 요청 수가 CPU 수를 넘는 것만으로 runnable 과구독을 증명하지 않는다. '
        '오른쪽 그래프는 해당 CPU들의 schedstat 실행 및 runqueue wait 시간 증가량을 관측시간으로 나눈 값이다. '
        'Running+waiting 곡선과 running 곡선의 차이가 대기 중인 runnable task의 평균 수이며, 8 CPU 기준선을 함께 그렸다. '
        '이 동시성 측정에서는 sched_schedstats를 켰으며 매 실행 뒤 원래 설정으로 복원했다. '
        'DSB 이외의 해당 CPU 작업도 포함하고 경계에 걸친 대기가 존재할 수 있다. '
        '[Linux schedstat v15 정의](https://www.kernel.org/doc/html/v6.8/scheduler/sched-stats.html). '
        'Closed loop의 처리량과 평균 지연시간은 in-flight 요청 수로 서로 연결되므로 두 지표를 독립적인 인과 증거로 취급하지 않는다. '
        '측정 범위에서 관측한 처리량이며, 모든 동시성·SLO에 걸친 절대 최대 지속 처리량으로 주장하지 않는다.','',
        '완료한 두 block의 12개 실행을 균형 있는 그래프에 사용했다. 추가로 끝난 동시 요청 16·32의 각 1회도 원자료에 보존했다. '
        '사용자의 범위 조정으로 세 번째 block의 다음 warmup을 중단하고 나머지 반복 및 별도 callee8 latency 확인을 실행하지 않았다. '
        '미실행 계획은 성공·실패 판정에 넣지 않았다. `scope_wrap.json`과 `latency_followup_status.json` 참조.','',
        '## 재현·보존','',
        '`dense_build.py prepare/build` → `dense_study.py audit/campaign` → `dense_report.py` 순서다. '
        '모든 설정·명령·소스와 binary SHA·치환 패치·실패/탈락 이유를 남겼다. '
        '각 빌드의 object/build tree, 끝난 실행의 request raw log·임시 데이터 volume, 탈락한 PF/NOP 실행 파일은 즉시 정리했다. '
        '원본 패키지·소스·입력과 현재 기준 바이너리는 유지했다. NAS 전송은 없었다.','',
        f'로컬 상세 결과: `{root}`. Git evidence는 compact JSON과 검증한 archive manifest를 포함한다.']
    document=b.REPO/'docs/class_b_dense_and_concurrency_20260927.md'
    document.write_text('\n'.join(lines)+'\n')
    checks=[]
    for path in root.rglob('*_before.json'):
        if path.name not in ('platform_before.json','hwp_before.json'):continue
        after=path.with_name(path.name.replace('_before','_restored'));checks.append(after.exists() and read(path)==read(after))
    sched=[read(p)['restored'] for p in root.rglob('scheduler_restoration.json')]
    assert checks and all(checks) and len(sched)==len(list((root/'concurrency').glob('*/protocol.json'))) and all(sched)
    b.save(root/'restoration.json',dict(all_restored=True,platform_checks=len(checks),scheduler_checks=len(sched)))
    evidence=b.REPO/'llvm_prefetchit/migration/evidence/class_b_dense_20260927';evidence.mkdir(exist_ok=True)
    names=['protocol','measurement_protocol','source_hashes','binary_audit','baseline_variation','selection',
        'dense_decision','pmu_summary','baseline_cpu_scope','scaling_summary','restoration','measurements_complete']
    for name in names:shutil.copyfile(root/(name+'.json'),evidence/(name+'.json'))
    for folder in ('baseline_aa','screen','concurrency','confirmation','latency_followup'):
        if (root/folder/'rows.json').exists():shutil.copyfile(root/folder/'rows.json',evidence/(folder+'_rows.json'))
    for path in root.glob('*_rejected_cleanup.json'):shutil.copyfile(path,evidence/path.name)
    for name in ('scope_wrap','complete'):
        shutil.copyfile(root/'concurrency'/(name+'.json'),evidence/('concurrency_'+name+'.json'))
    for path in root.glob('latency_followup_*.json'):shutil.copyfile(path,evidence/path.name)
    if (root/'latency_baseline_dedup_cleanup.json').exists():shutil.copyfile(root/'latency_baseline_dedup_cleanup.json',evidence/'latency_baseline_dedup_cleanup.json')
    archive_dir=root/'evidence_archive';archive_dir.mkdir(exist_ok=False);archive=archive_dir/'compact_results.tar.gz';manifest=[]
    excluded=('dependency_sources','original_packages','benchmark_source','evidence_archive')
    with tarfile.open(archive,'w:gz') as tf:
        for p in sorted(root.rglob('*')):
            if not p.is_file() or p.is_symlink() or any(v in p.relative_to(root).parts for v in excluded):continue
            if p.suffix not in ('.json','.log','.csv','.txt','.py','.cpp','.sh','.gz'):continue
            assert p.stat().st_size<12*2**20,p
            rel=str(p.relative_to(root));manifest.append(dict(path=rel,bytes=p.stat().st_size,sha256=b.sha(p)))
            tf.add(p,arcname=rel,recursive=False)
    with tarfile.open(archive,'r:gz') as tf:
        for row in manifest:assert hashlib.sha256(tf.extractfile(row['path']).read()).hexdigest()==row['sha256']
    b.save(archive_dir/'manifest.json',manifest)
    b.save(evidence/'archive.json',dict(path=str(archive),sha256=b.sha(archive),bytes=archive.stat().st_size,
        members=len(manifest),verified=True,manifest_sha256=b.sha(archive_dir/'manifest.json')))
    print(json.dumps(dict(document=str(document),evidence=str(evidence),archive_bytes=archive.stat().st_size)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root',type=Path)
    report(parser.parse_args().root)
