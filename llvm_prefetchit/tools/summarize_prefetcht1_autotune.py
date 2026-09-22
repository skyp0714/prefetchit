#!/usr/bin/env python3
"""Update the prefetcht1 autotune leaderboard after one variant run."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path


FIELDS = [
    "variant",
    "status",
    "run_dir",
    "top_k",
    "target_coverage_pct",
    "prefetch_byte_offsets",
    "operand_mode",
    "branch_depth_policy",
    "depth_min",
    "depth",
    "site_budget",
    "selection_mode",
    "sites_per_depth",
    "planned_injections",
    "pass_injected",
    "asm_prefetch",
    "elapsed_sec",
    "elapsed_delta_pct",
    "instructions",
    "instructions_delta_pct",
    "l2i_mpki",
    "l2i_mpki_delta_pct",
    "l2i_miss_count",
    "l2i_miss_count_delta_pct",
    "trace_samples",
    "trace_top_target",
    "trace_top_branch",
    "binary",
    "note",
]


def read_summary(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                out[row["metric"]] = float(row["mean"])
            except (KeyError, ValueError):
                continue
    return out


def read_plan(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def grep_int(text: str, pattern: str) -> int:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else 0


def grep_pair(text: str, pattern: str) -> str:
    m = re.search(pattern, text)
    if not m:
        return "N/A"
    return f"{m.group(1)} ({float(m.group(2)):.2f}%)"


def format_branch_policy(options: dict) -> str:
    policy = options.get("branch_depth_policy") or {}
    if not isinstance(policy, dict):
        return ""
    parts = []
    for key in sorted(policy):
        value = policy[key]
        if isinstance(value, list) and len(value) == 2:
            parts.append(f"{key}:{value[0]}-{value[1]}")
    return ",".join(parts)


def pct(new: float, old: float) -> float:
    if old == 0 or math.isnan(old):
        return float("nan")
    return (new - old) / old * 100.0


def fmt(value) -> str:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        return f"{value:.6f}"
    return str(value)


def load_existing(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: fmt(row.get(field, "")) for field in FIELDS})


def numeric(row: dict, key: str) -> float:
    try:
        return float(row.get(key, ""))
    except (TypeError, ValueError):
        return float("nan")


def write_leaderboard(path: Path, rows: list[dict], prefetch_label: str, rank_by: str) -> None:
    ok_rows = [r for r in rows if r.get("status") == "ok"]
    if rank_by == "runtime":
        ok_rows.sort(key=lambda r: (numeric(r, "elapsed_sec"), numeric(r, "l2i_mpki")))
    else:
        ok_rows.sort(key=lambda r: (numeric(r, "l2i_mpki"), numeric(r, "elapsed_sec")))

    md = [f"# {prefetch_label} Autotune Leaderboard", ""]
    if not ok_rows:
        md.append("No successful variants yet.")
    else:
        md.extend(
            [
                "| Rank | Variant | Target Cov % | Offsets | L2I MPKI | L2I Delta % | Runtime s | Runtime Delta % | Injected | Trace Samples |",
                "|---:|---|---:|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for rank, row in enumerate(ok_rows[:20], start=1):
            md.append(
                "| "
                f"{rank} | {row.get('variant','')} | "
                f"{numeric(row, 'target_coverage_pct'):.1f} | "
                f"{row.get('prefetch_byte_offsets','')} | "
                f"{numeric(row, 'l2i_mpki'):.6f} | "
                f"{numeric(row, 'l2i_mpki_delta_pct'):+.3f}% | "
                f"{numeric(row, 'elapsed_sec'):.3f} | "
                f"{numeric(row, 'elapsed_delta_pct'):+.3f}% | "
                f"{row.get('pass_injected','')} | {row.get('trace_samples','')} |"
            )
        best = ok_rows[0]
        md.extend(
            [
                "",
                "## Best",
                "",
                f"- Variant: `{best.get('variant','')}`",
                f"- Binary: `{best.get('binary','')}`",
                f"- Run dir: `{best.get('run_dir','')}`",
                f"- L2I MPKI delta: {numeric(best, 'l2i_mpki_delta_pct'):+.3f}%",
                f"- Runtime delta: {numeric(best, 'elapsed_delta_pct'):+.3f}%",
            ]
        )
    path.write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--autotune-dir", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--baseline-summary", required=True)
    ap.add_argument("--max-cycles", required=True)
    ap.add_argument("--status", choices=("ok", "fail"), required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--prefetch-label", default="prefetcht1")
    ap.add_argument("--rank-by", choices=("l2i", "runtime"), default="l2i")
    args = ap.parse_args()

    autotune_dir = Path(args.autotune_dir).resolve()
    run_dir = Path(args.run_dir).resolve()
    prefetch_label = args.prefetch_label
    baseline = read_summary(Path(args.baseline_summary).resolve())
    opt_summary = read_summary(
        run_dir / "detailed_profile" / f"{prefetch_label}_qsort_{args.max_cycles}" / "summary.csv"
    )
    plan_path = run_dir / "plan" / f"{prefetch_label}.plan.json"
    if not plan_path.exists():
        plan_candidates = sorted((run_dir / "plan").glob("*.plan.json"))
        plan_path = plan_candidates[0] if plan_candidates else plan_path
    plan = read_plan(plan_path)
    options = plan.get("options", {}) if isinstance(plan, dict) else {}
    stats = plan.get("stats", {}) if isinstance(plan, dict) else {}
    prefetch = plan.get("prefetch", {}) if isinstance(plan, dict) else {}

    asm_md = run_dir / "assembly_validation" / "prefetch_asm_validation.md"
    asm_text = asm_md.read_text(encoding="utf-8", errors="replace") if asm_md.exists() else ""
    trace_md = (
        run_dir
        / "trace_l2i_code_rd_miss_precise"
        / f"{prefetch_label}_qsort_{args.max_cycles}"
        / "l2_miss"
        / "trace_summary.md"
    )
    trace_text = trace_md.read_text(encoding="utf-8", errors="replace") if trace_md.exists() else ""

    elapsed = opt_summary.get("elapsed_sec", float("nan"))
    instructions = opt_summary.get("instructions", float("nan"))
    l2i = opt_summary.get("l2i_mpki", float("nan"))
    l2miss = l2i * instructions / 1000.0 if not math.isnan(l2i + instructions) else float("nan")
    base_elapsed = baseline.get("elapsed_sec", float("nan"))
    base_instr = baseline.get("instructions", float("nan"))
    base_l2i = baseline.get("l2i_mpki", float("nan"))
    base_l2miss = base_l2i * base_instr / 1000.0 if not math.isnan(base_l2i + base_instr) else float("nan")

    binary = run_dir / "bin" / f"simulator-chipyard.harness-DualMegaBoomAndSingleRocketConfig-llvm-{prefetch_label}"
    row = {
        "variant": args.variant,
        "status": args.status,
        "run_dir": str(run_dir),
        "top_k": options.get("top_k", ""),
        "target_coverage_pct": options.get("target_coverage_pct", ""),
        "prefetch_byte_offsets": ",".join(
            str(x) for x in options.get("prefetch_byte_offsets", [0])
        ),
        "operand_mode": prefetch.get("operand", ""),
        "branch_depth_policy": format_branch_policy(options),
        "depth_min": options.get("depth_min", ""),
        "depth": options.get("depth", ""),
        "site_budget": options.get("site_budget_per_target", ""),
        "selection_mode": options.get("selection_mode", ""),
        "sites_per_depth": options.get("sites_per_depth", ""),
        "planned_injections": stats.get("selected_injections", ""),
        "pass_injected": grep_int(asm_text, r"Pass injected count: ([0-9]+)"),
        "asm_prefetch": grep_int(asm_text, r"Assembly `[^`]+` count: ([0-9]+)"),
        "elapsed_sec": elapsed,
        "elapsed_delta_pct": pct(elapsed, base_elapsed),
        "instructions": instructions,
        "instructions_delta_pct": pct(instructions, base_instr),
        "l2i_mpki": l2i,
        "l2i_mpki_delta_pct": pct(l2i, base_l2i),
        "l2i_miss_count": l2miss,
        "l2i_miss_count_delta_pct": pct(l2miss, base_l2miss),
        "trace_samples": grep_int(trace_text, r"LBR samples parsed \(raw\):\s*([0-9]+)"),
        "trace_top_target": grep_pair(trace_text, r"Top miss target function: `([^`]+)` \(([0-9.]+)%\)"),
        "trace_top_branch": grep_pair(trace_text, r"Top branch type: `([^`]+)` \(([0-9.]+)%\)"),
        "binary": str(binary) if binary.exists() else "",
        "note": args.note,
    }

    aggregate = autotune_dir / "aggregate.csv"
    rows = [r for r in load_existing(aggregate) if r.get("variant") != args.variant]
    rows.append(row)
    write_csv(aggregate, rows)
    write_leaderboard(autotune_dir / "leaderboard.md", rows, prefetch_label, args.rank_by)

    ok_rows = [r for r in rows if r.get("status") == "ok"]
    if ok_rows:
        if args.rank_by == "runtime":
            ok_rows.sort(key=lambda r: (numeric(r, "elapsed_sec"), numeric(r, "l2i_mpki")))
        else:
            ok_rows.sort(key=lambda r: (numeric(r, "l2i_mpki"), numeric(r, "elapsed_sec")))
        best = ok_rows[0]
        (autotune_dir / "best_variant.txt").write_text(
            f"{best.get('variant','')}\n{best.get('run_dir','')}\n{best.get('binary','')}\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
