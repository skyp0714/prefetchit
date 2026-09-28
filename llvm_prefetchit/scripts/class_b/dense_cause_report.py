#!/usr/bin/env python3
"""Publish measured miss populations without assigning unobserved causality."""
import argparse
import collections
import gzip
import json
from pathlib import Path
import statistics
import subprocess

import dense_build as b


def read(path):
    if path.exists():return json.loads(path.read_text())
    with gzip.open(str(path)+'.gz','rt') as stream:return json.load(stream)
def pct(x,n):return 100*x/n if n else 0


def counter_summary(folder):
    output={}
    for path in sorted(folder.glob('*/result.json')):
        result=read(path);arm=path.parent.name;output[arm]={}
        for service in b.SERVICES:
            rows=[r for r in result['counters'] if r['service']==service]
            events={}
            for row in rows:
                n=row['window']['completed'];co=row['counters']
                for event,value in co.items():
                    if event in ('instructions:u','cycles:u'):continue
                    events.setdefault(event,[]).append(dict(value=value,requests=n,instructions=co['instructions:u'],cycles=co['cycles:u'],scheduled_pct=row['scheduled_pct'][event]))
            output[arm][service]={event:dict(per_request=sum(r['value'] for r in values)/sum(r['requests'] for r in values),
                per_ki=1000*sum(r['value'] for r in values)/sum(r['instructions'] for r in values),
                cycle_pct=pct(sum(r['value'] for r in values),sum(r['cycles'] for r in values)),
                minimum_per_request=min(r['value']/r['requests'] for r in values),maximum_per_request=max(r['value']/r['requests'] for r in values),
                windows=len(values),fully_scheduled=all(r['scheduled_pct']>=99.99 for r in values)) for event,values in events.items()}
    return output


def sampling_summary(analysis):
    output={}
    for arm,services in analysis.items():
        output[arm]={}
        for key,value in services.items():
            events={}
            for event,v in value['events'].items():
                c=v['counts'];n=c['samples']
                branch=sum(count for kind,count in v['instruction_classes'].items() if kind not in ('other','unknown','prefetch'))
                events[event]=dict(samples=n,main_pct=pct(c.get('main_samples',0),n),branch_ip_pct=pct(branch,n),
                    within_64B_pct=pct(c.get('within_64B_of_target',0),n),same_line_pct=pct(c.get('same_line_as_target',0),n),
                    associated_pct=pct(c.get('nearest_branch_target_associated',0),n),
                    preceding_mispredicted_pct=pct(c.get('nearest_branch_mispredicted',0),c.get('nearest_branch_target_associated',0)),
                    static_target_pct=pct(c.get('statically_targeted_samples',0),n),observed_matching_pf_pct=pct(c.get('preceding_matching_pf_samples',0),n),
                    any_observed_pf_pct=pct(c.get('preceding_observed_pf_samples',0),n),
                    dso_pct={k:pct(count,n) for k,count in v['dso_counts'].items()},
                    preceding_branch_pct={k:pct(count,c.get('nearest_branch_target_associated',0)) for k,count in v['preceding_branch_classes'].items()},
                    unmapped=c.get('unmapped',0),ip_not_boundary=c.get('ip_not_instruction_boundary',0),
                    top_functions=v['top_functions'][:10],lead=v['lead_retired_proxy'],footprint=v['footprint'])
            output[arm][key]=dict(events=events,static=value['static_prefetch'])
    return output


