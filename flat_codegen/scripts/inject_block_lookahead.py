#!/usr/bin/env python3
"""Intra-function block-lookahead prefetch for arcilator mega-functions.

The arc 'clock' function is one huge mostly-straight-line body (LLVM inlines
most arcs). Misses live in that stream. This inserts, at every STRIDE-th
basic block of the target function, a prefetcht1 of blockaddress(fn, block
i+LOOKAHEAD) — the IR-level analog of the JCS V4 lookahead that won +28% in
JIT, with layout-order ~ block order in the .ll.

Usage: inject_block_lookahead.py in.ll out.ll --fn TestHarness_clock \
         [--stride 8] [--lookahead 32] [--lines 1]
"""
import argparse
import re

LABEL_RE = re.compile(r'^([A-Za-z0-9_.$]+):')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inp')
    ap.add_argument('out')
    ap.add_argument('--fn', default='TestHarness_clock')
    ap.add_argument('--stride', type=int, default=8)
    ap.add_argument('--lookahead', type=int, default=32)
    ap.add_argument('--lines', type=int, default=1)
    args = ap.parse_args()

    lines_in = list(open(args.inp))
    # locate the target function body
    start = end = None
    for i, l in enumerate(lines_in):
        if start is None and re.match(
                rf'define .*@{re.escape(args.fn)}\(', l):
            start = i
        elif start is not None and l.startswith('}'):
            end = i
            break
    assert start is not None and end is not None, 'fn not found'

    # collect block labels in order (entry block is unlabeled; skip it)
    labels = []
    for i in range(start + 1, end):
        m = LABEL_RE.match(lines_in[i])
        if m:
            labels.append((i, m.group(1)))
    print(f'{args.fn}: {len(labels)} labeled blocks')

    # insertion: after label of block j (stride-selected), prefetch
    # blockaddress of block j+lookahead
    inserts = {}  # line_idx -> text
    uid = 0
    n_inj = 0
    for pos in range(0, len(labels), args.stride):
        tgt = pos + args.lookahead
        if tgt >= len(labels):
            break
        line_idx, _ = labels[pos]
        _, tgt_label = labels[tgt]
        txt = ''
        ba = f'blockaddress(@{args.fn}, %{tgt_label})'
        for k in range(args.lines):
            if k == 0:
                txt += (f'  call void @llvm.prefetch.p0(ptr {ba}, '
                        f'i32 0, i32 2, i32 1)\n')
            else:
                txt += (f'  %blpfg{uid} = getelementptr i8, ptr {ba}, '
                        f'i64 {64*k}\n'
                        f'  call void @llvm.prefetch.p0(ptr %blpfg{uid}, '
                        f'i32 0, i32 2, i32 1)\n')
            uid += 1
        inserts[line_idx] = txt
        n_inj += 1

    out = []
    for i, l in enumerate(lines_in):
        out.append(l)
        if i in inserts:
            out.append(inserts[i])
    out.append('declare void @llvm.prefetch.p0(ptr, i32 immarg, i32 immarg, '
               'i32 immarg)\n')
    open(args.out, 'w').writelines(out)
    print(f'injected {n_inj} block-lookahead prefetch points '
          f'(stride={args.stride}, lookahead={args.lookahead})')


if __name__ == '__main__':
    main()
