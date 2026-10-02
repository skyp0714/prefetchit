#!/usr/bin/env python3
"""Render explicit endpoint comparisons and request-normalized residual figures."""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from rpc_route_study import load
from rpc_predict_results import TAG

LABELS = {'original': '원본', 'full': '기존 정책', 'early': '인자 해석 전 T1',
          'late': '핸들러 진입 T1', 'split': '두 단계 분산 T1', 'nop': '동일 배치 NOP',
          'lean': '분산 T1·불필요 슬롯 제거', 'wide': 'RPC별 타깃 확대',
          'reply': '응답 헤더 후 T1 추가', 'reply_it0': '응답 헤더 후 IT0/T1 추가'}
CLASSES = [('not_targeted', '타깃에 없는 코드'), ('incumbent_stub', '기존 삽입 코드'),
           ('new_stub', '이번 삽입 코드'), ('targeted_no_bounded_witness', '타깃·최근 발행 확인 안 됨'),
           ('targeted_with_lbr_witness', '타깃·최근 발행 분기 관측'), ('unmapped', '주소 미분류')]


def label(name):
    return LABELS.get(name, LABELS.get(name.removesuffix('_nop'), name) + '의 NOP')


def effect(row, metric):
    value = row[metric]
    if metric == 'inverse_rps':
        return 100 * (value['speedup'] - 1), [100 * (v - 1) for v in value['speedup_ci95']]
    return value['cost_reduction_pct'], value['ci95_pct']


def formatted(row, metric):
    mid, (lo, hi) = effect(row, metric)
    return f'{mid:+.2f}% [{lo:+.2f}, {hi:+.2f}]'


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |', '|' + '---|' * len(headers)] +
                     ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows])


def save(fig, root, name):
    for suffix in ('png', 'svg'):
        fig.savefig(root / 'analysis' / (name + '.' + suffix), dpi=170, bbox_inches='tight')
    plt.close(fig)


