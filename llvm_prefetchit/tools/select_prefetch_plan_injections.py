#!/usr/bin/env python3
"""Select explicit injection records from a PrefetchIT JSON plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_indices(value: str) -> list[int]:
    indices: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        index = int(item)
        if index <= 0:
            raise argparse.ArgumentTypeError("indices are one-based and must be positive")
        indices.append(index)
    if not indices:
        raise argparse.ArgumentTypeError("at least one index is required")
    if len(indices) != len(set(indices)):
        raise argparse.ArgumentTypeError("indices must be unique")
    return indices


def target_key(injection: dict[str, Any]) -> tuple[Any, ...]:
    target = injection.get("target") or {}
    return (
        target.get("mangled") or target.get("function") or target.get("addr"),
        target.get("symbol_offset") or target.get("line") or target.get("addr"),
    )


def site_key(injection: dict[str, Any]) -> tuple[Any, ...]:
    site = injection.get("site") or {}
    return (
        site.get("mangled") or site.get("function") or site.get("addr"),
        site.get("symbol_offset") or site.get("line") or site.get("addr"),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--indices", type=parse_indices, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--byte-offsets",
        default=None,
        help="comma-separated target offsets; preserve the source plan when omitted",
    )
    args = parser.parse_args()

    plan = json.loads(args.input.read_text(encoding="utf-8"))
    injections = plan.get("injections") or []
    missing = [index for index in args.indices if index > len(injections)]
    if missing:
        raise SystemExit(
            f"indices exceed plan size {len(injections)}: "
            + ",".join(map(str, missing))
        )

    selected = [injections[index - 1] for index in args.indices]
    plan["injections"] = selected
    if args.byte_offsets is not None:
        offsets = [int(value.strip()) for value in args.byte_offsets.split(",")]
        plan.setdefault("prefetch", {})["byte_offsets"] = offsets
    else:
        offsets = (plan.get("prefetch") or {}).get("byte_offsets") or [0]

    options = plan.setdefault("options", {})
    options.update(
        {
            "label": args.label,
            "explicit_source_plan": str(args.input),
            "explicit_one_based_indices": args.indices,
            "prefetch_byte_offsets": offsets,
        }
    )
    stats = plan.setdefault("stats", {})
    stats.update(
        {
            "selected_injections": len(selected),
            "planned_prefetches": len(selected) * len(offsets),
            "selected_targets": len({target_key(injection) for injection in selected}),
            "unique_sites": len({site_key(injection) for injection in selected}),
        }
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"[ok] wrote {args.output}: injections={len(selected)} "
        f"prefetches={len(selected) * len(offsets)} indices={args.indices}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
