#!/usr/bin/env python3
"""Map precise miss IPs and retired taken-branch history to code/prefetch sites.

All profiles are read after the workload stops. The nearest taken branch is a
locality association, not proof of causality or of a missing BTB entry.
"""
import argparse
import bisect
import collections
import gzip
import json
from pathlib import Path
import re
import subprocess
import sys

import dense_build as b
sys.path.insert(0,str(b.REPO/'llvm_prefetchit/tools'))
from make_nop_control_binary import executable_sections
from lbr_padding_prefetch import HEADER,DSO,mapping_bias
EDGE=re.compile(r'0x([0-9a-f]+) ('+DSO+r')/0x([0-9a-f]+) ('+DSO+r')/([MPX-])/[^/]*/[^/]*/([0-9-]+)/([^/ ]+)/')
INSN=re.compile(r'^\s*([0-9a-f]+):\s*((?:[0-9a-f]{2}\s+)+)\s*(.*?)\s*$')
SYMBOL=re.compile(r'^([0-9a-f]+) <(.+)>:$')


def category(asm):
    words=asm.split()
    if not words:return 'unknown'
    while words and words[0] in ('bnd','notrack','rep','repz','repnz','data16','addr32'):words=words[1:]
    if not words:return 'other'
    op=words[0];operand=' '.join(words[1:])
    if op.startswith('call'):return 'indirect_call' if '*' in operand else 'direct_call'
    if op.startswith('ret'):return 'return'
    if op.startswith('jmp'):return 'indirect_jump' if '*' in operand else 'direct_jump'
    if op.startswith('j') or op.startswith('loop'):return 'conditional_branch'
    if op.startswith('prefetch'):return 'prefetch'
    return 'other'


class Code:
    def __init__(self,path):
        self.path=path;self.instructions={};self.symbols={};self.prefetches={};self.raw_targets={};self.unresolved=[]
        self.sections=executable_sections(str(path));function='unknown';history=[]
        cmd=['objdump','-d','--insn-width=16',str(path)]
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,text=True)
        for line in proc.stdout:
            symbol=SYMBOL.match(line.strip())
            if symbol:function=symbol[2];history=[];continue
            match=INSN.match(line)
            if not match:continue
            va=int(match[1],16);raw=bytes.fromhex(match[2]);asm=match[3]
            self.instructions[va]=(len(raw),asm,function)
            if category(asm)=='prefetch':
                target=None
                comment=re.search(r'#\s*([0-9a-f]+)',asm)
                if '(%rip)' in asm and comment:target=int(comment[1],16)
                else:
                    operand=re.search(r'(?:(0x[0-9a-f]+)|(-?\d+))?\(%(\w+)\)',asm)
                    if operand:
                        offset=int(operand[1] or operand[2] or '0',0);reg=operand[3]
                        # Resolve only the nearest write if it is an obvious constant.
                        for prev in reversed(history[-24:]):
                            if not re.search(r',%'+reg+r'\s*(?:#.*)?$',prev):continue
                            const=re.search(r'\$0x([0-9a-f]+),%'+reg,prev)
                            addr=re.search(r'#\s*([0-9a-f]+)',prev) if prev.startswith('lea') else None
                            if const or addr:target=int((const or addr)[1],16)+offset
                            break
                if target is None:self.unresolved.append(va)
                else:self.prefetches[va]=target&~63;self.raw_targets[va]=target
            history.append(asm)
            if category(asm) in ('direct_jump','indirect_jump','return'):history=[]
        assert proc.wait()==0
        self.addresses=sorted(self.instructions);self.pf_sites=sorted(self.prefetches)
        self.always_taken=sorted(va for va,row in self.instructions.items() if category(row[1]) in ('direct_call','indirect_call','direct_jump','indirect_jump','return'))
    def get(self,ip):return self.instructions.get(ip,(0,'unknown','unknown'))
    def sites(self,low,high):return self.pf_sites[bisect.bisect_left(self.pf_sites,low):bisect.bisect_right(self.pf_sites,high)]
    def straight(self,low,high):
        # Every unconditional branch before the endpoint must have appeared in LBR.
        return bisect.bisect_left(self.always_taken,high)==bisect.bisect_left(self.always_taken,low)


