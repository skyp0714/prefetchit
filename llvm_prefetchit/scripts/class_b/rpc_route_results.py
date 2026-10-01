#!/usr/bin/env python3
"""Summarize, retire unused RPC experiments, audit restoration and publish records."""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import tarfile
import time

import dense_build as b
from rpc_route_study import load
from rpc_future_finalize import effect, interval
from temporal_path_confirm import arm_paths, cleanup

TAG='class_b_rpc_route_20261001'


def summarize(root):
    complete=load(root/'measurement_complete.json');assert complete['valid']
    chosen=load(root/'confirmation_selection.json');nominee=chosen['nominee'];combined=chosen['combined']
    report=dict(selection=chosen,complete=complete,phases={})
    if (root/'resumption.json').exists():
        report['resumption']=load(root/'resumption.json')
    if (root/'training_classification.json').exists():report['training_classification']=load(root/'training_classification.json')
    phases=['screen','screen2','confirmation']
    if (root/'same_line_predeclared.json').exists():
        assert load(root/'same_line_complete.json')['valid']
        phases.append('same_line')
    for phase in phases:
        data=load(root/phase/'evaluation.json')
        report['phases'][phase]=dict(trials=data['trials'],
            absolute={name:dict(rps=v['rps'],util_pct=v['util_pct'],service_cpu=v['service_cpu'],**v['e2e']) for name,v in data['absolute'].items()},
            comparisons=data['e2e'])
    pmu={};services={};pool={}
    for path in sorted((root/'diagnostics').glob('*/result.json')):
        row=load(path);assert row['valid'];name=path.parent.name.split('_',1)[1]
        values=collections.defaultdict(float);service_rows={}
        for label,scopes in row['pmu_extra'].items():
            assert set(scopes)=={'movie','compose','rating'}
            for service,window in scopes.items():
                assert window['fully_scheduled']
                for event,value in window['per_request'].items():
                    values[label+':'+event]+=value
                    service_rows.setdefault(service,{})[label+':'+event]=value
        values['frontend_pct']=100*values['topdown:topdown-fe-bound:u']/values['topdown:slots:u']
        values['backend_pct']=100*values['topdown:topdown-be-bound:u']/values['topdown:slots:u']
        pmu[name]=dict(values);services[name]=service_rows;pool[name]=row['pool_pmu']
    assert len(pmu)==2
    contrast={key:dict(nop=pmu[combined+'_nop'][key],prefetch=value,
        change_pct=100*(value/pmu[combined+'_nop'][key]-1) if pmu[combined+'_nop'][key] else None)
        for key,value in pmu[combined].items()}
    report['pmu']=dict(absolute=pmu,contrast=contrast,services=services,pool=pool,
        scope='MovieId, ComposeReview and Rating only; each service/event group has a separate three-second request-normalized window. '
              'Pool user/kernel counts are separate and not additive to service counts. One diagnostic per arm, no PMU confidence intervals. '
              'No throughput/latency inference from diagnostic trials.')
    final=report['phases']['confirmation'];comparisons=final['comparisons']
    promoted=[]
    for name,control in [(nominee,'no_dso'),(combined,'full_dso')]:
        c=comparisons[name][control]
        if c['inverse_rps']['speedup_ci95'][0]>1 and c['stack_cpu']['cost_reduction_pct']>=-.5 and c['p99_ms']['cost_reduction_pct']>=-2:
            promoted.append(name)
    pruning=None
    if 'same_line' in report['phases']:
        name='full_rpc_worker_pruned';pruning=report['phases']['same_line']['comparisons'][name]
        c=pruning['full_dso']
        if c['inverse_rps']['speedup_ci95'][0]>1 and c['stack_cpu']['cost_reduction_pct']>=-.5 and c['p99_ms']['cost_reduction_pct']>=-2:
            promoted.append(name)
        b.save(root/'same_line_decision.json',dict(promoted=name in promoted,comparisons=pruning,
            rule=load(root/'same_line_predeclared.json')['promotion']))
    decision=dict(selected='full_rpc_worker_pruned' if 'full_rpc_worker_pruned' in promoted else combined if combined in promoted else 'full_dso',retained_new_references=promoted,
        rule='Promote only the frozen RPC nominees with positive lower individual paired-log throughput CI versus their own background policy, CPU cost <=+0.5%, and p99 cost <=+2%. '
             'Intervals are not multiplicity-adjusted; do not select a different RPC implementation from confirmation.',
        comparisons={name:comparisons[name][control] for name,control in [(nominee,'no_dso'),(combined,'full_dso')]},
        same_line_comparisons=pruning,epoch=time.time())
    b.save(root/'final_decision.json',decision)
    report['decision']=decision
    baseline=[row['achieved_rps'] for row in load(root/'confirmation/rows.json') if row['arm']=='original']
    report['baseline_variation']=dict(rps=baseline,cv_pct=100*statistics.stdev(baseline)/statistics.mean(baseline),
        min_rps=min(baseline),max_rps=max(baseline))
    b.save(root/'analysis/report.json',report)
    prepared=load(root/'prepared_candidates.json');arms=load(root/'arms.json')
    keep=[arms[name] for name in ['original','full_dso','no_dso']]
    keep += [prepared[name][kind] for name in promoted for kind in ['arm','nop']]
    rejected=[name for name in prepared if name not in promoted]
    cleanup(root,rejected,keep,'final_rejected_cleanup.json')
    retired=load(root/'final_rejected_cleanup.json')
    retired['reason']='Independent confirmation and separate PMU complete; preserve compact evidence and remove generated ELFs of RPC policies not promoted by the recorded rule.'
    b.save(root/'final_rejected_cleanup.json',retired)
    plot(root,report,nominee,combined)
    write_report(root,report,nominee,combined)
    print(json.dumps(dict(decision=decision,absolute=final['absolute']),indent=2))