def plots(root,counters,samples,pdist):
    import matplotlib
    matplotlib.use('Agg');matplotlib.rcParams['svg.hashsalt']='class-b-cause-20260927'
    import matplotlib.pyplot as plt
    keys=list(b.SERVICES);arms=['base','seq4k_nop','seq4k'];colors=['#777777','#bc5734','#176b87']
    fig,axes=plt.subplots(2,2,figsize=(11,7.4),layout='constrained')
    definitions=[('L2I','per_request','Speculative L2 code misses / request'),('ITLB_WALK_ACTIVE','cycle_pct','ITLB page-walker active / user cycles (%)'),('FE_L2','per_request','Retired L2-miss instructions / request'),('BACLEARS','per_ki','Unknown-branch resteers / 1,000 instructions')]
    for ax,(event,metric,title) in zip(axes.flat,definitions):
        for i,(arm,color) in enumerate(zip(arms,colors)):
            ax.bar([x+(i-1)*.25 for x in range(3)],[counters[arm][k][event][metric] for k in keys],width=.23,color=color,label=arm)
        ax.set(xticks=range(3),xticklabels=['MovieId','ComposeReview','Rating'],title=title,ylim=(0,None));ax.grid(axis='y',alpha=.2)
    axes[0,0].legend(frameon=False)
    fig.suptitle('Dense +4 KiB prefetch: separate diagnostic counters at concurrency 4\nTwo windows in one fresh run per arm; cycle metrics overlap',fontsize=12)
    dest=b.REPO/'docs/figures/class_b_dense_causes_20260927.png';fig.savefig(dest,dpi=180);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    for ax,metric,title in zip(axes,['branch_ip_pct','within_64B_pct'],['Sampled instruction itself is a branch','Sample IP <64 B after latest associated taken target']):
        for i,(event,label,color) in enumerate([('instructions_pdist','Instructions: PDIR','#777777'),('l2_pdist','L2 misses: PDist','#176b87')]):
            ax.bar([x+(i-.5)*.3 for x in range(3)],[pdist[k]['events'][event][metric] for k in keys],width=.28,label=label,color=color)
        ax.set(xticks=range(3),xticklabels=['MovieId','ComposeReview','Rating'],ylabel='Share of all samples (%)',title=title,ylim=(0,100));ax.grid(axis='y',alpha=.2)
    axes[0].legend(frameon=False,fontsize=8)
    fig.suptitle('Branch locality: baseline at concurrency 4; retired LBR association is not causation',fontsize=11)
    dest=b.REPO/'docs/figures/class_b_miss_branch_locality_20260927.png';fig.savefig(dest,dpi=180);plt.close(fig)


