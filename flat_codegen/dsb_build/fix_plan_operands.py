#!/usr/bin/env python3
"""Split one trace-derived plan into link-safe per-module plans.

Shared libraries cannot take R_X86_64_PC32 against preemptible/undefined
symbols, and a PIE main cannot take it against DSO symbols — discovered
2026-08-19: every earlier deps-with-plan image silently shipped STOCK libs
because these links failed and rebuild_deps_g.sh's `make && make install`
chain swallowed the error (set -e does not fire mid-&&-list).

  main.plan.json : target defined in thin main   -> pc-relative (default)
                   target exported by DSO dynsym -> got-symbol-offset
                   otherwise                     -> dropped
  libs.plan.json : target exported by DSO dynsym -> got-symbol-offset
                   otherwise                     -> dropped
                   (inside a .so even same-lib global symbols are
                   preemptible, so GOT is the only always-valid mode)

Usage: fix_plan_operands.py <plan.json> <thin_main_binary> <dynsyms.txt> <outdir>
"""
import json, subprocess, sys, copy

plan_p, binary, dynsyms_p, outdir = sys.argv[1:5]

defined_main = set()
out = subprocess.check_output(['llvm-nm-19', '--defined-only', binary],
                              text=True, errors='replace')
for line in out.splitlines():
    parts = line.split()
    if len(parts) >= 3:
        defined_main.add(parts[2])

dso_exports = set(l.strip() for l in open(dynsyms_p) if l.strip())

plan = json.load(open(plan_p))


def base_name(t):
    name = t.get('mangled') or t.get('function') or ''
    return name.split('@@')[0].split('@')[0]


def classify(t):
    b = base_name(t)
    if b in defined_main:
        return 'internal'
    if b in dso_exports:
        return 'got'
    return 'drop'


stats = {'internal': 0, 'got': 0, 'drop': 0}
main_inj, libs_inj = [], []
for inj in plan['injections']:
    cls = classify(inj['target'])
    stats[cls] += 1
    if cls == 'drop':
        continue
    mi = copy.deepcopy(inj)
    b = base_name(mi['target'])
    mi['target']['mangled'] = b
    mi['target']['function'] = b
    if cls == 'got':
        mi['target']['operand'] = 'got-symbol-offset'
        main_inj.append(mi)
        libs_inj.append(copy.deepcopy(mi))
    else:  # internal to main: pc-relative in main; a lib build cannot
        main_inj.append(mi)  # reference it, so main-plan only

for suffix, injs in (('main', main_inj), ('libs', libs_inj)):
    p = copy.deepcopy(plan)
    p['injections'] = injs
    p['stats']['selected_injections'] = len(injs)
    with open(f'{outdir}/{suffix}.plan.json', 'w') as fh:
        json.dump(p, fh, indent=1)

print(f'[ok] {outdir}: internal={stats["internal"]} got={stats["got"]} '
      f'dropped={stats["drop"]} -> main={len(main_inj)} libs={len(libs_inj)}')
