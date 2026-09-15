#!/usr/bin/env python3
"""Insert llvm.prefetch of the callee's entry code lines before direct calls
to arc functions in an arcilator-emitted .ll file.

Replicates the AOT winner (static callsite family: prefetcht1 of callee
entry +0/+64 at call sites) directly at IR level. llvm.prefetch with
rw=0 locality=2 lowers to prefetcht1 on x86; the pointer operand is the
callee function address, so the target is code.

Usage: inject_callsite_prefetch.py in.ll out.ll [--lines N] [--callee-re RE]
Prints injection stats.
"""
import argparse
import re

CALL_RE = re.compile(r'^(\s*)(?:%[\w.]+ = )?(?:tail )?call [^@]*@([\w.$]+)\(')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inp')
    ap.add_argument('out')
    ap.add_argument('--lines', type=int, default=2,
                    help='64B lines to prefetch per callee (default 2)')
    ap.add_argument('--callee-re', default=r'.*_arc(_|$)',
                    help='regex of callee names to prefetch')
    ap.add_argument('--lookahead', type=int, default=0,
                    help='prefetch the callee of the K-th NEXT matching call '
                         'in the same source line stream instead of this one '
                         '(gives ~K arc-executions of prefetch lead time)')
    ap.add_argument('--stride', type=int, default=1,
                    help='inject at every Nth matching call site only')
    ap.add_argument('--cache-type', type=int, default=1,
                    help='llvm.prefetch cache type: 1=data(prefetcht1), '
                         '0=instruction(needs -mprefetchi)')
    ap.add_argument('--base-offset', type=int, default=0,
                    help='byte offset added to the callee entry for the '
                         'first prefetched line (e.g. 64 skips the entry '
                         'line that HW next-line prefetch already covers)')
    args = ap.parse_args()
    callee_re = re.compile(args.callee_re)

    lines_in = list(open(args.inp))
    # Pre-scan: for lookahead mode, map each matching call line index to the
    # callee of the K-th next matching call (within a window; the arc caller
    # bodies are huge single functions, so plain line order is call order).
    call_idx = [i for i, l in enumerate(lines_in)
                if (m := CALL_RE.match(l)) and callee_re.match(m.group(2))]
    callee_at = {i: CALL_RE.match(lines_in[i]).group(2) for i in call_idx}
    target_for = {}
    for pos, i in enumerate(call_idx):
        if pos % args.stride != 0:
            continue
        j = pos + args.lookahead
        if j < len(call_idx):
            target_for[i] = callee_at[call_idx[j]]

    out = []
    n_inj = 0
    uid = 0
    for idx, line in enumerate(lines_in):
        if idx in callee_at and idx in target_for:
            ind = CALL_RE.match(line).group(1)
            tgt = target_for[idx]
            for k in range(args.lines):
                off = args.base_offset + 64 * k
                if off == 0:
                    ptr = f'@{tgt}'
                else:
                    out.append(f'{ind}%pfp{uid} = getelementptr i8, '
                               f'ptr @{tgt}, i64 {off}\n')
                    ptr = f'%pfp{uid}'
                out.append(f'{ind}call void @llvm.prefetch.p0(ptr {ptr}, '
                           f'i32 0, i32 2, i32 {args.cache_type})\n')
                uid += 1
            n_inj += 1
        out.append(line)
    out.append('declare void @llvm.prefetch.p0(ptr, i32 immarg, i32 immarg, '
               'i32 immarg)\n')
    open(args.out, 'w').writelines(out)
    print(f'injected {n_inj} call sites x {args.lines} lines')


if __name__ == '__main__':
    main()
