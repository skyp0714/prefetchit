#!/usr/bin/env python3
"""Summarize joint deployment without pooling clean timing and PMU windows."""
import argparse
import json
from pathlib import Path
import statistics

import dense_build as b
from fullset_study import summarize
from media_system_study import NATIVE, MONGO, MONITORED, LIMIT


def report(root):
    evaluation=json.loads((root/'screen_evaluation.json').read_text())
    prepared=json.loads((root/'prepared.json').read_text())
    screen=root/'screen';rows=json.loads((screen/'rows.json').read_text())
    cpu_rows=[]
    for row in rows:
        r=json.loads((Path(row['output'])/'result.json').read_text());values={}
        for key,names in dict(native=[v[0] for v in NATIVE.values()],mongo=list(MONGO.values()),all=list(r['all_services'])).items():
            for field in ['cpu_us','user_us','system_us']:
                values[key+':'+field]=sum(r['all_services'][n][field] for n in names)/r['pool']['completed']
        cpu_rows.append(dict(block=row['block'],arm=row['arm'],valid=True,metrics=values))
    cpu=summarize(cpu_rows,prepared['arms'])
    diag={};quality=[]
    for path in sorted((root/'diagnostics').glob('*/result.json')):
        arm=path.parent.name.split('_',1)[1];r=json.loads(path.read_text());assert r['valid']
        values={}
        for label,scopes in r['pmu_extra'].items():
            for scope,data in scopes.items():
                assert data['fully_scheduled']
                values.update({label+':'+scope+':'+k:v for k,v in data['per_request'].items()})
                quality.append(dict(run=path.parent.name,scope=scope,label=label,closure_error=data.get('topdown_closure_error_pct')))
        for label,scopes in r['pool_pmu'].items():
            for privilege,data in scopes.items():
                assert data['fully_scheduled']
                values.update({label+':pool_'+privilege+':'+k:v for k,v in data['per_request'].items()})
                quality.append(dict(run=path.parent.name,scope='pool_'+privilege,label=label,closure_error=data.get('topdown_closure_error_pct')))
        diag.setdefault(arm,[]).append(values)
    means={arm:{key:statistics.mean(row[key] for row in rr) for key in rr[0]} for arm,rr in diag.items()}
    def pmu(arm,scope,label,event):return means[arm][f'{label}:{scope}:{event}']
    def fe(arm,scope,privilege='u'):
        return 100*pmu(arm,scope,'topdown','topdown-fe-bound:'+privilege)/pmu(arm,scope,'topdown','slots:'+privilege)
    def reduction(a,z):return 100*(1-z/a) if a else None
    services={}
    for key in MONITORED:
        services[key]={arm:dict(code_read_miss=pmu(arm,key,'cache','L2I'),retired_l2=pmu(arm,key,'cache','FE_L2'),
            icache_stall_cycles=pmu(arm,key,'cache','ICACHE_DATA_STALL'),frontend_pct=fe(arm,key),
            frontend_slots=pmu(arm,key,'topdown','topdown-fe-bound:u'),
            itlb_walk_cycles=pmu(arm,key,'front','ITLB_WALK_ACTIVE')) for arm in means}
    kernel={arm:dict(frontend_pct=fe(arm,'pool_k','k'),
        frontend_slots=pmu(arm,'pool_k','topdown','topdown-fe-bound:k'),
        cycles=pmu(arm,'pool_k','topdown','cycles:k')) for arm in means}
    results=dict(clean_trials=len(rows),cpu=cpu,cpu_rows=cpu_rows,diagnostic_means=means,services=services,
        kernel=kernel,quality=quality,limitation=LIMIT,
        diagnostic_interpretation='Two fresh runs per arm, descriptive means; independent of 4-block clean endpoint timing. Service-summed PMU combines separate request-normalized windows.')
    b.save(root/'system_report.json',results)
    def pct(v):
        ci=v['ci95_pct'];return f"{v['cost_reduction_pct']:+.2f}% [{ci[0]:+.2f}, {ci[1]:+.2f}]"
    lines=['# Media 내부 서버 9개와 MongoDB 동시 적용','',
        '전체 Media 스택에 리뷰 쓰기 요청을 보냈다. C4, workload CPU 8개, 2GHz, tracing 100%를 유지했다. '
        '각 정책마다 새 스택·데이터, 50초 warmup, 60초 clean ROI를 사용했다. '
        '요청 처리량·평균/p99·전체 user+kernel CPU가 주 지표다. 최대 처리량 sweep은 아니다.',
        '', '## 전체 요청 성능','',
        '| 정책 | RPS | 평균 ms | p99 ms | CPU µs/request | CPU util % |',
        '|---|---:|---:|---:|---:|---:|']
    for arm,a in evaluation['absolute'].items():
        e=a['e2e'];lines.append(f"| {arm} | {a['rps']:.2f} | {e['mean_ms']:.4f} | {e['p99_ms']:.4f} | {e['stack_cpu']:.2f} | {a['util_pct']:.2f} |")
    lines += ['', '| 정책 / 대조군 | 처리량 배율 [95% CI] | 평균 지연 절감 [95% CI] | p99 절감 [95% CI] | CPU 절감 [95% CI] |',
        '|---|---:|---:|---:|---:|']
    for arm,controls in evaluation['e2e'].items():
        for control,v in controls.items():
            speed=v['inverse_rps'];ci=speed['speedup_ci95']
            lines.append(f"| {arm} / {control} | {speed['speedup']:.5f}× [{ci[0]:.5f}, {ci[1]:.5f}] | "+' | '.join(pct(v[k]) for k in ['mean_ms','p99_ms','stack_cpu'])+' |')
    lines += ['', '4개의 독립 seed block을 사전 순서로 균형 배치했다. 개별 paired-log t95 구간이며 다중비교 보정은 없다. '
        '느린 실행을 성능 기준으로 제외하거나 이전 campaign과 합산하지 않는다.', '', '## 적용 범위','',
        'original은 전체 원본, mongo는 기존 split75만 적용, combined는 split75와 내부 서버 9개 및 선택된 공유 라이브러리의 T1을 동시 적용했다. '
        'combined_nop는 MongoDB split75를 유지하고 내부 서버·라이브러리의 새 힌트만 같은 길이 NOP로 바꿔 점프·배치 비용을 남긴 대조군이다.',
        '', '| 내부 서버 | 삽입 위치 | 힌트 수 | 코드 순증가 bytes | 학습 커버리지 % | 검증 커버리지 % | main ELF 미스 표본 비중 % |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for key,s in prepared['summary'].items():
        lines.append(f"| {NATIVE[key][1]} | {s['sites']} | {s['hints']} | {s['extra_instruction_bytes']} | {100*s['train_coverage']:.2f} | {100*s['heldout_coverage']:.2f} | {100*s['main_sample_fraction']:.2f} |")
    lines += ['', '| 공유 라이브러리 | 삽입 위치 | 힌트 수 | 코드 순증가 bytes | 학습 커버리지 % | 검증 커버리지 % |',
        '|---|---:|---:|---:|---:|---:|']
    for s in prepared.get('library_summary',{}).values():
        lines.append(f"| {s['name']} | {s['sites']} | {s['hints']} | {s['extra_instruction_bytes']} | {100*s['train_coverage']:.2f} | {100*s['heldout_coverage']:.2f} |")
    lines += ['', '각 ELF의 실제 미스·선행 LBR·독립 near-call 빈도를 사용했다. 코드 주소와 호출 복귀 주소를 유지하는 direct-call stub 방식이다. '
        '65% 목표와 위치/발행 예산은 성능 측정 전에 고정했고, heldout은 선택에 사용하지 않았다. '
        '각 커버리지는 해당 ELF의 표본 경로 커버리지이며 실제 prefetch 수락률·정확도·미스 회피율이 아니다. '
        '라이브러리의 전체 native 미스 가중치 중 0.5% 이상을 차지한 DSO를 선택했다. 동일 DSO는 모든 대상 서버에서 같은 수정 파일로 바인딩했다. '
        'main ELF 밖에서 발생한 미스가 새 서버에서 61.5–86.4%여서, clean 성능 비교 전에 공유 라이브러리로 범위를 확장했다.',
        '', 'CastInfo·Plot·MovieInfo는 이번 요청의 주 경로가 아니며 원본이다. Nginx·Redis·Memcached·Jaeger 서버·선택되지 않은 DSO·커널 코드는 이번 패치 범위에서 제외됐다. '
        '따라서 Media의 모든 실행 파일이나 모든 API를 최적화했다고 해석하지 않는다.', '', '## 별도 PMU 진단','',
        '성능 측정이 끝난 뒤 원본/MongoDB만/동시 적용을 각각 새 스택 두 번으로 진단했다. 아래 절감률은 원본 대비 기술 통계이며 clean ROI의 paired 효과와 합산하지 않는다.',
        '', '| 대상 | FE % 원본 → Mongo만 → 동시 | L2 code-read miss 절감 % | Retired L2 절감 % | I-cache stall cycles 절감 % |',
        '|---|---:|---:|---:|---:|']
    for key,s in services.items():
        a=s['original'];z=s['combined']
        lines.append(f"| {MONITORED[key]} | "+' → '.join(f"{s[arm]['frontend_pct']:.2f}" for arm in ['original','mongo','combined'])+' | '+
            ' | '.join(f"{reduction(a[k],z[k]):+.2f}" for k in ['code_read_miss','retired_l2','icache_stall_cycles'])+' |')
    lines += ['', '| 커널 CPU 풀 | FE % | FE slots/request | cycles/request |','|---|---:|---:|---:|']
    for arm,k in kernel.items():lines.append(f"| {arm} | {k['frontend_pct']:.2f} | {k['frontend_slots']:.0f} | {k['cycles']:.0f} |")
    lines += ['', '서비스 간 경계는 별도 프로세스의 RPC이며 일반 함수 호출처럼 상대 서버의 주소를 prefetch할 수 없다. '
        '현재 힌트는 각 서버의 주소 공간에서 그 서버가 실행할 코드를 대상으로 한다. '
        '커널 진입·복귀 및 수신 태스크의 스케줄인 경로는 별도의 배치·타깃·대조군이 필요하다. '
        '커널 FE 비율만으로 prefetch의 이득을 확정하지 않으며, 해당 scope에는 스케줄러와 interrupt도 포함된다.',
        '', f"PMU 창 {len(quality)}개 모두 fully scheduled. Top-down raw closure 최대 절댓값은 "+
        f"{max(abs(q['closure_error']) for q in quality if q['closure_error'] is not None):.3f}%. 원자료와 배치·패치·해시는 evidence에 보존한다."]
    (root/'report.md').write_text('\n'.join(lines)+'\n')
    return results


def plot(root):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    e=json.loads((root/'screen_evaluation.json').read_text())
    fig,axes=plt.subplots(1,3,figsize=(12,3.5),constrained_layout=True)
    comparisons=[('mongo','original','Mongo / original'),('combined','original','Combined / original'),('combined','mongo','Combined / Mongo')]
    for ax,key,title in zip(axes,['inverse_rps','p99_ms','stack_cpu'],['Throughput gain (%)','p99 reduction (%)','CPU/request reduction (%)']):
        for i,(arm,control,label) in enumerate(comparisons):
            value=e['e2e'][arm][control][key]
            if key=='inverse_rps':point=100*(value['speedup']-1);lo,hi=[100*(v-1) for v in value['speedup_ci95']]
            else:point=value['cost_reduction_pct'];lo,hi=value['ci95_pct']
            ax.errorbar(point,i,xerr=[[point-lo],[hi-point]],fmt='o',capsize=4,color=['#356ba2','#168574','#ad6e18'][i])
        ax.axvline(0,color='#777777',lw=.8);ax.set_yticks(range(3),[x[2] for x in comparisons] if ax is axes[0] else [])
        ax.set_title(title);ax.invert_yaxis();ax.grid(axis='x',alpha=.2)
    fig.suptitle('Full Media compose-review: 4 fresh paired blocks, individual 95% intervals')
    fig.savefig(root/'system_e2e.png',dpi=180);fig.savefig(root/'system_e2e.svg');plt.close(fig)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();report(a.root);plot(a.root)
