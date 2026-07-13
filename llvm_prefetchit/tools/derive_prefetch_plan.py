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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--max-target-rank", type=int, default=0)
    parser.add_argument("--max-site-rank", type=int, default=0)
    parser.add_argument("--depth-min", type=int, default=1)
    parser.add_argument("--depth-max", type=int, default=0)
    parser.add_argument("--lead-instructions", type=int)
    parser.add_argument("--byte-offsets", type=parse_offsets, default=parse_offsets("0"))
    args = parser.parse_args()

    if args.lead_instructions is not None and args.lead_instructions < 0:
        parser.error("--lead-instructions must be non-negative")

    plan = json.loads(args.input.read_text(encoding="utf-8"))
    if plan.get("schema") != "prefetchit.plan.v1":
        raise SystemExit("unsupported input plan schema")

    selected = []
    branch_types: Counter[str] = Counter()
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
        selected.append(injection)
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
            "derive_depth_min": args.depth_min,
            "derive_depth_max": args.depth_max,
            "derive_lead_instructions": args.lead_instructions,
            "prefetch_byte_offsets": args.byte_offsets,
        }
    )
    targets = {identity(injection.get("target") or {}) for injection in selected}
    sites = {identity(injection.get("site") or {}) for injection in selected}
    plan.setdefault("stats", {}).update(
        {
            "selected_injections": len(selected),
            "planned_prefetches": len(selected) * len(args.byte_offsets),
            "selected_targets": len(targets),
            "selected_targets_with_injections": len(targets),
            "unique_sites": len(sites),
            "branch_type_injections": dict(sorted(branch_types.items())),
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
