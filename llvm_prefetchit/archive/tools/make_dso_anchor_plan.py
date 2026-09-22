#!/usr/bin/env python3
"""Build a per-request burst plan whose targets live inside DYNAMIC
libraries, reached via GOT-anchor addressing: for a hot DSO cacheline at
module offset X, pick an exported (dynsym) symbol A at offset a in the same
DSO and emit target = A + (X - a) with operand_mode got-symbol-offset. The
pass then emits `movq A@GOTPCREL(%rip), %reg; prefetcht1 delta(%reg)` —
register-based, works under ASLR with plain dynamic linking (intra-DSO
layout is fixed at lib link time).

Inputs: perf.data (L2I miss samples), the traced PID's maps snapshot,
site list (FUNC:file:line in the main binary), top-K.
"""
import argparse
import bisect
import json
import subprocess
from collections import Counter


def load_maps(maps_file):
    mods = []  # (start, end, path)
    for line in open(maps_file):
        parts = line.split()
        if len(parts) >= 6 and 'x' in parts[1]:
            s, e = (int(x, 16) for x in parts[0].split('-'))
            mods.append((s, e, parts[5]))
    return mods


def dynsyms(path):
    syms = []  # (off, name)
    try:
        out = subprocess.check_output(
            ['llvm-nm-19', '-D', '--defined-only', path], text=True)
    except subprocess.CalledProcessError:
        return syms
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 3 and p[1] in 'TWtw':
            syms.append((int(p[0], 16), p[2]))
    syms.sort()
    return syms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--perf-data', required=True)
    ap.add_argument('--maps', required=True)
    ap.add_argument('--site', action='append', required=True,
                    help='FUNC:file:line (site in main binary)')
    ap.add_argument('--top-k', type=int, default=64)
    ap.add_argument('--main-binary-name', default='PostStorageService')
    ap.add_argument('--output', required=True)
    args = ap.parse_args()

    mods = load_maps(args.maps)
    out = subprocess.check_output(
        ['perf', 'script', '-i', args.perf_data, '-F', 'ip'],
        text=True, stderr=subprocess.DEVNULL)
    lines = Counter()
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            ip = int(ln, 16)
        except ValueError:
            continue
        for s, e, path in mods:
            if s <= ip < e:
                # exec segment file offset ~ (ip - s) + segment file base;
                # for typical DSOs the exec segment vaddr == file offset
                # region start, so use module-relative offset of the SEGMENT
                # plus its p_vaddr base... approximate via ip - load_base
                # where load_base = s - segment_vaddr. We recover it from
                # the first exec segment's p_vaddr:
                lines[(path, (ip - s) >> 6, s)] += 1
                break

    # per-DSO segment vaddr for correcting module offsets
    segbase = {}
    for _, _, path in mods:
        if path in segbase or not path.startswith('/'):
            continue
        try:
            hdr = subprocess.check_output(['readelf', '-lW', path], text=True)
            for l in hdr.splitlines():
                p = l.split()
                if p and p[0] == 'LOAD' and 'E' in l.split()[-1] + l:
                    # first LOAD exec: VirtAddr field p[2]
                    if len(p) >= 3 and 'R E' in l:
                        segbase[path] = int(p[2], 16)
                        break
        except subprocess.CalledProcessError:
            pass

    dyncache = {}
    injections = []
    picked = 0
    for (path, seg_line_off, seg_start), cnt in lines.most_common():
        if picked >= args.top_k:
            break
        if args.main_binary_name in path:
            continue  # only DSO targets in this plan
        if path not in dyncache:
            dyncache[path] = dynsyms(path)
        syms = dyncache[path]
        if not syms:
            continue
        module_off = (seg_line_off << 6) + segbase.get(path, 0)
        offs = [o for o, _ in syms]
        i = bisect.bisect_right(offs, module_off) - 1
        if i < 0:
            continue
        aoff, aname = syms[i]
        delta = module_off - aoff
        if delta < 0 or delta > 0x7f000000:
            continue
        injections_per_site = {
            'mangled': aname, 'function': aname, 'demangled': aname,
            'file': path, 'line': 0, 'addr': hex(module_off),
            'cacheline64': hex(module_off & ~63),
            'symbol_offset': hex(delta & ~63),
            'symbol_size': '0x0', 'symbol_type': 'T',
            'operand': 'got-symbol-offset',
        }
        picked += 1
        for s in args.site:
            func, sfile, sline = s.split(':')[0], s.rsplit(':', 2)[1], \
                int(s.rsplit(':', 2)[2])
            injections.append({
                'prefetch_mnemonic': 'prefetcht1', 'samples': cnt,
                'site': {'mangled': func, 'function': func,
                         'demangled': func, 'file': sfile, 'line': sline,
                         'branch_type': 'BURST', 'lbr_depth': 1},
                'target': dict(injections_per_site),
                'site_rank': 1, 'target_rank': picked,
            })

    plan = {
        'schema': 'prefetchit.plan.v1',
        'binary': args.main_binary_name,
        'trace_dir': 'dso-anchor-burst',
        'injections': injections,
        'prefetch': {'mnemonic': 'prefetcht1',
                     'operand': 'got-symbol-offset',
                     'offset_mode': 'target-symbol-offset',
                     'byte_offsets': [0]},
        'options': {'generator': 'make_dso_anchor_plan'},
        'stats': {'planned_prefetches': len(injections),
                  'selected_injections': len(injections)},
    }
    with open(args.output, 'w') as fh:
        json.dump(plan, fh, indent=1)
    print(f'[ok] {picked} DSO targets x {len(args.site)} sites = '
          f'{len(injections)} injections')


if __name__ == '__main__':
    main()
