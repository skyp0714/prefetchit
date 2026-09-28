from pathlib import Path
import datetime, json, os, shutil, subprocess
r = Path('/storage/prefetchit/class_b_coverage_20260928')
read = lambda p: json.loads(p.read_text())
assert (r/'final_decision.json').exists()
restorations=[]; counters=[]
for stage in ('screen','screen_indirect','screen_paths','confirmation'):
    complete=read(r/stage/'complete.json'); rows=read(r/stage/'rows.json')
    assert len(rows)==complete['rows'] and all(x['valid'] for x in rows)
    for row in rows:
        folder=Path(row['output']); result=read(folder/'result.json')
        checks=dict(platform=read(folder.with_name(folder.name+'_platform')/'verified.json')['restored'],
                    scheduler=read(folder/'scheduler_restoration.json')['restored'],
                    module=read(folder/'clock_restoration.json')['unloaded'])
        assert all(checks.values())
        restorations.append(dict(stage=stage,trial=folder.name,checks=checks))
        for label,services in [('primary',result['pmu']),*result.get('pmu_extra',{}).items()]:
            for service,values in services.items():
                assert values['fully_scheduled'] and values['window']['completed']>0
                counters.append(dict(stage=stage,trial=folder.name,service=service,label=label,
                                     fully_scheduled=True))
captures=[]
for name in ('indirect_capture','selected_diagnostic'):
    assert read(r/(name+'_platform')/'verified.json')['restored']
    for p in sorted((r/name).glob('*/*/record_types.json')):
        values=read(p)
        assert not any(values.get(k,0) for k in ('LOST','LOST_SAMPLES','THROTTLE','UNTHROTTLE'))
        captures.append(dict(path=str(p),samples=values['SAMPLE'],quality_passed=True))
containers=subprocess.check_output(['docker','ps','-a','--filter','label=com.docker.compose.project=codex-b-fullset-media','--format','{{.Names}}'],text=True).splitlines()
modules={name:Path('/sys/module',name).exists() for name in ('prefetchit_sched_clock','wake_prefetch')}
assert not containers and not any(modules.values())
processes=[]
for line in subprocess.check_output(['ps','-eo','pid=,args='],text=True).splitlines():
    pid,args=line.strip().split(None,1)
    if int(pid)!=os.getpid() and str(r) in args and any(s in args for s in (
            'lean_study.py','dense_causes.py','closed_loop_load.py','perf record','perf stat',
            'build_paths.py','build_indirect.py','build_lift.py')):
        processes.append(dict(pid=int(pid),command=args))
assert not processes
result=dict(timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
    valid_e2e_trials=len(restorations),restorations=restorations,pmu_windows=counters,
    sample_captures=captures,remaining_experiment_containers=containers,
    modules_loaded=modules,remaining_experiment_processes=processes,
    free_bytes={p:shutil.disk_usage(p).free for p in ('/','/storage')},
    checks='All recorded platform and scheduler states restored; no campaign containers or kernel modules remain.')
(r/'final_environment_audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(valid_e2e_trials=len(restorations),pmu_windows=len(counters),
                     captures=len(captures),restored=True)))
