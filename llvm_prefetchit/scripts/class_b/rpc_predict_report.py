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
          'late': '핸들러 진입 T1', 'split': '두 단계 분산 T1',
          'full_quiet': '기존 정책·부하 제거 후', 'nop': '동일 배치 NOP',
          'lean': '분산 T1·불필요 슬롯 제거', 'wide': 'RPC별 타깃 확대',
          'wide_span': '타깃 확대·라인 경계 보정',
          'reply': '응답 헤더 후 T1 추가', 'reply_it0': '응답 헤더 후 IT0/T1 추가',
          'stack': '복원된 RPC 문맥으로 T1 추가'}
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


def short_symbol(name):
    # Keep long template signatures in the linked JSON, not a page-wide cell.
    name=name.replace('|','\\|')
    return '`'+(name if len(name)<=110 else name[:107]+'…')+'`'


def save(fig, root, name):
    for suffix in ('png', 'svg'):
        output=root / 'analysis' / (name + '.' + suffix)
        fig.savefig(output, dpi=170, bbox_inches='tight')
        if suffix=='svg':output.write_text('\n'.join(line.rstrip() for line in output.read_text().splitlines())+'\n')
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
    axes[0].set_yticks(range(len(names)), names); axes[0].set_ylim(len(names)-.5,-.5)
    fig.suptitle('응답 정책 단계: 독립 확인 6블록, 개별 paired-log 95% 구간', y=1.03)
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

    latest=report['stack_followup']['evaluation']['e2e']['stack']
    fig, axes=plt.subplots(1,4,figsize=(14,3.7),sharey=True)
    for ax,metric,title in zip(axes,['inverse_rps','mean_ms','p99_ms','stack_cpu'],
                              ['처리량 증가','평균 지연 절감','p99 절감','CPU/request 절감']):
        for i,name in enumerate(('full','stack_nop')):
            mid,(lo,hi)=effect(latest[name],metric)
            ax.errorbar(mid,i,xerr=[[mid-lo],[hi-mid]],fmt='o',capsize=4,
                        color='#166b8c' if lo>0 else '#777777')
            ax.annotate(f'{mid:+.2f}%',(mid,i),xytext=(0,10),textcoords='offset points',ha='center')
        ax.axvline(0,color='black',lw=.8);ax.grid(axis='x',alpha=.2)
        ax.set_title(title);ax.set_xlabel('개선율 (%) · 오른쪽이 개선');ax.set_ylim(1.6,-.6)
    axes[0].set_yticks([0,1],['새 RPC 문맥 정책 / 기존 정책','새 RPC 문맥 정책 / 동일 배치 NOP'])
    fig.suptitle('호출 스택 복원 후 추가 검증: 4블록, 개별 paired-log 95% 구간',y=1.03)
    fig.text(.5,-.04,'Compose의 5개 지점에 T1 40개 추가. 전체 HTTP 요청의 별도 측정이며 앞 단계와 합치지 않음.',ha='center',fontsize=9)
    fig.tight_layout();save(fig,root,'stack_followup_effects')

    profiles=report['stack_followup']['target_analysis']['heldout_profiles']
    fig,axes=plt.subplots(1,2,figsize=(13,4.8))
    for name,style in [('full','-'),('stack','--')]:
        points=[v for v in profiles[name]['time_bins'] if v['lo_us']<100]
        axes[0].stairs([v['estimated_events_per_scheduled_us'] for v in points],
                       [v['lo_us'] for v in points]+[100],label=label(name),linestyle=style,linewidth=1.8)
    axes[0].axvspan(10,20,color='#f6b54c',alpha=.2)
    axes[0].set(xlabel='태스크 선택 후 경과 시간 (µs)',ylabel='CPU 시간 1 µs당 retired L2 miss',xlim=(0,100),title='태스크 선택 이후 미스 발생률')
    axes[0].grid(alpha=.2);axes[0].legend(fontsize=8)
    bottom=np.zeros(2)
    for key,title,color in [('main_original','main ELF 원래 코드','#526c91'),('incumbent_stub','기존 삽입 코드','#cf9262'),
                            ('new_stub','새 삽입 코드','#ba4f4f'),('dso','공유 라이브러리','#8199aa'),('unmapped','미분류','#bbbbbb')]:
        values=np.array([profiles[n]['per_request'].get(key,0) for n in ('full','stack')])
        axes[1].barh([0,1],values,left=bottom,label=title,color=color);bottom+=values
    axes[1].set_yticks([0,1],['기존 정책','RPC 문맥 추가']);axes[1].invert_yaxis()
    axes[1].set(xlabel='요청당 retired L2 miss 추정',title='미스가 발생한 코드 위치')
    axes[1].legend(fontsize=8,loc='upper center',bbox_to_anchor=(.5,-.18),ncol=2)
    fig.suptitle('최신 RPC 문맥 정책: ComposeReview 한 서비스의 별도 표본',y=1.03)
    fig.text(.5,-.1,'정책별 독립 8초 표본. 미스는 사용자 코드, 시간 분모는 커널 실행도 포함. 전체 시스템 미스나 캐시 오염의 인과 분해가 아님.',ha='center',fontsize=9)
    fig.tight_layout();save(fig,root,'stack_followup_misses')

    arms = report['residuals']['arms']
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7), sharey=False)
    for ax, prefix, title in zip(axes, ['', 'mongo_'], ['앱 서버 9개 · 공유 라이브러리 포함', 'MongoDB 3개 · 공유 라이브러리 포함']):
        for name, style in [('full', '-'), (nominee, '--')]:
            key='full_quiet' if not prefix and name=='full' else prefix+name
            points = [v for v in arms[key]['age_bins'] if v['lo_us'] < 100]
            edges = [v['lo_us'] for v in points] + [100]
            values = [v['events_per_scheduled_us'] if v['events_per_scheduled_us'] is not None else np.nan for v in points]
            ax.stairs(values, edges, label=label(name), linestyle=style, linewidth=1.8)
        ax.axvspan(10, 20, color='#f6b54c', alpha=.2, label='10–20 µs')
        ax.set(xlabel='스케줄러가 태스크를 선택한 후 경과 시간 (µs)',
               ylabel='실행 CPU 시간 1 µs당 retired L2 miss', title=title, xlim=(0, 100))
        ax.grid(alpha=.2); ax.legend(fontsize=9)
    fig.suptitle('스레드가 CPU에 배정된 후 코드 미스 발생률', y=1.03)
    fig.text(.5, -.04, '서비스별 별도 8초 표본. 미스는 사용자 코드만, 분모는 커널 실행도 포함한 스케줄 구간 시간.\n첫 사용자 명령 시점이나 prefetch lead-time을 직접 측정한 그래프가 아님.', ha='center', fontsize=9)
    fig.tight_layout(); save(fig, root, 'miss_over_time')

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for column, (prefix, title) in enumerate([('', '앱 서버 9개'), ('mongo_', 'MongoDB 3개')]):
        for row_index, (origin, origin_label) in enumerate([('new_thread_first_run', '새 스레드 첫 실행'), ('resume', '기존 스레드 실행 재개')]):
            ax=axes[row_index,column]
            for name,style in [('full','-'),(nominee,'--')]:
                key='full_quiet' if not prefix and name=='full' else prefix+name
                points=[v for v in arms[key]['origin_age_bins'].get(origin,[]) if v['lo_us']<100]
                if not points:continue
                values=[v.get('estimated_events',0)/v['exposure_us'] if v.get('exposure_us') else np.nan for v in points]
                ax.stairs(values,[v['lo_us'] for v in points]+[100],label=label(name),linestyle=style,linewidth=1.8)
            ax.axvspan(10,20,color='#f6b54c',alpha=.2)
            ax.set(title=title+' · '+origin_label,xlim=(0,100),xlabel='태스크 선택 후 경과 시간 (µs)',
                   ylabel='실행 CPU 시간 1 µs당 retired L2 miss')
            ax.grid(alpha=.2)
            if ax.get_legend_handles_labels()[0]:ax.legend(fontsize=9)
            else:ax.text(.5,.5,'해당 분류의 관측 구간 없음',transform=ax.transAxes,ha='center',va='center',color='#666666')
    fig.suptitle('스레드 첫 실행과 재개를 분리한 미스 발생률',y=1.01)
    fig.text(.5,-.01,'관측 시작 전에 실행되던 스레드 등 기원을 확정할 수 없는 구간은 이 그림에서 제외. 노출 시간이 없는 구간은 결측.',ha='center',fontsize=9)
    fig.tight_layout();save(fig,root,'miss_by_thread_origin')

    names = ['full_quiet', 'lean', 'wide', 'wide_span', 'reply', 'reply_it0']
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    bottom = np.zeros(len(names))
    colors = ['#526c91', '#cf9262', '#ba4f4f', '#8199aa', '#51a99c', '#bbbbbb']
    for (key, title), color in zip(CLASSES, colors):
        values = np.array([arms[n]['per_request'].get(key, 0) for n in names])
        axes[0].barh(range(len(names)), values, left=bottom, label=title, color=color)
        bottom += values
    axes[0].set_yticks(range(len(names)), [label(n) for n in names]); axes[0].invert_yaxis()
    axes[0].set(xlabel='요청당 retired L2 miss 추정', title='앱 9개 잔여 미스 · 표본 시작 주소 기준')
    axes[0].legend(fontsize=8, loc='upper center', bbox_to_anchor=(.5, -.14), ncol=2)
    x = np.arange(len(names)); width=.19
    for index, (key, title) in enumerate([('selected_lines', '처음 고른 주소'),
                                        ('wide_selected_lines', '확대한 주소'), ('span_selected_lines', '경계 보정 주소'),
                                        ('reply_selected_lines', '응답용 주소')]):
        axes[1].bar(x + (index-1.5)*width, [arms[n]['selected_target_events_per_request'].get(key, 0) for n in names], width, label=title)
    axes[1].set_xticks(x, [label(n) for n in names], rotation=55, ha='right')
    axes[1].set(ylabel='요청당 retired L2 miss 추정', title='모든 정책에서 같은 타깃 주소 집합을 비교')
    axes[1].legend(fontsize=8); axes[1].grid(axis='y', alpha=.2)
    fig.text(.5, -.11, '주소 집합끼리는 중복 가능. 정책별 타깃 분류 변화 자체를 미스 감소로 계산하지 않음. 표본 진단값이며 speedup은 별도 clean 실행.', ha='center', fontsize=9)
    fig.tight_layout(); save(fig, root, 'residual_coverage')


