import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

repo=Path('/home/hnpark2/prefetchit')
sys.path.insert(0,str(repo/'llvm_prefetchit/scripts/class_b'))
import dense_build as b
from mechanism_archive import pack
from e2e_lbr import remove_generated

root=Path(__file__).parent
out=repo/'llvm_prefetchit/migration/evidence/class_b_mechanism_20260928/resume_frontend_completed'
out.mkdir(exist_ok=False)
b.space(root)
preflight=root/'hybrid_service_preflight'
rejected={p.name:p.read_text() for p in preflight.iterdir() if p.is_file() and 'rejection' in p.suffix}
b.save(preflight/'renamed_rejection_records.json',rejected)
old=root/'hybrid_native_preflight'
shim=old/'hybrid_map.so'
if shim.exists():
    audit=json.loads((old/'shim_build.json').read_text())
    assert b.sha(shim)==audit['sha256']
    source=subprocess.check_output(['git','show','HEAD:llvm_prefetchit/kernel/sched_clock/hybrid_map.c'],cwd=repo)
    assert hashlib.sha256(source).hexdigest()==audit['source_sha256']
    (old/'superseded_source.c').write_bytes(source)
    remove_generated([shim],old/'superseded_shim_cleanup.json',
        'Superseded only by diagnostic error-message changes. The successful UID999 ABI2 preflight retains and reuses hybrid_mapping_debug/hybrid_map.so. Preserve prior native outcomes, exact source, hash and build commands.')
phases=['callpath_frontend','resume_hint_probe','hybrid_service_preflight',
        'hybrid_mapping_debug','balanced_callpath_rejected_startup','hybrid_native_preflight']
pack(root,out/'artifacts',phases=phases)
manifest=json.loads((out/'artifacts/manifest.json').read_text())
bundles={}
for entry in manifest['entries']:
    p=out/'artifacts'/entry['bundle'];assert b.sha(p)==entry['sha256']
    with gzip.open(p,'rt') as stream:bundles[entry['bundle']]=json.load(stream)
traces=sorted((root/'callpath_frontend').rglob('request_path_traces.json'))
for p in traces:
    assert bundles['callpath_frontend.json.gz'][str(p.relative_to(root))]==json.loads(p.read_text())
remove_generated(traces,root/'callpath_frontend/request_trace_cleanup.json',
    'Request span graphs are incomplete and excluded from E2E/critical-path claims. Exact JSON values were verified against the compressed published bundle; keep compact quality/operation reports and archive/hash manifest, remove unused decoded copies.')
copies={
    'frontend_report.md':root/'callpath_frontend/report.md',
    'frontend_summary.json':root/'callpath_frontend/summary.json',
    'request_paths.json':root/'callpath_frontend/request_paths.json',
    'request_trace_cleanup.json':root/'callpath_frontend/request_trace_cleanup.json',
    'resume_probe_summary.json':root/'resume_hint_probe/summary.json',
    'hybrid_preflight_result.json':preflight/'diagnostic/result.json',
    'hybrid_preflight_complete.json':preflight/'complete.json',
    'superseded_shim_cleanup.json':old/'superseded_shim_cleanup.json',
    'publication_source.py':Path(__file__),
}
for name,source in copies.items():(out/name).write_bytes(source.read_bytes())
report=out/'frontend_report.md'
report.write_text(report.read_text().replace('../callpath_coverage75/screen_report.md','../coverage75_completed/screen_report.md')+
    '\nRequest spans: all six 200-trace sets have 177–200 incomplete parent graphs. Do not infer critical paths or E2E effects. See request_paths.json and the verified compressed raw records.\n')
b.save(out/'manifest.json',dict(source_root=str(root),files={p.name:dict(bytes=p.stat().st_size,sha256=b.sha(p)) for p in out.iterdir() if p.is_file()},
    phase_artifacts='artifacts/manifest.json',
    scope='Frontend diagnostics, native scheduler-handoff calibration and real hybrid functional preflight. No hybrid service E2E claim. Startup/mapping failures retained. Current balanced and hybrid timing campaigns are not archived while active.'))
print(json.dumps(dict(valid=True,output=str(out))))