def plots(root, report):
    plt.rcParams.update({'font.family': 'Noto Sans CJK JP', 'axes.unicode_minus': False,
                         'font.size': 10, 'svg.fonttype': 'none'})
    nominee = report['candidate']; e = report['phases']['production_confirmation']['comparisons']
    comparisons = [('full', 'original'), (nominee, 'original'), (nominee, 'full'),
                   (nominee, nominee + '_nop')]
    names = [f'{label(a)} / {label(b)}' for a, b in comparisons]
    fig, axes = plt.subplots(1, 4, figsize=(16, 4.6), sharey=True)
    for ax, metric, title in zip(axes, ['inverse_rps', 'mean_ms', 'p99_ms', 'stack_cpu'],
                                ['처리량 증가', '평균 지연 절감', 'p99 절감', 'CPU/request 절감']):
        for i, (a, b) in enumerate(comparisons):
            mid, (lo, hi) = effect(e[a][b], metric)
            ax.errorbar(mid, i, xerr=[[mid - lo], [hi - mid]], fmt='o', capsize=4,
                        color='#166b8c' if lo > 0 else '#777777')
            ax.annotate(f'{mid:+.2f}%', (mid, i), xytext=(0, 9), textcoords='offset points',
                        ha='center', fontsize=9)
        ax.axvline(0, color='black', lw=.8); ax.grid(axis='x', alpha=.2)
        ax.set_title(title); ax.set_xlabel('개선율 (%) · 오른쪽이 개선')
    axes[0].set_yticks(range(len(names)), names); axes[0].invert_yaxis()
    fig.suptitle('Media 전체 요청: 독립 확인 6블록, 개별 paired-log 95% 구간', y=1.03)
    fig.text(.52, -.02, '원본 대비 효과와 기존 정책에 더해진 효과를 구분. NOP은 새 힌트의 실행 효과 비교.', ha='center')
    fig.tight_layout(); save(fig, root, 'endpoint_effects')

    rows = load(root / 'production_confirmation' / 'rows.json')
    fig, ax = plt.subplots(figsize=(10, 4))
    for name in ('original', 'full', nominee, nominee + '_nop'):
        values = sorted((r['block'] + 1, r['achieved_rps']) for r in rows if r['arm'] == name)
        ax.plot(*zip(*values), marker='o', label=label(name))
    ax.set(xlabel='독립 확인 블록', ylabel='HTTP 요청/초', xticks=range(1, 7),
           title='각 블록의 실제 처리량 · 실행 순서는 정방향/역방향으로 균형화')
    ax.grid(alpha=.2); ax.legend(loc='center left', bbox_to_anchor=(1, .5))
    fig.tight_layout(); save(fig, root, 'endpoint_blocks')

    arms = report['residuals']['arms']
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7), sharey=False)
    for ax, prefix, title in zip(axes, ['', 'mongo_'], ['앱 서버 9개 · 공유 라이브러리 포함', 'MongoDB 3개 · 공유 라이브러리 포함']):
        for name, style in [('full', '-'), (nominee, '--')]:
            points = [v for v in arms[prefix + name]['age_bins'] if v['lo_us'] < 100]
            edges = [v['lo_us'] for v in points] + [100]
            values = [v['events_per_scheduled_us'] if v['events_per_scheduled_us'] is not None else np.nan for v in points]
            ax.stairs(values, edges, label=label(name), linestyle=style, linewidth=1.8)
        ax.axvspan(10, 20, color='#f6b54c', alpha=.2, label='10–20 µs')
        ax.set(xlabel='스케줄러가 태스크를 선택한 후 경과 시간 (µs)',
               ylabel='실행 CPU 시간 1 µs당 retired L2 miss', title=title, xlim=(0, 100))
        ax.grid(alpha=.2); ax.legend(fontsize=9)
    fig.suptitle('스레드 실행 재개 후 코드 미스 발생률', y=1.03)
    fig.text(.5, -.02, '서비스별 별도 8초 PEBS 표본. 커널 제외. 첫 사용자 명령 시점이나 prefetch lead-time을 직접 측정한 그래프가 아님.', ha='center', fontsize=9)
    fig.tight_layout(); save(fig, root, 'miss_over_time')

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for column, (prefix, title) in enumerate([('', '앱 서버 9개'), ('mongo_', 'MongoDB 3개')]):
        for row_index, (origin, origin_label) in enumerate([('new_thread_first_run', '새 스레드 첫 실행'), ('resume', '기존 스레드 실행 재개')]):
            ax=axes[row_index,column]
            for name,style in [('full','-'),(nominee,'--')]:
                points=[v for v in arms[prefix+name]['origin_age_bins'].get(origin,[]) if v['lo_us']<100]
                if not points:continue
                values=[v.get('estimated_events',0)/v['exposure_us'] if v.get('exposure_us') else np.nan for v in points]
                ax.stairs(values,[v['lo_us'] for v in points]+[100],label=label(name),linestyle=style,linewidth=1.8)
            ax.axvspan(10,20,color='#f6b54c',alpha=.2)
            ax.set(title=title+' · '+origin_label,xlim=(0,100),xlabel='태스크 선택 후 경과 시간 (µs)',
                   ylabel='실행 CPU 시간 1 µs당 retired L2 miss')
            ax.grid(alpha=.2);ax.legend(fontsize=9)
    fig.suptitle('스레드 첫 실행과 재개를 분리한 미스 발생률',y=1.01)
    fig.text(.5,-.01,'관측 시작 전에 실행되던 스레드 등 기원을 확정할 수 없는 구간은 이 그림에서 제외. 노출 시간이 없는 구간은 결측.',ha='center',fontsize=9)
    fig.tight_layout();save(fig,root,'miss_by_thread_origin')

    names = ['full', 'nop', 'early', 'late', 'split', 'lean', 'wide', 'reply', 'reply_it0']
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    bottom = np.zeros(len(names))
    colors = ['#526c91', '#cf9262', '#ba4f4f', '#8199aa', '#51a99c', '#bbbbbb']
    for (key, title), color in zip(CLASSES, colors):
        values = np.array([arms[n]['per_request'].get(key, 0) for n in names])
        axes[0].barh(range(len(names)), values, left=bottom, label=title, color=color)
        bottom += values
    axes[0].set_yticks(range(len(names)), [label(n) for n in names]); axes[0].invert_yaxis()
    axes[0].set(xlabel='요청당 retired L2 miss 추정', title='앱 9개 잔여 미스의 위치')
    axes[0].legend(fontsize=8, loc='upper center', bbox_to_anchor=(.5, -.14), ncol=2)
    x = np.arange(len(names)); width=.24
    for index, (key, title) in enumerate([('selected_lines', '처음 고른 주소'),
                                        ('wide_selected_lines', '확대한 주소'), ('reply_selected_lines', '응답용 주소')]):
        axes[1].bar(x + (index-1)*width, [arms[n]['selected_target_events_per_request'].get(key, 0) for n in names], width, label=title)
    axes[1].set_xticks(x, [label(n) for n in names], rotation=55, ha='right')
    axes[1].set(ylabel='요청당 retired L2 miss 추정', title='모든 정책에서 같은 타깃 주소 집합을 비교')
    axes[1].legend(fontsize=8); axes[1].grid(axis='y', alpha=.2)
    fig.text(.5, -.11, '주소 집합끼리는 중복 가능. 정책별 타깃 분류 변화 자체를 미스 감소로 계산하지 않음. 표본 진단값이며 speedup은 별도 clean 실행.', ha='center', fontsize=9)
    fig.tight_layout(); save(fig, root, 'residual_coverage')


