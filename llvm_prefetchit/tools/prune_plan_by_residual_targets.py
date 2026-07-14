#!/usr/bin/env python3
"""Keep PGO injections whose target misses fall in a residual profile."""

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path


def normalize_symbol(symbol: str) -> str:
    symbol = re.sub(r"@@?GLIBC[^ ]*$", "", symbol)
    return re.sub(r"@plt$", "", symbol)


def profile_symbol(target: str) -> str:
    fields = target.rsplit(":", 2)
    return normalize_symbol(fields[0] if len(fields) == 3 else target)


def read_counts(path: Path) -> Counter:
    counts = Counter()
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            counts[profile_symbol(row["target"])] += int(row["samples"])
    return counts


def target_aliases(target: dict) -> set[str]:
    return {
        normalize_symbol(str(target[key]))
        for key in ("demangled", "function", "mangled")
        if target.get(key)
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-plan", type=Path, required=True)
    parser.add_argument("--baseline-targets", type=Path, required=True)
    parser.add_argument("--residual-targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-csv", type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--min-baseline-samples", type=int, default=1)
    parser.add_argument("--min-absolute-reduction", type=int, default=1)
    parser.add_argument("--min-reduction-pct", type=float, default=0.0)
    parser.add_argument("--byte-offsets", default="0")
    args = parser.parse_args()

    offsets = [int(value) for value in args.byte_offsets.split(",")]
    baseline = read_counts(args.baseline_targets)
    residual = read_counts(args.residual_targets)
    rows = []
    for symbol in baseline.keys() | residual.keys():
        base = baseline[symbol]
        remaining = residual[symbol]
        reduction = base - remaining
        reduction_pct = 100.0 * reduction / base if base else 0.0
        eligible = (
            base >= args.min_baseline_samples
            and reduction >= args.min_absolute_reduction
            and reduction_pct >= args.min_reduction_pct
        )
        rows.append(
            {
                "symbol": symbol,
                "baseline_samples": base,
                "residual_samples": remaining,
                "reduction_samples": reduction,
                "reduction_pct": reduction_pct,
                "eligible": eligible,
            }
        )
    rows.sort(
        key=lambda row: (
            -row["reduction_samples"],
            -row["reduction_pct"],
            -row["baseline_samples"],
            row["symbol"],
        )
    )
    selected_rows = [row for row in rows if row["eligible"]]
    if args.max_symbols > 0:
        selected_rows = selected_rows[: args.max_symbols]
    selected_symbols = {row["symbol"] for row in selected_rows}

    plan = json.loads(args.input_plan.read_text())
    selected_injections = []
    matched_symbols = set()
    for injection in plan["injections"]:
        matches = target_aliases(injection["target"]) & selected_symbols
        if not matches:
            continue
        symbol = sorted(matches)[0]
        copy = dict(injection)
        copy["residual_target_delta"] = next(
            row for row in selected_rows if row["symbol"] == symbol
        )
        selected_injections.append(copy)
        matched_symbols.add(symbol)

    plan["injections"] = selected_injections
    plan.setdefault("prefetch", {})["byte_offsets"] = offsets
    options = plan.setdefault("options", {})
    options["label"] = args.label
    options["prefetch_byte_offsets"] = offsets
    options["residual_pruning"] = {
        "baseline_targets": str(args.baseline_targets),
        "residual_targets": str(args.residual_targets),
        "max_symbols": args.max_symbols,
        "min_baseline_samples": args.min_baseline_samples,
        "min_absolute_reduction": args.min_absolute_reduction,
        "min_reduction_pct": args.min_reduction_pct,
    }
    stats = plan.setdefault("stats", {})
    stats.update(
        {
            "selected_injections": len(selected_injections),
            "planned_prefetches": len(selected_injections) * len(offsets),
            "residual_selected_symbols": len(selected_symbols),
            "residual_matched_symbols": len(matched_symbols),
            "residual_selected_reduction_samples": sum(
                row["reduction_samples"] for row in selected_rows
            ),
            "residual_matched_reduction_samples": sum(
                row["reduction_samples"]
                for row in selected_rows
                if row["symbol"] in matched_symbols
            ),
        }
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2) + "\n")
    if args.audit_csv:
        args.audit_csv.parent.mkdir(parents=True, exist_ok=True)
        fields = list(rows[0]) + ["selected", "matched_plan"]
        with args.audit_csv.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        **row,
                        "selected": row["symbol"] in selected_symbols,
                        "matched_plan": row["symbol"] in matched_symbols,
                    }
                )
    print(
        f"[ok] selected_symbols={len(selected_symbols)} "
        f"matched_symbols={len(matched_symbols)} "
        f"injections={len(selected_injections)} "
        f"prefetches={len(selected_injections) * len(offsets)}"
    )


if __name__ == "__main__":
    main()
