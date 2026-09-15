#!/usr/bin/env python3

import argparse
import csv
import json
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--variant", action="append", required=True, type=Path)
    parser.add_argument("--output-prefix", required=True, type=Path)
    return parser.parse_args()


def load(path):
    with path.open() as handle:
        return json.load(handle)


def main():
    args = parse_args()
    baseline = load(args.baseline)
    rows = []
    for path in [args.baseline, *args.variant]:
        item = load(path)
        rows.append(
            {
                "label": item["label"],
                "valid": item["valid"],
                "qps": item["qps"],
                "speedup": item["qps"] / baseline["qps"],
                "l2i_mpki": item["l2i_mpki"],
                "l2i_reduction_pct": 100.0
                * (baseline["l2i_mpki"] - item["l2i_mpki"])
                / baseline["l2i_mpki"],
                "cpu_migrations": item["cpu_migrations"],
                "mid_tids": item["mid_tids"],
                "failed_responses": item["failed_responses"],
                "summary_path": str(path.resolve()),
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
