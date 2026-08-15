#!/usr/bin/env python3

import argparse
import csv
import json
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pgo-targets", required=True, type=Path)
    parser.add_argument("--static-plan", action="append", required=True, type=Path)
    parser.add_argument("--output-prefix", required=True, type=Path)
    return parser.parse_args()


def parse_int(value):
    return int(str(value), 0)


def main():
    args = parse_args()
    with args.pgo_targets.open(newline="") as handle:
        pgo_rows = list(csv.DictReader(handle))
    pgo = {}
    for row in pgo_rows:
        cacheline = parse_int(row["cacheline64"])
        pgo[cacheline] = pgo.get(cacheline, 0) + int(row["samples"])
    pgo_samples = sum(pgo.values())

    rows = []
    for path in args.static_plan:
        plan = json.loads(path.read_text())
        static = {
            parse_int(injection["target"]["cacheline64"])
            for injection in plan["injections"]
        }
        hits = static & pgo.keys()
        hit_samples = sum(pgo[cacheline] for cacheline in hits)
        rows.append(
            {
                "label": plan.get("options", {}).get(
                    "merge_label",
                    plan.get("options", {}).get("label", path.stem),
                ),
                "pgo_target_cachelines": len(pgo),
                "static_target_cachelines": len(static),
                "overlap_cachelines": len(hits),
                "pgo_target_recall": len(hits) / len(pgo) if pgo else 0.0,
                "pgo_sample_weighted_recall": hit_samples / pgo_samples
                if pgo_samples
                else 0.0,
                "static_precision": len(hits) / len(static) if static else 0.0,
                "plan_path": str(path.resolve()),
            }
        )

    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    with args.output_prefix.with_suffix(".csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    args.output_prefix.with_suffix(".json").write_text(
        json.dumps(rows, indent=2) + "\n"
    )
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