def plot(root,report,nominee,combined):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    names=['full_dso','no_dso',nominee,combined]
    hint='IT0' if nominee.endswith('it0') else 'T1'
    labels=['Existing full policy','Without DSO hints',f'No DSO + worker {hint}',f'Full policy + worker {hint}']
    fig,axes=plt.subplots(2,2,figsize=(12,6.8))
    for ax,key,title in zip(axes.flat,['inverse_rps','mean_ms','p99_ms','stack_cpu'],
            ['Throughput increase','Mean latency reduction','p99 latency reduction','CPU/request reduction']):
        for i,(name,color) in enumerate(zip(names,['#176b55','#3268a8','#bd7131','#7d4c9f'])):
            value,(lo,hi)=effect(report['phases']['confirmation']['comparisons'][name]['original'],key)
            ax.errorbar(value,i,xerr=[[value-lo],[hi-value]],fmt='o',color=color,capsize=4,linewidth=1.7)
            ax.annotate(f'{value:+.2f}%',(value,i),xytext=(0,-15),textcoords='offset points',ha='center',fontsize=9,color=color)
        ax.set_yticks(range(4),labels,fontsize=9);ax.set_ylim(3.6,-.6)
        ax.axvline(0,color='#888888',linewidth=1);ax.grid(axis='x',alpha=.2)
        ax.set_title(title,loc='left');ax.set_xlabel('Improvement over original (%) — right is better',fontsize=9)
        ax.spines[['top','right']].set_visible(False)
    blocks=report['selection']['blocks']
    fig.suptitle('DSB Media: RPC-aware prefetch, independent confirmation',fontsize=15,y=.99)
    fig.text(.5,.01,f'{blocks} fresh paired blocks · individual paired-log 95% intervals · balanced C4 · 8 server CPUs\n'
        '23 worker hints in six callsites. Separate three-hint ablation is reported in the text. Diagnostic timing is excluded.',ha='center',fontsize=9)
    fig.tight_layout(rect=[0,.075,1,.96])
    for extension in ('png','svg'):
        path=root/'analysis'/('endpoint_effects.'+extension);fig.savefig(path,dpi=180)
        if extension=='svg':path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines())+'\n')
    plt.close(fig)


