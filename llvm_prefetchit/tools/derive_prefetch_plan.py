#!/usr/bin/env python3
"""Derive a smaller aggressiveness variant from a full PrefetchIT plan."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def parse_offsets(raw: str) -> list[int]:
    offsets = []
    for item in raw.split(","):
        value = int(item.strip(), 0)
        if value < 0:
            raise argparse.ArgumentTypeError("byte offsets must be non-negative")
        if value not in offsets:
            offsets.append(value)
    if not offsets:
        raise argparse.ArgumentTypeError("at least one byte offset is required")
    return offsets


def identity(record: dict) -> tuple[str, str]:
    return (
        str(record.get("mangled") or record.get("function") or record.get("addr")),
        str(record.get("symbol_offset") or record.get("line") or record.get("addr")),
    )


def cacheline64(record: dict) -> int | None:
    raw = record.get("cacheline64")
    if raw is None:
        return None
    try:
        return int(str(raw), 0)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--max-target-rank", type=int, default=0)
    parser.add_argument("--max-site-rank", type=int, default=0)
    parser.add_argument("--sites-per-target-after-filter", type=int, default=0)
    parser.add_argument("--depth-min", type=int, default=1)
    parser.add_argument("--depth-max", type=int, default=0)
    parser.add_argument("--lead-instructions", type=int)
    parser.add_argument("--byte-offsets", type=parse_offsets, default=parse_offsets("0"))
    parser.add_argument(
        "--exclude-site-target-same-cacheline",
        action="store_true",
        help="drop injections whose site already resides in the target's 64-byte line",
    )
    args = parser.parse_args()

    if args.lead_instructions is not None and args.lead_instructions < 0:
        parser.error("--lead-instructions must be non-negative")
    if args.sites_per_target_after_filter < 0:
        parser.error("--sites-per-target-after-filter must be non-negative")

    plan = json.loads(args.input.read_text(encoding="utf-8"))
    if plan.get("schema") != "prefetchit.plan.v1":
        raise SystemExit("unsupported input plan schema")

    eligible = []
    same_cacheline_filtered = 0
    same_cacheline_new_covered_samples_filtered = 0
    for injection in plan.get("injections") or []:
        target_rank = int(injection.get("target_rank") or 0)
        site_rank = int(injection.get("site_rank") or 0)
        site = injection.get("site") or {}
        depth = int(site.get("lbr_depth") or 0)
        if args.max_target_rank > 0 and target_rank > args.max_target_rank:
            continue
        if args.max_site_rank > 0 and site_rank > args.max_site_rank:
            continue
        if depth < args.depth_min:
            continue
        if args.depth_max > 0 and depth > args.depth_max:
            continue
        site_cacheline = cacheline64(site)
        target_cacheline = cacheline64(injection.get("target") or {})
        if (
            args.exclude_site_target_same_cacheline
            and site_cacheline is not None
            and site_cacheline == target_cacheline
        ):
            same_cacheline_filtered += 1
            same_cacheline_new_covered_samples_filtered += int(
                injection.get("new_covered_samples") or 0
            )
            continue
        eligible.append(injection)

    selected = []
    sites_kept_per_target: Counter[tuple[str, str]] = Counter()
    for injection in eligible:
        target_key = identity(injection.get("target") or {})
        if (
            args.sites_per_target_after_filter > 0
            and sites_kept_per_target[target_key]
            >= args.sites_per_target_after_filter
        ):
            continue
        selected.append(injection)
        sites_kept_per_target[target_key] += 1

    branch_types: Counter[str] = Counter()
    for injection in selected:
        site = injection.get("site") or {}
        branch_types[str(site.get("branch_type") or "UNKNOWN").upper()] += 1

    plan["injections"] = selected
    plan.setdefault("prefetch", {})["byte_offsets"] = args.byte_offsets
    if args.lead_instructions is not None:
        plan["prefetch"]["lead_instructions"] = args.lead_instructions
    plan.setdefault("options", {}).update(
        {
            "label": args.label,
            "derived_from": str(args.input.resolve()),
            "derive_max_target_rank": args.max_target_rank,
            "derive_max_site_rank": args.max_site_rank,
            "derive_sites_per_target_after_filter": (
                args.sites_per_target_after_filter
            ),
            "derive_depth_min": args.depth_min,
            "derive_depth_max": args.depth_max,
            "derive_lead_instructions": args.lead_instructions,
            "exclude_site_target_same_cacheline": (
                args.exclude_site_target_same_cacheline
            ),
            "prefetch_byte_offsets": args.byte_offsets,
        }
    )
    targets = {identity(injection.get("target") or {}) for injection in selected}
    sites = {identity(injection.get("site") or {}) for injection in selected}
    selected_new_covered_samples = sum(
        int(injection.get("new_covered_samples") or 0) for injection in selected
    )
    selected_site_samples = sum(
        int(injection.get("samples") or 0) for injection in selected
    )
    plan.setdefault("stats", {}).update(
        {
            "selected_injections": len(selected),
            "planned_prefetches": len(selected) * len(args.byte_offsets),
            "selected_targets": len(targets),
            "selected_targets_with_injections": len(targets),
            "unique_sites": len(sites),
            "selected_new_covered_samples": selected_new_covered_samples,
            "selected_site_samples": selected_site_samples,
            "branch_type_injections": dict(sorted(branch_types.items())),
            "same_cacheline_injections_filtered": same_cacheline_filtered,
            "same_cacheline_new_covered_samples_filtered": (
                same_cacheline_new_covered_samples_filtered
            ),
        }
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"[ok] wrote {args.output} injections={len(selected)} "
        f"prefetches={len(selected) * len(args.byte_offsets)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