def report(root):
    folder=root/'causes_c4';assert (folder/'complete.json').exists()
    counters=counter_summary(folder);samples=sampling_summary(read(folder/'analysis.json'))
    peak=counter_summary(root/'causes_c16') if (root/'causes_c16/complete.json').exists() else None
    pages=[]
    import re
    for path in folder.glob('*/*/smaps.txt'):
        current=None
        for line in path.read_text().splitlines():
            if re.match(r'^[0-9a-f]+-[0-9a-f]+ ',line):
                fields=line.split(None,5)
                current=dict(arm=path.parent.parent.name,service=path.parent.name,mapping=line) if 'x' in fields[1] else None
                if current is not None:pages.append(current)
            elif current is not None and line.startswith(('Size:','KernelPageSize:','MMUPageSize:','FilePmdMapped:','AnonHugePages:')):
                key,value=line.split(':',1);current[key]=value.strip()
    b.save(root/'cause_executable_pages.json',pages)
    b.save(root/'cause_counter_summary.json',dict(c4=counters,c16=peak));b.save(root/'cause_sample_summary.json',samples)
    pdist=read(root/'pdist_sample_summary.json')
    plots(root,counters,samples,pdist)
    lines=['# 고밀도 프리패치의 코드 미스·ITLB·분기 원인 진단','',
        '[동시성·E2E 전체 결과](class_b_dense_and_concurrency_20260927.md)에서 CPU 약 86%인 동시 요청 4개와 처리량 plateau인 16개를 확인했고, 상세 진단은 동시 요청 4개에서 수행했다. '
        '세 대상(MovieId, ComposeReview, Rating) 모두에 같은 정책을 적용했다. `seq4k`는 20 eligible IR 명령마다 RIP+4096의 PREFETCHT1 및 정의된 직접 호출 대상 4라인이다. '
        '재빌드한 세 실행 파일의 SHA는 이전 고밀도 실험과 모두 같았다.','',
        '## 측정과 해석 범위','',
        '8 CPU/2 GHz/C6 off, 서비스당 인스턴스 하나, closed-loop 동시 요청 4. 각 arm은 fresh stack, 50초 warmup, '
        'PMU 없는 30초 ROI 뒤에 세 서비스의 user-mode cgroup PMU를 순차 수집했다. '
        '카운터 6묶음×5초를 두 차례 수집하되 두 번째는 순서를 뒤집었다. 같은 실행의 두 window이며 독립 반복 신뢰구간이 아니다. '
        'retired L2 miss·unknown branch·일반 retired instruction을 각각 8초간 PEBS+LBR로 수집했다. '
        '서로 다른 FRONTEND selector는 같은 MSR을 공유하므로 동시 측정하지 않았다.','',
        '모든 값은 event/request 또는 event/1,000 retired instructions로 정규화했다. '
        'Speculative L2 code request와 retired miss instruction은 서로 다른 모집단이다. 두 수의 차이를 wrong-path 비율로 계산하지 않는다. '
        'page walk active와 cache/resteer cycles는 겹칠 수 있으며, stall 손실률처럼 더하지 않는다. '
        '[Intel GNR 이벤트 정의](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).','',
        '![Separate miss causes](figures/class_b_dense_causes_20260927.png)','',
        '## Cache·translation·branch 지표','',
        '| 서비스 | arm | L2 code miss/request | retired L2 miss/request | ITLB walk/request | walk active / cycles | I-cache data stall / cycles | BACLEAR/ki | branch mispredict/ki |','|---|---|---:|---:|---:|---:|---:|---:|---:|']
    findings=['고밀도 +4 KiB 정책은 원본 대비 순 code miss/request 감소를 만들지 못했다. '
        'MovieId 5,902→5,972, ComposeReview 11,026→11,212, Rating 5,640→5,632였다. '
        '동일 배치 NOP 대비 감소는 각각 −0.19%, +2.89%, +1.50%로 서비스마다 달랐다. '
        '독립 E2E 7묶음 확인에서도 10% 개선은 확인되지 않았다.','',
        '직접 관측한 구현상의 약점은 **미래 실행 경로와 PF target의 불일치**다. '
        '+4 KiB 힌트의 96–98%가 다른 함수로 향하고, 초기 pp miss 표본의 직전 관측 LBR에서 같은 miss line을 겨냥한 PF는 1.3–1.8%였다. '
        '이는 전체 미스의 절대 커버리지 추정값이 아니라 유한한 LBR/표본에서 확인한 수치다.','',
        'PDIR/PDist 교차 확인에서는 미스 IP 자체가 branch인 비중이 3–7%이고, 직전 taken target의 64 B 안에 있는 비중은 94–97%였다. '
        '기준 ITLB page walk active는 user cycles의 9.3–11.5%, 간접 분기 오예측률은 40.8–52.4%였다. '
        'Translation과 prediction 문제가 함께 존재한다. 현재 데이터로 각 code miss를 ITLB 또는 BTB/FDIP 원인으로 완전히 분해할 수는 없다.','']
    lines[2:2]=findings
    for key in b.SERVICES:
        for arm in ('base','seq4k_nop','seq4k'):
            v=counters[arm][key]
            lines.append(f'| {key} | {arm} | {v["L2I"]["per_request"]:.1f} | {v["FE_L2"]["per_request"]:.1f} | {v["ITLB_WALK"]["per_request"]:.1f} | {v["ITLB_WALK_ACTIVE"]["cycle_pct"]:.2f}% | {v["ICACHE_DATA_STALL"]["cycle_pct"]:.2f}% | {v["BACLEARS"]["per_ki"]:.2f} | {v["branch-misses:u"]["per_ki"]:.2f} |')
    lines += ['', '| 서비스 | arm | retired ITLB miss/ki | unknown branch/ki | indirect misprediction / indirect branches | SWPF L2 hit 비중 |','|---|---|---:|---:|---:|---:|']
    for key in b.SERVICES:
        for arm in ('base','seq4k_nop','seq4k'):
            v=counters[arm][key]
            lines.append(f'| {key} | {arm} | {v["FE_ITLB"]["per_ki"]:.2f} | {v["FE_UNKNOWN"]["per_ki"]:.2f} | {pct(v["MISP_INDIRECT"]["per_request"],v["BR_INDIRECT"]["per_request"]):.1f}% | {pct(v["SWPF_HIT"]["per_request"],v["SWPF_HIT"]["per_request"]+v["SWPF_MISS"]["per_request"]):.1f}% |')
    lines += ['', 'BACLEAR는 instruction fetch에서 미등록 분기를 발견해 frontend가 방향을 다시 잡는 지표다. '
        'ITLB walk와 이 이벤트가 실제로 발생한다는 근거를 얻었으나, 어느 하나가 모든 L2 miss의 원인이라는 분해는 아니다. '
        'SWPF hit 비중은 수락·계수된 요청의 L2 hit 비중이고 향후 실행 정확도, fill 성공률, queue-drop 비율은 아니다.','',
        '## 어디서 미스가 발생하는가','',
        '아래 첫 표는 초기 pp 캡처의 값이다. 최종 분기 위치 비교는 이어지는 독립 PDIR/PDist 표와 그래프를 사용한다.','',
        '![Branch locality comparison](figures/class_b_miss_branch_locality_20260927.png)','',
        '| 서비스 | arm | L2 샘플 수 | main ELF 비중 | 미스 IP 자체가 branch | 미스 IP가 직전 taken target에서 <64 B | 초기 ANY_P 참고치(pp)의 <64 B 비중 | 직전 분기의 misprediction 비중 |','|---|---|---:|---:|---:|---:|---:|---:|']
    for key in b.SERVICES:
        for arm in ('base','seq4k_nop','seq4k'):
            event=samples[arm][key]['events'];v=event['l2'];i=event['instructions']
            lines.append(f'| {key} | {arm} | {v["samples"]:,} | {v["main_pct"]:.1f}% | {v["branch_ip_pct"]:.1f}% | {v["within_64B_pct"]:.1f}% | {i["within_64B_pct"]:.1f}% | {v["preceding_mispredicted_pct"]:.1f}% |')
    lines += ['', '초기 ANY_P pp instruction 표본은 branch 비중이 PMU의 retired branch/instruction 비율보다 높아 분포 편향의 우려가 있다. 아래 독립 PDIR 확인과 구분한다. 일반 instruction과 L2 miss의 샘플링 주기·선택 조건이 다르다. 표는 각 모집단 내부의 비중이며 단순 샘플 수를 비교하지 않는다. '
        '분기 명령 자체의 miss와 분기 후 도착한 코드의 miss를 구별했다. '
        '가장 최근 LBR가 샘플 IP 자체이면 그 다음 LBR를 predecessor로 사용한다. 동일 DSO 안에서 target≤IP, 거리≤64 KiB이며 그 사이에 기록되지 않은 무조건 분기/call/return이 없는 경우만 연결한다. '
        '연결되지 않은 샘플도 전체 분모에 유지한다. 분기 직후라는 공간적 관련성만으로 그 분기의 BTB miss가 원인이었다고 단정하지 않는다.','',
        '| 서비스 | baseline miss DSO | 비중 |','|---|---|---:|']
    for key in b.SERVICES:
        for dso,value in sorted(samples['base'][key]['events']['l2']['dso_pct'].items(),key=lambda x:-x[1]):
            if value>=1:lines.append(f'| {key} | {Path(dso).name} | {value:.1f}% |')
    lines += ['', '### Precise Distribution으로 표본 편향 교차 확인','',
        '새 baseline stack/seed 45002에서 L2 miss pp, L2 miss ppp(PDist), instructions ppp(PDIR)를 각각 별도 8초/서비스로 측정했다. '
        'ppp preflight의 precise_ip=3을 기록했고, workload capture 9개 모두 유실·throttle이 없었다. '
        '위의 분기 비교 그래프는 이 독립 ppp 표본만 사용한다. 초기 pp instruction 표본을 unbiased 실행 빈도로 사용하지 않는다. '
        '[Intel의 PDIR 정의](https://github.com/intel/perfmon/blob/main/GNR/events/graniterapids_core.json), '
        '[Linux의 ppp counter 제약](https://github.com/torvalds/linux/blob/v6.8/arch/x86/events/intel/core.c#L4102).','',
        '| 서비스 | L2 pp branch IP | L2 ppp branch IP | PDIR instruction branch IP | L2 ppp target <64 B | PDIR instruction target <64 B |','|---|---:|---:|---:|---:|---:|']
    for key in b.SERVICES:
        v=pdist[key]['events'];a=v['l2'];z=v['l2_pdist'];i=v['instructions_pdist']
        lines.append(f'| {key} | {a["branch_ip_pct"]:.1f}% | {z["branch_ip_pct"]:.1f}% | {i["branch_ip_pct"]:.1f}% | {z["within_64B_pct"]:.1f}% | {i["within_64B_pct"]:.1f}% |')
    lines += ['', 'main ELF에는 정적으로 링크된 C++ runtime과 의존 라이브러리도 포함되므로 main ELF 비중을 서비스 소스의 비중으로 해석하지 않는다. '
        'stripped shared library는 가장 가까운 공개 symbol 범위로만 표시될 수 있어 함수명 정확도가 제한된다.','',
        '| 서비스 | baseline의 주요 miss symbol | 샘플 비중 |','|---|---|---:|']
    for key in b.SERVICES:
        for row in samples['base'][key]['events']['l2']['top_functions'][:6]:
            symbol=row['name'].split('::',1)[-1];demangled=subprocess.check_output(['c++filt',symbol],text=True).strip()
            lines.append(f'| {key} | `{demangled[:150].replace(chr(124),chr(47))}` | {row["share_pct"]:.2f}% |')
    lines += ['', '| 서비스 | baseline L2 miss의 고유 sampled lines | 고유 sampled 4 KiB pages | 두 번 이상 미스 샘플된 line에 속한 샘플 비중 |', '|---|---:|---:|---:|']
    for key in b.SERVICES:
        v=samples['base'][key]['events']['l2'];f=v['footprint']
        lines.append(f'| {key} | {f["unique_sampled_lines"]:,} | {f["unique_sampled_4k_pages"]:,} | {pct(f["samples_on_repeated_lines"],v["samples"]):.1f}% |')
    lines += ['', '이 footprint는 8초 동안 샘플에 나타난 주소의 하한이며 동시에 cache에 있어야 하는 working set 크기는 아니다. '
        '반복 샘플된 line은 첫 실행 한 번의 compulsory miss만으로 설명되지 않는다. '
        '다른 CPU에서의 재진입·eviction·capacity/conflict·분기 경로 문제 중 어떤 원인인지는 이 집계만으로 분리하지 않는다.']
    lines += ['', '## 왜 밀도를 높여도 미스가 남는가: 주소와 실행 이력의 커버리지','',
        '| 서비스 | seq4k의 정적으로 해석된 PF | 해석 못한 PF | +4 KiB가 다른 함수/실행 영역 밖으로 가는 비중 | miss 주소를 정적으로 겨냥한 비중 | 직전 관측 LBR 경로에서 같은 miss line을 겨냥한 PF가 있는 비중 | 직전 경로에 어떤 PF든 있는 비중 |','|---|---:|---:|---:|---:|---:|---:|']
    for key in b.SERVICES:
        v=samples['seq4k'][key];s=v['static'];event=v['events']['l2']
        lines.append(f'| {key} | {s["resolved"]:,} | {s["unresolved"]:,} | {pct(s.get("periodic_other_function",0)+s.get("periodic_outside_executable",0),s.get("periodic_sites",0)):.1f}% | {event["static_target_pct"]:.1f}% | {event["observed_matching_pf_pct"]:.2f}% | {event["any_observed_pf_pct"]:.1f}% |')
    lines += ['', 'PF target는 RIP-relative 주소와 명백한 상수 register 설정만 해석했다. 미해석 대상은 해석 성공으로 가정하지 않는다. '
        '정적 커버리지는 실행 여부를 무시한 주소 교집합이다. 동적 열은 해당 miss 전에 기록된 retired taken-branch 사이의 직선 구간에서 PF site와 target line이 모두 일치하는 경우다. '
        'LBR 길이 밖의 힌트는 보지 못하므로 전체 실행의 절대 커버리지·정확도·prefetch 성공률이 아니다. '
        'NOP에서는 원래 PF 위치를 같은 방식으로 분석해 배치가 동일함을 이용했다. '
        '이 PF coverage 수치는 초기 pp 캡처에서 얻었다. 추가 PDIR/PDist 확인은 baseline의 위치 특성 검증이며 PF arm의 coverage를 ppp로 재측정한 것은 아니다. '
        '기록된 retired 순서·cycle age는 실제 fetch lead time이 아니므로 너무 늦었는지 여부를 확정하지 않는다.','',
        '현재 +4 KiB 방식은 물리적인 주소 증가를 따른다. 분기·호출이 바꾸는 미래 경로와 그 주소가 일치하는지는 별개다. '
        'PREFETCHT1으로 코드 line을 요청해도 branch predictor의 target 등록을 직접 수행하지 않으며, instruction translation 문제 해결도 보장하지 않는다. '
        '가까운 +256 B 정책은 앞선 screen에서 수락된 SWPF의 약 97.4%가 이미 L2 hit였고, +4 KiB는 여기서 실제 경로 커버리지와 함께 판단한다.','',
        'BTB가 FDIP의 경로 추적 범위를 제한할 수 있다는 가설은 '
        '[FDIP 연구](https://arxiv.org/abs/2006.13547) 및 [shadow branch 연구](https://arxiv.org/abs/2408.12592)와 부합한다. '
        '이번 실기계 카운터는 그 가설을 지지하는 간접 지표다. 미스별 BTB 상태나 FDIP queue를 관측하지 않았으며, '
        '논문의 시뮬레이터 개선율을 이 서버의 예상 개선율로 옮기지 않는다.']
    if peak:
        lines += ['', '## 처리량 plateau(동시 요청 16)에서의 교차 확인','',
            '한 번씩 새 스택에서 같은 카운터를 수집한 보조 진단이다. E2E 개선 확인용 독립 반복이 아니다.','',
            '| 서비스 | arm | L2 code miss/request | ITLB walk active / cycles | BACLEAR/ki |','|---|---|---:|---:|---:|']
        for key in b.SERVICES:
            for arm in ('base','seq4k'):
                v=peak[arm][key]
                lines.append(f'| {key} | {arm} | {v["L2I"]["per_request"]:.1f} | {v["ITLB_WALK_ACTIVE"]["cycle_pct"]:.2f}% | {v["BACLEARS"]["per_ki"]:.2f} |')
    quality=[]
    for path in folder.glob('*/*/*/record_types.json'):
        row=read(path);quality.append(dict(path=str(path),records=row,valid=not any(row.get(k,0) for k in ('LOST','LOST_SAMPLES','THROTTLE','UNTHROTTLE'))))
    assert len(quality)==27 and all(r['valid'] for r in quality)
    assert all(v['fully_scheduled'] for services in counters.values() for values in services.values() for v in values.values())
    b.save(root/'cause_quality.json',dict(captures=quality,all_fully_scheduled=True))
    lines += ['', '## 재현·품질·보존','',
        '초기 27개와 추가 PDIR/PDist 9개 PEBS capture 모두 LOST/LOST_SAMPLES/THROTTLE/UNTHROTTLE=0이고, 모든 PMU window는 100% scheduled다. '
        '명령·source/binary SHA·maps·smaps·event 정의·샘플별 집계·상위 IP·cache-line 빈도·품질·삭제 manifest를 보존한다. '
        'raw perf.data는 decode/품질 검증 뒤 제거했고, decoded copy 및 진단용 실행 파일·라이브러리 복사본도 분석 결과를 추출한 뒤 제거했다. '
        '원본 입력·소스·패키지와 현재 baseline은 유지한다.','',
        f'상세 결과: `{root}`. 집계 스크립트: `dense_causes.py`, `dense_cause_analysis.py`, `dense_cause_report.py`.']
    doc=b.REPO/'docs/class_b_dense_miss_causes_20260927.md';doc.write_text('\n'.join(lines)+'\n')
    print(doc)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);a=p.parse_args();report(a.root)