def write_report(root,report,nominee,combined):
    hint='IT0' if nominee.endswith('it0') else 'T1'
    labels={'original':'원본','full_dso':'기존 DSO 포함','no_dso':'DSO 제거',nominee:'DSO 제거 + 작업 스레드 '+hint,
            combined:'기존 정책 + 작업 스레드 '+hint}
    final=report['phases']['confirmation'];c=final['comparisons'];decision=report['decision']
    lines=['# RPC 타입·실행 단계·비동기 작업을 활용한 프리패치', '',
        ('2026-10-01 후속 캠페인. 호스트 재부팅으로 오전 확인 실험이 중단되어, 사용자의 재개 요청 후 같은 후보로 새 독립 확인을 수행했다. '
         if 'resumption' in report else '2026-10-01 오전 10시 CDT(15:00 UTC)까지의 후속 캠페인. ')+
        '전체 Media compose-review 처리량·평균·p99·CPU/request를 기준으로 평가했다. '
        '아래 독립 확인값은 두 탐색 단계와 별도로 얻었다.', '',
        f"기존 정책에 RPC 작업 스레드 힌트를 결합한 버전의 처리량 변화는 원본 대비 **{interval(c[combined]['original'],'inverse_rps')}**, "
        f"기존 정책 대비 **{interval(c[combined]['full_dso'],'inverse_rps')}**다. "
        f"DSO 제거판에 같은 힌트를 더한 변화는 DSO 제거 대조군 대비 **{interval(c[nominee]['no_dso'],'inverse_rps')}**다.", '',
        ('독립 확인에서 추가 이득이 확인된 새 정책을 보존했다.' if decision['retained_new_references'] else
         '이번 RPC 추가의 처리량 이득은 독립 확인에서 확정되지 않아 기존 정책을 유지한다.'), '',
        '| 정책 | RPS | 평균 ms | p99 ms | CPU µs/request | CPU util |','|---|---:|---:|---:|---:|---:|']
    for name in ['original','full_dso','no_dso',nominee,combined]:
        v=final['absolute'][name]
        lines.append(f"| {labels[name]} | {v['rps']:.2f} | {v['mean_ms']:.4f} | {v['p99_ms']:.4f} | {v['stack_cpu']:.2f} | {v['util_pct']:.2f}% |")
    maximum=max(effect(c[name]['original'],'inverse_rps')[0] for name in ['full_dso','no_dso',nominee,combined])
    lines+=['',f'원본 대비 처리량 증가의 최대 점추정은 {maximum:+.2f}%다. '+
            ('10% 목표에는 도달하지 못했다.' if maximum<10 else '10% 점추정을 넘었으며 각 비교의 불확실성은 아래 구간에 표시했다.')]
    lines+=['','표는 산술평균, 아래 변화율은 같은 블록의 로그 비율이다. 양수는 개선, 음수는 악화다. '
        '구간은 다중 비교 보정 없는 개별 paired-log t95다. 3회 반복이면 작은 차이의 불확실성이 크다.', '',
        '| 비교 | 처리량 증가 | 평균 지연 절감 | p99 절감 | CPU/request 절감 |','|---|---:|---:|---:|---:|']
    for name,control in [('full_dso','original'),('no_dso','original'),(nominee,'original'),(combined,'original'),
                          (nominee,'no_dso'),(combined,'full_dso'),(combined,nominee)]:
        lines.append('| '+labels[name]+' / '+labels[control]+' | '+' | '.join(interval(c[name][control],k)
                     for k in ['inverse_rps','mean_ms','p99_ms','stack_cpu'])+' |')
    baseline=report['baseline_variation']
    lines+=['',f'![독립 확인의 처리량·지연·CPU 변화](figures/{TAG}_endpoint_effects.png)','',
        f"독립 확인 원본 RPS의 변동계수는 {baseline['cv_pct']:.2f}%, 범위는 {baseline['min_rps']:.2f}–{baseline['max_rps']:.2f}다. "
        '탐색의 가장 빠른 실행 하나를 최종 speedup으로 사용하지 않았다.', '',
        '## RPC에서 무엇을 이용했나', '',
        'Thrift RPC 타입이 정해진 decoder 호출, 실제 handler의 첫 direct call, 그리고 타입이 고정된 '
        '`std::async` 작업의 `_M_run` 첫 direct call을 후보로 삼았다. 이전 전체 정책의 잔여 L2 PEBS와 '
        '최근 32개 분기 LBR에서 RPC/handler/작업 타입을 식별해 main ELF의 다음 코드 라인을 골랐다. '
        '이번에는 handler 입구 두 라인을 의무적으로 넣지 않고 미스가 관측된 내부 경로를 우선했다.', '',
        '```mermaid','flowchart LR','  A[RPC 타입 결정] --> B[인자 디코딩] --> C[Handler] --> D[비동기 작업 생성]',
        '  D --> E[새 작업 스레드 실행] --> F[작업 타입별 코드 prefetch] --> G[call_once와 콜백] --> H[후속 RPC]',
        '```','',
        '본 확인 후보는 MovieId·ComposeReview·Rating의 6개 호출 지점에 힌트 23개, 코드 220바이트를 추가한다. '
        '부모 스레드에만 발행하던 방식과 달리 실제 작업 스레드 안에서 타입별 후속 코드를 가져온다. '
        '발행 후 CPU migration을 금지하거나 정확한 fetch lead-time을 측정한 것은 아니다. '
        '이미 선택된 코드 타입과 별도 과거 trace를 사용하며, 현재 요청의 미래 결과를 읽거나 handler를 미리 실행하지 않는다.', '',
        '| 탐색 정책 | 추가 지점 | 추가 힌트 | 추가 코드 B | 내용 |','|---|---:|---:|---:|---|',
        '| `rpc_route` | 13 | 95 | 770 | RPC별 decoder 직전에 후속 경로 타깃 발행 |',
        '| `rpc_worker` | 6 | 23 | 220 | 실제 typed async worker의 첫 direct call 직전에 T1 |',
        '| `rpc_staged` | 31 | 137 | 1343 | decoder·handler·작업 스레드에 나눠 발행 |',
        '| `rpc_worker_it0` | 6 | 23 | 220 | 같은 위치·주소·분기를 유지하고 새 worker 힌트만 IT0 |',
        f'| `{combined}` | 6 | 23 | 220 | 선택한 worker 힌트를 기존 DSO 포함 정책에 결합 |','',
        '모든 이전 힌트와 원래 명령 주소를 그대로 보존하는 두 번째 stub 삽입이다. '
        'worker의 기존 local 힌트까지 합해 지점당 최대 8개다. IT0 비교는 추가 힌트의 ModRM '
        '23바이트만 바뀐 것을 검사했다. 커널이나 schedule-in hook을 바꾸지 않았고 새 DSO 타깃도 추가하지 않았다. '
        '결합판은 이미 확인된 기존 DSO·MongoDB 정책을 유지한다.', '',
        '훈련 잔여 표본과의 정적 주소 겹침은 route 6.88%, worker 2.08%, staged 8.78%였다. '
        '이 값은 이번 타깃 선택에 사용한 훈련 자료의 수치다. 실제 미스 감소율이나 독립 검증 커버리지, '
        '속도 향상 상한으로 해석하지 않는다. 기존 handler 입구 위주 정책의 1.81%와는 선택 규칙도 다르다.', '',
        '## 두 탐색 단계', '',
        '각 단계에서 같은 seed 블록끼리 비교하며 서로 다른 단계의 값을 합산하지 않는다. '
        '첫 단계의 worker 처리량 +1.61%는 두 번째 단계에서 재현되지 않았다. '
        '두 번째 단계에서는 no-DSO 대조군이 앞섰으며, T1은 결합 실험의 확인 대상으로 고정했을 뿐 '
        '성능 향상이 확인된 정책으로 승격하지 않았다.', '',
        '| 단계 | 정책 | RPS | 평균 ms | p99 ms | CPU µs/request |','|---|---|---:|---:|---:|---:|']
    for phase in ['screen','screen2']:
        for name,v in report['phases'][phase]['absolute'].items():
            lines.append(f"| {phase} | {name} | {v['rps']:.2f} | {v['mean_ms']:.4f} | {v['p99_ms']:.4f} | {v['stack_cpu']:.2f} |")
    if 'training_classification' in report:
        training=report['training_classification']
        lines+=['','잔여 훈련 표본을 RPC 문맥에 연결하는 단계에서도 커버리지가 제한됐다. '
            f"decoder·handler·worker 중 하나로 분류된 비중은 {training['recognized_rpc_pct']:.2f}%였다. "
            '최근 32개 분기에서 문맥을 찾는 방식으로는 긴 공통 함수 경로의 RPC 타입을 모두 복원하지 못한다. '
            '아래는 요청 수로 정규화한 훈련 표본 분포이며 실제 raw L2 miss의 원인 분해가 아니다.', '',
            '| 훈련 표본 영역 | 비중 |','|---|---:|']
        for key,label in [('outside_main','main ELF 밖'),('not_original_instruction','원본 ELF에서 명령어로 해석되지 않은 주소'),
                          ('main_unclassified','main ELF이지만 RPC 문맥 미분류'),('context_decoder','RPC decoder 문맥'),
                          ('context_handler','handler 문맥'),('context_worker','typed worker 문맥')]:
            lines.append(f"| {label} | {training['categories'][key]['pct']:.2f}% |")
        lines+=['','원본 명령어로 해석되지 않은 주소를 전부 주입 stub이라고 단정하지 않았다. '
            '이 분류와 최종 타깃의 2.08% 주소 겹침은 타깃 선정 범위가 좁다는 증거이며, BTB miss 비중이나 속도 개선 상한은 아니다.']
    lines+=['','## 이번 추가가 겨냥한 CPU 비용', '',
        'Clean E2E 실행의 cgroup CPU 회계다. 변경한 세 앱의 사용자 시간에는 프리패치로 줄일 수 없는 명령 실행도 포함된다. '
        '커널 시간에는 해당 프로세스가 실행한 커널 코드가 포함되며, 아래 비중을 latency 개선 상한으로 해석하지 않는다.', '',
        '| 정책 | 세 앱 사용자 µs/request | 세 앱 커널 µs/request | 세 앱 사용자 / 전체 CPU |','|---|---:|---:|---:|']
    for name in ['original','full_dso',combined]:
        v=final['absolute'][name];cpu=v['service_cpu'];user=cpu['targets:user_us/request'];kernel=cpu['targets:system_us/request']
        lines.append(f"| {labels[name]} | {user:.2f} | {kernel:.2f} | {100*user/v['stack_cpu']:.2f}% |")
    lines+=['','## Prefetch 자체의 PMU 효과', '',
        '결합판과 새 23개 힌트만 NOP으로 바꾼 동일 배치 대조군을 별도로 측정했다. '
        '이 PMU 실행의 처리량·지연은 위 speedup 계산에서 제외한다. '
        '아래는 실제 바꾼 앱 서버 3개(MovieId·ComposeReview·Rating)의 사용자 코드 합계이며, '
        '앱 서버 전체 9개나 MongoDB의 합계가 아니다. 서비스·이벤트별 3초 창의 HTTP 완료 수로 정규화했다. '
        '정책당 진단 1회이므로 작은 PMU 차이는 반복 일관성이 검증된 값이 아니다.', '',
        '| 요청당 이벤트 | RPC NOP | RPC prefetch | 변화 |','|---|---:|---:|---:|']
    metrics={'cache:L2I':'L2 code-read miss','cache:FE_L2':'Retired L2 code miss','translation:FE_L1':'Retired L1I miss',
        'cache:ICACHE_DATA_STALL':'I-cache data stall cycles','translation:ITLB_WALK_ACTIVE':'ITLB page-walk active cycles',
        'translation:DTLB_LOAD_WALKS':'DTLB load walk 완료','translation:DTLB_STORE_WALKS':'DTLB store walk 완료',
        'prefetch:T1_T2_EXECUTED':'T1/T2 실행','prefetch:SWPF_MISS':'Software-prefetch L2 miss',
        'prefetch:SWPF_HIT':'Software-prefetch L2 hit','prefetch:L1D_FB_FULL':'L1D fill-buffer full',
        'topdown:topdown-fe-bound:u':'Frontend-bound slots'}
    for key,label in metrics.items():
        v=report['pmu']['contrast'][key]
        lines.append(f"| {label} | {v['nop']:,.2f} | {v['prefetch']:,.2f} | {v['change_pct']:+.2f}% |")
    for key,label in [('frontend_pct','Frontend-bound slots %'),('backend_pct','Backend-bound slots %')]:
        v=report['pmu']['contrast'][key]
        lines.append(f"| {label} | {v['nop']:.2f} | {v['prefetch']:.2f} | {v['prefetch']-v['nop']:+.2f}%p |")
    v=report['pmu']['contrast']
    lines+=['',f"새 힌트를 켰을 때 raw L2 code-read miss는 {v['cache:L2I']['change_pct']:+.2f}%, "
        f"retired L2 이벤트는 {v['cache:FE_L2']['change_pct']:+.2f}% 변했다. "
        '이 진단에서 새 RPC 타깃이 미스를 크게 줄였다고 해석할 근거는 없다. '
        '선정된 worker 타깃과 훈련 잔여 표본의 주소 겹침 자체가 2.08%로 좁았고, 추가 23개 중 3개는 발행 지점과 같은 캐시 라인이었다. '
        '타깃 선정의 제한은 확인했지만, 정확한 hint-to-fetch 시간과 하드웨어 수용 여부는 측정하지 않았다.', '',
        f"수정한 세 앱의 사용자 slot 비중은 frontend {v['frontend_pct']['prefetch']:.2f}%, "
        f"backend {v['backend_pct']['prefetch']:.2f}%다. "
        '이 둘을 전체 요청 시간 비중으로 바꾸거나 남은 frontend 비용을 전부 BTB miss로 분류하지 않는다. '
        '앞의 원본 대비 E2E 이득과 새 힌트 자체의 효과는 별도 비교이며, 아래 동일 배치 NOP의 clean E2E 결과로 후자를 추가 점검했다.']
    lines+=['','Raw L2 code-read와 retired L2 miss는 다른 이벤트다. I-cache stall 표는 cycle 수이며 발생 구간 수가 아니다. '
        'T1/T2 실행은 speculative 카운트이며 기존 데이터 프리패치도 포함한다. L1D fill-buffer 지표는 instruction fetch queue의 점유율이 아니다. '
        'DTLB walk 전체를 software-prefetch 탓으로 분류하지 않는다. Frontend/backend 비율은 사용자 slot 비율이며 요청 지연 비중이 아니다. '
        '이 자료만으로 fetch queue가 비었는지, 정확한 hint-to-fetch 시간, BTB miss 비율을 판정하지 않는다.', '',
        '## 측정·보존', '',
        f"Clean E2E {report['complete']['clean_trials']}회, 별도 PMU 2회, 전체 스택 smoke {report['complete']['smoke_trials']}회를 완료했다. "
        'MovieId 포함 Media compose-review 전체 HTTP 요청, balanced C4 지속 연결, 서버 CPU32–39의 8개 CPU, '
        '2GHz, tracing100%, 매번 새 스택·데이터와 50초 warmup·60초 ROI다. '
        '최대 처리량을 다시 찾는 부하 스윕이나 다른 Media API 검증은 아니다. '
        '고정 closed-loop 동시성의 처리량과 평균 지연은 연관되므로 독립 증거 두 개로 세지 않는다.', '',
        '공유 호스트의 다른 작업은 건드리지 않았다. 측정 중 빌드나 무거운 분석을 겹치지 않았다. '
        '유효한 실행을 성능에 따라 제외·재시도하거나 확인값을 보고 RPC 구현을 다시 선택하지 않았다. '
        '기존 native 테스트 28개를 통과한 stub writer의 소스 해시가 동일함을 확인했고, '
        '이번 ELF별 기존 힌트 보존·타깃 경계·정확한 IT0 byte 변경 및 전체 요청 기능을 검증했다.', '',
        '단계별 탈락 정책은 수치·명령·소스·patch·해시·사유를 보존한 뒤 생성 ELF를 제거했다. '
        '최종 설정 복원과 실험 컨테이너·네트워크·볼륨 제거를 감사했다. 원본 입력과 공유 의존성은 유지했고 NAS I/O는 없었다.', '',
        f'[전체 수치](../llvm_prefetchit/migration/evidence/{TAG}/report.json), '
        f'[최종 결정](../llvm_prefetchit/migration/evidence/{TAG}/final_decision.json), '
        f'[복원 감사](../llvm_prefetchit/migration/evidence/{TAG}/final_restoration_audit.json), '
        f'[검증된 기록 목록](../llvm_prefetchit/migration/evidence/{TAG}/records_manifest.json). '
        '압축 기록의 모든 구성 파일을 SHA-256으로 검증했다.', '',
        '구현: [RPC/worker 타깃 선정](../llvm_prefetchit/scripts/class_b/rpc_route_study.py), '
        '[기존 정책 결합·진단](../llvm_prefetchit/scripts/class_b/rpc_route_followup.py), '
        '[독립 검증](../llvm_prefetchit/scripts/class_b/rpc_route_finish.py).','']
    if 'resumption' in report:
        lines+=['## 중단과 재개 기록','',
            '오전 독립 확인은 8회가 완료되고 9번째 실행 중 중단됐다. 중단된 실행의 시작보다 뒤인 호스트 boot 시간을 확인했다. '
            '완료 8회의 원자료·설정·해시는 보존하고 중단된 확인 묶음 전체를 최종 확인 통계에서 제외했다. '
            '성능값에 따라 재시도 대상을 고르지 않았으며, 고정한 5개 후보와 3개 블록 순서를 유지해 재부팅 후 15회를 새 seed로 실행했다. '
            '재개 전 생성된 실험 컨테이너와 임시 DB 볼륨을 제거했고, 원본 입력은 유지했다.', '',
            '정상 완료된 실행은 설정 복원을 검증했다. 재부팅으로 끊긴 실행은 정상적인 MSR/sysfs 복원을 했다고 주장하지 않는다. '
            '재개 후 실행은 새 부팅 상태를 각각 기록하고 그 상태로 복원했다. '
            f"따라서 clean E2E 집계 {report['complete']['clean_trials']}회 외에, 통계에서 제외한 중단 전 완료 8회와 미완료 1회의 기록이 별도로 남아 있다.", '',
            f'[재개·정리 기록](../llvm_prefetchit/migration/evidence/{TAG}/resumption.json), '
            '[재개 구현](../llvm_prefetchit/scripts/class_b/rpc_route_resume.py).','']
    if 'same_line' in report['phases']:
        extra=report['phases']['same_line'];name='full_rpc_worker_pruned'
        lines+=['## 이미 실행한 캐시 라인 힌트 3개 제거','',
            '별도 정적 점검에서 MovieId의 2개, Rating의 1개 추가 힌트가 원래 발행 callsite와 같은 64바이트 라인을 가리켰다. '
            '기존 검증 도중 코드나 후보를 바꾸지 않고, 그 검증과 PMU 종료 후 3개만 같은 길이 NOP으로 바꾼 20-hint 버전을 만들었다. '
            f"다른 바이트·주소·분기·CFI·기존 힌트는 모두 같음을 검사하고 smoke 후 새 두 블록 {extra['trials']}회로 비교했다. "+
            '이는 발행 제거 효과를 분리하는 실험이며 파일 크기나 코드 배치를 줄인 실험은 아니다.', '',
            '향후 타깃 생성기에서도 발행 라인을 제외하도록 수정했다. 이 20-hint 측정에서는 차순위 타깃을 채우지 않고 기존 목록의 3개만 제거했다.', '',
            '| 정책 | RPS | 평균 ms | p99 ms | CPU µs/request |','|---|---:|---:|---:|---:|']
        for policy,label in [('full_dso','기존 정책'),('full_rpc_worker','작업 힌트 23개'),('full_rpc_worker_nop','새 힌트만 모두 NOP'),(name,'작업 힌트 20개')]:
            v=extra['absolute'][policy]
            lines.append(f"| {label} | {v['rps']:.2f} | {v['mean_ms']:.4f} | {v['p99_ms']:.4f} | {v['stack_cpu']:.2f} |")
        lines+=['','| 20-hint 비교 | 처리량 증가 | 평균 지연 절감 | p99 절감 | CPU/request 절감 |','|---|---:|---:|---:|---:|']
        for control,label in [('full_dso','기존 정책 대비'),('full_rpc_worker','23-hint 대비'),('full_rpc_worker_nop','새 힌트 전부 NOP 대비')]:
            lines.append('| '+label+' | '+' | '.join(interval(extra['comparisons'][name][control],key)
                for key in ['inverse_rps','mean_ms','p99_ms','stack_cpu'])+' |')
        lines+=['',f"23-hint / NOP의 clean 처리량 증가는 {interval(extra['comparisons']['full_rpc_worker']['full_rpc_worker_nop'],'inverse_rps')}다. "+
            'NOP 대조군도 기존 프리패치는 그대로 유지하며, 새 힌트만 끈다. 추가 stub과 주소 배치가 같으므로 이 비교로 새 prefetch 자체의 효과를 분리한다.', '',
            '위 PMU 표는 23-hint 버전의 결과다. 20-hint의 PMU 감소율로 인용하지 않는다. '
            '두 블록 비교는 앞의 세 블록과 합산하지 않으며, 개별 95% 구간과 사전 기록한 승격 규칙을 적용했다. '
            +('20-hint를 새 참고 정책으로 보존했다.' if name in decision['retained_new_references'] else '20-hint의 추가 이득도 승격 규칙을 충족하지 않아 기존 결정을 유지한다.'), '',
            f'[같은 라인 제거 기록](../llvm_prefetchit/migration/evidence/{TAG}/same_line_encoding_validation.json), '
            '[구현](../llvm_prefetchit/scripts/class_b/rpc_route_prune.py).','']
    (root/'report.md').write_text('\n'.join(lines))