def report_text(root, report):
    nominee = report['candidate']; final = report['phases']['production_confirmation']
    e = final['comparisons']; decision = report['decision']
    text = ['# RPC의 알려진 실행 단계를 이용한 코드 프리패치', '',
            '2026-10-02 UTC 실험. Media compose-review 전체 HTTP 요청을 측정했다. 원본 대비 이득과 기존 정책에 더해진 이득을 따로 비교한다.', '',
            f'최종 후보 **{label(nominee)}**의 처리량은 원본 대비 **{formatted(e[nominee]["original"], "inverse_rps")}**, '
            f'기존 정책 대비 **{formatted(e[nominee]["full"], "inverse_rps")}**다. '
            f'같은 코드 배치의 NOP 대비 변화는 **{formatted(e[nominee][nominee+"_nop"], "inverse_rps")}**다.', '',
            ('사전에 정한 승격 기준을 충족해 이 후보를 유지한다.' if decision['promoted'] else
             '사전에 정한 추가 이득의 승격 기준을 충족하지 않아 기존 정책을 유지한다.'), '',
            table(['정책', 'RPS', '평균 ms', 'p99 ms', 'CPU µs/request', 'CPU util'],
                  [[label(n), f'{v["rps"]:.2f}', f'{v["mean_ms"]:.4f}', f'{v["p99_ms"]:.4f}',
                    f'{v["stack_cpu"]:.2f}', f'{v["util_pct"]:.2f}%'] for n, v in final['absolute'].items()]), '',
            table(['비교', '처리량 증가', '평균 절감', 'p99 절감', 'CPU/request 절감'],
                  [[f'{label(a)} / {label(b)}'] + [formatted(e[a][b], m) for m in ('inverse_rps', 'mean_ms', 'p99_ms', 'stack_cpu')]
                   for a, b in [('full', 'original'), (nominee, 'original'), (nominee, 'full'), (nominee, nominee+'_nop')]]), '',
            '표의 절대값은 산술평균, 개선율은 같은 블록의 로그 비율이다. 구간은 다중 비교 보정 없는 개별 paired-log t95다. 최종 확인은 탐색과 별도의 6블록이며 단계별 결과를 합치지 않는다. '
            '고정 closed-loop 동시성에서 처리량과 평균 지연은 서로 연관된다. 최대 처리량을 다시 찾는 부하 스윕 결과는 아니다.', '',
            f'![최종 독립 확인](figures/{TAG}_endpoint_effects.png)', '',
            f'![블록별 처리량](figures/{TAG}_endpoint_blocks.png)', '',
            '## 무엇을 바꾸고 어떻게 구분했나', '',
            '처음에는 RPC별 동일한 타깃 4개를 인자 해석 전, 핸들러의 첫 direct call, 두 단계 분산으로 각각 발행했다. '
            '두 발행 stub과 8개 슬롯을 모두 유지하고 힌트/NOP 바이트만 바꿔 발행 시점과 코드 배치 효과를 구분했다. '
            '이후 활성 힌트만 남긴 작은 구현, RPC별 최대 16개 타깃, 응답 헤더를 받은 뒤의 타입별 재발행, 응답 지점의 첫 2개를 IT0로 바꾼 구현을 비교했다.', '',
            '```mermaid\nflowchart LR\n  A[RPC 타입 결정] --> B[인자 해석 전 T1]\n  B --> C[핸들러 진입 T1]\n  C --> D[후속 RPC 대기]\n  D --> E[응답 헤더 수신]\n  E --> F[응답 타입별 T1 또는 IT0/T1]\n  F --> G[결과 디코딩과 후속 코드]\n```', '',
            '응답 정책은 Thrift Client::recv_METHOD에서 readMessageBegin과 헤더 검사를 지난 presult.read 호출을 이용한다. '
            '이미 알고 있는 RPC 메서드와 응답 처리 타입으로 주소를 고른다. 현재 요청의 미래 결과나 미실행 분기 결과를 사용하지 않는다. '
            '응답 본문을 읽다가 추가로 기다릴 수 있으므로 이 지점이 모든 네트워크 대기 이후라고 가정하지 않는다.', '',
            '모든 타깃은 별도 과거 PEBS/LBR 훈련 자료에서 선택했다. 이번 검증 trace로 타깃을 다시 고르지 않았다. '
            '새 힌트는 9개 앱의 main ELF에만 추가했고 기존 MongoDB·DSO 정책은 유지했다. 커널이나 schedule-in hook은 바꾸지 않았다. '
            '직접 호출 stub을 사용하므로 RPC 이름이나 간접 함수 포인터를 요청마다 검색하는 런타임 코드는 추가하지 않았다.', '',
            f'최종 NOP의 범위: {"새 응답 힌트만 끄며 입력 RPC 힌트는 유지한다" if nominee.startswith("reply") else "이번에 추가한 입력 RPC 힌트를 끄며 기존 정책 힌트는 유지한다"}.', '',
            '## 구현별 탐색 결과', '']
    for phase, title in [('screen', '동일 배치의 발행 시점 비교'), ('confirmation', '발행 시점 후보의 독립 확인'),
                         ('coverage_screen', '슬롯 축소·커버리지·응답 시점 탐색')]:
        p=report['phases'][phase]
        text += [f'### {title}', '', table(['정책', 'RPS', '기존 대비 처리량', '평균 ms', 'p99 ms', 'CPU µs/request'],
            [[label(n), f'{v["rps"]:.2f}', '기준' if n=='full' else formatted(p['comparisons'][n]['full'], 'inverse_rps'),
              f'{v["mean_ms"]:.4f}', f'{v["p99_ms"]:.4f}', f'{v["stack_cpu"]:.2f}'] for n,v in p['absolute'].items()]), '']
    timing=report['phases']['screen']['comparisons']
    text += ['동일 배치 비교는 다음과 같다. 기존 정책과의 비교에는 추가 stub의 실행 비용도 포함되며, 아래 NOP 비교는 새 힌트의 효과를 분리한다.', '',
             table(['동일 배치 비교','처리량 증가','CPU/request 절감'],
                   [[f'{label(a)} / {label(c)}',formatted(timing[a][c],'inverse_rps'),formatted(timing[a][c],'stack_cpu')]
                    for a,c in [('early','late'),('early','nop'),('late','nop'),('split','nop')]]),'']
    build_rows=[]
    for name, builds in report['prepared'].items():
        build_rows.append([label(name), len(builds), sum(v.get('active_hints',v.get('it0_hints',0)+v.get('t1_hints',0)) for v in builds.values()),
                           sum(v.get('extra_instruction_bytes',0) for v in builds.values())])
    text += [table(['구현', '변경 ELF 수', '해당 추가 단계의 정적 힌트 수', '해당 추가 단계 코드 B'], build_rows), '',
             'reply와 reply_it0는 lean 위에 응답 힌트를 추가한다. 정적 힌트 수는 요청당 실행 횟수가 아니다. '
             '상세 patch·타깃·소스 해시는 보존했다.', '', '## 남은 L2 미스', '',
             f'![잔여 미스와 고정 주소의 미스](figures/{TAG}_residual_coverage.png)', '']
    residual=report['residuals']['arms']
    text += ['타깃 주소 집합을 고정한 비교다. 각 열은 모든 정책에서 똑같은 원래 코드 주소를 세며, 세 주소 집합은 서로 중복될 수 있다.', '',
             table(['정책','처음 고른 주소 miss/request','확대한 주소 miss/request','응답용 주소 miss/request'],
                   [[label(n)]+[f'{residual[n]["selected_target_events_per_request"].get(key,0):.2f}'
                                for key in ('selected_lines','wide_selected_lines','reply_selected_lines')]
                    for n in ('full','nop','early','late','split','lean','wide','reply','reply_it0')]),'']
    for prefix,title in [('', '앱 서버 9개'), ('mongo_', 'MongoDB 3개')]:
        f=residual[prefix+'full']['per_request'];c=residual[prefix+nominee]['per_request']
        text += [f'### {title} · 공유 라이브러리 포함', '',
                 table(['위치', '기존 miss/request', '후보 miss/request', '후보 내 비중'],
                       [[title, f'{f.get(key,0):.2f}', f'{c.get(key,0):.2f}', f'{100*c.get(key,0)/c["all"]:.2f}%'] for key,title in CLASSES]+
                       [['전체', f'{f["all"]:.2f}', f'{c["all"]:.2f}', '100%']]), '']
        associated=residual[prefix+nominee]['branch_association_per_request']
        share=100*associated.get('within_64B_after_taken',0)/c['all']
        text += [f'후보 표본 중 최근 taken branch의 타깃 뒤 64바이트 안에 잡힌 비중은 {share:.2f}%다. '
                 '실행되는 코드의 위치 관계이며 BTB miss 비율이 아니다.', '']
        group='mongo_' if prefix else 'apps_'
        details=report['residual_symbols']['groups'][group+nominee]
        text += [table(['주요 잔여 위치', '이미지', '영역', 'miss/request'],
            [[v['demangled'].replace('|','\\|'), v['image'],
              '삽입 코드 → 원 호출 함수' if v['location']=='inserted_stub' else '기존 함수',
              f'{v["events_per_request"]:.2f}'] for v in details['top_functions'][:10]]), '',
            '심볼은 실제 표본 IP가 ELF 심볼 크기 범위에 포함될 때만 붙였다. 삽입 코드 표본은 patch 기록을 따라 원래 호출 지점의 함수로 연결했다. '
            '같은 stub을 여러 호출 지점이 공유하면 특정 함수 하나로 추정하지 않았다.', '']
    text += ['위 표는 retired L2 miss PEBS 표본의 위치 분류다. 삽입 코드 내부 미스도 실제 코드 fetch의 일부이지만, '
             '그 숫자를 prefetch가 새로 유발한 미스 수로 해석하지 않는다. LBR에 stub 실행 분기가 있으면 발행 경로 실행의 증거가 되지만 '
             '하드웨어의 prefetch 수용·완료를 뜻하지 않는다. 최근 32분기에 발행이 없다는 것만으로 미발행을 확정하지 않는다.', '',
             f'![실행 재개 후 미스](figures/{TAG}_miss_over_time.png)', '',
             f'![새 스레드와 실행 재개 분리](figures/{TAG}_miss_by_thread_origin.png)', '',
             '시간 그래프는 각 구간의 스케줄된 CPU 시간으로 나눈 발생률이다. 구간 길이가 다른 원시 표본 수를 직접 비교하지 않았다. '
             '시간 0은 스케줄러의 태스크 선택 시점이며 첫 사용자 명령 실행 시점이 아니다. 서비스별 8초 표본 1회이므로 작은 차이는 기술적 관측값이다.', '',
             '## 별도 PMU 진단', '',
             '아래는 기존 정책과 최종 후보의 별도 진단이다. 성능 표에는 PMU·PEBS 실행의 처리량을 섞지 않았다. '
             '각 서비스·이벤트 창을 같은 창의 HTTP 완료 수로 정규화한 후 합산했다. 서비스별·이벤트별 진단 1회이므로 작은 차이의 반복 일관성은 검증하지 않았다.', '']
    metrics=[('L2 code-read miss/request','per_request','cache:L2I'), ('Retired L2 miss/request','per_request','cache:FE_L2'),
             ('Retired L1I miss/request','per_request','l1:FE_L1'), ('I-cache stall cycles/request','per_request','cache:ICACHE_DATA_STALL'),
             ('I-cache stall periods/request','per_request','cache:ICACHE_STALL_PERIODS'),
             ('ITLB walk active cycles/request','per_request','front:ITLB_WALK_ACTIVE'),
             ('L2 code-read MPKI','ratios','code_read_mpki'), ('Retired L2 MPKI','ratios','retired_l2_mpki'),
             ('Retired L1I MPKI','ratios','retired_l1_mpki'), ('Frontend-bound %','ratios','fe-bound_pct'),
             ('Backend-bound %','ratios','be-bound_pct'), ('Unknown-branch cycles %','ratios','unknown_branch_cycles_pct'),
             ('Recovery cycles %','ratios','recovery_cycles_pct'), ('Clear-resteer cycles %','ratios','clear_resteer_cycles_pct')]
    for scope,title in [('native','앱 서버 9개'),('mongo','MongoDB 3개')]:
        rows=[]
        for title_metric,section,key in metrics:
            a=report['pmu']['arms']['full'][scope][section].get(key);c=report['pmu']['arms'][nominee][scope][section].get(key)
            if a is None or c is None:continue
            change=f'{c-a:+.2f}%p' if key.endswith('_pct') else f'{100*(c/a-1):+.2f}%' if a else '—'
            rows.append([title_metric,f'{a:,.2f}',f'{c:,.2f}',change])
        text += [f'### {title} · 사용자 코드와 공유 라이브러리', '',table(['지표','기존','후보','변화'],rows),'']
    from media_system_study import NATIVE, MONGO
    cpu_rows=[]
    for name in ('original','full',nominee):
        values=final['absolute'][name];counts=values['service_cpu']
        app_user=sum(counts[v[0]+':user_us/request'] for v in NATIVE.values())
        app_kernel=sum(counts[v[0]+':system_us/request'] for v in NATIVE.values())
        mongo_user=sum(counts[v+':user_us/request'] for v in MONGO.values())
        mongo_kernel=sum(counts[v+':system_us/request'] for v in MONGO.values())
        remaining=values['stack_cpu']-app_user-app_kernel-mongo_user-mongo_kernel
        cpu_rows.append([label(name)]+[f'{v:.2f}' for v in (app_user,app_kernel,mongo_user,mongo_kernel,remaining)])
    text += ['### 전체 요청에서의 CPU 시간', '',
             table(['정책','앱 9개 user µs','앱 9개 kernel µs','Mongo 3개 user µs','Mongo 3개 kernel µs','나머지 µs'],cpu_rows),'',
             '모두 요청당 clean 실행의 cgroup CPU 회계다. 사용자 코드의 frontend 슬롯 비율을 전체 요청 시간 비율로 곱하지 않는다. '
             '여러 서비스가 병렬로 실행되므로 CPU 합계의 비중도 요청 지연의 비중이나 speedup 상한이 아니다.', '']
    text += ['Raw L2 code-read miss와 retired L2 miss는 서로 다른 이벤트 집합이다. 둘의 차를 잘못 예측한 경로의 미스 수로 환산하지 않는다. '
             'Frontend/backend는 슬롯 비율이며 전체 요청 지연의 비율이 아니다. Unknown-branch와 분기 직후 표본도 BTB miss 점유율을 직접 측정하지 않는다. '
             '스톨 지표끼리는 중첩되므로 합산하지 않는다. LATE_SWPF는 PREFETCHIT에 관한 이벤트이며 일반 T1 데이터 힌트의 지연 지표로 쓰지 않는다. '
             '[Intel Granite Rapids 이벤트 정의](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).', '',
             '## 해석과 다음 수정의 근거', '', '<!-- Add measured interpretation after inspecting every final result. -->', '',
             '## 측정과 보존', '',
             '서버 CPU32–39, 부하 CPU16–19, 제어 CPU84–85, 2GHz, balanced C4 지속 연결, tracing100%, 매회 새 스택·데이터, '
             '50초 warmup·60초 clean ROI다. MovieId를 포함한 compose-review 경로를 평가했으며 다른 Media API 전체를 검증한 것은 아니다. '
             '타이밍 탐색 후 구조를 확장한 각 정책은 해당 실행 전에 기록했다. 최종 후보는 커버리지 탐색에서 고정하고 독립 확인 결과로 재선택하지 않았다. '
             '유효 실행은 성능에 따라 제외하거나 재시도하지 않았다.', '']
    for phase,values in report['baseline_variation'].items():
        text += [f'{phase}: '+', '.join(f'{label(n)} RPS 변동계수 {v["cv_pct"]:.2f}%' for n,v in values.items())+'.', '']
    text += ['단계별 불필요 ELF·임시 object·decoded trace를 수치·명령·소스·patch·해시 보존 후 정리했다. '
             '현재 실행에 필요한 원본·기존 정책·유효 후보만 유지하고 입력 자료와 공유 의존성은 보존했다. NAS I/O는 사용하지 않았다. '
             '최종 감사는 CPU 설정의 정확한 복원, 소유 실험 컨테이너·네트워크·볼륨 정리, 오류 없는 요청과 매핑 유지, trace 품질을 검사한다.', '',
             f'[전체 수치](../llvm_prefetchit/migration/evidence/{TAG}/report.json), '
             f'[최종 결정](../llvm_prefetchit/migration/evidence/{TAG}/final_decision.json), '
             f'[설정 복원 감사](../llvm_prefetchit/migration/evidence/{TAG}/final_restoration_audit.json), '
             f'[압축 기록 목록](../llvm_prefetchit/migration/evidence/{TAG}/records_manifest.json).', '']
    (root/'report.md').write_text('\n'.join(text))


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);args=parser.parse_args()
    report=load(args.root/'analysis/report.json');plots(args.root,report);report_text(args.root,report)