def analyze_service(folder,policy_folder=None,kinds=('l2','unknown','instructions')):
    maps=(folder/'maps.txt').read_text();metadata=json.loads((folder/'dsos.json').read_text())
    codes={};biases={};cache={};dsos={}
    for dso,entry in metadata.items():
        digest=entry['sha256']
        if digest not in cache:cache[digest]=Code(Path(entry['local']))
        codes[dso]=cache[digest]
        biases[dso]=mapping_bias(maps,re.compile('^'+re.escape(dso)+'$'),codes[dso].sections)
        dsos[Path(dso).name]=dso
    main=next(k for k in codes if k.startswith('/custom/'))
    actual_code=codes[main];policy_code=actual_code
    if policy_folder is not None:
        meta=json.loads((policy_folder/'dsos.json').read_text());policy_code=Code(Path(meta[main]['local']))
        # NOP twin has exactly the same instruction boundaries / targets.
        assert set(policy_code.instructions)==set(actual_code.instructions)
    target_lines=set(policy_code.prefetches.values())
    def resolve(dso):
        name=dso[1:-1]
        if name in codes:return name
        return dsos.get(Path(name).name)
    outputs={}
    for kind in kinds:
        path=folder/kind/'samples.txt'
        if not path.exists():continue
        counts=collections.Counter();dc=collections.Counter();fc=collections.Counter();ips=collections.Counter();ic=collections.Counter();bc=collections.Counter();distance=collections.Counter();lines=collections.Counter();lead=collections.Counter();spatial=collections.Counter()
        sample_rows=[]
        for text in path.open():
            header=HEADER.match(text)
            if not header:continue
            counts['samples']+=1;ip=int(header[2],16);dso=resolve(header[3]);dc[dso or header[3]]+=1
            if dso is None or biases[dso] is None:counts['unmapped']+=1;continue
            va=ip-biases[dso];code=codes[dso];length,asm,function=code.get(va)
            if not length:counts['ip_not_instruction_boundary']+=1
            ic[category(asm)]+=1;fc[dso+'::'+function]+=1;ips[(dso,va,asm,function)]+=1;lines[(dso,va&~63)]+=1
            if dso==main:
                counts['main_samples']+=1
                if va&~63 in target_lines:counts['statically_targeted_samples']+=1
            edges=[]
            for fr,fd,to,td,pred,cyc,typ in EDGE.findall(text):
                edges.append((int(fr,16),resolve(fd),int(to,16),resolve(td),pred,int(cyc) if cyc.isdigit() else None,typ))
            if not edges:counts['without_lbr']+=1;continue
            counts['with_lbr']+=1
            # A branch sampled on its own retirement can itself be newest LBR.
            if edges[0][0]==ip and edges[0][1]==dso:
                counts['sample_is_newest_branch']+=1;prior=edges[1:]
            else:prior=edges
            segments=[];nearest=None
            if prior:
                newest=prior[0]
                if newest[3]==dso and 0<=ip-newest[2]<=65536 and code.straight(newest[2]-biases[dso],va):
                    delta=ip-newest[2];counts['nearest_branch_target_associated']+=1
                    if delta<64:counts['within_64B_of_target']+=1
                    if ip>>6==newest[2]>>6:counts['same_line_as_target']+=1
                    bucket='0' if delta==0 else '1-15' if delta<16 else '16-63' if delta<64 else '64-255' if delta<256 else '256+'
                    distance[bucket]+=1
                    source_dso=newest[1]
                    branch_asm=codes[source_dso].get(newest[0]-biases[source_dso])[1] if source_dso in codes and biases[source_dso] is not None else 'unknown'
                    bc[category(branch_asm)]+=1
                    if newest[4]=='M':counts['nearest_branch_mispredicted']+=1
                    nearest=dict(source=hex(newest[0]),target=hex(newest[2]),type=category(branch_asm),mispredicted=newest[4]=='M',distance=delta)
                    segments.append((dso,newest[2],ip-1,0,'final_partial'))
            age=0
            for newer,older in zip(prior,prior[1:]):
                if (newer[1] is not None and newer[1]==older[3] and biases[newer[1]] is not None
                        and 0<=newer[0]-older[2]<=65536
                        and codes[newer[1]].straight(older[2]-biases[newer[1]],newer[0]-biases[newer[1]])):
                    segments.append((newer[1],older[2],newer[0],age,'completed'))
                if newer[5] is None or newer[5]>=65535:break
                age+=newer[5]
            issued=[];matching=[]
            for segd,low,high,age,where in segments:
                if segd!=main:continue
                bias=biases[main]
                for site in policy_code.sites(low-bias,high-bias):
                    issued.append((site,policy_code.prefetches[site],age,where))
                    if dso==main and policy_code.prefetches[site]==va&~63:matching.append((site,age,where))
            if issued:counts['preceding_observed_pf_samples']+=1
            counts['preceding_observed_pf_sites_total']+=len(issued)
            if matching:
                counts['preceding_matching_pf_samples']+=1
                if any(m[2]=='final_partial' for m in matching):lead['same_partial_block']+=1
                else:
                    minage=min(m[1] for m in matching)
                    lead['prior_block_minage_'+('0-31' if minage<32 else '32-127' if minage<128 else '128-511' if minage<512 else '512+')]+=1
            # Compact example rows are bounded; aggregate counts cover every sample.
            if len(sample_rows)<20:sample_rows.append(dict(ip=hex(va),dso=dso,asm=asm,nearest=nearest,pf_sites_seen=len(issued),matching_sites=[hex(m[0]) for m in matching]))
        n=counts['samples']
        recorded=json.loads((folder/kind/'record_types.json').read_text())['SAMPLE']
        assert n==recorded and n>100,(path,n,recorded)
        result=dict(counts=dict(counts),dso_counts=dict(dc),instruction_classes=dict(ic),preceding_branch_classes=dict(bc),distance_bytes=dict(distance),lead_retired_proxy=dict(lead),
            top_functions=[dict(name=name,samples=v,share_pct=100*v/n) for name,v in fc.most_common(25)],
            top_ips=[dict(dso=x[0],va=hex(x[1]),asm=x[2],function=x[3],samples=v) for x,v in ips.most_common(40)],
            footprint=dict(unique_sampled_lines=len(lines),unique_sampled_4k_pages=len({(d,va>>12) for d,va in lines}),
                samples_on_repeated_lines=sum(v for v in lines.values() if v>1)),
            line_counts=[dict(dso=d,va=hex(va),samples=v) for (d,va),v in lines.most_common()],
            examples=sample_rows,sha256=b.sha(path),bytes=path.stat().st_size)
        selected=[row for row in result['top_ips'] if row['dso']==main][:12]
        if selected:
            command=['addr2line','-a','-f','-C','-i','-e',str(actual_code.path),*[row['va'] for row in selected]]
            resolved=subprocess.check_output(command,text=True)
            result['main_ip_source_locations']=dict(command=command,output=resolved)
        outputs[kind]=result;b.save(folder/kind/'analysis.json',result)
    static=collections.Counter(resolved=len(policy_code.prefetches),unresolved=len(policy_code.unresolved),target_lines=len(target_lines))
    for site,target in policy_code.raw_targets.items():
        index=bisect.bisect_right(policy_code.addresses,target)-1
        inside=any(va<=target<va+size for va,off,size in policy_code.sections)
        periodic='0x1000(%rip)' in policy_code.get(site)[1]
        if periodic:static['periodic_sites']+=1
        if not inside:
            static['target_outside_executable_sections']+=1
            if periodic:static['periodic_outside_executable']+=1
            continue
        target_func=policy_code.get(policy_code.addresses[index])[2]
        if policy_code.get(site)[2]==target_func:static['target_same_function']+=1
        else:static['target_other_function']+=1
        if periodic:
            if policy_code.get(site)[2]==target_func:static['periodic_same_function']+=1
            else:static['periodic_other_function']+=1
    summary=dict(main_dso=main,static_prefetch=dict(static),events=outputs)
    b.save(folder/'analysis.json',summary)
    return summary


def analyze(root):
    output={}
    for arm in ('base','seq4k','seq4k_nop'):
        assert (root/arm/'complete.json').exists()
        output[arm]={}
        for key in b.SERVICES:
            output[arm][key]=analyze_service(root/arm/key,root/'seq4k'/key if arm=='seq4k_nop' else None)
    with gzip.open(root/'analysis.json.gz','wt') as stream:json.dump(output,stream,separators=(',',':'))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);a=p.parse_args();analyze(a.root)
