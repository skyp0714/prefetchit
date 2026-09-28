#!/usr/bin/env python3
"""Attribute retained miss-line aggregates to function ranges, without new traces.

Cache-line aggregates lose exact IPs. A line can overlap multiple functions, so
the output retains that ambiguity and apportions its weight by overlap bytes.
These are ranking scores, not exact per-function miss counts.
"""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import subprocess
import dense_build as b
import lean_plan


def symbol_ranges(binary):
    command=['nm','-S','-n','--defined-only',str(binary)]
    text=subprocess.check_output(command,text=True)
    aliases=defaultdict(set)
    for line in text.splitlines():
        fields=line.split(maxsplit=3)
        if len(fields)!=4 or fields[2] not in 'tTwW':
            continue
        start,size=int(fields[0],16),int(fields[1],16)
        if size:
            aliases[(start,start+size)].add(fields[3])
    return [dict(start=a,end=z,names=sorted(names)) for (a,z),names in sorted(aliases.items())],command


def attribute(lines, ranges, dso):
    scores=defaultdict(float)
    audit=[]
    total=unmapped=ambiguous=0
    for line in lines:
        if line['dso']!=dso:
            continue
        va=int(line['va'],16);count=line['samples'];total+=count
        overlaps=[(r,min(va+64,r['end'])-max(va,r['start'])) for r in ranges
                  if r['start']<va+64 and r['end']>va]
        denominator=sum(n for _,n in overlaps)
        if not denominator:
            unmapped+=count
            continue
        if len(overlaps)>1:
            ambiguous+=count
        candidates=[]
        for symbol, overlap in overlaps:
            score=count*overlap/denominator
            # Alias names share a single score; selecting either retains both.
            names=tuple(symbol['names']);scores[names]+=score
            candidates.append(dict(names=list(names),weight=score,overlap_bytes=overlap))
        audit.append(dict(va=line['va'],samples=count,candidates=candidates))
    ranked=[dict(names=list(names),score=score) for names,score in
            sorted(scores.items(),key=lambda item:(-item[1],item[0]))]
    return dict(total_main_samples=total,unmapped_samples=unmapped,
                ambiguous_line_samples=ambiguous,ranked=ranked,lines=audit)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('analysis',type=Path)
    parser.add_argument('baseline_root',type=Path)
    parser.add_argument('out',type=Path)
    parser.add_argument('--coverage',type=float,default=.8)
    args=parser.parse_args()
    if not 0<args.coverage<=1:
        parser.error('coverage must be in (0,1]')
    data=json.load(gzip.open(args.analysis,'rt'))['base']
    args.out.mkdir(parents=True,exist_ok=False)
    combined=set();results={}
    for service,exe in b.SERVICES.items():
        binary=args.baseline_root/service/exe
        ranges,command=symbol_ranges(binary)
        result=attribute(data[service]['events']['l2']['line_counts'],ranges,data[service]['main_dso'])
        target=args.coverage*(result['total_main_samples']-result['unmapped_samples'])
        selected=[];weight=0
        for symbol in result['ranked']:
            if weight>=target:
                break
            selected.extend(symbol['names']);weight+=symbol['score']
        combined.update(selected)
        result.update(binary=str(binary),sha256=b.sha(binary),symbol_command=command,
                      selected_names=selected,selected_score=weight,target_coverage=args.coverage)
        results[service]=result
    (args.out/'functions.txt').write_text('\n'.join(sorted(combined))+'\n')
    b.save(args.out/'profile.json',dict(analysis=str(args.analysis),analysis_sha256=b.sha(args.analysis),
        services=results,selected_union_count=len(combined),
        limitation='Byte-apportioned cache-line samples are ranking scores. Source availability and caller/target coverage need a separate final-build audit.'))


if __name__=='__main__':
    main()
