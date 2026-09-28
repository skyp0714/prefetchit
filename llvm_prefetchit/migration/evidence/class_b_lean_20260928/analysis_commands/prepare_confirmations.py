from pathlib import Path
import json,sys
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b
from lean_evaluate import evaluate
from e2e_lbr import remove_generated
r=Path('/storage/prefetchit/class_b_lean_20260928');b.space(r)
d=evaluate(r/'screen_v4');spec=json.loads((r/'screen_v4_spec.json').read_text())
eligible=[(v['minimum_effect_pct'],k) for k,v in d['decisions'].items() if v['point_eligible']]
rank=eligible or [(v['minimum_effect_pct'],k) for k,v in d['decisions'].items()]
selected=max(rank)[1];nop=d['decisions'][selected]['matched_nop']
# Best balanced point estimate is a diagnostic selection when none qualifies.
choice=dict(selected=selected,matched_nop=nop,eligible=eligible,promoted=False,
    selection_kind='eligible exploratory candidate' if eligible else 'diagnostic best tradeoff; no eligible screen winner',
    criterion='Largest minimum CPU/mean cost reduction over original and own NOP; fresh confirmation still required.',
    evaluation_sha256=b.sha(r/'screen_v4/evaluation.json'),design=str(r/'confirmation_design.json'))
b.save(r/'v4_selection.json',choice)
arms={'base':dict(spec['arms']['base']),
      'matched_nop':dict(spec['arms'][nop],controls=['base']),
      'selected_candidate':dict(spec['arms'][selected],controls=['base','matched_nop'])}
for concurrency,seeds in [(4,56001),(16,57001)]:
 out=r/f'confirmation_c{concurrency}'
 frozen=dict(out=str(out),blocks=6,concurrency=concurrency,roi_s=60,seedbase=seeds,
    arms=arms,module=spec['module'],clock_options=spec['clock_options'],
    pmu_blocks=[0],pmu_event_sets=spec['pmu_event_sets'],
    phase='Independent new-seed confirmation; no screen data pooled',selection=choice,
    decision=json.loads((r/'confirmation_design.json').read_text()),
    saturation='C16 is near the previously measured throughput plateau on the same8CPUs, not proof of a universal maximum',
    postroi_worker_snapshot='Lifetime worker CPU only; retained without excluding any performance outlier')
 b.save(out.with_suffix('.json'),frozen)
# A gated diagnostic can expose early/late gating even if the selected policy
# is ungated. Keep that pair only until a diagnostic replacement is validated.
gated=max((v['minimum_effect_pct'],k) for k,v in d['decisions'].items() if spec['arms'][k].get('clock',True))[1]
gated_nop=d['decisions'][gated]['matched_nop']
retain={selected,nop,gated,gated_nop};keep={Path(p) for k in retain for p in spec['arms'][k]['overrides'].values()}
old=json.loads((r/'screen_v3_spec.json').read_text())
paths={Path(p) for k,s in spec['arms'].items() if k not in ('base','base_clock') for p in s['overrides'].values()}-keep
paths |= {Path(p) for k in ('profile_nop','profile_it0') for p in old['arms'][k]['overrides'].values() if Path(p).exists()}
b.save(r/'v4_retention.json',dict(active_selected=selected,gated_diagnostic=gated,retained=sorted(retain),reason='Selected pair is active for independentC4/C16 confirmation; best gated pair remains useful until diagnostic replacement validates. Other screen variants are superseded, not proven statistically inferior.'))
remove_generated(sorted(paths),r/'v4_superseded_cleanup.json','Completed V4 screen; compact measurements, selection, audits, sources and hashes retained before removing unused candidate/control binaries.')
print(json.dumps(dict(choice=choice,gated_diagnostic=gated,means=d['means']),indent=2))