def report_text(root, report):
    nominee = report['candidate']; final = report['phases']['production_confirmation']
    e = final['comparisons']; decision = report['decision']
    follow=report['stack_followup'];follow_e=follow['evaluation']['e2e']['stack']
    text = ['# RPC의 알려진 실행 단계를 이용한 코드 프리패치', '',
            '2026-10-02 UTC 실험. Media compose-review 전체 HTTP 요청을 측정했다. 원본 대비 이득과 기존 정책에 더해진 이득을 따로 비교한다.', '',
            f'최신 추가 검증인 **{label("stack")}**의 처리량은 기존 정책 대비 **{formatted(follow_e["full"],"inverse_rps")}**, '
            f'같은 배치의 NOP 대비 **{formatted(follow_e["stack_nop"],"inverse_rps")}**다. '
            + ('승격 기준을 충족해 추가 정책을 유지한다.' if follow['decision']['promoted'] else '승격 기준을 충족하지 않아 기존 정책을 유지한다.'), '',
            '이 추가 검증에는 원본 실행이 없다. 아래 앞 단계의 원본 대비 효과와 곱하거나 합산하지 않는다.', '',
            '## 호출 스택 복원 후 추가 정책 · 4블록 12회', '',
            table(['정책','RPS','평균 ms','p99 ms','CPU µs/request','CPU util'],
                  [[label(n),f'{v["rps"]:.2f}',f'{v["e2e"]["mean_ms"]:.4f}',f'{v["e2e"]["p99_ms"]:.4f}',
                    f'{v["e2e"]["stack_cpu"]:.2f}',f'{v["util_pct"]:.2f}%']
                   for n,v in follow['evaluation']['absolute'].items()]), '',
            table(['비교','처리량 증가','평균 절감','p99 절감','CPU/request 절감'],
                  [[f'{label("stack")} / {label(n)}']+[formatted(follow_e[n],m) for m in ('inverse_rps','mean_ms','p99_ms','stack_cpu')]
                   for n in ('full','stack_nop')]), '',
            f'![RPC 문맥 추가 검증](figures/{TAG}_stack_followup_effects.png)', '',
            'ComposeReview 하나의 main ELF에만 T1 40개를 5개 발행 지점에 추가했다. 추가 명령은 317바이트이며 기존 힌트 642개는 바이트 단위로 보존했다. '
            'NOP은 새 40개만 끈다. 나머지 앱·MongoDB·공유 라이브러리 정책은 기존과 같다. '
            '복원된 물리 호출 스택에서 RPC가 하나로 식별되고 최근 분기 기록만으로는 식별되지 않은 표본을 사용했다. '
            '실제 handler 프레임이 첫 direct call 이후인 표본만 허용하고, 해당 타깃의 발행 분기가 이미 관측된 경우는 제외했다. '
            'RPC별 최소 10표본인 상위 8개 라인을 골라 handler의 첫 direct call에 발행한다. '
            '스택 수집은 훈련 때만 하며 실제 요청 처리 중에는 호출 스택을 걷지 않는다. '
            '훈련은 별도 과거 capture이며 이 12회 결과로 타깃을 바꾸지 않았다.', '',
            '## 앞 단계: 응답 타입을 이용한 정책 · 독립 확인 6블록 24회', '',
            f'응답 정책 후보 **{label(nominee)}**의 처리량은 원본 대비 **{formatted(e[nominee]["original"], "inverse_rps")}**, '
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
            '표의 절대값은 산술평균, 개선율은 같은 블록의 로그 비율이다. 구간은 다중 비교 보정 없는 개별 paired-log t95다. 응답 정책 확인은 탐색과 별도의 6블록이며 단계별 결과를 합치지 않는다. '
            '고정 closed-loop 동시성에서 처리량과 평균 지연은 서로 연관된다. 최대 처리량을 다시 찾는 부하 스윕 결과는 아니다.', '',
            f'![응답 정책 독립 확인](figures/{TAG}_endpoint_effects.png)', '',
            f'![블록별 처리량](figures/{TAG}_endpoint_blocks.png)', '',
            '## 무엇을 바꾸고 어떻게 구분했나', '',
            '처음에는 RPC별 동일한 타깃 4개를 인자 해석 전, 핸들러의 첫 direct call, 두 단계 분산으로 각각 발행했다. '
            '두 발행 stub과 8개 슬롯을 모두 유지하고 힌트/NOP 바이트만 바꿔 발행 시점과 코드 배치 효과를 구분했다. '
            '이후 활성 힌트만 남긴 작은 구현, RPC별 최대 16개 타깃, 응답 헤더를 받은 뒤의 타입별 재발행, 응답 지점의 첫 2개를 IT0로 바꾼 구현을 비교했다.', '',
            '```mermaid\nflowchart LR\n  A[RPC 타입 결정] --> B[인자 해석 전 T1]\n  B --> C[핸들러 진입 T1]\n  C --> D[후속 RPC 대기]\n  D --> E[응답 헤더 수신]\n  E --> F[응답 타입별 T1 또는 IT0/T1]\n  F --> G[결과 디코딩과 후속 코드]\n```', '',
            '응답 정책은 Thrift Client::recv_METHOD에서 readMessageBegin과 헤더 검사를 지난 presult.read 호출을 이용한다. '
            '이미 알고 있는 RPC 메서드와 응답 처리 타입으로 주소를 고른다. 현재 요청의 미래 결과나 미실행 분기 결과를 사용하지 않는다. '
            '응답 본문을 읽다가 추가로 기다릴 수 있으므로 이 지점이 모든 네트워크 대기 이후라고 가정하지 않는다.', '',
            '각 정책의 타깃은 해당 성능 검증 전 별도 PEBS/LBR 훈련 자료에서 선택했다. 호출 스택 추가 정책은 아래 보정한 진단을 새 훈련 자료로 삼았다. '
            '새 힌트는 9개 앱의 main ELF에만 추가했고 기존 MongoDB·DSO 정책은 유지했다. 커널이나 schedule-in hook은 바꾸지 않았다. '
            '직접 호출 stub을 사용하므로 RPC 이름이나 간접 함수 포인터를 요청마다 검색하는 런타임 코드는 추가하지 않았다.', '',
            '정적 검토에서 새 RPC 생성기가 명령의 시작 라인을 골랐고 기존 전체 경로 생성기는 경계에 걸친 명령의 다음 라인을 고려했다는 차이를 발견했다. '
            '후속 성능 측정이 시작되기 전에 `wide_span`을 추가했다. 동일한 과거 훈련 자료에서 명령 길이를 디코딩하고, 경계에 걸친 경우 다음 명령의 라인으로 타깃을 재선정한다. '
            'RPC별 최대 16개·최소 표본 3개 규칙은 유지한다. 실제 선택 개수와 타깃도 달라지므로 wide와의 차이를 경계 처리 하나만의 효과로 단정하지 않는다.', '',
            f'응답 정책 NOP의 범위: {"새 응답 힌트만 끄며 입력 RPC 힌트는 유지한다" if nominee.startswith("reply") else "이번에 추가한 입력 RPC 힌트를 끄며 기존 정책 힌트는 유지한다"}.', '',
            '## 구현별 탐색 결과', '']
    for phase, title in [('screen', '동일 배치의 발행 시점 비교'), ('confirmation', '발행 시점 후보의 독립 확인'),
                         ('quiet_coverage_screen', '외부 부하 제거 후 전체 후보 재탐색')]:
        p=report['phases'][phase]
        text += [f'### {title}', '', table(['정책', 'RPS', '기존 대비 처리량', '평균 ms', 'p99 ms', 'CPU µs/request'],
            [[label(n), f'{v["rps"]:.2f}', '기준' if n=='full' else formatted(p['comparisons'][n]['full'], 'inverse_rps'),
              f'{v["mean_ms"]:.4f}', f'{v["p99_ms"]:.4f}', f'{v["stack_cpu"]:.2f}'] for n,v in p['absolute'].items()]), '']
    timing=report['phases']['screen']['comparisons']
    text += ['동일 배치 비교는 다음과 같다. 기존 정책과의 비교에는 추가 stub의 실행 비용도 포함되며, 아래 NOP 비교는 새 힌트의 효과를 분리한다.', '',
             table(['동일 배치 비교','처리량 증가','CPU/request 절감'],
                   [[f'{label(a)} / {label(c)}',formatted(timing[a][c],'inverse_rps'),formatted(timing[a][c],'stack_cpu')]
                    for a,c in [('early','late'),('early','nop'),('late','nop'),('split','nop')]]),'']
    coverage=report['phases']['quiet_coverage_screen']['comparisons']
    text += ['후속 구현끼리의 비교도 별도로 남긴다. IT0/T1 대 T1은 응답 지점의 ModRM 18바이트만 다르다. '
             '경계 보정 대 타깃 확대는 선택된 타깃 개수·주소도 달라져 경계 처리 하나만의 인과 효과가 아니다.', '',
             table(['후속 구현 비교','처리량 증가','CPU/request 절감'],
                   [[f'{label(a)} / {label(c)}',formatted(coverage[a][c],'inverse_rps'),formatted(coverage[a][c],'stack_cpu')]
                    for a,c in [('reply_it0','reply'),('reply','lean'),('wide','lean'),('wide_span','wide')]]),'']
    build_rows=[]
    for name, builds in report['prepared'].items():
        build_rows.append([label(name), len(builds), sum(v.get('active_hints',v.get('it0_hints',0)+v.get('t1_hints',0)) for v in builds.values()),
                           sum(v.get('extra_instruction_bytes',0) for v in builds.values())])
    text += [table(['구현', '변경 ELF 수', '해당 추가 단계의 정적 힌트 수', '해당 추가 단계 코드 B'], build_rows), '',
             'reply와 reply_it0는 lean 위에 응답 힌트를 추가한다. 정적 힌트 수는 요청당 실행 횟수가 아니다. '
             '상세 patch·타깃·소스 해시는 보존했다.', '', '## 남은 L2 미스', '',
             f'![잔여 미스와 고정 주소의 미스](figures/{TAG}_residual_coverage.png)', '']
    residual=report['residuals']['arms']
    text += ['타깃 주소 집합을 고정한 비교다. 각 열은 모든 정책에서 똑같은 원래 코드 주소를 세며, 네 주소 집합은 서로 중복될 수 있다.', '',
             table(['정책','처음 고른 주소 miss/request','확대한 주소 miss/request','경계 보정 주소 miss/request','응답용 주소 miss/request'],
                   [[label(n)]+[f'{residual[n]["selected_target_events_per_request"].get(key,0):.2f}'
                                for key in ('selected_lines','wide_selected_lines','span_selected_lines','reply_selected_lines')]
                    for n in ('full_quiet','lean','wide','wide_span','reply','reply_it0')]),'']
    union_before=residual['full_quiet']['selected_target_events_per_request']['incoming_and_reply_lines']
    union_after=residual['reply_it0']['selected_target_events_per_request']['incoming_and_reply_lines']
    text += [f'입력·응답 타깃 주소의 합집합에서 관측한 미스는 요청당 {union_before:.2f} → {union_after:.2f}다. '
             f'기존 정책의 전체 앱 표본에서 이 주소들이 차지한 비중은 {100*union_before/residual["full_quiet"]["per_request"]["all"]:.2f}%다. '
             '중복 주소를 한 번만 센 고정 주소 집합의 관측 비중이며, 동적 prefetch 성공률이나 성능 향상 상한은 아니다.', '']
    import collections
    training=collections.Counter()
    for v in report['training_rpc_selection'].values():training.update(v)
    text += ['### 타깃 선택 전에 빠지는 범위', '',
             '아래는 별도의 과거 훈련 자료에 적용한 선택 규칙이다. 이번 검증 미스 감소율이나 성능 상한이 아니다.', '',
             table(['훈련 잔여 표본의 분류','비중'],
                   [[title,f'{100*training.get(key,0)/training["all"]:.2f}%'] for key,title in
                    [('outside_main','main ELF 밖·새 타깃 범위에서 제외'),
                     ('decoder_or_processor','두 발행 시점 비교를 위해 decoder/processor 제외'),
                     ('no_rpc_context','최근 32개 분기에서 RPC 문맥 미복원'),
                     ('rpc_associated','RPC 문맥에 연결됨')]]), '',
             f'RPC 문맥에 연결된 표본 중에서도 전체의 {100*training["already_targeted"]/training["all"]:.2f}%는 '
             '기존 정책의 타깃 목록에 이미 있다는 이유로 입력 RPC 후보에서 제외했다. 정적으로 타깃에 있다는 것과 해당 요청에서 제때 발행됐다는 것은 다르다. '
             '응답 힌트는 동일 발행 지점의 기존 타깃만 제외하며, 다른 지점에서 이미 타깃인 코드의 재발행은 허용한다. '
             '문맥을 복원하지 못한 코드를 소프트웨어가 예측할 수 없는 코드라고 해석하지 않는다. 긴 공통 함수 경로와 비동기 작업은 더 긴 실행 문맥이 필요하다.', '']
    diagnostic=report['corrected_callchain'];samples=diagnostic['quality']['samples']
    categories=[('both_same_unique','분기 기록·스택 모두 같은 RPC'),
                ('stack_only_unique','스택에서만 RPC 하나 복원'),
                ('lbr_only_unique','분기 기록에서만 RPC 하나 복원'),
                ('both_disagree','양쪽 RPC가 다름'),
                ('both_ambiguous_overlap','양쪽 문맥 중첩·복수 후보'),
                ('stack_only_ambiguous','스택만 복수 후보'),
                ('lbr_only_ambiguous','분기 기록만 복수 후보'),('neither','양쪽 모두 미복원')]
    text += ['### ComposeReview 호출 스택으로 RPC 문맥을 더 복원할 수 있나', '',
             '응답 정책 검증 뒤 기존 정책에서 별도의 8초 진단을 수행했다. 같은 L2 미스 표본에 최근 분기 기록과 '
             '8192바이트 사용자 스택의 DWARF unwind를 함께 수집했다. 이 추가 진단은 주기 257을 사용하며, 일반 L2 시간축 표본의 주기는 1021이다. '
             '현재 살아 있는 handler/processor 프레임의 주소 범위로만 RPC를 붙인다. '
             '첫 진단은 물리 프레임이 2개 이상 복원된 비율이 16.87%에 불과했고 main ELF 표본은 모두 1개에서 끊겼다.', '',
             '**원인은 perf 6.8의 ELF 기준 주소 계산이었다.** libunwind 경로가 여러 mapping의 `start - pgoff` 중 최솟값을 쓴다. '
             '삽입 코드의 PT_LOAD는 파일 오프셋이 가상주소보다 훨씬 커서 이 값이 실제 기준 주소보다 작아졌고 CFI 조회가 실패했다. '
             '[Linux perf 6.8 구현](https://raw.githubusercontent.com/torvalds/linux/v6.8/tools/perf/util/unwind-libunwind-local.c).', '',
             '두 번째 진단의 **같은 14,411개 표본**을 두 방식으로 해석해 확인했다. 오프라인 전용 ELF 사본에서 파일 배치만 가상주소 기준으로 정규화하고 '
             'perf 기록의 해당 MMAP 파일 오프셋만 맞췄다. 코드·CFI·할당 섹션의 주소와 바이트, SAMPLE 기록, 표본 식별자와 leaf 주소의 동일성을 검사했다. '
             '실행 프로그램이나 하드웨어 카운터를 바꾼 실험이 아니다. 이 문제는 새 DWARF 진단의 호출 스택 복원에 해당하며, '
             '앞선 E2E 측정과 PT_LOAD별 주소를 처리하던 일반 PEBS 분석이 이 잘못된 기준 주소를 사용한 것은 아니다.', '']
    normalization=report['unwind_normalization'];frame_rows=[]
    for key,title in [('main_original','main ELF 원래 코드'),('main_stub','main ELF 삽입 코드'),('dso','공유 라이브러리')]:
        before=normalization['exact']['by_leaf'][key];after=normalization['normalized']['by_leaf'][key]
        frame_rows.append([title,before['samples'],f'{100*before["two_physical_frames"]/before["samples"]:.2f}%',
                           f'{100*after["two_physical_frames"]/after["samples"]:.2f}%'])
    text += [table(['같은 표본의 위치','표본 수','2개 이상 물리 프레임·보정 전','보정 후'],frame_rows),'',
             '전체의 2개 이상 물리 프레임 복원율은 **17.67% → 98.81%**, 스택에서 RPC 하나를 식별한 비율은 **14.78% → 62.14%**다. '
             '아래는 보정 후 결과다. 분기 기록에서 놓쳤지만 스택으로 복원한 39.00%를 새 타깃 후보로 삼았다.', '',
             table(['같은 표본의 RPC 문맥 비교','표본 수','전체 표본 내 비중'],
                   [[title,diagnostic['categories'].get(key,0),f'{100*diagnostic["categories"].get(key,0)/samples:.2f}%']
                    for key,title in categories]), '',
             '프레임 출력 자체가 완전한 unwind를 보장하지는 않는다. 분기 기록에는 이미 끝난 호출도 남고, 스택에는 비동기 작업의 부모 RPC가 없을 수 있다. '
             '따라서 서로 다른 라벨을 즉시 어느 한쪽의 오분류로 판정하지 않았다.', '',
             '정적 stub 기록도 확인했다. 여러 원 호출 지점이 하나의 stub을 공유하는데 마지막 지점 하나로 귀속하면 RPC 종류를 잘못 붙일 수 있다. '
             '이번 추가 진단은 가능한 원 호출 지점들을 모두 보존해 복수 RPC를 명시한다. 기존에 측정한 바이너리를 사후 변경하지 않았다.', '']
    ta=follow['target_analysis'];tc=ta['training_counts']
    text += [f'추가 정책의 정적 힌트 {ta["static_hints"]}개는 서로 다른 코드 라인 {ta["unique_target_lines"]}개를 가리킨다. '
             '여러 RPC에서 같은 함수를 부르므로 RPC별 발행 위치가 다르다. '
             f'별도 훈련 표본에서 이 고정 라인의 비중은 시작 라인 기준 {100*tc["fixed_start_lines"]/tc["all"]:.2f}%, '
             f'끝 라인 가정 기준 {100*tc["fixed_end_lines"]/tc["all"]:.2f}%다. '
             '훈련상 주소 비중이며 새 검증에서 줄어든 미스 비율이나 예측 정확도가 아니다. '
             '타깃의 bounded symbol에는 ComposeReviewHandler::_ComposeAndUpload, future 결과 대기·정리, '
             'Jaeger 추적 문맥·vector, 로그 attribute, C++ stream 초기화가 있다. 모두 해당 main ELF에 포함된 코드이며 새 DSO 힌트는 추가하지 않았다.', '']
    profile=follow['profile_summary']['arms'];pf=profile['full']['per_request'];pc=profile['stack']['per_request']
    text += ['### 복원된 RPC 문맥 정책의 새 미스 측정', '',
             f'![최신 정책 미스 시간축과 코드 위치](figures/{TAG}_stack_followup_misses.png)', '',
             '이 표는 추가 성능 검증 뒤 ComposeReview 하나에서 각각 수집한 독립 PEBS 표본이다. 전체 앱이나 전체 시스템의 L2 미스 감소율이 아니다. '
             '타깃 라인 집합은 두 정책에서 고정했으며 시작 라인과 명령 마지막 바이트의 라인 두 가정을 함께 남겼다.', '',
             table(['ComposeReview miss/request','기존 정책','추가 정책','변화'],
                   [[title,f'{pf.get(key,0):.2f}',f'{pc.get(key,0):.2f}',
                     f'{100*(pc.get(key,0)/pf[key]-1):+.2f}%' if pf.get(key) else '—']
                    for key,title in [('all','전체·DSO 포함'),('main','main ELF'),
                                      ('fixed_start_lines','고정 타깃·시작 라인'),('fixed_end_lines','고정 타깃·끝 라인')]]),'',
             table(['ComposeReview 코드 위치','기존 miss/request','추가 정책 miss/request'],
                   [[title]+[f'{ta["heldout_profiles"][n]["per_request"].get(key,0):.2f}' for n in ('full','stack')]
                    for key,title in [('main_original','main ELF 원래 코드'),('incumbent_stub','기존 삽입 코드'),
                                      ('new_stub','새 삽입 코드'),('dso','공유 라이브러리'),('unmapped','미분류')]]),'',
             '코드 위치별 관측 변화이며 캐시 오염을 원인으로 확정하는 표는 아니다. 각 정책 1회의 perturbing 표본만으로 작은 변화의 재현성을 판단하지 않는다.', '',
             '아래 전체 앱·MongoDB 진단표와 시간축 그래프는 앞 단계의 응답 정책 후보를 비교한 것이다. 추가 정책의 진단값과 합치지 않는다.', '']
    geometry_rows=[]
    for n in ('full_quiet','wide','wide_span',nominee):
        if any(v[0]==label(n) for v in geometry_rows):continue
        v=residual[n];g=v['continuation_line_model']['geometry_per_request'];total=v['per_request']['all']
        geometry_rows.append([label(n),f'{100*g.get("straddling",0)/total:.2f}%',
            f'{v["per_request"].get("not_targeted",0):.2f}',
            f'{v["continuation_line_model"]["per_request"].get("not_targeted",0):.2f}',
            f'{v["per_request"].get("targeted_with_lbr_witness",0):.2f}',
            f'{v["continuation_line_model"]["per_request"].get("targeted_with_lbr_witness",0):.2f}',
            f'{100*g.get("undecoded",0)/total:.2f}%'])
    text += ['### 명령이 캐시라인 경계에 걸치는 경우', '',
             table(['정책','경계 표본 비중','시작 라인 미타깃','끝 라인 가정 미타깃','발행 분기 관측·시작 라인','발행 분기 관측·끝 라인','길이 미분류'],geometry_rows),'',
             '비중 외의 수치는 miss/request다. 시작 라인에 대한 발행 분기가 있어도 경계를 넘어선 라인까지 가져왔다는 뜻은 아니다.', '',
             '표본 IP는 명령의 시작 주소다. 두 라인에 걸친 명령에서 어느 라인이 실제로 미스했는지는 이 이벤트만으로 확정할 수 없다. '
             '따라서 시작 라인 분류와 마지막 바이트가 있는 라인으로 옮긴 민감도 분석을 함께 보존한다. 전체 L2 미스 수는 바뀌지 않는다. '
             '아래 위치 표는 시작 주소 기준이며, 이 분류 변경을 실제 미스 감소로 계산하지 않는다.', '']
    for prefix,title in [('', '앱 서버 9개'), ('mongo_', 'MongoDB 3개')]:
        reference='full_quiet' if not prefix else 'mongo_full'
        f=residual[reference]['per_request'];c=residual[prefix+nominee]['per_request']
        text += [f'### {title} · 공유 라이브러리 포함', '',
                 table(['위치', '기존 miss/request', '후보 miss/request', '후보 내 비중'],
                       [[title, f'{f.get(key,0):.2f}', f'{c.get(key,0):.2f}', f'{100*c.get(key,0)/c["all"]:.2f}%'] for key,title in CLASSES]+
                       [['전체', f'{f["all"]:.2f}', f'{c["all"]:.2f}', '100%']]), '']
        concentration=residual[reference]['sampled_address_concentration']
        text += [f'기존 정책 표본에서 관측한 서로 다른 서비스·이미지·시작 라인은 {concentration["observed_service_image_lines"]:,}개다. '
                 f'가장 큰 1개 라인의 비중은 {concentration["top_line_share_pct"]["1"]:.2f}%, '
                 f'상위 100개 합은 {concentration["top_line_share_pct"]["100"]:.2f}%다. '
                 '동일 주소의 발행 관측 여부 분류는 합쳤다. 표본의 분산 정도이며 전체 실행 footprint나 성능 상한은 아니다.', '']
        associated=residual[prefix+nominee]['branch_association_per_request']
        share=100*associated.get('within_64B_after_taken',0)/c['all']
        text += [f'후보 표본 중 최근 taken branch의 타깃 뒤 64바이트 안에 잡힌 비중은 {share:.2f}%다. '
                 '실행되는 코드의 위치 관계이며 BTB miss 비율이 아니다.', '']
        kinds=residual[prefix+nominee]['sample_instruction_kind_per_request']
        branch_kinds=('direct_call','indirect_call','direct_jump','indirect_jump','conditional_branch','return')
        text += [f'표본 명령 자체가 분기인 비중은 {100*sum(kinds.get(k,0) for k in branch_kinds)/c["all"]:.2f}%, '
                 f'prefetch 명령인 비중은 {100*kinds.get("prefetch",0)/c["all"]:.2f}%, 명령 종류 미분류는 {100*kinds.get("unknown",0)/c["all"]:.2f}%다. '
                 '분기 명령의 코드 fetch 미스와 분기 예측 실패는 다른 사건이다.', '']
        gaps=residual[prefix+nominee]['targeted_retired_lbr_gap_per_request']
        text += [table(['타깃 코드의 최근 발행 분기와 거리','miss/request'],
                       [[key,f'{gaps.get(key,0):.2f}'] for key in
                        ('0_64','64_256','256_1024','1024_4096','4096_16384','16384_plus','unavailable_cycles','no_bounded_witness')]), '',
                 '거리 숫자는 최근 retired branch들 사이의 유효한 cycle 필드 합계다. 단위는 cycles이며 prefetch와 fetch 사이의 실제 lead time이 아니다. '
                 '마지막 분기부터 표본까지의 간격과 prefetch부터 stub 끝 분기까지의 간격은 빠져 있고 fetch·retirement도 겹친다. '
                 'cycle 필드가 없거나 포화된 경우, 최근 32분기에 발행 분기가 없는 경우를 따로 보존했다.', '']
        group='mongo_' if prefix else 'apps_'
        details=report['residual_symbols']['groups'][group+nominee]
        text += [table(['주요 잔여 위치', '이미지', '영역', 'miss/request'],
            [[short_symbol(v['demangled']), v['image'],
              '삽입 코드 → 원 호출 함수' if v['location']=='inserted_stub' else '기존 함수',
              f'{v["events_per_request"]:.2f}'] for v in details['top_functions'][:10]]), '',
            '심볼은 실제 표본 IP가 ELF 심볼 크기 범위에 포함될 때만 붙였다. 삽입 코드 표본은 patch 기록을 따라 원래 호출 지점의 함수로 연결했다. '
            '같은 stub을 여러 호출 지점이 공유하면 특정 함수 하나로 추정하지 않았다. 긴 심볼의 원문은 전체 수치 JSON에 보존했다.', '']
    text += ['위 표는 retired L2 miss PEBS 표본의 위치 분류다. 삽입 코드 내부 미스도 실제 코드 fetch의 일부이지만, '
             '그 숫자를 prefetch가 새로 유발한 미스 수로 해석하지 않는다. LBR에 stub 실행 분기가 있으면 발행 경로 실행의 증거가 되지만 '
             '하드웨어의 prefetch 수용·완료를 뜻하지 않는다. 최근 32분기에 발행이 없다는 것만으로 미발행을 확정하지 않는다.', '',
             f'![실행 재개 후 미스](figures/{TAG}_miss_over_time.png)', '',
             f'![새 스레드와 실행 재개 분리](figures/{TAG}_miss_by_thread_origin.png)', '',
             '시간 그래프는 각 구간의 스케줄된 CPU 시간으로 나눈 발생률이다. 구간 길이가 다른 원시 표본 수를 직접 비교하지 않았다. '
             '분모에는 커널 실행 구간도 포함되지만 PMU 미스 표본은 사용자 코드에서만 수집한다. '
             '시간 0은 스케줄러의 태스크 선택 시점이며 첫 사용자 명령 실행 시점이 아니다. 서비스별 8초 표본 1회이므로 작은 차이는 기술적 관측값이다.', '']
    age_rows=[]
    for prefix,title in [('', '앱 서버 9개'),('mongo_', 'MongoDB 3개')]:
        reference='full_quiet' if not prefix else 'mongo_full'
        for lo,hi in [(0,5),(5,10),(10,20),(20,50),(50,None)]:
            values=[]
            for name in (reference,prefix+nominee):
                values.append(sum(sum(v['events_per_request'].get(k,0) for k,_ in CLASSES)
                    for v in residual[name]['age_bins'] if v['lo_us']>=lo and (hi is None or v['lo_us']<hi)))
            a,c=values
            age_rows.append([title,f'{lo}–{hi}' if hi is not None else f'{lo} 이상',f'{a:.2f}',f'{c:.2f}',f'{100*(c/a-1):+.2f}%' if a else '—'])
    text += ['시간별 발생률 그래프와 별도로, 각 구간에 속한 요청당 미스 수를 비교한다. 아래 변화율은 감소가 음수다. '
             '각 서비스의 별도 표본 창을 요청 수로 정규화한 추정값이다.', '',
             table(['프로그램','태스크 선택 후 µs','기존 miss/request','후보 miss/request','변화'],age_rows),'']
    schedule_rows=[]
    for prefix,title in [('', '앱'),('mongo_', 'MongoDB')]:
        reference='full_quiet' if not prefix else 'mongo_full'
        for service,entry in residual[reference]['services'].items():
            a=entry['schedule'];c=residual[prefix+nominee]['services'][service]['schedule']
            schedule_rows.append([title+' '+service,f'{a["migrated_pct"]:.2f}%',f'{c["migrated_pct"]:.2f}%',
                f'{a["median_run_us"]:.2f}',f'{a["median_off_us"]:.2f}'])
    text += ['### 대기를 사이에 둔 CPU 이동', '',
             table(['서비스','기존 CPU 이동 비율','후보 CPU 이동 비율','기존 실행 구간 중앙값 µs','기존 비실행 구간 중앙값 µs'],schedule_rows),'',
             'CPU 이동 비율의 분모는 이전 switch-out CPU를 확인할 수 있는 실행 재개 횟수다. 미스 표본의 비율이 아니다. '
             '대기 전에 한 CPU에서 발행한 프리패치와 다른 CPU에서의 후속 실행을 같게 취급할 수 없다는 근거지만, '
             '이 기록만으로 특정 미스의 원인이 CPU 이동이라고 확정하지 않는다. 응답 헤더 뒤에도 본문 읽기가 다시 대기할 수 있어, '
             '응답 지점 이동의 효과에는 lead-time과 대기 위치가 함께 관여할 수 있다.', '']
    text += ['## 별도 PMU 진단', '',
             '아래는 기존 정책과 최종 후보의 별도 진단이다. 성능 표에는 PMU·PEBS 실행의 처리량을 섞지 않았다. '
             '각 서비스·이벤트 창을 같은 창의 HTTP 완료 수로 정규화한 후 합산했다. 서비스별·이벤트별 진단 1회이므로 작은 차이의 반복 일관성은 검증하지 않았다.', '']
    if report['diagnostic_rejections']:
        text += [f'품질 기준으로 제외한 PMU 시도 {len(report["diagnostic_rejections"])}회는 별도 보존했다. '
                 'Top-down 합계 오차의 기존 2% 기준을 유지하고, 같은 seed·이벤트·순서·측정 코드로 새 스택에서 해당 진단 전체를 다시 실행했다. '
                 '제외된 시도의 부분 카운터는 평균에 넣지 않았고 clean 성능 회차는 반복하지 않았다.', '',
                 table(['제외 시도','합계 오차'],[[Path(v['path']).name,f'{v["closure_error_pct"]:.3f}%'] for v in report['diagnostic_rejections']]),'']
    metrics=[('L2 code-read miss/request','per_request','cache:L2I'),
             ('L2 code-read lookups/request','per_request','cache:L2_CODE_ALL'),
             ('L2 code-read miss %','ratios','code_read_miss_pct'),
             ('I-cache stall cycles/period','ratios','cycles_per_icache_stall_period'), ('Retired L2 miss/request','per_request','cache:FE_L2'),
             ('Retired L1I miss/request','per_request','l1:FE_L1'), ('I-cache stall cycles/request','per_request','cache:ICACHE_DATA_STALL'),
             ('I-cache stall periods/request','per_request','cache:ICACHE_STALL_PERIODS'),
             ('ITLB walk active cycles/request','per_request','front:ITLB_WALK_ACTIVE'),
             ('ITLB STLB hits/request','per_request','l1:ITLB_STLB_HIT'),
             ('ITLB walks completed/request','per_request','l1:ITLB_WALK_COMPLETED'),
             ('Instructions/request (cache 창)','per_request','cache:instructions:u'),
             ('T1/T2 executed/request','per_request','prefetch:T1_T2_EXECUTED'),
             ('NTA/T0/T1/T2 L2 misses/request','per_request','prefetch:SWPF_MISS'),
             ('NTA/T0/T1/T2 L2 hits/request','per_request','prefetch:SWPF_HIT'),
             ('Late IT-prefetch retired tags/request','per_request','recovery:FE_LATE_SWPF'),
             ('DSB uops/request','per_request','front:DSB_UOPS'),
             ('MITE uops/request','per_request','front:MITE_UOPS'),
             ('L2 code-read MPKI','ratios','code_read_mpki'), ('Retired L2 MPKI','ratios','retired_l2_mpki'),
             ('Retired L1I MPKI','ratios','retired_l1_mpki'), ('Frontend-bound %','ratios','fe-bound_pct'),
             ('Fetch-latency-bound %','ratios','fetch-lat_pct'),
             ('Frontend-bound slots/request','per_request','topdown:topdown-fe-bound:u'),
             ('Fetch-latency-bound slots/request','per_request','topdown:topdown-fetch-lat:u'),
             ('Backend-bound slots/request','per_request','topdown:topdown-be-bound:u'),
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
             'SWPF HIT/MISS는 fill buffer가 가득 차지 않은 경우의 NTA/T0/T1/T2 요청 카운트이며 IT0 수용·완료 횟수로 쓰지 않는다. '
             '[Intel Granite Rapids 이벤트 정의](https://perfmon-events.intel.com/platforms/graniterapids/core-events/core/).', '',
             '## 해석과 다음 수정의 근거', '',
             (load(root/'interpretation.json')['markdown'] if (root/'interpretation.json').exists()
              else '<!-- Add measured interpretation after inspecting every final result. -->'), '',
             '## 측정과 보존', '',
             '서버 CPU32–39, 부하 CPU16–19, 제어 CPU84–85, 2GHz, balanced C4 지속 연결, tracing100%, 매회 새 스택·데이터, '
             '50초 warmup·60초 clean ROI다. MovieId를 포함한 compose-review 경로를 평가했으며 다른 Media API 전체를 검증한 것은 아니다. '
             '타이밍 탐색 후 구조를 확장한 각 정책은 해당 실행 전에 기록했다. 응답 정책 후보는 커버리지 탐색에서 고정하고 독립 확인 결과로 재선택하지 않았다. '
             '추가 호출 스택 진단의 주소 계산 문제를 확인·보정한 뒤 한 개의 후속 정책을 별도 사전 규칙으로 고정해 12회 더 측정했다. '
             '기존 측정에 추가 확인 결과를 합치지 않았다. '
             '유효 실행은 성능에 따라 제외하거나 재시도하지 않았다. 외부 부하가 발생한 단계는 전부 별도 보존하고 전체 후보를 새 단계에서 다시 측정했다.', '']
    text += ['경계 보정판 추가를 위해 후속 코디네이터만 기능 검사 사이에서 교체했다. 진행 중이던 wide 기능 검사는 정상 종료와 설정 복원을 기다렸으며, '
             '완료된 lean·lean NOP·wide 검사는 보존하고 반복하지 않았다. 이때 커버리지 성능 측정은 아직 시작하지 않았다. '
             '수정된 탐색은 6개 정책×4블록이며, 최종 독립 확인 4개 정책×6블록은 유지했다. 교체 전 코디네이터 로그와 변경 사유를 모두 보존했다.', '']
    text += ['### 외부 부하와 재측정', '',
             '후속 탐색 중 다른 작업으로 서버 밖 CPU가 거의 100% 사용되고 클라이언트 CPU도 포화됐다. 사용자 지시에 따라 외부 계산 작업과 재실행 배치를 종료했다. '
             '진행 중인 실험 회차는 정상 종료·설정 복원까지 기다렸다. 기존 탐색의 완료된 19회는 외부 부하 및 전환 조건의 보조 자료로 모두 보존했다. '
             '후보 선택에는 사용하지 않았으며, 여섯 정책 모두 새 seed로 4블록을 다시 수행했다. 최종 확인은 별도 6블록이다.', '',
             '초기 split PEBS 9개는 외부 부하와 겹친다. 앞서 언급한 특정 타깃 미스 41% 감소는 같은 조건의 인과 비교로 사용할 수 없어 철회한다. '
             '초기 full·early·late·NOP 표본과 이 split 표본을 묶어 감소율을 계산하지 않는다. '
             '최종 앱 그래프는 새 full_quiet 표본과 같은 외부 부하 제거 조건의 후보 표본만 비교한다. '
             '관측 조건 분류는 사후 환경 주석이며 사전 성능 제외 규칙이 아니다. 최초 탐색 일부에는 관측 기록이 부족해 조용했다고 단정하지 않는다.', '',
             table(['단계','관측 조건','회차 수'],
                   [[phase,condition,sum(v['descriptive_condition']==condition for v in rows)]
                    for phase,rows in report['conditions']['endpoints'].items()
                    for condition in sorted({v['descriptive_condition'] for v in rows})]), '']
    for phase,values in report['baseline_variation'].items():
        text += [f'{phase}: '+', '.join(f'{label(n)} RPS 변동계수 {v["cv_pct"]:.2f}%' for n,v in values.items())+'.', '']
    follow_conditions=follow['conditions']['endpoints']['confirmation']
    text += ['호출 스택 후속 검증의 관측 조건도 같은 사후 정의로 따로 남긴다. 성능에 따른 제외나 재시도에 쓰지 않았다.', '',
             table(['후속 검증 관측 조건','회차 수'],
                   [[condition,sum(v['descriptive_condition']==condition for v in follow_conditions)]
                    for condition in sorted({v['descriptive_condition'] for v in follow_conditions})]), '',
             '후속 검증: '+', '.join(f'{label(n)} RPS 변동계수 {v["cv_pct"]:.2f}%'
                                   for n,v in follow['baseline_variation'].items())+'.', '']
    text += ['단계별 불필요 ELF·임시 object·decoded trace를 수치·명령·소스·patch·해시 보존 후 정리했다. '
             '현재 실행에 필요한 원본·기존 정책·유효 후보만 유지하고 입력 자료와 공유 의존성은 보존했다. NAS I/O는 사용하지 않았다. '
             '최종 감사는 CPU 설정의 정확한 복원, 소유 실험 컨테이너·네트워크·볼륨 정리, 오류 없는 요청과 매핑 유지, trace 품질을 검사한다.', '',
             '완료된 주 측정은 E2E 90회, 기능 검사 15회, 일반 PEBS capture 107개다. 별도 외부 부하·전환 조건의 E2E 19회, '
             '호출 스택 진단 2개도 보존했다. PMU 진단은 유효 4회이며, top-down 검증에서 거부된 1회는 부분 결과와 제외 사유를 보존했다.', '',
             f'저장소의 파일당 10MiB 제한에 따라 전체 압축 기록은 `{root}/compact_records.tar.gz`에 로컬 보존한다. '
             'Git에는 구현·수치·그래프·설정 복원 감사와 모든 압축 기록의 SHA-256 목록을 저장한다. 압축 파일의 위치·크기·해시는 evidence의 manifest.json에 있다.', '',
             f'[전체 수치](../llvm_prefetchit/migration/evidence/{TAG}/report.json), '
             f'[최종 결정](../llvm_prefetchit/migration/evidence/{TAG}/final_decision.json), '
             f'[설정 복원 감사](../llvm_prefetchit/migration/evidence/{TAG}/final_restoration_audit.json), '
             f'[압축 기록 목록](../llvm_prefetchit/migration/evidence/{TAG}/records_manifest.json).', '']
    (root/'report.md').write_text('\n'.join(text))


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);args=parser.parse_args()
    report=load(args.root/'analysis/report.json');plots(args.root,report);report_text(args.root,report)
