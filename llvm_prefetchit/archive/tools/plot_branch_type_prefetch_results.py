#!/usr/bin/env python3
"""Plot baseline, branch-type-specific, and general prefetch results."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any


def finite_positive(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x <= 0:
        return None
    return x


def read_metric_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def stats(values: list[float]) -> tuple[int, float, float, float]:
    if not values:
        return 0, float("nan"), float("nan"), float("nan")
    mean = statistics.fmean(values)
    if len(values) > 1:
        std = statistics.stdev(values)
        sem = std / math.sqrt(len(values))
    else:
        std = 0.0
        sem = 0.0
    return len(values), mean, std, sem


def summarize_profile(label: str, category: str, branch_type: str, per_iter: Path, run_dir: Path | None) -> dict[str, Any]:
    rows = read_metric_rows(per_iter)
    runtimes = [x for r in rows if (x := finite_positive(r.get("elapsed_sec"))) is not None]
    l2s = [x for r in rows if (x := finite_positive(r.get("l2i_mpki"))) is not None]
    l1s = [x for r in rows if (x := finite_positive(r.get("l1i_mpki"))) is not None]
    insts = [x for r in rows if (x := finite_positive(r.get("instructions"))) is not None]

    rn, rmean, rstd, rsem = stats(runtimes)
    ln, lmean, lstd, lsem = stats(l2s)
    _, l1mean, l1std, l1sem = stats(l1s)
    _, imean, istd, isem = stats(insts)

    plan_path = ""
    injections = ""
    planned_prefetches = ""
    asm_count = ""
    asm_ok = ""
    binary = ""
    if run_dir:
        plan_candidates = sorted((run_dir / "plan").glob("*.plan.json")) if (run_dir / "plan").exists() else []
        if plan_candidates:
            plan_path = str(plan_candidates[0])
            try:
                plan = json.loads(plan_candidates[0].read_text(encoding="utf-8"))
                st = plan.get("stats") or {}
                injections = st.get("selected_injections", "")
                planned_prefetches = st.get("planned_prefetches", "")
            except Exception:
                pass
        asm_csv = run_dir / "assembly_validation" / "prefetch_asm_validation.csv"
        if asm_csv.exists():
            with asm_csv.open(newline="", encoding="utf-8") as f:
                asm_rows = list(csv.DictReader(f))
            asm_count = len(asm_rows)
            asm_ok = sum(1 for r in asm_rows if (r.get("parse_status") or "") == "ok")
        bins = sorted((run_dir / "bin").glob("simulator-chipyard*")) if (run_dir / "bin").exists() else []
        if bins:
            binary = str(bins[0])

    valid = rn > 0 and ln > 0 and math.isfinite(rmean) and math.isfinite(lmean)
    return {
        "label": label,
        "category": category,
        "branch_type": branch_type,
        "valid": "1" if valid else "0",
        "iterations": rn,
        "runtime_mean_sec": rmean,
        "runtime_std_sec": rstd,
        "runtime_sem_sec": rsem,
        "l2i_mpki_mean": lmean,
        "l2i_mpki_std": lstd,
        "l2i_mpki_sem": lsem,
        "l1i_mpki_mean": l1mean,
        "l1i_mpki_std": l1std,
        "l1i_mpki_sem": l1sem,
        "instructions_mean": imean,
        "instructions_std": istd,
        "instructions_sem": isem,
        "planned_injections": injections,
        "planned_prefetches": planned_prefetches,
        "asm_prefetch_count": asm_count,
        "asm_ok_count": asm_ok,
        "per_iteration_csv": str(per_iter),
        "plan_path": plan_path,
        "binary": binary,
        "run_dir": str(run_dir) if run_dir else "",
    }


def read_metadata(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "label",
        "category",
        "branch_type",
        "valid",
        "iterations",
        "runtime_mean_sec",
        "runtime_std_sec",
        "runtime_sem_sec",
        "l2i_mpki_mean",
        "l2i_mpki_std",
        "l2i_mpki_sem",
        "l1i_mpki_mean",
        "l1i_mpki_std",
        "l1i_mpki_sem",
        "instructions_mean",
        "instructions_std",
        "instructions_sem",
        "planned_injections",
        "planned_prefetches",
        "asm_prefetch_count",
        "asm_ok_count",
        "per_iteration_csv",
        "plan_path",
        "binary",
        "run_dir",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            out = {}
            for k in fields:
                value = row.get(k, "")
                if isinstance(value, float) and not math.isfinite(value):
                    value = ""
                out[k] = value
            writer.writerow(out)


def write_md(path: Path, rows: list[dict[str, Any]], title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {title}",
        "",
        "| Scheme | Branch Type | Iterations | Runtime Mean (s) | Runtime Std (s) | L2 MPKI Mean | L2 MPKI Std | Planned Injections | ASM Prefetches |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        if row.get("valid") != "1":
            continue
        lines.append(
            "| {label} | {branch_type} | {iterations} | {runtime:.6f} | {runtime_std:.6f} | {l2:.6f} | {l2_std:.6f} | {inj} | {asm} |".format(
                label=row["label"],
                branch_type=row.get("branch_type") or "all",
                iterations=row["iterations"],
                runtime=float(row["runtime_mean_sec"]),
                runtime_std=float(row["runtime_std_sec"]),
                l2=float(row["l2i_mpki_mean"]),
                l2_std=float(row["l2i_mpki_std"]),
                inj=row.get("planned_injections", ""),
                asm=row.get("asm_prefetch_count", ""),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot(path: Path, rows: list[dict[str, Any]], title: str, xlabel: str) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    rows = [r for r in rows if r.get("valid") == "1"]
    labels = [r["label"] for r in rows]
    x = np.arange(len(labels))
    runtime = np.array([float(r["runtime_mean_sec"]) for r in rows])
    runtime_err = np.array([float(r["runtime_std_sec"]) for r in rows])
    l2 = np.array([float(r["l2i_mpki_mean"]) for r in rows])
    l2_err = np.array([float(r["l2i_mpki_std"]) for r in rows])

    fig, ax1 = plt.subplots(figsize=(15, 7))
    bar_color = "#4C78A8"
    line_color = "#D62728"
    ax1.bar(x, runtime, yerr=runtime_err, color=bar_color, alpha=0.82, capsize=5, label="Execution Time")
    ax1.set_ylabel("Execution Time (s)", fontsize=18)
    ax1.set_ylim(bottom=0)
    ax1.tick_params(axis="y", labelsize=15)
    ax1.grid(axis="y", linestyle="--", alpha=0.25)

    ax2 = ax1.twinx()
    ax2.errorbar(x, l2, yerr=l2_err, color=line_color, marker="o", linewidth=2.6, markersize=7, capsize=4, label="L2 MPKI")
    ax2.set_ylabel("L2 MPKI", fontsize=18)
    ax2.tick_params(axis="y", labelsize=15)

    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=25, ha="right", fontsize=15)
    ax1.set_xlabel(xlabel, fontsize=18)
    ax1.set_title(title, fontsize=20, pad=14)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=14, frameon=False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    fig.savefig(path.with_suffix(".pdf"))
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metadata", type=Path, required=True)
    ap.add_argument("--baseline-per-iteration", type=Path, required=True)
    ap.add_argument("--general-per-iteration", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--profile-name", default="prefetcht1_qsort_538240")
    ap.add_argument("--title", default="Prefetcht1 Branch-Type Injection")
    ap.add_argument("--xlabel", default="Injection Scheme")
    args = ap.parse_args()

    rows: list[dict[str, Any]] = []
    rows.append(summarize_profile("Baseline", "baseline", "", args.baseline_per_iteration, None))

    branch_rows = []
    for meta in read_metadata(args.metadata):
        status = (meta.get("profile_status") or meta.get("build_status") or "").lower()
        run_dir = Path(meta["run_dir"])
        per_iter = run_dir / "detailed_profile" / args.profile_name / "per_iteration.csv"
        row = summarize_profile(meta.get("plot_label") or meta.get("branch_type") or meta["variant"], "branch", meta.get("branch_type", ""), per_iter, run_dir)
        if status and status != "ok":
            row["valid"] = "0"
        branch_rows.append(row)

    preferred = ["COND", "RET", "UNCOND", "CALL", "IND_CALL", "IND"]
    order = {k: i for i, k in enumerate(preferred)}
    branch_rows.sort(key=lambda r: (order.get((r.get("branch_type") or "").upper(), 999), r["label"]))
    rows.extend(branch_rows)
    rows.append(summarize_profile("General", "general", "all", args.general_per_iteration, None))

    valid_rows = [row for row in rows if row.get("valid") == "1"]
    write_csv(args.out_dir / "branch_type_prefetch_status.csv", rows)
    write_csv(args.out_dir / "branch_type_prefetch_summary.csv", valid_rows)
    write_md(args.out_dir / "branch_type_prefetch_summary.md", valid_rows, args.title)
    plot(args.out_dir / "branch_type_prefetch_runtime_l2mpki.png", valid_rows, args.title, args.xlabel)
    print(args.out_dir / "branch_type_prefetch_summary.csv")
    print(args.out_dir / "branch_type_prefetch_runtime_l2mpki.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
