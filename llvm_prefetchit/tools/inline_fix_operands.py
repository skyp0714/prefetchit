#!/usr/bin/env python3
"""Make trace-derived prefetchit.plan.v1 plans link-safe for a multi-DSO build.
main plan : target defined in the executable -> pc-relative-symbol-offset; exported by a DSO -> got-symbol-offset; else drop
lib plans : every target -> got-symbol-offset if exported by some DSO's dynsym (a .so's own globals are preemptible), else drop
Usage: inline_fix_operands.py --main main.raw.plan.json --exe UserTimelineService --dynsyms dynsyms.txt
                              --libs lib1.raw.plan.json ... --out-main main.plan.json --out-libs libs.plan.json
dynsyms.txt: "<dso-file> <symbol>" per line (nm -D --defined-only, T/W/i)."""
import argparse, json, subprocess, copy
ap = argparse.ArgumentParser()
ap.add_argument('--main', required=True); ap.add_argument('--exe', required=True); ap.add_argument('--dynsyms', required=True)
ap.add_argument('--libs', nargs='*', default=[]); ap.add_argument('--out-main', required=True); ap.add_argument('--out-libs', required=True)
a = ap.parse_args()
exported = {ln.split()[1].split('@')[0] for ln in open(a.dynsyms) if len(ln.split()) >= 2}
defined_main = set()
for ln in subprocess.run(['llvm-nm-19', '--defined-only', a.exe], capture_output=True, text=True).stdout.splitlines():
    p = ln.split()
    if len(p) >= 3: defined_main.add(p[2])
def fix(plan, is_main):
    keep = []; st = {'pc': 0, 'got': 0, 'drop': 0}
    for inj in plan['injections']:
        sym = inj['target'].get('mangled') or inj['target'].get('function')
        if is_main and sym in defined_main:
            inj['target']['operand'] = 'pc-relative-symbol-offset'; st['pc'] += 1
        elif sym in exported:
            inj['target']['operand'] = 'got-symbol-offset'; st['got'] += 1
        else:
            st['drop'] += 1; continue
        keep.append(inj)
    plan['injections'] = keep
    return st
main = json.load(open(a.main)); s = fix(main, True)
json.dump(main, open(a.out_main, 'w')); print(f"main: {s} -> {len(main['injections'])} injections")
libs_plan = None; tot = {'pc': 0, 'got': 0, 'drop': 0}
for lp in a.libs:
    p = json.load(open(lp)); s = fix(p, False)
    for k in tot: tot[k] += s[k]
    if libs_plan is None:
        libs_plan = copy.deepcopy(p); libs_plan['injections'] = []
    libs_plan['injections'].extend(p['injections'])
    print(f"{lp.split('/')[-1]}: {s}")
if libs_plan is not None:
    libs_plan['prefetch']['operand'] = 'got-symbol-offset'
    json.dump(libs_plan, open(a.out_libs, 'w')); print(f"libs: {tot} -> {len(libs_plan['injections'])} injections")
