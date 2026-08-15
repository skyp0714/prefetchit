#!/usr/bin/env python3
"""Rerank static RET target CSVs using nested breadth-first ordering.

This is a fast iteration tool: it reuses the full feature CSV emitted by
static_return_target_candidates.py and changes only the priority order.
Candidate generation remains profile-free.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        return fields, list(reader)


def row_float(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def row_int(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, default)))
    except (TypeError, ValueError):
        return default


def is_helper_or_external(row: dict[str, str], helper_cacheline_max: int) -> bool:
    return row_int(row, "callee_known", 1) == 0 or row_float(row, "callee_cachelines", 0.0) <= helper_cacheline_max


def nested_local_score(row: dict[str, str], hot_score: float) -> float:
    base = row_float(row, "base_score", row_float(row, "score", 0.0))
    external_bonus = 100.0 if row_int(row, "callee_known", 1) == 0 else 0.0
    helper_bonus = 50.0 if row_float(row, "callee_cachelines", 0.0) <= 12 else 0.0
    distance_bonus = 2.0 * math.log2(max(0.0, row_float(row, "layout_distance_kb", 0.0)) + 1.0)
    return hot_score + external_bonus + helper_bonus + base + distance_bonus


def verilator_phase_score(name: str) -> int:
    if "eval_nba__0" in name:
        return 5
    if "nba_sequent__TOP__" in name:
        return 4
    if "eval_nba__9" in name:
        return 3
    if "eval_nba" in name:
        return 2
    if "eval(" in name or "eval_step" in name:
        return 1
    return 0


def is_external_call(row: dict[str, str]) -> bool:
    return row_int(row, "callee_known", 1) == 0 or "@plt" in row.get("callee_function", "")


def structural_tail_risk(row: dict[str, str], base_weight: float = 1.0) -> float:
    base = row_float(row, "base_score", row_float(row, "score", 0.0))
    external = 1 if is_external_call(row) else 0
    big_external = 1 if external and row_float(row, "caller_size_bytes", 0.0) >= 4096 else 0
    layout = math.log2(row_float(row, "layout_distance_kb", 0.0) + 1.0)
    return (
        base_weight * base
        + 75.0 * external
        + 25.0 * big_external
        + 20.0 * verilator_phase_score(row["target_function"])
        + 5.0 * layout
    )


def hybrid_tail_order(rows: list[dict[str, str]], prefix_count: int, tail_mode: str) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(row: dict[str, str]) -> None:
        key = (row["target_function"], row["target_cacheline64"])
        if key in seen:
            return
        seen.add(key)
        selected.append(row)

    for row in rows[:prefix_count]:
        add(row)

    tail = [row for row in rows if (row["target_function"], row["target_cacheline64"]) not in seen]
    if tail_mode == "risk":
        tail = sorted(tail, key=lambda row: structural_tail_risk(row, 1.0), reverse=True)
    elif tail_mode == "risk-ext-first":
        tail = sorted(tail, key=lambda row: (is_external_call(row), structural_tail_risk(row, 1.0)), reverse=True)
    elif tail_mode == "risk-low-base":
        tail = sorted(tail, key=lambda row: structural_tail_risk(row, 0.2), reverse=True)
    else:
        raise ValueError(f"unknown tail mode {tail_mode}")

    for row in tail:
        add(row)

    total = len(selected)
    out: list[dict[str, str]] = []
    for idx, row in enumerate(selected, 1):
        row = dict(row)
        row["rank"] = str(idx)
        row["score"] = str(float(total - idx))
        out.append(row)
    return out


def rerank(
    rows: list[dict[str, str]],
    base_count: int,
    per_callee: int,
    helper_only: bool,
    helper_cacheline_max: int,
    round_robin: bool,
) -> list[dict[str, str]]:
    base_order = sorted(rows, key=lambda r: row_float(r, "base_score", row_float(r, "score", 0.0)), reverse=True)
    by_target_func: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in base_order:
        by_target_func[row["target_function"]].append(row)

    selected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    hot_callees: dict[str, float] = {}

    def add(row: dict[str, str]) -> None:
        key = (row["target_function"], row["target_cacheline64"])
        if key in seen:
            return
        seen.add(key)
        selected.append(row)

    for row in base_order[:base_count]:
        add(row)
        callee = row["callee_function"]
        score = row_float(row, "base_score", row_float(row, "score", 0.0))
        hot_callees[callee] = max(hot_callees.get(callee, float("-inf")), score)

    nested_lists: list[list[dict[str, str]]] = []
    for callee, hot_score in sorted(hot_callees.items(), key=lambda item: item[1], reverse=True):
        nested = by_target_func.get(callee, [])
        if helper_only:
            nested = [row for row in nested if is_helper_or_external(row, helper_cacheline_max)]
        nested = sorted(nested, key=lambda row: nested_local_score(row, hot_score), reverse=True)
        nested_lists.append(nested[:per_callee])

    if round_robin:
        for depth in range(per_callee):
            for nested in nested_lists:
                if depth < len(nested):
                    add(nested[depth])
    else:
        for nested in nested_lists:
            for row in nested:
                add(row)

    for row in base_order:
        add(row)

    total = len(selected)
    out: list[dict[str, str]] = []
    for idx, row in enumerate(selected, 1):
        row = dict(row)
        row["rank"] = str(idx)
        row["score"] = str(float(total - idx))
        out.append(row)
    return out


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--base-count", type=int, default=1500)
    ap.add_argument("--per-callee", type=int, default=32)
    ap.add_argument("--include-all-calls", action="store_true")
    ap.add_argument("--helper-cacheline-max", type=int, default=12)
    ap.add_argument("--round-robin", action="store_true")
    ap.add_argument("--tail-risk-mode", choices=["none", "risk", "risk-ext-first", "risk-low-base"], default="none")
    ap.add_argument("--prefix-count", type=int, default=1500)
    args = ap.parse_args()

    fields, rows = read_rows(args.input)
    if args.tail_risk_mode != "none":
        ranked = hybrid_tail_order(rows, args.prefix_count, args.tail_risk_mode)
    else:
        ranked = rerank(
            rows,
            args.base_count,
            args.per_callee,
            not args.include_all_calls,
            args.helper_cacheline_max,
            args.round_robin,
        )
    write_rows(args.output, fields, ranked)
    print(f"[ok] wrote {args.output} rows={len(ranked)} base_count={args.base_count} per_callee={args.per_callee} round_robin={args.round_robin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
