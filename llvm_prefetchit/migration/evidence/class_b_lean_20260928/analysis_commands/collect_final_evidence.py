from pathlib import Path
import hashlib,json,shutil
repo=Path('/home/hnpark2/prefetchit');r=Path('/storage/prefetchit/class_b_lean_20260928')
out=repo/'llvm_prefetchit/migration/evidence/class_b_lean_20260928'
manifest=json.loads((out/'manifest.json').read_text())
def keep(source,relative=None):
    assert source.is_file() and not source.is_symlink(),str(source)
    relative=relative or source.relative_to(r)
    dest=out/relative;dest.parent.mkdir(parents=True,exist_ok=True)
    assert source.stat().st_size<8_000_000,'Review unusually large compact artifact: '+str(source)
    shutil.copyfile(source,dest)
    manifest[str(relative)]=dict(source=str(source),stored=str(dest.relative_to(repo)),
        sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),bytes=dest.stat().st_size)
for phase in ('screen_v3','screen_v4','confirmation_c4','confirmation_c16','screen_v5'):
    root=r/phase
    if phase=='screen_v5' and not root.exists():continue
    if phase!='screen_v5':assert (root/'complete.json').exists(),phase
    for name in ('protocol.json','rows.json','complete.json','summary.json','evaluation.json',
                 'compact_pmu.json','restoration_audit.json','service_rows.json','service_comparisons.json'):
        if (root/name).exists():keep(root/name)
    rows=json.loads((root/'rows.json').read_text()) if (root/'rows.json').exists() else []
    for row in rows:
        trial=Path(row['output'])
        for name in ('result.json','nginx_processes_postroi.json'):
            if (trial/name).exists():keep(trial/name,Path(phase)/'trials'/(trial.name+'.'+name))
patterns=['*_cleanup.json','*_failure.json','sources_*.json','test_v4*.log','test_v4*.command.json',
          'v4*json','v5*json','confirmation*json','diagnostics*.json','gate_diag*json','static_progression.json',
          'evaluator_service_validation.json','timeline_normalization_test.json','final*json',
          'artifact_retention.json','build_v4c_complete.json','remaining_sequence.json','late_sequence.json','diagnostic_sequence_hold.json','build_gate_diagnostic.log','finish_gate_diagnostic.log']
selected=set()
for pattern in patterns:selected.update(p for p in r.glob(pattern) if p.is_file())
for path in sorted(selected):keep(path)
# Keep the small final-address patch maps with the results so reviewers can
# reconstruct the exact NOP/IT0 edits after the rejected ELFs are removed.
for path in sorted(r.glob('builds/*/*/*.patches.json.gz')):keep(path)
for pattern in ('lean_v4_*_metadata.json.gz','lean_v3_profile_metadata.json.gz',
                'gate_diag_metadata.json.gz','v5_metadata.json.gz'):
    for path in sorted(r.glob(pattern)):keep(path)
for pattern in ('build_v5.log','screen_v5.log','diagnostics_late.log',
                'run_late_v5.log','confirmation_c4.log','confirmation_c16.log'):
    if (r/pattern).exists():keep(r/pattern)
for name in ('prepare_confirmations.py','build_gate_diagnostic.py','prepare_diagnostics.py',
             'run_confirmations.py','run_remaining.py','build_v5.py','run_late_v5.py','make_final_sections.py','finalize_campaign.py','finish_gate_diagnostic.py','gate_diag_failed_builder.py','summarize_final_pmu.py','analyze_residual_locations.py','render_final_report.py','collect_final_evidence.py'):
    keep(r/name,Path('analysis_commands')/name)
for name in ('final_methods.md','final_interpretation.md'):
    if (r/name).exists():keep(r/name,Path('analysis_commands')/name)
for diagnostic in (r/'diagnostics_v4',r/'diagnostics_c16',r/'diagnostics_late'):
    if not diagnostic.exists():continue
    for name in ('protocol.json','complete.json','timeline_summary.json','decode_failures.json'):
        if (diagnostic/name).exists():keep(diagnostic/name)
    for trial in diagnostic.iterdir():
        if not trial.is_dir() or trial.name.endswith('_platform'):continue
        for name in ('protocol.json','complete.json','load_validation.json','clock_restoration.json','failure.json','failed_capture_cleanup.json','decode_failures.json','gate_only.json'):
            if (trial/name).exists():keep(trial/name)
        for path in trial.glob('*.symbols.json.gz'):keep(path)
        platform=trial.with_name(trial.name+'_platform')/'verified.json'
        if platform.exists():keep(platform)
        for capture in trial.glob('*_p*'):
            if not capture.is_dir():continue
            for name in ('timeline.json','target_overlap.json','request_window.json','gate_activity.json',
                         'record_types.json','cleanup.json','protocol.json','record.log','decode_command.json',
                         'quality_command.json','decode_failure.json','main_ip_counts.json.gz'):
                if (capture/name).exists():keep(capture/name)
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(dict(files=len(manifest),bytes=sum(v['bytes'] for v in manifest.values())),indent=2))
