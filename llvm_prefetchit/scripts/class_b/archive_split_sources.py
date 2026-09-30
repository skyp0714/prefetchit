#!/usr/bin/env python3
"""Retain byte-exact source revisions recorded by the completed experiments."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import dense_build as b


def archive(root):
    for stage in root.glob('*_screen'):
        if stage.is_dir():assert json.loads((stage/'complete.json').read_text())['valid'],stage
    requirements={}
    def require(path,sha,record):
        path=Path(path)
        if path.suffix not in ['.py','.c','.cc','.cpp','.h','.S','.s']:return
        relative=path.relative_to(b.REPO)
        requirements.setdefault((str(relative),sha),[]).append(str(record.relative_to(root)))
    records=[root/'prepared_complete.json',*root.glob('*_screen/protocol.json'),
        *root.glob('*confirmation_plan.json'),root/'l1_topdown_quality_amendment.json']
    for path in records:
        if not path.exists():continue
        value=json.loads(path.read_text())
        for source,sha in value.get('source_hashes',{}).items():require(source,sha,path)
    path=root/'l1_topdown_quality_amendment.json'
    if path.exists():require(b.REPO/'llvm_prefetchit/scripts/class_b/split_l1_continue.py',
        json.loads(path.read_text())['source_sha256'],path)
    for path in [*root.glob('*_screen/topdown.json'),root/'diagnosis/summary.json']:
        if path.exists():
            script='split_topdown_report.py' if path.name=='topdown.json' else 'split_diagnosis_summary.py'
            require(b.REPO/'llvm_prefetchit/scripts/class_b'/script,json.loads(path.read_text())['source_sha256'],path)
    for folder,script in [('l1_supplement','split_l1_supplement.py'),('latency_retarget','split_latency_retarget.py')]:
        path=root/folder/'protocol.json'
        if not path.exists():continue
        value=json.loads(path.read_text())
        require(b.REPO/'llvm_prefetchit/scripts/class_b'/script,value['source_sha256'],path)
        require(b.REPO/'llvm_prefetchit/scripts/class_b/backend_prefetch.py',value['capture_sha256'],path)
        if 'builder_sha256' in value:
            require(b.REPO/'llvm_prefetchit/tools/call_stub_prefetch.py',value['builder_sha256'],path)
    out=root/'source_snapshots';out.mkdir(exist_ok=True);entries=[]
    if (out/'manifest.json').exists():assert not json.loads((out/'manifest.json').read_text())['complete']
    sha256=lambda data:hashlib.sha256(data).hexdigest()
    for (relative,expected),used_by in sorted(requirements.items()):
        path=b.REPO/relative;raw=path.read_bytes() if path.is_file() else b''
        origin='current workspace';revision=None
        if sha256(raw)!=expected:
            revisions=subprocess.check_output(['git','log','-n','100','--format=%H','--',relative],cwd=b.REPO,text=True).splitlines()
            for revision in revisions:
                result=subprocess.run(['git','show',revision+':'+relative],cwd=b.REPO,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                if result.returncode==0 and sha256(result.stdout)==expected:
                    raw=result.stdout;origin='git blob';break
            else:raise AssertionError(('Recorded source revision not found',relative,expected))
        assert len(raw)<1024*1024 and sha256(raw)==expected
        destination=out/(expected+'_'+path.name)
        if destination.exists():assert destination.read_bytes()==raw
        else:destination.write_bytes(raw)
        entries.append(dict(path=relative,sha256=expected,snapshot=str(destination.relative_to(root)),
            bytes=len(raw),origin=origin,git_revision=revision,used_by=used_by))
        b.save(out/'manifest.json',dict(complete=False,entries=entries))
    b.save(out/'manifest.json',dict(complete=True,entries=entries,source_sha256=b.sha(__file__),
        git_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=b.REPO,text=True).strip(),
        scope='Exact recorded E2E/confirmation/quality-wrapper source hashes, plus L1I and long-stall preparation/capture/builder revisions. Generated binaries are not copied. Historical blobs are searched at most 100 file-changing commits per path and checked by SHA-256.'))
    print(json.dumps(dict(snapshots=len(entries),bytes=sum(row['bytes'] for row in entries))))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);archive(parser.parse_args().root)
