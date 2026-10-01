#!/usr/bin/env python3
"""Assemble the Korean report from completed, independently checked records."""
import argparse
import json
from pathlib import Path

import dense_build as b


TAG = 'class_b_temporal_20261001'


def read(path):
    return json.loads(path.read_text())


def residual_interpretation(data):
    lines = []
    for group, label in [('native', '앱'), ('mongo', 'MongoDB')]:
        row = next(item for item in data['residual'] if item['group'] == group and item['kind'] == 'l2')
        pct = row['sample_pct']
        witnessed = sum(value for key, value in pct.items() if key.startswith('matching_stub_observed_'))
        lines.append(f'{label}에 남은 retired L2 miss 표본 중 '
            f'{pct.get("line_not_statically_targeted", 0):.2f}%는 정적 타깃 밖 라인, '
            f'{pct.get("added_hint_stub_fetch", 0):.2f}%는 새 hint stub 코드, '
            f'{pct.get("targeted_line_without_matching_stub_in_bounded_lbr", 0):.2f}%는 타깃이지만 '
            f'최근 32개 분기에 대응 hint stub이 보이지 않는 경우다. '
            f'대응 stub을 실제로 거친 흔적이 있는 경우는 {witnessed:.2f}%다.')
    lines += ['이 분류에서 타깃 밖 비중이 높으면 다른 경로·주소의 커버리지를, stub 비중이 높으면 '
        '추가 실행 코드 자체의 비용을 먼저 다뤄야 한다. 단, 이 비중은 이미 크게 줄어든 잔여 집합의 구성이다. '
        '대응 힌트가 보이는 표본도 늦은 발행·이후 축출·주소 변환 문제 중 어느 하나로 확정할 수 없다.']
    return '\n\n'.join(lines)


def recovery_interpretation(data):
    best = data['selected']
    lines = []
    for group, label in [('native', '앱'), ('mongo', 'MongoDB')]:
        values = data['pmu'][group]['per_request']
        nop = data['pmu_absolute'][best + '_nop'][group]['per_request']
        new = data['pmu_absolute'][best][group]['per_request']
        keys = [('recovery:RECOVERY_CYCLES', 'recovery cycle'),
                ('recovery:CLEAR_RESTEER_CYCLES', 'clear→첫 uop cycle'),
                ('l1:FE_L1', 'L1I miss')]
        parts = [f'{label}:']
        for key, name in keys:
            parts.append(f'{name}는 원본 대비 {values[key]["change_pct"]:+.2f}%, '
                         f'같은 배치 NOP 대비 {100*(new[key]/nop[key]-1):+.2f}%다.')
        lines.append(' '.join(parts))
    lines += ['분기 예측 실패 뒤의 복구 자체와 첫 uop 공급까지의 지연을 분리한 관찰이다. '
        '같은 배치 NOP 대비 recovery는 거의 그대로인데 clear→첫 uop 비용은 줄어, '
        'prefetch가 복구 이후 코드 공급을 도울 수 있다는 해석과 맞는다. '
        '반면 L1I miss는 NOP과 거의 같아, 추가 배치와 실행 경로에서 생긴 L1I 비용이 남았다. '
        '각 카운터는 별도 진단 창에서 얻었고 서로 겹칠 수 있으므로 더해서 요청 지연으로 환산하지 않는다.']
    return '\n\n'.join(lines)