def audit(root):
    assert load(root/'measurement_complete.json')['valid']
    comparisons=[];settings={};interrupted=[]
    resume=load(root/'resumption.json') if (root/'resumption.json').exists() else None
    interrupted_platform=Path(resume['interrupted_platform']) if resume else None
    for name in ['platform_before.json','hwp_before.json']:
        for before in sorted(root.rglob(name)):
            if interrupted_platform is not None and before.is_relative_to(interrupted_platform):
                assert resume['cleanup_complete'] and resume['boot_epoch']>resume['interrupted_trial_started']
                interrupted.append(str(before.relative_to(root)))
                continue
            after=before.with_name(name.replace('_before','_restored'))
            valid=after.exists() and load(before)==load(after);assert valid,before
            comparisons.append(dict(before=str(before.relative_to(root)),restored=valid))
            if name=='platform_before.json':
                for path,value in load(before).items():settings.setdefault(path,set()).add(value)
    current=[dict(path=path,actual=Path(path).read_text().strip(),expected=sorted(values)) for path,values in sorted(settings.items())]
    assert current and all(v['actual'] in v['expected'] for v in current)
    latest=max((root/'diagnostics').glob('*_platform'),key=lambda p:(p/'command.json').stat().st_mtime)
    expected={}
    # The first nested context records the baseline for shared controls;
    # later contexts record the baseline for their own per-CPU controls.
    for cpu in load(latest/'command.json')['cpus']:
        for path,value in load(latest/f'cpu{cpu}'/'platform_before.json').items():expected.setdefault(path,value)
    latest_check=[dict(path=path,expected=value,actual=Path(path).read_text().strip()) for path,value in expected.items()]
    assert all(v['actual']==v['expected'] for v in latest_check)
    project='codex-b-fullset-media';owned={}
    for kind,command in [('containers',['docker','ps','-aq']),('networks',['docker','network','ls','-q']),('volumes',['docker','volume','ls','-q'])]:
        owned[kind]=subprocess.check_output(command+['--filter','label=com.docker.compose.project='+project],text=True).splitlines()
    assert not any(owned.values()),owned
    modules={name:Path('/sys/module',name).exists() for name in ['wake_prefetch','prefetchit']};assert not any(modules.values())
    quality=[]
    for phase in ['screen','screen2','confirmation']+(['same_line'] if (root/'same_line/complete.json').exists() else []):
        for row in load(root/phase/'rows.json'):
            info=load(Path(row['output'])/'load/load.json')
            assert row['valid'] and info['mapping_preserved'] and not info['steady_errors']
            quality.append(dict(phase=phase,block=row['block'],arm=row['arm'],steady_errors=info['steady_errors'],
                mapping_preserved=info['mapping_preserved'],warmup_errors=info['errors']))
    old_tests=load(Path('/storage/prefetchit/class_b_rpc_future_20261001/tests_nested.json'))
    for path,digest in old_tests['sources'].items():assert b.sha(b.REPO/path)==digest
    decision=load(root/'final_decision.json');prepared=load(root/'prepared_candidates.json')
    keep=set();expected={}
    for name in decision['retained_new_references']:
        for kind in ['arm','nop']:keep.update(arm_paths(prepared[name][kind]))
        for row in prepared[name]['builds'].values():
            for key,digest in [('binary','sha256'),('nop','nop_sha256')]:
                expected[Path(row[key])]=row[digest]
    retained=[]
    for path in (root/'builds').rglob('*'):
        if path.is_symlink() or not path.is_file():continue
        with path.open('rb') as stream:elf=stream.read(4)==b'\x7fELF'
        if elf:
            assert path.resolve() in keep,path
            digest=b.sha(path);assert expected[path]==digest,path
            retained.append(dict(path=str(path),bytes=path.stat().st_size,sha256=digest))
    result=dict(valid=True,epoch=time.time(),platform_comparisons=comparisons,current_sysfs=current,
        latest_platform_baseline=latest_check,
        interrupted_records_without_normal_restoration=interrupted,
        hwp_note='Each privileged wrapper checked exact MSR restoration; final audit uses those records.',
        owned_resources=owned,modules=modules,endpoint_quality=quality,retained_generated_elves=retained,
        unchanged_tested_native_sources=old_tests,free_bytes={str(p):shutil.disk_usage(p).free for p in [Path('/'),root]},
        source_sha256=b.sha(__file__))
    b.save(root/'final_restoration_audit.json',result)
    print(json.dumps(dict(valid=True,restored_records=len(comparisons),clean_trials=len(quality),retained_elves=len(retained))))


