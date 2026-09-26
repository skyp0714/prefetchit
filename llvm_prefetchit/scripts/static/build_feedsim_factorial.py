#!/usr/bin/env python3
"""Private FeedSim v2 F/G/FG builds with unchanged generated copy functions.

F = existing lead-four runtime target lookahead. G = static direct-call graph
plan applied to the seven handwritten feature-extractor translation units.
This explicitly bounded G scope is not a whole-program prefetch ceiling.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'llvm_prefetchit/tools'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from callgraph_prefetch_plan import symbol_table, parse_edges
from static_prefetch_graph import descendants, code_lines
from feedsim_future_policy import transform as future_source, MODES as FUTURE_MODES


def ir_edges(text, unit):
    """Recover direct IR calls before large-model lowering uses registers.

    Only syntactic direct callees are edges. Unknown SSA callees stay unknown;
    private/internal definitions have translation-unit-qualified identities.
    """
    name=r'("[^"\n]+"|[-a-zA-Z$._0-9]+)'
    definitions={}
    for line in text.splitlines():
        m=re.match(r'^define\b.*?@'+name+r'\(',line)
        if m:
            symbol=m[1].strip('"')
            definitions[symbol]=symbol+'@ir:'+unit if re.search(r'\b(internal|private)\b',line[:m.start(1)]) else symbol
    graph={v:[] for v in definitions.values()};current=None
    for line in text.splitlines():
        m=re.match(r'^define\b.*?@'+name+r'\(',line)
        if m:current=definitions[m[1].strip('"')];continue
        if line.startswith('}'):current=None;continue
        call=re.match(r'^\s*(?:%[^=]+=\s*)?(?:(?:tail|musttail|notail)\s+)?(?:call|invoke)\b(.*)',line)
        if not call or re.search(r'\basm\b',call[1].split('@',1)[0]):continue
        m=re.search(r'^[^@\n]*@'+name+r'\(',call[1])
        if current and m:
            target=m[1].strip('"');target=definitions.get(target,target)
            if target!=current and target not in graph[current]:graph[current].append(target)
    return graph


def digest(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def allocated_sections(path):
    """Verify debug stripping preserves every allocated section's bytes/VA."""
    with path.open('rb') as f:
        header=struct.unpack('<16sHHIQQQIHHHHHH',f.read(64))
        assert header[0][:6]==b'\x7fELF\x02\x01' and header[11]==64
        f.seek(header[6]); sections=[struct.unpack('<IIQQQQIIQQ',f.read(64)) for _ in range(header[12])]
        names=sections[header[13]];f.seek(names[4]);strings=f.read(names[5])
        result={}
        for section in sections:
            name,typ,flags,addr,offset,size,*_=section
            if not flags&2:continue
            key=strings[name:strings.index(b'\0',name)].decode()
            value=None
            if typ!=8:
                f.seek(offset);value=hashlib.sha256(f.read(size)).hexdigest()
            result[key]=(typ,flags,addr,size,value)
        return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--name',required=True)
    p.add_argument('--future',action='store_true')
    p.add_argument('--future-mode',choices=FUTURE_MODES,default='lead4')
    p.add_argument('--future-work-budget',type=int,default=0,
                   help='estimated static code bytes between current and future call; immutable startup metadata')
    p.add_argument('--future-work-lines',type=int,choices=[1,3],default=3,
                   help='static-work target coverage; default 3 matches the staged/near-entry comparison')
    p.add_argument('--depth',type=int,default=0)
    p.add_argument('--lines',type=int,default=1)
    a=p.parse_args()
    if a.future_mode!='lead4' and not a.future: p.error('--future-mode requires --future')
    if a.future_work_budget and (not a.future or a.future_mode!='lead4'):
        p.error('--future-work-budget requires --future with default future-mode')
    if a.future_work_budget<0:p.error('negative work budget')
    out=a.out.resolve(); d=out/a.name
    d.mkdir(parents=True,exist_ok=False)
    f=ROOT/'benchmarks/dcperf_v2/benchmarks/feedsim'
    build=f/'src/build-cbase'; sources=f/'src/workloads/ranking/feature_extractors'
    original=ROOT/'llvm_prefetchit/results/class_a2_20260923/feedsim/build/base/LeafNodeRank'
    work_meta=None
    if a.future_work_budget:
        from feedsim_work_policy import prepare_header, transform as work_source, copy_sizes
        work_meta=prepare_header(original,d)
        if a.future_work_lines==3:assert work_meta['size_min']>=129, 'Three-line coverage exceeds a generated function body'
    commands=subprocess.check_output(['ninja','-t','commands','workloads/ranking/LeafNodeRank'],cwd=build,text=True).splitlines()
    compile_commands=[]
    for source in sorted(sources.glob('*.cpp')):
        matches=[line for line in commands if '-c '+str(source) in line]
        if len(matches)!=1: raise RuntimeError(f'compile command missing/ambiguous: {source}')
        compile_commands.append((source,shlex.split(matches[0])))
    link_line=next(line for line in reversed(commands) if '-o workloads/ranking/LeafNodeRank ' in line)
    link_line=link_line.removeprefix(': && ').removesuffix(' && :')
    assert '&&' not in link_line
    roots=set()
    class_names={source.stem for source,_ in compile_commands}
    for _,cmd in compile_commands:
        obj=build/cmd[cmd.index('-o')+1]
        for line in subprocess.check_output(['nm','--defined-only',str(obj)],text=True).splitlines():
            parts=line.split()
            if (len(parts)==3 and parts[1] in {'T','W'} and
                    any(name in parts[2] for name in class_names)):
                roots.add(parts[2])
    plan=None
    if a.depth:
        cache=out/'graph.json'
        if cache.exists():
            data=json.loads(cache.read_text())
            assert data['sha256']==digest(original)
        else:
            symbols=symbol_table(original)
            proc=subprocess.Popen(['llvm-objdump-19','-d','--no-show-raw-insn',str(original)],stdout=subprocess.PIPE,text=True)
            graph=parse_edges(proc.stdout,symbols)
            if proc.wait(): raise RuntimeError('disassembly failed')
            data={'sha256':digest(original),'graph':graph,
                  'sizes':{v[0]:v[1] for v in symbols.values()},
                  'globals':[v[0] for v in symbols.values() if v[2]]}
            cache.write_text(json.dumps(data))
        if not data.get('ir_augmented'):
            ir_dir=out/'ir';ir_dir.mkdir(exist_ok=True)
            ir_manifest=[]
            for source,original_cmd in compile_commands:
                cmd=list(original_cmd);ir=ir_dir/(source.stem+'.ll')
                cmd[cmd.index('-o')+1]=str(ir)
                if '-MF' in cmd:cmd[cmd.index('-MF')+1]=str(ir)+'.d'
                cmd+=['-emit-llvm','-S']
                with (ir_dir/(source.stem+'.log')).open('w') as log:
                    subprocess.run(cmd,cwd=build,stdout=log,stderr=subprocess.STDOUT,check=True)
                edges=ir_edges(ir.read_text(),source.stem)
                data['graph'].update(edges)
                ir_manifest.append({'source':str(source),'source_sha256':digest(source),
                                    'ir_sha256':digest(ir),'command':cmd,'functions':len(edges),
                                    'edges':sum(map(len,edges.values()))})
            data['ir_augmented']=ir_manifest
            cache.write_text(json.dumps(data))
            (out/'ir_manifest.json').write_text(json.dumps(ir_manifest,indent=2))
        for entry in data['ir_augmented']:
            assert digest(Path(entry['source']))==entry['source_sha256'], 'IR source cache is stale'
        public=set(data['globals']); sites={}
        for site in sorted(roots & public):
            targets=[t for t in descendants(data['graph'],site,a.depth,a.depth)
                     if t!=site and t in public][:4]
            hints=code_lines(targets,data['sizes'],lines=a.lines,cap_to_size=True,budget=4,order='target')
            if hints: sites[site]={'k':7*len(hints),'t':hints}
        if not sites: raise RuntimeError('empty graph plan')
        plan=d/'graph_plan.json';plan.write_text(json.dumps({'sites':sites}))
        print(json.dumps({'graph_sites':len(sites),'hints':sum(len(s['t']) for s in sites.values())}),flush=True)
    env={k:v for k,v in os.environ.items() if not k.startswith('PREFETCHIT_')}
    if plan: env.update(PREFETCHIT_COLD_PLAN=str(plan),PREFETCHIT_COLD_DIRECT_IN_PIC='1')
    plugin=ROOT/'llvm_prefetchit/build/PrefetchITPass.so'
    emitted=[]; changed=[]
    for source,cmd in compile_commands:
        # F-only rebuilding other units is unnecessary; G applies to all seven.
        if source.name!='FeatureExtractorSuite.cpp' and not plan: continue
        code=source.read_text();private=d/source.name
        if source.name=='FeatureExtractorSuite.cpp' and a.future:
            code=work_source(code,a.future_work_budget,a.future_work_lines) if a.future_work_budget else future_source(code,a.future_mode)
        private.write_text(code)
        obj=d/(source.name+'.o')
        cmd[cmd.index('-o')+1]=str(obj);cmd[cmd.index('-c')+1]=str(private)
        if '-MF' in cmd:cmd[cmd.index('-MF')+1]=str(obj)+'.d'
        cmd+=['-I'+str(source.parent)]
        if plan:cmd+=['-fpass-plugin='+str(plugin)]
        with (d/(source.name+'.log')).open('w') as log:
            subprocess.run(cmd,cwd=build,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
        emitted.append({'source':str(source),'sha256':digest(private),'command':cmd})
        changed.append(obj)
    archive=d/'libfeatureExtractors.a'; full=d/'LeafNodeRank.full'; binary=d/'LeafNodeRank'
    shutil.copy2(build/'workloads/ranking/libfeatureExtractors.a',archive)
    subprocess.run(['llvm-ar-19','r',str(archive),*[str(obj) for obj in changed]],check=True)
    link=shlex.split(link_line);link[link.index('-o')+1]=str(full)
    link=[str(archive) if v.endswith('/libfeatureExtractors.a') else v for v in link]
    with (d/'link.log').open('w') as log:
        subprocess.run(link,cwd=build,stdout=log,stderr=subprocess.STDOUT,check=True)
    # Strip debug consistently across all arms; preserve loaded sections/symbols.
    subprocess.run(['objcopy','--strip-debug',str(full),str(binary)],check=True)
    allocated=allocated_sections(full)
    assert allocated==allocated_sections(binary), 'debug stripping changed loaded code/data'
    if work_meta:
        final_sizes=copy_sizes(binary)
        assert hashlib.sha256(json.dumps(final_sizes).encode()).hexdigest()==work_meta['sizes_and_names_sha256'], 'generated function size/order changed'
    meta={'future':a.future,'future_mode':'static_work' if a.future_work_budget else a.future_mode,'depth':a.depth,'lines':a.lines,'plan':str(plan),
          'compile':emitted,'link':link,'sha256':digest(binary),
          'original_sha256':digest(original),'plugin_sha256':digest(plugin),
          'strip_allocated_sections_verified':len(allocated),
          'scope':'seven handwritten extractor TUs; generated copy functions unchanged'}
    if work_meta:meta.update(future_work_budget=a.future_work_budget,future_work_lines=a.future_work_lines,work_sizes=work_meta,
                            dispatch_metadata='Second half of existing immutable vector, one future pointer per original dispatch index; original call permutation and cursor modulus preserved')
    (d/'manifest.json').write_text(json.dumps(meta,indent=2))
    full.unlink();archive.unlink()
    print(json.dumps({'name':a.name,'size':binary.stat().st_size,'sha256':meta['sha256']}),flush=True)


if __name__=='__main__':main()