def report(root):
    assert read(root / 'confirmation_and_diagnostics_complete.json')['valid']
    data = read(root / 'analysis/final_summary.json')
    best = data['selected']
    contrast = data['confirmation']['e2e'][best]['original']
    rps = contrast['inverse_rps']
    gain = 100 * (rps['speedup'] - 1)
    ci = [100 * (v - 1) for v in rps['speedup_ci95']]
    prepared = read(root / 'prepared_candidates.json')[best]
    env = read(root / 'analysis/final_environment_summary.json')
    baseline = next(row for row in env['variation'] if row['campaign'] == 'confirmation' and row['arm'] == 'original')
    exploratory = read(root / 'screen1/evaluation.json')['e2e']['pathwide']['original']['inverse_rps']
    trials = sum(len(read(root / campaign / 'rows.json')) for campaign in ('screen1', 'screen2', 'screen3', 'confirmation')
                 if (root / campaign / 'rows.json').exists())
    code = data['footprint']
    hints = sum(row['hints'] for row in prepared['builds'].values())
    nop = data['confirmation']['e2e'][best + '_nop']['original']['inverse_rps']
    hint_effect = data['confirmation']['e2e'][best][best + '_nop']['inverse_rps']
    mongo_contrast = data['confirmation']['e2e'][best]['mongo']['inverse_rps']
    wide_contrast = data['confirmation']['e2e'][best]['pathwide']['inverse_rps']
    native = data['pmu_absolute'][best]['native']['ratios']
    mongo = data['pmu_absolute'][best]['mongo']['ratios']
    cpu = data['cpu_us_per_request'][best]
    original_cpu = data['cpu_us_per_request']['original']
    mongo_code_bytes = next(row['extra_instruction_bytes'] for row in prepared['builds'].values()
                            if Path(row['binary']).name == 'mongod')
    stall_text = []
    for group, label in [('native', '앱'), ('mongo', 'MongoDB')]:
        values = data['pmu'][group]
        duration = values['ratios']['cycles_per_icache_stall_period']
        stall_text.append(f'{label}의 I-cache stall 구간 수는 '
            f'{values["per_request"]["cache:ICACHE_STALL_PERIODS"]["change_pct"]:+.2f}% 변했지만, '
            f'총 stall cycle 변화는 {values["per_request"]["cache:ICACHE_DATA_STALL"]["change_pct"]:+.2f}%다. '
            f'평균 구간 길이는 {duration["before"]:.2f}→{duration["after"]:.2f} cycle이다.')
    lines = [
        '# DSB Media: schedule-in 이후 코드 미스와 전체 요청 성능', '',
        f'2026-10-01, 01:52–08:52 UTC의 7시간 캠페인. 최종 정책은 `{best}`다. '
        f'원본 대비 독립 재검증 처리량 변화는 **{gain:+.2f}%** '
        f'(개별 paired-log 95% CI {ci[0]:+.2f}–{ci[1]:+.2f}%, {rps["pairs"]}쌍), '
        f'평균 지연 절감은 **{contrast["mean_ms"]["cost_reduction_pct"]:+.2f}%**, '
        f'p99 절감은 **{contrast["p99_ms"]["cost_reduction_pct"]:+.2f}%**, '
        f'전체 CPU/request 절감은 **{contrast["stack_cpu"]["cost_reduction_pct"]:+.2f}%**다. '
        '지연·CPU 절감이 음수이면 악화다.', '',
        ('이 운영점의 개별 처리량 대비에서 95% 구간 하한도 0보다 높다.' if ci[0] > 0 else
         '처리량 95% 구간 전체가 0보다 낮아 원본 대비 악화로 나타났다.' if ci[1] < 0 else
         '처리량 95% 구간이 0을 포함하므로, 이 반복 수만으로 처리량 개선을 확정하지 않는다.'), '',
        ('10% 처리량 향상 목표에는 도달하지 못했다.' if gain < 10 else
         '처리량 점추정치는 10% 목표에 도달했다. 구간의 하한과 측정 범위를 함께 해석해야 한다.'), '',
        f'초기 탐색의 `pathwide`는 원본 대비 {100*(exploratory["speedup"]-1):+.2f}%였지만 '
        f'{exploratory["pairs"]}쌍의 탐색값이다. 최종 성능 주장은 위의 새 {rps["pairs"]}쌍 확인값을 사용한다. '
        '서로 다른 시드·측정 시점의 차이를 하나의 원인으로 단정하거나 두 단계를 합산하지 않았다.', '',
        f'MongoDB만 기존 split75로 최적화한 `mongo` 기준 대비 추가 처리량 변화는 '
        f'{100*(mongo_contrast["speedup"]-1):+.2f}% '
        f'(95% CI {100*(mongo_contrast["speedup_ci95"][0]-1):+.2f}–{100*(mongo_contrast["speedup_ci95"][1]-1):+.2f}%)다. '
        '이 비교에는 앱·라이브러리 변경과 MongoDB의 추가 타깃이 함께 포함된다. '
        f'공유 GOT 개선 자체의 `pathwide` 대비 변화는 {100*(wide_contrast["speedup"]-1):+.2f}% '
        f'(95% CI {100*(wide_contrast["speedup_ci95"][0]-1):+.2f}–{100*(wide_contrast["speedup_ci95"][1]-1):+.2f}%)다. '
        '두 추가 대비는 원본 대비 전체 변경의 이득과 구분한다.', '',
        f'최종 원본 {baseline["trials"]}회 RPS의 변동계수는 {baseline["rps_cv_pct"]:.2f}%, '
        f'범위는 {baseline["min_rps"]:.2f}–{baseline["max_rps"]:.2f}다. '
        f'탐색과 확인을 합쳐 {trials}개의 새 스택 실행을 완료했으며, 서로 다른 탐색 단계의 성능 수치는 합치지 않았다.', '',
        f'![독립 재검증의 처리량·지연·CPU 변화와 신뢰구간](figures/{TAG}_final_endpoint_effects.png)', '',
        '## 무엇을 바꿨나', '',
        f'실행 trace의 이전 호출과 실제 코드 미스 주소를 연결하고, 정적 direct-call/CFG 분석으로 '
        f'삽입 가능한 경로를 확인했다. 최종 {code["elf_count"]}개 ELF에 호출 지점 {code["sites"]:,}개, '
        f'힌트 명령 {hints:,}개를 사용한다. 원본에 덧붙인 코드 합계는 {code["appended_code_bytes"]:,}바이트다. '
        '이는 서비스별 메모리 사용량이나 전체 프로세스 크기가 아니라 수정한 ELF별 추가 코드의 합계다.', '',
        '같은 요청을 처리하는 앱 서버 9개, 공유 라이브러리 8종, MongoDB 실행 파일을 함께 최적화했다. '
        'MovieId도 포함했다. 아래 모든 E2E 수치는 compose-review 전체 요청을 잰 결과다.', '',
        '| 단계 | 정책 | 반복/정책 | RPS | 평균 지연 ms | p99 ms | CPU µs/request |',
        '|---|---|---:|---:|---:|---:|---:|',
    ]
    for campaign in ('screen1', 'screen2', 'screen3'):
        path = root / campaign / 'evaluation.json'
        if not path.exists():
            continue
        for name, row in read(path)['absolute'].items():
            costs = row['e2e']
            lines.append(f'| {campaign} | `{name}` | {row["trials"]} | {row["rps"]:.2f} | '
                         f'{costs["mean_ms"]:.4f} | {costs["p99_ms"]:.4f} | {costs["stack_cpu"]:.2f} |')
    lines += ['',
        '`pathwide`는 넓은 trace 경로를 이용한다. `aligned`는 stub의 캐시라인 배치, '
        '`neighbor`는 인접 라인 1개 추가, `shared_anchor`는 DSO 주소 계산용 GOT load 공유, '
        '`native_it0`는 앱/라이브러리의 RIP-relative T1을 IT0으로 교체, '
        '`compact`·`compact16`은 호출 지점 감소를 시험했다. '
        '`repair`는 공유 GOT 방식을 유지하면서 잔여 미스의 다른 호출 경로에 힌트 347개를 추가했다. '
        '이 보강은 호출 지점 수를 늘리지 않았다.', '',
        '탐색 단계에서는 미리 정한 CPU·p99 제한 안에서 처리량이 높은 정책을 선택했다. '
        '선택 이후의 확인 실험으로 다시 승자를 고르지 않았다. 실패·탈락 결과도 모두 보존했다.', '',
        '## 시간에 따른 미스와 남은 위치', '',
        f'![schedule-in 이후 원본과 최종 정책의 미스](figures/{TAG}_final_temporal_overview.png)', '',
        '10–20µs가 모든 서비스의 동일한 최적 구간은 아니었다. 앱의 짧은 실행 구간과 '
        'MongoDB의 긴 실행 구간을 나눴고, 초반뿐 아니라 이후 호출 경로에서도 힌트를 발행했다. '
        '아래 잔여 미스 그래프는 타깃 밖 코드, 대응 힌트가 최근 LBR에 보이지 않는 코드, '
        '삽입한 stub 자체, 대응 힌트가 보이는 코드를 구분한다.', '',
        f'![남은 L2 미스의 위치별 시간 분포](figures/{TAG}_final_residual_time.png)', '',
        residual_interpretation(data), '',
        f'![새 스레드 첫 실행과 재실행을 분리한 L2 미스](figures/{TAG}_final_temporal_origin.png)', '',
        '스케줄 인을 전부 같은 상황으로 다루지 않기 위해, 새 스레드의 첫 실행과 기존 스레드의 '
        '재실행도 나눴다. MovieId·ComposeReview 소스는 요청 경로에서 여러 '
        '`std::async(std::launch::async, ...)`를 사용하며, 실제 FORK·스케줄 기록에서도 '
        '짧게 실행하는 새 스레드가 관찰된다. 이 구분은 초반 미스와 커널 CPU 비중을 해석하는 데 '
        '도움이 되지만, 스레드 생성이 커널 CPU의 얼마를 차지하는지 직접 측정한 것은 아니다.', '',
        f'[서비스별 L2 시간 그래프](figures/{TAG}_matched_miss_age_per_request.png)와 '
        f'[실제 schedule 시간으로 정규화한 그래프](figures/{TAG}_matched_miss_age_exposure.png), '
        f'[L1I](figures/{TAG}_matched_l1_age_per_request.png), '
        f'[128-cycle 이상 delivery gap](figures/{TAG}_matched_lat128_age_per_request.png)도 함께 보존했다.', '',
        'retired L2 true-miss 태그는 해당 미스를 겪은 retired 명령을 센다. '
        'L2 code-read miss는 speculative instruction-fetch 요청도 포함하는 별도 이벤트다. '
        '하나의 감소율을 다른 이벤트 전체의 감소율로 바꿔 말하지 않는다. '
        '힌트가 실행된 흔적은 캐시 채움 완료의 증명이 아니며, 이 자료만으로 실제 fetch queue 점유율이나 '
        '정확한 hint-to-fetch lead-time을 계산할 수는 없다. '
        '주소별 잔여 분류도 precise retired 이벤트에 대한 것이며, 전체 speculative code-read miss의 주소 지도는 아니다. '
        '[Intel 이벤트 정의](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/)', '',
        '## 실제 성능 및 PMU 세부 결과', '',
        (root / 'analysis/final_tables.md').read_text(),
        '## 해석 및 남은 제약', '',
        ' '.join(stall_text) + ' 구간 수와 평균 길이를 구분해야 하며, 구간 수 증가만으로 비용 증가를 판단하지 않는다.', '',
        recovery_interpretation(data), '',
        f'CPU 기준으로 원본에서 MongoDB가 차지한 비중은 '
        f'{100*original_cpu["mongo:cpu_us"]/original_cpu["all:cpu_us"]:.2f}%다. '
        f'이 그룹의 CPU/request가 {100*(1-cpu["mongo:cpu_us"]/original_cpu["mongo:cpu_us"]):.2f}% 줄어 '
        f'전체 CPU를 약 {100*(original_cpu["mongo:cpu_us"]-cpu["mongo:cpu_us"])/original_cpu["all:cpu_us"]:.2f}%p 줄이는 데 기여했다. '
        f'앱 서버 합계의 기여는 약 {100*(original_cpu["native:cpu_us"]-cpu["native:cpu_us"])/original_cpu["all:cpu_us"]:.2f}%p다. '
        '이는 CPU 작업량의 분해이며 각 서비스의 요청 지연을 순서대로 더한 결과가 아니다.', '',
        'T1은 L1I에 직접 채우는 정책이 아니므로 L2에서 가져오는 지연을 줄여도 L1I 미스 횟수가 '
        '같이 줄어든다고 보장되지 않는다. 분기 복구, target을 다시 찾는 시간, ITLB 변환, '
        '삽입 코드 fetch 비용도 구별해야 한다. NOP 대비는 같은 코드 배치에서 prefetch 자체의 순효과를 '
        '보며, 원본 대비는 삽입 비용까지 포함한 시스템 이득을 본다.', '',
        f'이 CPU의 코어별 L1I는 64KiB이고, MongoDB에 덧붙인 코드만 {mongo_code_bytes/1024:.2f}KiB다. '
        '추가 바이트 전부가 동시에 실행되는 working set이라는 뜻은 아니지만, 전체 ELF 대비 크기 증가율만으로 '
        'I-cache 비용을 판단할 수는 없다. 추가 코드·분기·GOT 접근의 합산 비용은 NOP 비교로 확인한다. '
        '`analysis/cache_topology.json`에 실제 workload CPU의 sysfs 기록을 보존했다.', '',
        f'최종 정책의 NOP 대비 처리량 변화는 {100*(hint_effect["speedup"]-1):+.2f}%이고, '
        f'NOP 자체의 원본 대비 처리량 변화는 {100*(nop["speedup"]-1):+.2f}%다. '
        '각 대비의 오차 범위는 위 표와 원자료에 있다.', '',
        f'추가 명령의 실행 빈도도 작지 않다. T1/T2 실행 카운터는 요청당 앱 '
        f'{data["pmu_absolute"][best]["native"]["per_request"]["prefetch:T1_T2_EXECUTED"]:,.0f}회, MongoDB '
        f'{data["pmu_absolute"][best]["mongo"]["per_request"]["prefetch:T1_T2_EXECUTED"]:,.0f}회다. '
        '동일 이벤트의 원본·NOP 값은 0이었다. 힌트 수를 더 늘리는 정책보다, '
        '반복 발행과 새 stub fetch를 줄이면서 실제로 남은 경로를 커버하는 정책이 다음 우선순위다. '
        '이는 다음 탐색 방향이며, 아직 측정하지 않은 정책의 성능을 예측한 수치는 아니다.', '',
        f'최종 사용자 코드의 frontend/backend-bound slots는 앱 '
        f'{native["fe-bound_pct"]:.2f}%/{native["be-bound_pct"]:.2f}%, MongoDB '
        f'{mongo["fe-bound_pct"]:.2f}%/{mongo["be-bound_pct"]:.2f}%다. '
        f'별도로 전체 cgroup CPU/request 중 커널 시간은 '
        f'{100*cpu["all:system_us"]/cpu["all:cpu_us"]:.2f}%다. '
        '사용자 코드 PMU의 비율과 전체 요청의 CPU 구성은 분모가 다르다. '
        '커널 시간은 이번 사용자 코드 힌트로 직접 최적화한 대상이 아니다.', '',
        f'요청당 frontend-bound slot 수 자체의 변화는 앱 '
        f'{data["pmu"]["native"]["per_request"]["topdown:topdown-fe-bound:u"]["change_pct"]:+.2f}%, '
        f'MongoDB {data["pmu"]["mongo"]["per_request"]["topdown:topdown-fe-bound:u"]["change_pct"]:+.2f}%다. '
        '실행 시간이 줄면 전체 slot 수도 줄기 때문에, frontend-bound 비율이 여전히 높다는 사실과 '
        '요청당 frontend 비용이 줄었다는 사실은 동시에 성립할 수 있다.', '',
        'IT0 교체 진단에서는 T1 중간 정책보다 앱의 ITLB page walk 완료가 약 51%, '
        'clear-to-first-uop cycle이 약 20% 늘었고 L1I 미스도 줄지 않았다. '
        '그때 MongoDB는 T1을 그대로 유지했으며 해당 수치가 거의 변하지 않았다. '
        '서로 다른 진단 실행의 관찰이므로 주소 변환 준비가 성능에 영향을 준다는 단서로 해석한다. '
        'IT0가 TLB miss에서 반드시 버려진다거나 fetch queue가 완전히 비어야만 동작한다는 '
        '하드웨어 조건을 입증한 것은 아니다.', '',
        'frontend-bound 비중 전체를 BTB miss라고 볼 수 없다. branch-miss, recovery, '
        'clear-resteer, unknown-branch bubble은 서로 다른 이벤트이며 일부 시간이 겹친다. '
        '분기 타깃 근처의 미스가 많다는 사실도 그 미스가 분기 명령 자체에서 났거나 '
        'BTB 부재 때문에 났다는 뜻은 아니다. 위 표의 절대 횟수·cycle과 잔여 trace 관계를 함께 봐야 한다.', '',
        '## 측정 방법과 재현 자료', '',
        '최종 PMU는 정책별로 서비스·이벤트 그룹당 5초 진단 1회, 시간 분포는 '
        '서비스·이벤트당 8초 capture를 사용했다. PMU 변화율에는 반복 실험의 신뢰구간을 부여하지 않았다. '
        '95% 구간은 별도로 수행한 clean E2E 반복에서 계산한 것이다.', '',
        (root / 'report_methods.md').read_text(), '',
        f'[전체 수치](../llvm_prefetchit/migration/evidence/{TAG}/final_summary.json), '
        f'[독립 재검증](../llvm_prefetchit/migration/evidence/{TAG}/confirmation.json), '
        f'[PMU 원본/NOP/prefetch 요약](../llvm_prefetchit/migration/evidence/{TAG}/final_pmu_summary.json), '
        f'[보존 기록 목록](../llvm_prefetchit/migration/evidence/{TAG}/records_manifest.json). '
        '각 archive 구성 파일은 크기와 SHA-256으로 검증했다. '
        '원본 입력·현재 참조/최종 바이너리·재사용 가능한 compact branch observations는 로컬에 남겼다. '
        '탈락한 실행 파일과 원시/디코딩 trace는 필요한 수치·명령·소스·해시를 뽑은 뒤 제거했다.', '',
        '실험 코드는 [temporal_path_confirm.py](../llvm_prefetchit/scripts/class_b/temporal_path_confirm.py), '
        '[잔여 경로 보강](../llvm_prefetchit/scripts/class_b/temporal_path_repair.py), '
        '[잔여 미스 분석](../llvm_prefetchit/scripts/class_b/temporal_path_residual.py)에 있다. '
        '각 실험의 정확한 명령·설정·소스 스냅샷·바이너리 해시는 evidence archive에 포함했다.', '',
    ]
    (root / 'report.md').write_text('\n'.join(lines))
    b.save(root / 'report_source.json', dict(source_sha256=b.sha(__file__),
        data_sha256=b.sha(root / 'analysis/final_summary.json'), report_sha256=b.sha(root / 'report.md')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    report(parser.parse_args().root)