def publish(root):
    assert load(root/'final_restoration_audit.json')['valid']
    destination=b.REPO/'llvm_prefetchit/migration/evidence'/TAG;destination.mkdir(parents=True,exist_ok=False)
    for name in ['protocol.json','measurement_complete.json','screen_decision.json','screen2_decision.json',
                 'confirmation_selection.json','combined_predeclared.json','final_decision.json','final_restoration_audit.json',
                 'screen_rejected_cleanup.json','screen2_rejected_cleanup.json','final_rejected_cleanup.json',
                 'prepared_summary.json','combined_prepared.json','it0_encoding_validation.json','footprint_summary.json']:
        shutil.copyfile(root/name,destination/name)
    if (root/'resumption.json').exists():shutil.copyfile(root/'resumption.json',destination/'resumption.json')
    for name in ['same_line_predeclared.json','same_line_encoding_validation.json','same_line_decision.json','training_classification.json']:
        if (root/name).exists():shutil.copyfile(root/name,destination/name)
    shutil.copyfile(root/'analysis/report.json',destination/'report.json')
    for path in Path(__file__).parent.glob('rpc_route_*.py'):
        digest=b.sha(path);snapshot=root/'source_versions'/(digest+'.py')
        if not snapshot.exists():snapshot.write_bytes(path.read_bytes())
    files=[];records={};omitted=[]
    for path in sorted(root.rglob('*')):
        if path.is_symlink() or not path.is_file():continue
        relative=str(path.relative_to(root))
        if path.name in ['requests.json.gz','observations.json.gz','perf.data','events.txt','samples.txt',
                         'background_environment.json','work_state.json','progress.py'] or path.name.startswith(('external_cpu_','background_cpu_watch')):continue
        if relative.startswith('plans/'):
            omitted.append(dict(path=relative,bytes=path.stat().st_size,sha256=b.sha(path)));continue
        if path.suffix not in ['.json','.csv','.log','.txt','.py','.s','.ld','.asm']:continue
        with path.open('rb') as stream:assert stream.read(4)!=b'\x7fELF'
        files.append(path);records[relative]=dict(bytes=path.stat().st_size,sha256=b.sha(path),archive='records_00.tar.gz')
    archive=destination/'records_00.tar.gz'
    with tarfile.open(archive,'w:gz') as output:
        for path in files:output.add(path,arcname=str(path.relative_to(root)),recursive=False)
    with tarfile.open(archive) as source:
        assert set(source.getnames())==set(records)
        for member in source:
            data=source.extractfile(member).read();assert len(data)==records[member.name]['bytes']
            assert hashlib.sha256(data).hexdigest()==records[member.name]['sha256']
    assert archive.stat().st_size<90*2**20
    b.save(destination/'records_manifest.json',records)
    b.save(destination/'local_plans.json',dict(root=str(root),records=omitted))
    figures={}
    for extension in ['png','svg']:
        src=root/'analysis'/('endpoint_effects.'+extension);target=b.REPO/'docs/figures'/(TAG+'_endpoint_effects.'+extension)
        shutil.copyfile(src,target);assert b.sha(src)==b.sha(target)
        figures[str(target.relative_to(b.REPO))]=dict(bytes=target.stat().st_size,sha256=b.sha(target))
    report=b.REPO/'docs'/(TAG+'.md');shutil.copyfile(root/'report.md',report)
    manifest={str(p.relative_to(destination)):dict(bytes=p.stat().st_size,sha256=b.sha(p)) for p in destination.iterdir() if p.is_file()}
    b.save(destination/'manifest.json',dict(files=manifest,source=str(root),verified_archive=True,archived_records=len(records),figures=figures,
        report=dict(path=str(report.relative_to(b.REPO)),sha256=b.sha(report)),source_sha256=b.sha(__file__),
        exclusions='No ELF/object/build bulk, datasets, raw/decoded traces, full request lists or identifying details of unrelated host processes. Plans remain local with hashes.'))
    print(json.dumps(dict(evidence=str(destination),archived_records=len(records),archive_bytes=archive.stat().st_size)))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['summarize','audit','publish']);parser.add_argument('root',type=Path)
    args=parser.parse_args();globals()[args.action](args.root)
