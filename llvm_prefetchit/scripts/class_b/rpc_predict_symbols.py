#!/usr/bin/env python3
"""Name residual sampled instructions using bounded symbols and patch lineage.

No nearest-symbol guesses for whole cache lines. Symbol groups are descriptive
software locations, not causal hardware categories or dynamic call stacks.
"""
import argparse
import bisect
import collections
from pathlib import Path
import subprocess

import dense_build as b
from rpc_route_study import load
from temporal_path_analysis import read


class Symbols:
    def __init__(self,root):
        self.tables={};self.records={};self.by_digest={}
        paths=set()
        for arm in load(root/'arms.json').values():
            paths.update(arm['overrides'].values());paths.add(arm['mongo_binary'])
            for libraries in arm.get('libraries',{}).values():paths.update(libraries.values())
        metadata={Path(p+'.json') for p in paths}
        metadata.update((root/'builds').rglob('*.json'))
        for path in metadata:
            if not path.exists():continue
            record=load(path)
            if 'patches' in record:self.by_digest[record['sha256']]=record

    def bind(self,path,digest):
        # The recorder may retain a same-SHA local reference copy without the
        # builder's adjacent metadata. Identity follows SHA, not that copy path.
        if digest in self.by_digest:self.records[path]=self.by_digest[digest]

    def original(self, path, ip):
        seen=set();layers=[]
        while True:
            assert path not in seen;seen.add(path)
            if path not in self.records:
                meta=Path(str(path)+'.json')
                self.records[path]=load(meta) if meta.exists() else {}
            record=self.records[path]
            if 'patches' not in record or 'source' not in record:break
            containing=[p for p in record['patches'] if p['stub']<=ip<max(p['terminal_jumps'])+5]
            if containing:
                # Canonically shared stubs can correspond to several call sites.
                sites=sorted({p['site'] for p in containing})
                layers.append(dict(binary=str(path),sites=sites))
                if len(sites)!=1:return None,None,layers
                ip=sites[0]
            path=Path(record['source'])
        return path,ip,layers

    def lookup(self,path,ip):
        if path is None:return 'shared_stub_multiple_callsites'
        if path not in self.tables:
            assert path.is_file(),path
            symbols={}
            for mode in ([],['-D']):
                result=subprocess.run(['nm',*mode,'-S','--defined-only',str(path)],capture_output=True,text=True)
                for line in result.stdout.splitlines():
                    v=line.split()
                    if len(v)!=4 or v[2] not in 'TtWwiI':continue
                    try:start,size=int(v[0],16),int(v[1],16)
                    except ValueError:continue
                    if size:symbols[start]=(size,v[3])
            self.tables[path]=(sorted(symbols),symbols)
        starts,symbols=self.tables[path];index=bisect.bisect_right(starts,ip)-1
        if index<0:return 'no_bounded_symbol'
        start=starts[index];size,name=symbols[start]
        return name if ip<start+size else 'no_bounded_symbol'


def analyze(root):
    assert load(root/'all_measurements_complete.json')['valid']
    nominee=load(root/'production_selection.json')['nominee'];lookup=Symbols(root);outputs={}
    for scope,directory in [('apps','profiles'),('mongo','mongo_profiles')]:
        for name in ('full',nominee):
            functions=collections.Counter();segments=collections.Counter();stubs=collections.Counter()
            for path in sorted((root/directory/name).glob('*/l2/observations.json.gz')):
                data=read(path);weight=data['period']/data['requests'];catalog=data['catalog']
                for entry in catalog.values():lookup.bind(Path(entry['binary']),entry['sha256'])
                for row in data['rows']:
                    index=row['dso'];segments['all']+=weight
                    if index<0:segments['unmapped']+=weight;continue
                    image=data['names'][index];local=Path(catalog[image]['binary']);ip=row['ip']
                    original,address,layers=lookup.original(local,ip)
                    symbol=lookup.lookup(original,address)
                    segment='main' if image.startswith('/custom/') or Path(image).name=='mongod' else 'dso'
                    location='inserted_stub' if layers else 'original_code'
                    segments[segment+'_'+location]+=weight
                    functions[data['service'],segment,location,Path(image).name,symbol]+=weight
                    if layers:
                        first=layers[0]
                        stubs[data['service'],Path(image).name,tuple(first['sites'])]+=weight
            top=functions.most_common(50)
            names=[k[-1] for k,v in top]
            demangled=subprocess.check_output(['c++filt'],input='\n'.join(names)+'\n',text=True).splitlines()
            outputs[scope+'_'+name]=dict(per_request=dict(segments),top_functions=[
                dict(service=key[0],segment=key[1],location=key[2],image=key[3],symbol=key[4],
                     demangled=pretty,events_per_request=value,share_pct=100*value/segments['all'])
                for (key,value),pretty in zip(top,demangled)],top_stub_origins=[
                dict(service=key[0],image=key[1],original_callsites=list(key[2]),events_per_request=value)
                for key,value in stubs.most_common(30)])
    result=dict(groups=outputs,source_sha256=b.sha(__file__),
        interpretation='Actual sampled IP and bounded ELF symbol sizes; appended stub IPs mapped through recorded patch lineage to original callsite. Ambiguous shared stubs labeled explicitly. This identifies software locations, not BTB/TLB causality or dynamic call stacks. Original-code categories include prefetch targets and non-targets; do not equate them with uncovered counts.')
    b.save(root/'analysis/residual_symbols.json',result)
    for key,value in outputs.items():print(key,value['per_request'],value['top_functions'][:5])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);analyze(parser.parse_args().root)
