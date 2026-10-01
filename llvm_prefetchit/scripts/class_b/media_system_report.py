#!/usr/bin/env python3
"""Summarize joint deployment without pooling clean timing and PMU windows."""
import argparse
import collections
import json
from pathlib import Path
import statistics

import dense_build as b
from fullset_study import summarize
from media_system_study import NATIVE, MONGO, MONITORED, LIMIT


def boundaries(root):
    complete=root/'boundaries/complete.json'
    if not complete.exists():return None
    output={}
    for arm in ['original','combined']:
        base=root/'boundaries'/arm
        result=json.loads((base/'result.json').read_text());assert result['valid']
        windows={row['privilege']+':'+row['label']:row for row in result['windows']}
        assert len(windows)==4 and all(w['fully_scheduled'] for w in windows.values())
        stats={}
        for privilege in ['u','k']:
            cache=windows[privilege+':cache']['per_request'];l1=windows[privilege+':l1']['per_request']
            stats[privilege]=dict(code_read_miss=cache['L2I'],retired_l2=cache['FE_L2'],
                icache_stall_cycles=cache['ICACHE_STALL'],retired_l1=l1['FE_L1I'],
                icache_stall_periods=l1['ICACHE_PERIODS'],itlb_walk_cycles=l1['ITLB_WALK_ACTIVE'],
                cycles_per_stall_period=l1['ICACHE_STALL']/l1['ICACHE_PERIODS'],
                code_read_mpki=1000*cache['L2I']/cache['instructions:'+privilege],
                code_read_requests=cache['L2_CODE_ALL'],code_read_miss_pct=100*cache['L2I']/cache['L2_CODE_ALL'])
        symbols={}
        for event in ['cycles','l2']:
            data=json.loads((base/event/'symbols.json').read_text())
            assert data['samples']==data['record_samples'] and not data['unparsed']
            lines=collections.Counter()
            for row in data['instruction_histogram']:lines[(int(row['ip'],16)//64,row['dso'])]+=row['samples']
            symbols[event]=dict(samples=data['samples'],unknown_samples=sum(x['samples'] for x in data['histogram'] if x['symbol']=='[unknown]'),
                top=[dict(row,share_pct=100*row['samples']/data['samples']) for row in data['histogram'][:25]],
                symbol_count=len(data['histogram']),sampled_ip_line_count=len(lines),
                function_top_coverage_pct={n:100*sum(row['samples'] for row in data['histogram'][:n])/data['samples'] for n in [16,64,256]},
                sampled_ip_line_top_coverage_pct={n:100*sum(value for _,value in lines.most_common(n))/data['samples'] for n in [16,64,256]},
                full_record=str(base/event/'symbols.json'))
        trace=json.loads((base/'request_path_summary.json').read_text())
        output[arm]=dict(pmu=stats,symbols=symbols,request_path=trace)
    summary=dict(arms=output,limitation='One fresh diagnostic per arm, separate from timing and from service PMU. CPU pool scope includes other kernel work. Cycles and precise retired L2 samples are separate populations, not call-chain evidence or cache-miss latency. No kernel code changed.')
    b.save(root/'boundary_summary.json',summary)
    return summary


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
    assert set(diag)=={'original','mongo','combined'} and all(len(rr)==2 for rr in diag.values())
    means={arm:{key:statistics.mean(row[key] for row in diag[arm]) for key in diag[arm][0]}
        for arm in ['original','mongo','combined']}
    def pmu(arm,scope,label,event):return means[arm][f'{label}:{scope}:{event}']
    def fe(arm,scope,privilege='u'):
        return 100*pmu(arm,scope,'topdown','topdown-fe-bound:'+privilege)/pmu(arm,scope,'topdown','slots:'+privilege)
    def reduction(a,z):return 100*(1-z/a) if a else None
    services={}
    for key in MONITORED:
        services[key]={arm:dict(code_read_miss=pmu(arm,key,'cache','L2I'),retired_l2=pmu(arm,key,'cache','FE_L2'),
            icache_stall_cycles=pmu(arm,key,'cache','ICACHE_DATA_STALL'),frontend_pct=fe(arm,key),
            frontend_slots=pmu(arm,key,'topdown','topdown-fe-bound:u'),
            itlb_walk_cycles=pmu(arm,key,'front','ITLB_WALK_ACTIVE'),
            unknown_branch_cycles=pmu(arm,key,'front','UNKNOWN_BRANCH_CYCLES'),
            instructions=pmu(arm,key,'cache','instructions:u'),
            backend_pct=100*pmu(arm,key,'topdown','topdown-be-bound:u')/pmu(arm,key,'topdown','slots:u'),
            fetch_latency_pct=100*pmu(arm,key,'topdown','topdown-fetch-lat:u')/pmu(arm,key,'topdown','slots:u')) for arm in means}
    aggregates={}
    for group,keys in dict(native=list(NATIVE),mongo=list(MONGO),monitored=list(MONITORED)).items():
        aggregates[group]={}
        for arm in means:
            counts={k:sum(services[key][arm][k] for key in keys) for k in
                ['code_read_miss','retired_l2','icache_stall_cycles','frontend_slots','itlb_walk_cycles','unknown_branch_cycles','instructions']}
            counts['frontend_pct']=100*counts['frontend_slots']/sum(pmu(arm,key,'topdown','slots:u') for key in keys)
            counts['backend_pct']=100*sum(pmu(arm,key,'topdown','topdown-be-bound:u') for key in keys)/sum(pmu(arm,key,'topdown','slots:u') for key in keys)
            counts['fetch_latency_pct']=100*sum(pmu(arm,key,'topdown','topdown-fetch-lat:u') for key in keys)/sum(pmu(arm,key,'topdown','slots:u') for key in keys)
            counts['icache_stall_cycles_pct']=100*counts['icache_stall_cycles']/sum(pmu(arm,key,'cache','cycles:u') for key in keys)
            counts['unknown_branch_cycles_pct']=100*counts['unknown_branch_cycles']/sum(pmu(arm,key,'front','cycles:u') for key in keys)
            counts['itlb_walk_cycles_pct']=100*counts['itlb_walk_cycles']/sum(pmu(arm,key,'front','cycles:u') for key in keys)
            aggregates[group][arm]=counts
    kernel={arm:dict(frontend_pct=fe(arm,'pool_k','k'),
        frontend_slots=pmu(arm,'pool_k','topdown','topdown-fe-bound:k'),
        backend_pct=100*pmu(arm,'pool_k','topdown','topdown-be-bound:k')/pmu(arm,'pool_k','topdown','slots:k'),
        memory_pct=100*pmu(arm,'pool_k','topdown','topdown-mem-bound:k')/pmu(arm,'pool_k','topdown','slots:k'),
        cycles=pmu(arm,'pool_k','topdown','cycles:k')) for arm in means}
    boundary=boundaries(root)
    results=dict(clean_trials=len(rows),cpu=cpu,cpu_rows=cpu_rows,diagnostic_means=means,services=services,
        kernel=kernel,quality=quality,aggregates=aggregates,limitation=LIMIT,
        boundaries=boundary,
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
        '진단 전용 실행은 warmup 50초 뒤 5초 CPU 구간과 각 3초 PMU 창을 사용한다. 진단 실행의 E2E 수치는 성능 표에 넣지 않는다. '
        'Nginx의 기존 연결당 10만 요청 제한과 top-down 합계 오차 2% 기준으로 무효 처리한 시도는 별도 보존하고, 같은 seed로 재측정했다.',
        '', '| 대상 | FE % 원본 → Mongo만 → 동시 | L2 code-read miss 절감 % | Retired L2 절감 % | I-cache stall cycles 절감 % |',
        '|---|---:|---:|---:|---:|']
    for key,s in services.items():
        a=s['original'];z=s['combined']
        lines.append(f"| {MONITORED[key]} | "+' → '.join(f"{s[arm]['frontend_pct']:.2f}" for arm in ['original','mongo','combined'])+' | '+
            ' | '.join(f"{reduction(a[k],z[k]):+.2f}" for k in ['code_read_miss','retired_l2','icache_stall_cycles'])+' |')
    lines += ['', '| 합산 범위 | FE % 원본 → Mongo만 → 동시 | L2 code-read miss 절감 % | Retired L2 절감 % | I-cache stall cycles 절감 % | ITLB walk cycles 절감 % |',
        '|---|---:|---:|---:|---:|---:|']
    for group,s in aggregates.items():
        lines.append(f"| {group} | "+' → '.join(f"{s[arm]['frontend_pct']:.2f}" for arm in ['original','mongo','combined'])+' | '+
            ' | '.join(f"{reduction(s['original'][k],s['combined'][k]):+.2f}" for k in ['code_read_miss','retired_l2','icache_stall_cycles','itlb_walk_cycles'])+' |')
    lines += ['', 'native는 애플리케이션 서버 9개, mongo는 활발한 DB 3개, monitored는 이 12개와 Nginx다. '
        '합산 FE 비율은 slots 가중치이며, 서로 다른 시점의 request-normalized 창을 합산한 기술 통계다. '
        'L2 code-read miss는 speculative 요청, retired L2는 은퇴 명령어 이벤트로 서로 다른 모집단이다.',
        '', '| 범위 / 정책 | FE slots % | BE slots % | fetch latency slots % | I-cache stall cycles % | unknown-branch cycles % | ITLB walk cycles % |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for group in ['native','mongo']:
        for arm,values in aggregates[group].items():
            lines.append(f'| {group} / {arm} | '+' | '.join(f'{values[k]:.2f}' for k in
                ['frontend_pct','backend_pct','fetch_latency_pct','icache_stall_cycles_pct','unknown_branch_cycles_pct','itlb_walk_cycles_pct'])+' |')
    lines += ['', '비율은 각각 같은 PMU 창의 slots 또는 cycles로 나눴다. 이벤트가 겹치므로 합산하지 않는다. '
        'Unknown-branch bubble은 분기 발견/전환 관련 지연이며, 이 카운터만으로 BTB 부재나 FDIP 실패의 원인을 확정하지 않는다. '
        '[Intel 이벤트 정의](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/)를 따른다.',
        '', '| clean CPU 범위 | 원본 CPU µs/request | 동시 CPU µs/request | user 절감 % [95% CI] | kernel 절감 % [95% CI] |',
        '|---|---:|---:|---:|---:|']
    for group in ['native','mongo','all']:
        absolute={arm:statistics.mean(r['metrics'][group+':cpu_us'] for r in cpu_rows if r['arm']==arm) for arm in ['original','combined']}
        lines.append(f"| {group} | {absolute['original']:.2f} | {absolute['combined']:.2f} | "+
            ' | '.join(pct(cpu['combined']['original'][group+':'+field]) for field in ['user_us','system_us'])+' |')
    lines += ['', '| 커널 CPU 풀 | FE % | BE % | memory-bound % (BE의 부분집합) | FE slots/request | cycles/request |','|---|---:|---:|---:|---:|---:|']
    for arm,k in kernel.items():lines.append(f"| {arm} | {k['frontend_pct']:.2f} | {k['backend_pct']:.2f} | {k['memory_pct']:.2f} | {k['frontend_slots']:.0f} | {k['cycles']:.0f} |")
    lines += ['', '서비스 간 경계는 별도 프로세스의 RPC이며 일반 함수 호출처럼 상대 서버의 주소를 prefetch할 수 없다. '
        '현재 힌트는 각 서버의 주소 공간에서 그 서버가 실행할 코드를 대상으로 한다. '
        '커널 진입·복귀 및 수신 태스크의 스케줄인 경로는 별도의 배치·타깃·대조군이 필요하다. '
        '커널 FE 비율만으로 prefetch의 이득을 확정하지 않으며, 해당 scope에는 스케줄러와 interrupt도 포함된다.',
        '', f"PMU 창 {len(quality)}개 모두 fully scheduled. Top-down raw closure 최대 절댓값은 "+
        f"{max(abs(q['closure_error']) for q in quality if q['closure_error'] is not None):.3f}%. 원자료와 배치·패치·해시는 evidence에 보존한다."]
    if boundary:
        lines += ['', '## 사용자 코드와 커널 코드의 분리 진단','',
            '각 정책을 새 스택으로 한 번 더 실행했다. CPU 풀 전체의 user/kernel을 나눠 집계했으며 '
            '각 5초 창의 완료 요청 수로 정규화했다. 각 행은 해당 모드의 이벤트/request다. '
            'PMU 창과 샘플 수집 구간은 clean 성능 측정과 별개다.',
            '최초 커널 cycles 샘플은 throttle이 검출되어 제외했다. 두 비교 조건 모두 cycles period 1,000,003 및 retired L2 period 1,021로 다시 수집했으며 '
            'LOST/THROTTLE 없는 기록만 함수별 분석에 사용했다. 커널의 샘플링 제한 설정은 바꾸지 않았다.',
            '', '| 정책 / 모드 | L2 code-read miss | retired L2 | retired L1I | I-cache stall cycles | stall periods | ITLB walk cycles | cycles/stall period |',
            '|---|---:|---:|---:|---:|---:|---:|---:|']
        for arm,data in boundary['arms'].items():
            for privilege,values in data['pmu'].items():
                lines.append(f'| {arm} / {privilege} | '+' | '.join(f'{values[k]:.2f}' for k in
                    ['code_read_miss','retired_l2','retired_l1','icache_stall_cycles','icache_stall_periods','itlb_walk_cycles','cycles_per_stall_period'])+' |')
        lines += ['', 'stall periods는 미스 개수가 아니며, cycles/period는 같은 L1 측정 창의 비율이다. '
            '이 비율을 개별 미스 지연으로 해석하지 않는다.',
            '이벤트 정의: [Intel Granite Rapids PMU](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/). '
            'L2 code 요청/미스와 retired 명령어 미스를 직접 나눠 잘못된 분기 경로 비중으로 해석하지 않는다.',
            '', '| 정책 / 커널 표본 | 전체 표본 | 상위 10개 실제 함수와 표본 비중 |','|---|---:|---|']
        for arm,data in boundary['arms'].items():
            for event,s in data['symbols'].items():
                lines.append(f"| {arm} / {event} | {s['samples']} | "+'; '.join(f"`{v['symbol']}` {v['share_pct']:.2f}%" for v in s['top'][:10])+' |')
        lines += ['', 'cycles와 retired L2는 서로 다른 표본이다. 함수별 비중은 측정 위치를 보여주며 '
            '호출 경로·프리패치 효과·syscall 경계의 인과적 비용을 증명하지 않는다. 커널 패치는 적용하지 않았다.']
        lines += ['', '| 정책 / 커널 retired L2 | 관측 함수 수 | 상위 64개 함수의 표본 비중 % | 상위 64개 sampled-IP 64B 구간의 비중 % |',
            '|---|---:|---:|---:|']
        for arm,data in boundary['arms'].items():
            s=data['symbols']['l2'];lines.append(f"| {arm} | {s['symbol_count']} | {s['function_top_coverage_pct'][64]:.2f} | {s['sampled_ip_line_top_coverage_pct'][64]:.2f} |")
        lines += ['', 'sampled-IP 64B 구간은 은퇴 명령어 주소를 묶은 값이며 실제 instruction fetch miss 주소나 prefetch 정확도가 아니다. '
            '한 함수의 전체 코드와 몇 개의 캐시라인을 가져오는 것도 서로 다르다.']
        lines += ['', '## 실제 RPC 요청 추적','',
            '각 경계 진단에서 부하와 PMU가 모두 종료된 뒤 기존 Jaeger의 마지막 5초 구간에서 최대 200개 요청을 조회했다. '
            '아래 span 시간은 하위 호출과 대기를 포함하며 서로 겹친다. CPU 비용이나 독립적인 성능 비교로 사용하지 않는다.',
            '', '| 정책 | trace 수 | parent 누락 trace | API 경고 span |','|---|---:|---:|---:|']
        for arm,data in boundary['arms'].items():
            trace=data['request_path']
            if trace['valid']:
                q=trace['quality'];lines.append(f"| {arm} | {q['traces']} | {q['traces_with_missing_parent']} | {q['spans_with_api_warnings']} |")
            else:lines.append(f"| {arm} | 조회 실패: 별도 기록 | — | — |")
        if any(data['request_path'].get('valid') and data['request_path']['quality']['traces_with_missing_parent'] for data in boundary['arms'].values()):
            lines += ['', '부모 span 누락과 API 경고가 있어 완전한 call graph로 사용하지 않았다. 아래 표는 실제 관측된 operation만 보여준다.']
        original=boundary['arms']['original']['request_path']
        if original['valid']:
            lines += ['', '| 원본에서 관측된 서비스 / operation | span 수 | 평균 span µs |','|---|---:|---:|']
            for row in sorted(original['operations'],key=lambda row:row['mean_us'],reverse=True)[:15]:
                lines.append(f"| {row['service']} / `{row['operation']}` | {row['spans']} | {row['mean_us']:.2f} |")
    decision=root/'decision.json'
    if decision.exists():
        value=json.loads(decision.read_text())
        lines += ['', '## 판정과 다음 정책','']+value.get('report_paragraphs_ko',[])
    lines += ['', '## 구현 검증과 재현','',
        'DSO 식별·배치 선택·기존 call stub 관련 16개 테스트를 통과했다. 공유 라이브러리 지원을 추가한 뒤 call stub 8개 테스트를 다시 통과했다. '
        'PT_PHDR 없는 DSO의 dlopen/dlclose 반복, 함수 인수·복귀 주소, 예외 unwind와 호스트 AT_PHDR 유지를 검사했다. '
        '실서비스 smoke에서는 14,669개 요청을 처리했고, 각 실행에서 실제 프로세스에 매핑된 실행 파일·공유 라이브러리 해시를 확인했다.',
        'E2E는 16개 clean 실행 전체를 보존한다. 진단은 PMU 기준을 만족한 6개 실행과 무효 시도를 함께 보존한다. '
        '플랫폼 설정의 복구 기록, 명령, 원본/수정 바이너리 해시, 어셈블리 패치, source snapshot과 정리 내역은 재현 자료에 포함한다.']
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
