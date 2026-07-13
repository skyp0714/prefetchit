#!/usr/bin/env python3
"""Merge multiple prefetchit plan JSON files into one deduplicated plan."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def injection_key(inj: dict[str, Any]) -> tuple[Any, ...]:
    site = inj.get("site") or {}
    target = inj.get("target") or {}
    return (
        inj.get("prefetch_mnemonic", ""),
        site.get("mangled") or site.get("function") or site.get("addr"),
        site.get("symbol_offset") or site.get("line") or site.get("addr"),
        target.get("mangled") or target.get("function") or target.get("addr"),
        target.get("symbol_offset") or target.get("line") or target.get("addr"),
    )


def target_key(inj: dict[str, Any]) -> tuple[Any, ...]:
    target = inj.get("target") or {}
    return (
        target.get("mangled") or target.get("function") or target.get("addr"),
        target.get("symbol_offset") or target.get("line") or target.get("addr"),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--label", default="merged")
    ap.add_argument("--plan", type=Path, action="append", required=True)
    args = ap.parse_args()

    plans = [json.loads(path.read_text(encoding="utf-8")) for path in args.plan]
    if not plans:
        raise SystemExit("no plans provided")

    first = plans[0]
    schema = first.get("schema")
    prefetch = first.get("prefetch") or {}
    byte_offsets = prefetch.get("byte_offsets") or [0]

    merged: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    source_stats = []
    branch_counts: Counter[str] = Counter()
    duplicates = 0
    for path, plan in zip(args.plan, plans):
        if plan.get("schema") != schema:
            raise SystemExit(f"schema mismatch in {path}")
        if (plan.get("prefetch") or {}).get("byte_offsets") != byte_offsets:
            raise SystemExit(f"byte_offsets mismatch in {path}")
        stats = dict(plan.get("stats") or {})
        stats["plan"] = str(path)
        stats["branch_type_filter"] = (plan.get("options") or {}).get("branch_type_filter", [])
        source_stats.append(stats)
        for inj in plan.get("injections") or []:
            key = injection_key(inj)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            site = inj.get("site") or {}
            branch_counts[str(site.get("branch_type") or "UNKNOWN").upper()] += 1
            merged.append(inj)

    out = dict(first)
    out["injections"] = merged
    out["options"] = dict(first.get("options") or {})
    out["options"].update(
        {
            "label": args.label,
            "merge_label": args.label,
            "merge_source_plans": [str(p) for p in args.plan],
            "merge_strategy": "dedupe_by_site_target_symbol_offset",
            "branch_type_filter": sorted(branch_counts),
        }
    )
    out["stats"] = dict(first.get("stats") or {})
    target_cachelines = {
        (inj.get("target") or {}).get("cacheline64") for inj in merged
    }
    target_cachelines.discard(None)
    unique_sites = {
        (
            (inj.get("site") or {}).get("mangled")
            or (inj.get("site") or {}).get("function"),
            (inj.get("site") or {}).get("symbol_offset")
            or (inj.get("site") or {}).get("addr"),
        )
        for inj in merged
    }
    out["stats"].update(
        {
            "input_plans": len(plans),
            "source_plan_stats": source_stats,
            "source_duplicate_injections_removed": duplicates,
            "selected_injections": len(merged),
            "planned_prefetches": len(merged) * len(byte_offsets),
            "selected_targets": len({target_key(inj) for inj in merged}),
            "selected_target_cachelines": len(target_cachelines),
            "unique_sites": len(unique_sites),
            "branch_type_injections": dict(sorted(branch_counts.items())),
        }
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[ok] wrote {args.output}")
    print(f"[ok] injections={len(merged)} planned_prefetches={len(merged) * len(byte_offsets)} duplicates_removed={duplicates}")
    for branch, count in sorted(branch_counts.items()):
        print(f"[ok] branch {branch}: injections={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
