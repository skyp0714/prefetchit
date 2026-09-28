from pathlib import Path
import gzip,hashlib,json,os,shutil,subprocess
r=Path('/storage/prefetchit/class_b_coverage_20260928');repo=Path('/home/hnpark2/prefetchit')
assert (r/'final_decision.json').exists() and (r/'selected_diagnostic_summary.json').exists()
out=repo/'llvm_prefetchit/migration/evidence/class_b_coverage_20260928';out.mkdir(parents=True,exist_ok=False)
allowed={'.json','.gz','.csv','.md','.py','.sh','.log','.txt','.tsv','.c','.cpp','.h'}
excluded={'benchmark_source','dependency_sources','__pycache__','plugin_indirect','plugin_lift','plugin_paths'}
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for x in iter(lambda:f.read(1024*1024),b''):h.update(x)
 return h.hexdigest()
manifest=[]
for directory,dirs,files in os.walk(r,followlinks=False):
 dirs[:]=sorted(d for d in dirs if d not in excluded and not d.startswith(('test_cache','tests_')) and not (Path(directory)/d).is_symlink())
 for name in sorted(files):
  p=Path(directory)/name
  if p.is_symlink() or p.suffix not in allowed or name in ('requests.json.gz','samples.txt','perf.data'):continue
  if p.suffix=='.gz' and not name.endswith(('.json.gz','.log.gz')):continue
  # Source/patch/result records only; no ELF, archive or trace payloads.
  with p.open('rb') as f:magic=f.read(8)
  assert not magic.startswith((b'\x7fELF',b'!<arch>')),(p,magic)
  relative=p.relative_to(r);dest=out/relative;compressed=p.suffix=='.log' and p.stat().st_size>65536
  if compressed:dest=dest.with_name(dest.name+'.gz')
  dest.parent.mkdir(parents=True,exist_ok=True)
  if compressed:
   with p.open('rb') as src,dest.open('wb') as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as target:shutil.copyfileobj(src,target)
  else:shutil.copyfile(p,dest)
  manifest.append(dict(source=str(p),source_sha256=sha(p),path=str(dest.relative_to(out)),sha256=sha(dest),bytes=dest.stat().st_size,lossless_log_compression=compressed))
(out/'manifest.json').write_text(json.dumps(dict(root=str(r),code_head_before_artifact_commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip(),files=manifest,bytes=sum(x['bytes'] for x in manifest),retention='No benchmark inputs, shared dependency trees, executable payloads or raw/decoded trace copies. Controlled copies are local; no NAS transfer.'),indent=2)+'\n')
print(json.dumps(dict(files=len(manifest),bytes=sum(x['bytes'] for x in manifest),path=str(out))))
