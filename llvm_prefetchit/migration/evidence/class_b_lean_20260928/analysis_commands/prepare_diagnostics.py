from pathlib import Path
import json,sys
repo=Path('/home/hnpark2/prefetchit');sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b
r=Path('/storage/prefetchit/class_b_lean_20260928')
spec=json.loads((r/'confirmation_c4.json').read_text())
diag=json.loads((r/'gate_diag_build.json').read_text())
common=dict(module=spec['module'],clock_options=spec['clock_options'],concurrency=4,
    seed=58001,services=['movie','compose','rating'])
trials=[]
for name,arm in [('base_c4','base'),('selected_c4','selected_candidate')]:
    setting=spec['arms'][arm]
    trials.append(dict(common,name=name,overrides=setting['overrides'],clock=setting.get('clock',True),
        periods=[1021,4093] if arm=='base' else [4093,1021]))
trials.append(dict(common,name='gate_counter_c4',overrides=diag['overrides'],clock=True,
    periods=[],gate_stats=True,gate_only=True,original_gated=diag['original_gated']))
result=dict(out=str(r/'diagnostics_v4'),trials=trials,
    purpose='After all accepted E2E timings, separate schedule-age/residual-target/gate diagnostic',
    limitations=['Counter build changes execution. It is not the selected performance binary. It uses a separate counter-only window without PEBS.',
      'Counter policy is best gated screen policy; it can differ from the selected ungated policy.',
      'Base/candidate are reported at both periods, without pooling samples or selecting favorable bins.'],
    frozen_before_any_diagnostic=True)
b.save(r/'diagnostics_v4.json',result)
print(json.dumps(result,indent=2))

# Frozen optional saturation diagnostic; admission depends only on wall time.
saturation=[]
for name,arm in [('base_c16','base'),('selected_c16','selected_candidate')]:
    setting=spec['arms'][arm]
    saturation.append(dict(common,name=name,overrides=setting['overrides'],clock=setting.get('clock',True),
        concurrency=16,seed=59001,services=['movie'],periods=[1021,4093] if arm=='base' else [4093,1021]))
b.save(r/'diagnostics_c16.json',dict(out=str(r/'diagnostics_c16'),trials=saturation,
    purpose='MovieId schedule-age comparison near the prior throughput plateau; separate from E2E metrics',
    admission='Run only if primary diagnostics finish before12:33UTC, leaving >=19minutes for both captures and final report. Admission depends on time, never observed speedup.',
    frozen_before_any_diagnostic=True))
