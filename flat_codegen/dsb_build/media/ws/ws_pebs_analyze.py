#!/usr/bin/env python3
"""ws_pebs_analyze.py — what DATA is cold after a wake? Classifies PEBS load-latency samples (perf script -F tid,time,ip,sym,addr,weight,dso)
by memory region (thread stacks, heap, exe data/bss, library data, mmap/anon), by latency class, by time since the thread's last switch-in,
and lists the top load sites. Usage: ws_pebs_analyze.py PEBS_DIR"""
import sys, os, re, bisect, collections, statistics

d = sys.argv[1]
regions = []
for l in open(os.path.join(d, 'maps.txt')):
    p = l.split()
    a, b = (int(x, 16) for x in p[0].split('-')); perm = p[1]; path = p[5] if len(p) > 5 else ''
    size = b - a
    if path.startswith('/'):
        kind = ('exe:' if 'MovieIdService' in path else 'lib:') + os.path.basename(path).split('.so')[0] + (':text' if 'x' in perm else ':data' if 'w' in perm else ':ro')
    elif path == '[heap]': kind = 'heap(brk)'
    elif path == '[stack]': kind = 'stack(main)'
    elif path.startswith('['): kind = path
    elif 8 << 20 <= size <= (8 << 20) + (64 << 10) and 'w' in perm: kind = 'stack(thread)'
    elif size >= (1 << 20) and 'w' in perm: kind = 'anon>=1MB(malloc arena/mmap)'
    else: kind = 'anon<1MB'
    regions.append((a, b, kind))
regions.sort(); starts = [r[0] for r in regions]
def region(addr):
    i = bisect.bisect_right(starts, addr) - 1
    return regions[i][2] if i >= 0 and addr < regions[i][1] else 'unmapped'
# switch-in times per tid
sw = collections.defaultdict(list)
for l in open(os.path.join(d, 'switch.txt')):
    m = re.match(r"\s*(\d+)\s+(\d+\.\d+):.*SWITCH(?:_CPU_WIDE)?\s+IN", l)
    if m: sw[int(m.group(1))].append(float(m.group(2)))
for t in sw: sw[t].sort()
samples = []
for l in open(os.path.join(d, 'samples.txt')):
    tok = l.split()
    if len(tok) < 6: continue
    try:   # perf script -F tid,time,ip,sym,addr,weight,dso prints: tid time: addr weight ip sym (dso)
        tid = int(tok[0]); t = float(tok[1].rstrip(':'))
        addr = int(tok[2], 16); w = int(tok[3]); ip = int(tok[4], 16); dso = tok[-1].strip('()')
        sym = ' '.join(tok[5:-1])
    except (ValueError, IndexError): continue
    since = None
    if tid in sw:
        i = bisect.bisect_right(sw[tid], t) - 1
        if i >= 0: since = (t - sw[tid][i]) * 1e6
    samples.append((tid, t, ip, sym, addr, w, dso, since))
print(f"samples {len(samples)}; latency (cycles) median {statistics.median(s[5] for s in samples):.0f}, p90 {sorted(s[5] for s in samples)[int(0.9*len(samples))]}")
def table(title, keyf, top=12):
    c = collections.Counter(); wsum = collections.Counter()
    for s in samples: c[keyf(s)] += 1; wsum[keyf(s)] += s[5]
    W = sum(wsum.values()) or 1; N = len(samples) or 1
    print(f"\n{title}: share of samples | share of latency-weight | median latency")
    for k, n in c.most_common(top):
        lat = statistics.median(s[5] for s in samples if keyf(s) == k)
        print(f"  {str(k)[:60]:60s} {100*n/N:5.1f}% | {100*wsum[k]/W:5.1f}% | {lat:5.0f}")
table("by region", lambda s: region(s[4]))
table("by latency class", lambda s: '<64' if s[5] < 64 else '64-127 (L2/near L3)' if s[5] < 128 else '128-255 (L3)' if s[5] < 256 else '256-511 (far L3/mem)' if s[5] < 512 else '>=512 (memory)')
table("by time since switch-in", lambda s: 'no switch info' if s[7] is None else '<5us' if s[7] < 5 else '5-20us' if s[7] < 20 else '20-50us' if s[7] < 50 else '>=50us')
table("top load sites (sym)", lambda s: s[3][:58], top=15)
table("region x latency>=128", lambda s: region(s[4]) if s[5] >= 128 else 'lat<128', top=10)
