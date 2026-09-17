#!/usr/bin/env python3
"""Build per-file post-link plans from LBR-attributed (direct call site -> missed line) pairs.
Input pairs_direct.json: [[site_dso, site_off, target_dso, line_off, samples], ...] sorted by samples desc
(see flat_codegen/dsb_build/postlink/results/trace_utl). Greedy: take pairs in order until the requested
coverage of all pair samples is reached, honoring a per-site target budget; skip targets on the site's own line.
Usage: postlink_trace_plan.py pairs_direct.json OUTDIR --coverage 75 --budget 4
Writes OUTDIR/plan_<dso>.json (rewriter --plan format) and prints a summary."""
import argparse, collections, json, os
ap = argparse.ArgumentParser()
ap.add_argument('pairs'); ap.add_argument('outdir')
ap.add_argument('--coverage', type=float, default=75); ap.add_argument('--budget', type=int, default=4)
ap.add_argument('--min-samples', type=int, default=2)
a = ap.parse_args()
pairs = json.load(open(a.pairs)); tot = sum(p[4] for p in pairs)
plans = collections.defaultdict(lambda: collections.defaultdict(list)); cum = 0; used = 0
for sd, so, td, line, v in pairs:
    if cum >= a.coverage / 100 * tot or v < a.min_samples: break
    if sd == td and (line == (so & ~63)): continue
    lst = plans[sd][so]
    if len(lst) >= a.budget: continue
    lst.append([td, line]); cum += v; used += 1
os.makedirs(a.outdir, exist_ok=True)
for sd, sites in plans.items():
    json.dump([{"site": so, "targets": t} for so, t in sites.items()], open(os.path.join(a.outdir, f'plan_{sd}.json'), 'w'))
print(f"coverage {100*cum/tot:.1f}% of pair samples with {used} targets at {sum(len(s) for s in plans.values())} sites; per file: " +
      ", ".join(f"{sd} {len(s)} sites/{sum(len(t) for t in s.values())} targets" for sd, s in plans.items()))
