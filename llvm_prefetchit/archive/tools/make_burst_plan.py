#!/usr/bin/env python3
"""Build a per-request BURST prefetch plan: a small set of sites (request/
query entry functions, executed once per unit of work) each prefetching the
top-K hot miss cachelines (symbol+offset targets). This bounds the dynamic
prefetch issue rate to requests/sec x K instead of callsite-execution rate —
the fix for ubiquitous-callee overload in OLTP/service workloads.

Usage:
  make_burst_plan.py --targets-csv selected_top_targets.csv \
     --site FUNC[:file:line] ... --top-k 64 --binary BIN --output plan.json
Site line is resolved from the binary debug info when not given
(first line of the function via nm+addr2line).
"""
import argparse
import csv
import json
import subprocess


def resolve_site(binary, func, addr2line, nm):
    out = subprocess.check_output([nm, '-S', '--defined-only', binary],
                                  text=True)
    addr = size = None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[3] == func and parts[2] in 'tT':
            addr, size = int(parts[0], 16), int(parts[1], 16)
            break
    if addr is None:
        raise SystemExit(f'function {func} not found in {binary}')
    # probe a few offsets into the function for a stable file:line
    for off in (0x10, 0x20, 0x40, 0x8):
        loc = subprocess.check_output(
            [addr2line, '-e', binary, hex(addr + off)], text=True).strip()
        if ':' in loc and not loc.startswith('??'):
            f, l = loc.rsplit(':', 1)
            l = l.split(' ')[0]
            if l.isdigit() and int(l) > 0:
                return f, int(l), addr
    raise SystemExit(f'no line info for {func}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--targets-csv', required=True)
    ap.add_argument('--site', action='append', required=True,
                    help='FUNC or FUNC:file:line')
    ap.add_argument('--top-k', type=int, default=64)
    ap.add_argument('--skip-top', type=int, default=0,
                    help='skip the N hottest targets (self-warming lines)')
    ap.add_argument('--binary', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--mnemonic', default='prefetcht1')
    ap.add_argument('--addr2line', default='llvm-addr2line-19')
    ap.add_argument('--nm', default='llvm-nm-19')
    args = ap.parse_args()

    targets = []
    with open(args.targets_csv) as fh:
        for row in csv.DictReader(fh):
            targets.append(row)
    targets = targets[args.skip_top:args.skip_top + args.top_k]

    # symbol table for target symbol_offset computation (cacheline - sym base)
    symtab = {}
    out = subprocess.check_output([args.nm, '-S', '--defined-only',
                                   args.binary], text=True)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[2] in 'tTwW':
            symtab[parts[3]] = int(parts[0], 16)

    injections = []
    for s in args.site:
        if s.count(':') >= 2:
            func, sfile, sline = s.split(':')[0], s.rsplit(':', 2)[1], \
                int(s.rsplit(':', 2)[2])
        else:
            sfile, sline, _ = resolve_site(args.binary, s, args.addr2line,
                                           args.nm)
            func = s
        for rank, t in enumerate(targets, 1):
            injections.append({
                'prefetch_mnemonic': args.mnemonic,
                'samples': int(t['samples']),
                'site': {
                    'mangled': func, 'function': func, 'demangled': func,
                    'file': sfile, 'line': sline,
                    'branch_type': 'BURST', 'lbr_depth': 1,
                },
                'target': {
                    'mangled': t['mangled'], 'function': t['function'],
                    'demangled': t['function'], 'file': t['file'],
                    'line': int(t['line']), 'addr': t['addr'],
                    'cacheline64': t['cacheline64'],
                    'symbol_offset': hex(max(0,
                        int(t['cacheline64'], 16)
                        - symtab.get(t['mangled'],
                                     int(t['cacheline64'], 16)))),
                    'symbol_size': t.get('symbol_size', '0x0'),
                    'symbol_type': 'T',
                },
                'site_rank': 1, 'target_rank': rank,
            })

    plan = {
        'schema': 'prefetchit.plan.v1',
        'binary': args.binary,
        'trace_dir': 'burst',
        'injections': injections,
        'prefetch': {
            'mnemonic': args.mnemonic,
            'operand': 'pc-relative-symbol-offset',
            'offset_mode': 'target-symbol-offset',
            'byte_offsets': [0],
        },
        'options': {'generator': 'make_burst_plan'},
        'stats': {'planned_prefetches': len(injections),
                  'selected_injections': len(injections)},
    }
    with open(args.output, 'w') as fh:
        json.dump(plan, fh, indent=1)
    print(f'[ok] burst plan: {len(args.site)} sites x '
          f'{len(targets)} targets = {len(injections)} injections')


if __name__ == '__main__':
    main()
