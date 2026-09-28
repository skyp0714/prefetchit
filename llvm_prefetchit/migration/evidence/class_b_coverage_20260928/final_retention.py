from pathlib import Path
import json, sys, shutil
repo = Path('/home/hnpark2/prefetchit')
sys.path.insert(0, str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b
from e2e_lbr import remove_generated
r = Path('/storage/prefetchit/class_b_coverage_20260928')
decision = json.loads((r/'final_decision.json').read_text())
assert (r/'selected_diagnostic_cleanup.json').exists()
spec = json.loads((r/'confirmation_spec.json').read_text())
originals = set(spec['arms']['base']['overrides'].values())
selected = set(spec['arms']['selected_it0']['overrides'].values()) | set(spec['arms']['selected_nop']['overrides'].values())
confirmed = decision['code_miss_confirmed']
paths = []
if not confirmed:
    for name in sorted(selected-originals):
        p = Path(name)
        assert p.is_relative_to(r/'builds')
        if p.exists(): paths.append(p)
# Keep the latest tested compiler plugin; older intermediate plugins are
# reproducible from retained snapshots, compiler command records and hashes.
for name in ('plugin_indirect', 'plugin_lift'):
    p = r/name/'PrefetchITPass.so'
    if p.exists(): paths.append(p)
if paths:
    remove_generated(paths, r/'final_generated_cleanup.json',
        'Residual diagnostics and compact results extracted. Remove unconfirmed candidate ELF/NOP files and superseded compiler plugins; retain originals, source/input/dependency resources and latest tested compiler plugin.')
removed_empty_directories=[]
for name in ('plugin_indirect','plugin_lift'):
    p=r/name
    if p.is_dir() and not p.is_symlink() and not any(p.iterdir()):
        p.rmdir();removed_empty_directories.append(str(p))
retained = [dict(path=name, bytes=Path(name).stat().st_size, sha256=b.sha(name))
            for name in sorted(selected-originals) if Path(name).exists()]
b.save(r/'final_retention.json', dict(code_miss_confirmed=confirmed,
    e2e_confirmed=decision['e2e_confirmed'], candidates=retained,
    purpose=('Confirmed code-miss research reference plus exact-layout controls. '
             'E2E promotion remains subject to the separate recorded decision.' if confirmed
             else 'No independently confirmed code-miss candidate retained.'),
    latest_plugin=dict(path=str(r/'plugin_paths/PrefetchITPass.so'),
                       sha256=b.sha(r/'plugin_paths/PrefetchITPass.so')),
    original_binaries_untouched=sorted(originals),
    removed_empty_directories=removed_empty_directories,
    free_bytes={p:shutil.disk_usage(p).free for p in ('/', '/storage')},
    nas_transfer=False))
print(json.dumps(dict(retained_candidate_files=len(retained), code_miss_confirmed=confirmed)))
