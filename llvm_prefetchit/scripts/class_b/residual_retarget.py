#!/usr/bin/env python3
"""Reuse existing RIP-hint slots for future branch targets seen in miss LBRs.

Train on an exact-layout NOP control, so useful existing hints are not punished
for having removed their own misses. Retired LBR cycle age is only a placement
proxy; no inference about actual issue-to-fetch latency or fill success.
"""
import argparse
import collections
import gzip
import json
from pathlib import Path
import re
import struct
import dense_build as b
from dense_cause_analysis import Code, HEADER, EDGE, mapping_bias
from lean_plan import sections, RECORD, SECTION, read_image

def observations(folder, policy, min_age=64, max_age=1024):
    code=Code(policy);maps=(folder/'maps.txt').read_text()
    active={r['site']:r['target'] for r in read_image(policy)['records'] if r['active'] and r['direct']}
    assert all(code.raw_targets[s]==t and code.get(s)[1].startswith('prefetcht1') for s,t in active.items())
    code.raw_targets=active;code.prefetches={s:t&~63 for s,t in active.items()};code.pf_sites=sorted(active)
    dsos=json.loads((folder/'dsos.json').read_text())
    main=next(k for k in dsos if k.startswith('/custom/'))
    # The trace binary is the exact-layout NOP version of this policy.
    nop=Path(dsos[main]['local']);control=Code(nop)
    assert set(code.instructions)==set(control.instructions)
    bias=mapping_bias(maps,re.compile('^'+re.escape(main)+'$'),code.sections)
    assert bias is not None
    def ismain(dso):return dso[1:-1] in (main,Path(main).name)
    rows=[];quality=collections.Counter()
    for text in (folder/'l2/samples.txt').open():
        header=HEADER.match(text)
        if not header:continue
        quality['samples']+=1
        if not ismain(header[3]):continue
        ip=int(header[2],16)-bias
        if ip not in code.instructions:continue
        quality['main_samples']+=1
        edges=[(int(fr,16)-bias,ismain(fd),int(to,16)-bias,ismain(td),int(cyc) if cyc.isdigit() else None)
               for fr,fd,to,td,pred,cyc,typ in EDGE.findall(text)]
        if edges and edges[0][0]==ip and edges[0][1]:edges=edges[1:]
        if not edges:continue
        target=ip
        newest=edges[0]
        if newest[3] and newest[2]//64==ip//64 and newest[2] in code.instructions:
            target=newest[2]  # actual taken destination, not an arbitrary byte
        eligible=set();age=0
        for newer,older in zip(edges,edges[1:]):
            if min_age<=age<=max_age and newer[1] and older[3]:
                low,high=older[2],newer[0]
                if 0<=high-low<=65536 and code.straight(low,high):eligible.update(code.sites(low,high))
            if newer[4] is None or newer[4]>=65535:break
            age+=newer[4]
            if age>max_age:break
        rows.append(dict(target=target,line=target//64,sites=sorted(eligible)))
    quality['eligible_samples']=sum(bool(x['sites']) for x in rows)
    return rows,dict(quality),code

def plan(rows, original, max_fraction=.25, min_gain=8):
    """Greedy observed-miss coverage, preserving old coverage via gain penalty."""
    exposures=collections.defaultdict(set);candidates=collections.defaultdict(set);anchors={}
    for index,row in enumerate(rows):
        anchors.setdefault(row['line'],row['target'])
        for site in row['sites']:
            exposures[site].add(index);candidates[(site,row['line'])].add(index)
    assignments={s:t//64 for s,t in original.items()}
    coverage=collections.Counter()
    for site,line in assignments.items():coverage.update(candidates.get((site,line),set()))
    initial=sum(v>0 for v in coverage.values());choices=[];changed=set()
    # Bound weak, speculative alternatives before optimization.
    bounded=[];by_site=collections.defaultdict(list)
    for (site,line),ids in candidates.items():by_site[site].append((len(ids),line))
    for site in sorted(exposures):
        top=sorted(by_site[site],key=lambda x:(-x[0],x[1]))[:8]
        bounded.extend((site,line) for count,line in top if count>=min_gain)
    for _ in range(int(len(original)*max_fraction)):
        best=None
        for site,line in bounded:
            if site in changed or assignments[site]==line:continue
            old=candidates.get((site,assignments[site]),set());new=candidates[(site,line)]
            gain=sum(coverage[i]==0 for i in new)-sum(coverage[i]==1 for i in old-new)
            key=(gain,len(new),-site,-line)
            if gain>=min_gain and (best is None or key>best[0]):best=(key,site,line)
        if best is None:break
        key,site,line=best;oldline=assignments[site]
        coverage.subtract(candidates.get((site,oldline),set()));coverage.update(candidates[(site,line)])
        choices.append(dict(site=site,old_target=original[site],target=anchors[line],gain=key[0],observations=key[1]))
        assignments[site]=line;changed.add(site)
    return dict(changes=choices,initial_covered=initial,final_covered=sum(v>0 for v in coverage.values()),
        samples=len(rows),hints=len(original),min_gain=min_gain,max_fraction=max_fraction,
        rule='At most one replacement per site; observed coverage loss charged against gain. No additional hint instructions.')

def patch(source,dest,choices,expected_sha):
    assert not dest.exists() and b.sha(source)==expected_sha
    code=Code(source)
    assert all(x['target'] in code.instructions for x in choices)
    original=source.read_bytes();data=bytearray(original);table=sections(original);audit=[]
    def offset(va):
        found=[s for s in table if s['flags']&4 and s['va']<=va< s['va']+s['size']]
        assert len(found)==1
        return found[0]['offset']+va-found[0]['va']
    updates={x['site']:x for x in choices};assert len(updates)==len(choices)
    for site,row in updates.items():
        off=offset(site);assert data[off:off+3]==b'\x0f\x18\x15'
        assert site+7+struct.unpack_from('<i',data,off+3)[0]==row['old_target']
        offset(row['target']);disp=row['target']-site-7;assert -(1<<31)<=disp<(1<<31)
        before=bytes(data[off+3:off+7]);struct.pack_into('<i',data,off+3,disp)
        audit.append(dict(offset=off+3,original=before.hex(),replacement=data[off+3:off+7].hex(),**row))
    metadata=set()
    for section in table:
        if section['name']!=SECTION:continue
        assert not section['flags']&2 and section['size']%RECORD.size==0
        for off in range(section['offset'],section['offset']+section['size'],RECORD.size):
            site,target,module,function,instance,group,arg,flags=RECORD.unpack_from(data,off)
            if site in updates:
                assert flags==3 and target==updates[site]['old_target']
                struct.pack_into('<Q',data,off+8,updates[site]['target']);metadata.add(site)
    assert metadata==set(updates)
    dest.parent.mkdir(parents=True,exist_ok=True);b.space(dest.parent)
    dest.write_bytes(data);dest.chmod(source.stat().st_mode)
    checked=Code(dest)
    for row in choices:
        assert row['target'] in checked.instructions and checked.raw_targets[row['site']]==row['target']
    b.save(dest.with_suffix('.retarget.json'),dict(source=str(source),source_sha256=expected_sha,
        path=str(dest),sha256=b.sha(dest),same_layout=True,extra_instructions=0,extra_executable_bytes=0,
        metadata_updated=True,changes=audit))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);p.add_argument('policy',type=Path)
    p.add_argument('dest',type=Path);p.add_argument('--min-age',type=int,default=64);p.add_argument('--max-age',type=int,default=1024)
    a=p.parse_args();rows,quality,code=observations(a.folder,a.policy,a.min_age,a.max_age)
    result=plan(rows,code.raw_targets);result.update(quality=quality,min_age=a.min_age,max_age=a.max_age,
        training_sha256=b.sha(a.folder/'l2/samples.txt'),binary_sha256=b.sha(a.policy))
    b.save(a.dest.with_suffix('.plan.json'),result)
    with gzip.open(a.dest.with_suffix('.observations.json.gz'),'wt') as f:json.dump(rows,f,separators=(',',':'))
    patch(a.policy,a.dest,result['changes'],result['binary_sha256'])
