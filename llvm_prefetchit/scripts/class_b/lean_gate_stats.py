#!/usr/bin/env python3
"""Decode explicit diagnostic gate counters; these are not performance samples."""
import struct
import time
import os
from pathlib import Path

CATEGORIES=('early','eligible','expired','memo_cached')


def read(path):
    before=time.monotonic()
    with Path(path).open('rb') as source:
        raw=source.read();identity=os.fstat(source.fileno())
    after=time.monotonic()
    header=struct.unpack_from('<8Q',raw)
    magic,version,cpus,tiers,categories,pid,size,stride=header
    assert (magic,version,cpus,tiers,categories,stride)==(0x5046474154453031,1,4096,3,4,128)
    assert size==len(raw)==64+cpus*stride
    counts={}
    for cpu in range(cpus):
        values=struct.unpack_from('<12Q',raw,64+cpu*stride)
        if any(values):counts[str(cpu)]=list(values)
    return dict(header=list(header),file_identity=dict(device=identity.st_dev,inode=identity.st_ino),
        counts_by_cpu=counts,monotonic_before=before,monotonic_after=after,
        categories=CATEGORIES,layout='CPU rows; tier0 categories0..3, tier1, tier2',
        limitation='Relaxed atomic counters read while live, without a global stop. Counter instrumentation perturbs execution; eligible gate returns are not completed cache fills or exact hardware hint-issue counts.')


def delta(before,after):
    assert before['header']==after['header'],'Diagnostic service/file identity changed'
    assert before['file_identity']==after['file_identity'],'Diagnostic counter file replaced'
    totals=[0]*12
    for cpu in set(before['counts_by_cpu'])|set(after['counts_by_cpu']):
        a=after['counts_by_cpu'].get(cpu,[0]*12);b=before['counts_by_cpu'].get(cpu,[0]*12)
        difference=[x-y for x,y in zip(a,b)]
        assert all(x>=0 for x in difference),'Counters decreased'
        totals=[x+y for x,y in zip(totals,difference)]
    return dict(tiers=[dict(zip(CATEGORIES,totals[4*tier:4*tier+4])) for tier in range(3)],
        checks=sum(totals),eligible=sum(totals[1::4]),
        eligible_pct=100*sum(totals[1::4])/sum(totals) if sum(totals) else None,
        elapsed_s=after['monotonic_before']-before['monotonic_before'],limitation=after['limitation'])
