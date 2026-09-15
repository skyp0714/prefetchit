#!/usr/bin/env python3
"""Summarize RET-only PGO-limit and static return-prefetch experiments."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

METRICS = ("elapsed_sec", "instructions", "l1i_mpki", "l2i_mpki", "itlb_mpki", "stlb_mpki")


def finite_float(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def read_per_iter(path: Path) -> list[dict[str, float]]:
    if not path.exists():
        return []
    out: list[dict[str, float]] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            parsed: dict[str, float] = {}
            ok = True
            for key in METRICS:
                val = finite_float(row.get(key))
                if val is None:
                    ok = False
                    break
                parsed[key] = val
            if ok:
                out.append(parsed)
    return out


def mean(rows: list[dict[str, float]], key: str) -> float:
    vals = [r[key] for r in rows if math.isfinite(r.get(key, float("nan")))]
    return statistics.fmean(vals) if vals else float("nan")


def stdev(rows: list[dict[str, float]], key: str) -> float:
    vals = [r[key] for r in rows if math.isfinite(r.get(key, float("nan")))]
    return statistics.stdev(vals) if len(vals) > 1 else 0.0


def fmt(value: Any, digits: int = 6) -> str:
    val = finite_float(value)
    return "" if val is None else f"{val:.{digits}f}"


def read_metadata(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def plan_stats(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return plan.get("stats") or {}


def asm_count(run_dir: Path) -> int | str:
    asm_csv = run_dir / "assembly_validation" / "prefetch_asm_validation.csv"
    if not asm_csv.exists():
        return ""
    with asm_csv.open(newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def row_from_profile(label: str, category: str, per_iter: Path, baseline_elapsed: float, baseline_l2: float, baseline_inst: float, meta: dict[str, str] | None = None) -> dict[str, Any]:
    meta = meta or {}
    rows = read_per_iter(per_iter)
    elapsed = mean(rows, "elapsed_sec")
    l2 = mean(rows, "l2i_mpki")
    inst = mean(rows, "instructions")
    run_dir = Path(meta.get("run_dir", "")) if meta.get("run_dir") else None
    plan_path = Path(meta.get("plan_path", "")) if meta.get("plan_path") else None
    st = plan_stats(plan_path) if plan_path else {}
    valid = bool(rows) and math.isfinite(elapsed) and math.isfinite(l2)
    return {
        "label": label,
        "category": category,
        "valid": 1 if valid else 0,
        "iterations": len(rows),
        "elapsed_sec_mean": elapsed,
        "elapsed_sec_stdev": stdev(rows, "elapsed_sec") if rows else float("nan"),
        "speedup_vs_baseline_pct": (baseline_elapsed / elapsed - 1.0) * 100.0 if valid and baseline_elapsed > 0 else float("nan"),
        "l2i_mpki_mean": l2,
        "l2i_mpki_stdev": stdev(rows, "l2i_mpki") if rows else float("nan"),
        "l2i_mpki_delta_vs_baseline_pct": (l2 / baseline_l2 - 1.0) * 100.0 if valid and baseline_l2 > 0 else float("nan"),
        "l1i_mpki_mean": mean(rows, "l1i_mpki") if rows else float("nan"),
        "instructions_mean": inst,
        "instructions_delta_vs_baseline_pct": (inst / baseline_inst - 1.0) * 100.0 if valid and baseline_inst > 0 else float("nan"),
        "planned_injections": st.get("selected_injections", ""),
        "planned_prefetches": st.get("planned_prefetches", ""),
        "selected_targets": st.get("selected_targets", ""),
        "asm_prefetches": asm_count(run_dir) if run_dir else "",
        "pgo_ret_coverage_pct": meta.get("pgo_ret_coverage_pct", ""),
        "static_top_k": meta.get("static_top_k", ""),
        "site_strategy": meta.get("site_strategy", ""),
        "site_budget": meta.get("site_budget", ""),
        "target_weighted_recall": meta.get("target_weighted_recall", ""),
        "site_weighted_coverage": meta.get("site_weighted_coverage", ""),
        "run_dir": str(run_dir) if run_dir else "",
        "plan_path": str(plan_path) if plan_path else "",
        "per_iteration_csv": str(per_iter),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "label", "category", "valid", "iterations", "elapsed_sec_mean", "elapsed_sec_stdev",
        "speedup_vs_baseline_pct", "l2i_mpki_mean", "l2i_mpki_stdev", "l2i_mpki_delta_vs_baseline_pct",
        "l1i_mpki_mean", "instructions_mean", "instructions_delta_vs_baseline_pct",
        "planned_injections", "planned_prefetches", "selected_targets", "asm_prefetches",
        "pgo_ret_coverage_pct", "static_top_k", "site_strategy", "site_budget",
        "target_weighted_recall", "site_weighted_coverage", "run_dir", "plan_path", "per_iteration_csv",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            clean = {}
            for key in fields:
                value = row.get(key, "")
                if isinstance(value, float) and not math.isfinite(value):
                    value = ""
                clean[key] = value
            w.writerow(clean)


def write_md(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# RET Static vs PGO-Limit Prefetch Compare",
        "",
        "| Scheme | N | Runtime (s) | Runtime stdev | Speedup vs baseline | L2I MPKI | L2I delta | Injections | Prefetches | Target recall | Site coverage |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        if row.get("valid") != 1:
            continue
        lines.append(
            f"| {row['label']} | {row['iterations']} | {fmt(row['elapsed_sec_mean'])} | {fmt(row['elapsed_sec_stdev'])} | "
            f"{fmt(row['speedup_vs_baseline_pct'], 3)}% | {fmt(row['l2i_mpki_mean'])} | {fmt(row['l2i_mpki_delta_vs_baseline_pct'], 3)}% | "
            f"{row.get('planned_injections', '')} | {row.get('planned_prefetches', '')} | "
            f"{fmt(float(row['target_weighted_recall']) * 100.0, 2) + '%' if row.get('target_weighted_recall') else ''} | "
            f"{fmt(float(row['site_weighted_coverage']) * 100.0, 2) + '%' if row.get('site_weighted_coverage') else ''} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot(path: Path, rows: list[dict[str, Any]]) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    valid = [r for r in rows if r.get("valid") == 1]
    labels = [str(r["label"]).replace("pgo_ret_", "PGO ").replace("static_", "Static ") for r in valid]
    x = np.arange(len(valid))
    runtime = np.array([float(r["elapsed_sec_mean"]) for r in valid])
    runtime_err = np.array([float(r["elapsed_sec_stdev"]) for r in valid])
    l2 = np.array([float(r["l2i_mpki_mean"]) for r in valid])
    l2_err = np.array([float(r["l2i_mpki_stdev"]) for r in valid])
    colors = ["#666666" if r["category"] == "baseline" else "#4C78A8" if r["category"] == "pgo_ret" else "#F58518" for r in valid]

    fig, ax1 = plt.subplots(figsize=(max(14, len(valid) * 0.9), 7.5))
    ax1.bar(x, runtime, yerr=runtime_err, capsize=4, color=colors, alpha=0.85, label="Execution Time")
    ax1.set_ylabel("Execution Time (s)", fontsize=18)
    ax1.tick_params(axis="y", labelsize=15)
    ax1.grid(axis="y", linestyle="--", alpha=0.25)

    ax2 = ax1.twinx()
    ax2.errorbar(x, l2, yerr=l2_err, marker="o", color="#D62728", linewidth=2.5, capsize=4, label="L2 MPKI")
    ax2.set_ylabel("L2 MPKI", fontsize=18)
    ax2.tick_params(axis="y", labelsize=15)

    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=30, ha="right", fontsize=13)
    ax1.set_title("RET Static vs PGO-Limit Prefetch", fontsize=20, pad=14)
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper right", fontsize=13, frameon=False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    fig.savefig(path.with_suffix(".pdf"))
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metadata", type=Path, required=True)
    ap.add_argument("--baseline-per-iteration", type=Path, required=True)
    ap.add_argument("--profile-name", default="prefetcht1_qsort_538240")
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    baseline_rows = read_per_iter(args.baseline_per_iteration)
    if not baseline_rows:
        raise SystemExit(f"missing/empty baseline per-iteration CSV: {args.baseline_per_iteration}")
    base_elapsed = mean(baseline_rows, "elapsed_sec")
    base_l2 = mean(baseline_rows, "l2i_mpki")
    base_inst = mean(baseline_rows, "instructions")

    rows = [row_from_profile("baseline", "baseline", args.baseline_per_iteration, base_elapsed, base_l2, base_inst)]
    for meta in read_metadata(args.metadata):
        status = (meta.get("profile_status") or meta.get("build_status") or "").lower()
        run_dir = Path(meta["run_dir"])
        per_iter = run_dir / "detailed_profile" / args.profile_name / "per_iteration.csv"
        row = row_from_profile(meta["label"], meta.get("category", ""), per_iter, base_elapsed, base_l2, base_inst, meta)
        if status and status != "ok":
            row["valid"] = 0
        rows.append(row)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "ret_static_vs_pgo_summary.csv", rows)
    write_md(args.out_dir / "ret_static_vs_pgo_summary.md", rows)
    plot(args.out_dir / "ret_static_vs_pgo_runtime_l2mpki.png", rows)
    print(args.out_dir / "ret_static_vs_pgo_summary.csv")
    print(args.out_dir / "ret_static_vs_pgo_runtime_l2mpki.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
