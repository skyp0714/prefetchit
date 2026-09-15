#!/usr/bin/env python3
"""Plot prior prefetch-injection count vs frontend/runtime metrics."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--aggregate",
        action="append",
        default=[],
        help="Aggregate CSV to include. May be passed multiple times.",
    )
    ap.add_argument(
        "--results-root",
        default="llvm_prefetchit/results",
        help="Root used to discover aggregate.csv files when --aggregate is omitted.",
    )
    ap.add_argument("--baseline-summary", required=True)
    ap.add_argument("--max-cycles", default="538240")
    ap.add_argument("--out-dir", required=True)
    return ap.parse_args()


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


def as_float(value: str | None) -> float:
    try:
        return float(value or "nan")
    except ValueError:
        return float("nan")


def as_int(value: str | None) -> int:
    try:
        return int(float(value or "0"))
    except ValueError:
        return 0


def discover_aggregates(args: argparse.Namespace) -> list[Path]:
    if args.aggregate:
        return [Path(item) for item in args.aggregate]
    root = Path(args.results_root)
    return sorted(root.glob("**/aggregate.csv"))


def load_rows(args: argparse.Namespace) -> list[dict[str, str | float | int]]:
    rows: list[dict[str, str | float | int]] = []
    seen_run_dirs: set[str] = set()

    baseline = read_summary(Path(args.baseline_summary))
    if baseline:
        rows.append(
            {
                "source": "baseline",
                "variant": "baseline",
                "run_dir": "",
                "pass_injected": 0,
                "planned_injections": 0,
                "asm_prefetch": 0,
                "elapsed_sec": baseline.get("elapsed_sec", float("nan")),
                "instructions": baseline.get("instructions", float("nan")),
                "l1i_mpki": baseline.get("l1i_mpki", float("nan")),
                "l2i_mpki": baseline.get("l2i_mpki", float("nan")),
                "itlb_mpki": baseline.get("itlb_mpki", float("nan")),
                "stlb_mpki": baseline.get("stlb_mpki", float("nan")),
                "target_coverage_pct": 0.0,
                "selection_mode": "baseline",
                "prefetch_byte_offsets": "",
            }
        )

    for aggregate in discover_aggregates(args):
        if not aggregate.exists():
            continue
        with aggregate.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") != "ok":
                    continue
                run_dir = row.get("run_dir", "")
                if not run_dir or run_dir in seen_run_dirs:
                    continue
                seen_run_dirs.add(run_dir)
                summary = (
                    Path(run_dir)
                    / "detailed_profile"
                    / f"prefetcht1_qsort_{args.max_cycles}"
                    / "summary.csv"
                )
                metrics = read_summary(summary)
                if not metrics:
                    continue
                pass_injected = as_int(row.get("pass_injected"))
                if pass_injected <= 0:
                    continue
                rows.append(
                    {
                        "source": str(aggregate),
                        "variant": row.get("variant", ""),
                        "run_dir": run_dir,
                        "pass_injected": pass_injected,
                        "planned_injections": as_int(row.get("planned_injections")),
                        "asm_prefetch": as_int(row.get("asm_prefetch")),
                        "elapsed_sec": metrics.get("elapsed_sec", as_float(row.get("elapsed_sec"))),
                        "instructions": metrics.get("instructions", as_float(row.get("instructions"))),
                        "l1i_mpki": metrics.get("l1i_mpki", float("nan")),
                        "l2i_mpki": metrics.get("l2i_mpki", as_float(row.get("l2i_mpki"))),
                        "itlb_mpki": metrics.get("itlb_mpki", float("nan")),
                        "stlb_mpki": metrics.get("stlb_mpki", float("nan")),
                        "target_coverage_pct": as_float(row.get("target_coverage_pct")),
                        "selection_mode": row.get("selection_mode", ""),
                        "prefetch_byte_offsets": row.get("prefetch_byte_offsets", ""),
                    }
                )
    rows.sort(key=lambda r: (int(r["pass_injected"]), str(r["variant"])))
    return rows


def write_csv(path: Path, rows: list[dict[str, str | float | int]]) -> None:
    fields = [
        "source",
        "variant",
        "run_dir",
        "pass_injected",
        "planned_injections",
        "asm_prefetch",
        "elapsed_sec",
        "instructions",
        "l1i_mpki",
        "l2i_mpki",
        "itlb_mpki",
        "stlb_mpki",
        "target_coverage_pct",
        "selection_mode",
        "prefetch_byte_offsets",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def finite_xy(rows, ykey: str):
    xs: list[float] = []
    ys: list[float] = []
    labels: list[str] = []
    for row in rows:
        x = float(row["pass_injected"])
        try:
            y = float(row[ykey])
        except (TypeError, ValueError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            xs.append(x)
            ys.append(y)
            labels.append(str(row["variant"]))
    return xs, ys, labels


def plot(path: Path, rows: list[dict[str, str | float | int]]) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    plt.rcParams.update(
        {
            "font.size": 14,
            "axes.labelsize": 15,
            "xtick.labelsize": 12,
            "ytick.labelsize": 12,
            "legend.fontsize": 11,
        }
    )

    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    specs = [
        ("instructions", "Dynamic Instructions"),
        ("l1i_mpki", "L1I MPKI"),
        ("l2i_mpki", "L2I MPKI"),
        ("elapsed_sec", "Execution Time (s)"),
    ]
    best_runtime = min(
        (r for r in rows if int(r["pass_injected"]) > 0),
        key=lambda r: float(r["elapsed_sec"]),
        default=None,
    )
    for ax, (key, ylabel) in zip(axes.flat, specs):
        xs, ys, _ = finite_xy(rows, key)
        ax.scatter(xs, ys, s=42, alpha=0.78, edgecolor="black", linewidth=0.25)
        baseline = next((r for r in rows if r["variant"] == "baseline"), None)
        if baseline is not None and math.isfinite(float(baseline.get(key, float("nan")))):
            ax.axhline(float(baseline[key]), color="#666666", linestyle="--", linewidth=1.2)
        if best_runtime is not None and math.isfinite(float(best_runtime.get(key, float("nan")))):
            ax.scatter(
                [float(best_runtime["pass_injected"])],
                [float(best_runtime[key])],
                s=90,
                marker="*",
                color="#c83232",
                edgecolor="black",
                linewidth=0.4,
                zorder=5,
            )
        ax.set_xlabel("Injected Prefetch Count")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.25)
        def human_count(x, _):
            if abs(x) >= 1_000_000:
                return f"{x / 1_000_000:.1f}M"
            if abs(x) >= 1_000:
                return f"{x / 1_000:.0f}k"
            return f"{int(x)}"

        ax.xaxis.set_major_formatter(FuncFormatter(human_count))
    fig.suptitle("Prefetch Injection Effects", fontsize=18)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_report(path: Path, rows: list[dict[str, str | float | int]]) -> None:
    opt_rows = [r for r in rows if int(r["pass_injected"]) > 0]
    opt_rows.sort(key=lambda r: float(r["elapsed_sec"]))
    lines = ["# Prefetch Injection Effects", ""]
    lines.append(f"- Rows plotted: {len(rows)}")
    lines.append(f"- Optimized variants: {len(opt_rows)}")
    if opt_rows:
        best = opt_rows[0]
        lines.extend(
            [
                "",
                "## Best Runtime Row",
                "",
                f"- Variant: `{best['variant']}`",
                f"- Injected prefetch count: {int(best['pass_injected']):,}",
                f"- Runtime: {float(best['elapsed_sec']):.6f}s",
                f"- L1I MPKI: {float(best['l1i_mpki']):.6f}",
                f"- L2I MPKI: {float(best['l2i_mpki']):.6f}",
                f"- Instructions: {float(best['instructions']):.0f}",
                f"- Run dir: `{best['run_dir']}`",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = load_rows(args)
    write_csv(out_dir / "injection_effects.csv", rows)
    plot(out_dir / "injection_effects.png", rows)
    write_report(out_dir / "injection_effects.md", rows)


if __name__ == "__main__":
    main()
