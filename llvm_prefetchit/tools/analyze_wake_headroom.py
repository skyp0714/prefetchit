#!/usr/bin/env python3
"""Study retained Class-B first-touch marginals; these are NOT cache misses.

No benchmark, trace regeneration, NAS access, or source modification is performed.
The context-conditioned result is an oracle comparison: method/return context
observed after wake must not be assumed available to a switch-in kernel hook.
"""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path


def load_lines(path):
    with path.open() as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return [{"dso": r["dso"], "line": int(r["elf_line"], 16),
             "p": float(r["p"]), "rank": float(r["idx_med"]),
             "us": float(r["us_med"])} for r in rows]


def choose(rows, budget, p_min, horizon):
    # Probability prioritizes avoiding pollution; rank breaks ties toward early use.
    eligible = [r for r in rows if r["p"] >= p_min and r["rank"] < horizon]
    return sorted(eligible, key=lambda r: (-r["p"], r["rank"], r["dso"], r["line"]))[:budget]


def analyze(root):
    with (root / "runs.tsv").open() as f:
        runs = list(csv.DictReader(f, delimiter="\t"))
    if not runs:
        raise ValueError("empty runs")
    counts = collections.Counter(r["method"] + "__m" + r["first_mark"] for r in runs)
    first_touches = sum(int(r["distinct_lines"]) for r in runs)
    bytype = {name: load_lines(root / ("list_" + name + ".tsv"))
              for name in counts if (root / ("list_" + name + ".tsv")).exists()}
    # Missing rare-type files contribute no targets; never silently renormalize.
    combined = {}
    for name, rows in bytype.items():
        for row in rows:
            key = row["dso"], row["line"]
            x = combined.setdefault(key, dict(dso=key[0], line=key[1], p=0., rank_sum=0., mass=0.))
            mass = counts[name] * row["p"]
            x["p"] += mass / len(runs)
            x["rank_sum"] += mass * row["rank"]
            x["mass"] += mass
    global_rows = [dict(dso=x["dso"], line=x["line"], p=x["p"],
                        rank=x["rank_sum"] / x["mass"] if x["mass"] else 0)
                   for x in combined.values()]
    policies = []
    for budget in (8, 16, 32, 64):
        for p_min in (.5, .8, .95):
            for horizon in (32, 64, 128):
                selected = choose(global_rows, budget, p_min, horizon)
                useful = sum(r["p"] for r in selected)
                oracle_useful = oracle_issued = 0.
                for name, rows in bytype.items():
                    picked = choose(rows, budget, p_min, horizon)
                    weight = counts[name] / len(runs)
                    oracle_useful += weight * sum(r["p"] for r in picked)
                    oracle_issued += weight * len(picked)
                policies.append(dict(budget=budget, p_min=p_min, horizon=horizon,
                    global_issued_per_run=len(selected), global_expected_touched_per_run=useful,
                    global_touch_precision=useful / len(selected) if selected else None,
                    global_total_first_touch_coverage_pct=100 * useful * len(runs) / first_touches,
                    oracle_context_issued_per_run=oracle_issued,
                    oracle_context_expected_touched_per_run=oracle_useful,
                    oracle_context_touch_precision=oracle_useful / oracle_issued if oracle_issued else None,
                    oracle_context_total_first_touch_coverage_pct=100 * oracle_useful * len(runs) / first_touches,
                    global_targets=[dict(dso=r["dso"], elf_line=hex(r["line"]),
                                         p=r["p"], mean_context_median_rank=r["rank"]) for r in selected]))
    return dict(runs=len(runs), first_touches=first_touches,
                mean_first_touches_per_run=first_touches / len(runs),
                represented_runs=sum(counts[n] for n in bytype),
                by_type=dict(counts), policies=policies,
                input_hashes={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted(root.glob("*.tsv")) if "__shadow" not in p.name},
                limitations=["Rounded training marginals; no held-out accuracy estimate.",
                    "A touched line need not be a cache miss, critical, or reached after prefetch completes.",
                    "Median rank is not a per-run timing guarantee; global rank averages context medians.",
                    "Oracle method/return context is known after resumption, not at sched_switch.",
                    "Rare types omitted by the original exporter contribute zero predicted coverage."])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trace-root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    result = {}
    for service in ("compose", "rating", "composepost", "usertimeline"):
        root = a.trace_root / service / "runs"
        if root.exists():
            result[service] = analyze(root)
    if not result:
        p.error("no retained runs found")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2) + "\n")
    for service, r in result.items():
        print(service, "runs", r["runs"], "first touches/run", round(r["mean_first_touches_per_run"], 1))
        for row in r["policies"]:
            if row["p_min"] == .8 and row["horizon"] == 64:
                print("  budget", row["budget"], "global touched/run", round(row["global_expected_touched_per_run"], 2),
                      "oracle touched/run", round(row["oracle_context_expected_touched_per_run"], 2),
                      "global coverage %", round(row["global_total_first_touch_coverage_pct"], 2))


if __name__ == "__main__":
    main()
