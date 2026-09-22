#!/usr/bin/env python3
"""Plot injected prefetch count versus runtime/frontend metrics by prefetch kind."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any


METRIC_KEYS = [
    ("instructions", "Dynamic Instructions"),
    ("l1i_mpki", "L1I MPKI"),
    ("l2i_mpki", "L2I MPKI"),
    ("elapsed_sec", "Execution Time (s)"),
]

KIND_LABELS = {
    "prefetcht1": "prefetcht1",
    "prefetchit1": "prefetchit1",
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results-root", default="llvm_prefetchit/results")
    ap.add_argument("--baseline-summary", required=True)
    ap.add_argument("--max-cycles", default="538240")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument(
        "--aggregate",
        action="append",
        default=[],
        help="Aggregate CSV to include. If omitted, discover aggregate.csv under --results-root.",
    )
    ap.add_argument(
        "--x-scale",
        choices=("linear", "symlog"),
        default="symlog",
        help="Injected prefetch count axis scale. symlog keeps low-count prefetchit points visible next to large prefetcht sweeps.",
    )
    ap.add_argument(
        "--x-linthresh",
        type=float,
        default=1000.0,
        help="Linear threshold for --x-scale symlog.",
    )
    ap.add_argument(
        "--errorbar",
        choices=("none", "std", "sem"),
        default="std",
        help="Vertical errorbar statistic for points with multiple iterations.",
    )
    return ap.parse_args()


def as_float(value: Any, default: float = float("nan")) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def read_summary(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            metric = row.get("metric")
            if not metric:
                continue
            value = as_float(row.get("mean"))
            if math.isfinite(value):
                out[metric] = value
                out[f"{metric}_min"] = as_float(row.get("min"))
                out[f"{metric}_max"] = as_float(row.get("max"))
    per_iteration = path.with_name("per_iteration.csv")
    if per_iteration.exists():
        with per_iteration.open(newline="", encoding="utf-8") as f:
            per_rows = list(csv.DictReader(f))
        for metric, _label in METRIC_KEYS:
            values = [
                as_float(row.get(metric))
                for row in per_rows
                if math.isfinite(as_float(row.get(metric)))
            ]
            if not values:
                continue
            n = len(values)
            mean = statistics.mean(values)
            std = statistics.stdev(values) if n > 1 else 0.0
            out[metric] = mean
            out[f"{metric}_min"] = min(values)
            out[f"{metric}_max"] = max(values)
            out[f"{metric}_std"] = std
            out[f"{metric}_sem"] = std / math.sqrt(n) if n > 1 else 0.0
            out[f"{metric}_n"] = float(n)
    return out


def metric_stat_fields(metrics: dict[str, float]) -> dict[str, float]:
    fields: dict[str, float] = {}
    for metric, _label in METRIC_KEYS:
        for suffix in ("std", "sem", "n"):
            key = f"{metric}_{suffix}"
            if key in metrics:
                fields[key] = metrics[key]
    return fields


def read_compare_summary(path: Path, label: str) -> dict[str, float]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("label") == label:
                return {
                    "elapsed_sec": as_float(row.get("elapsed_sec_mean")),
                    "l2i_mpki": as_float(row.get("l2i_mpki_mean")),
                }
    return {}


def parse_validation_counts(path: Path, kind: str) -> tuple[int, int]:
    pass_injected = 0
    asm_prefetch = 0
    if not path.exists():
        return pass_injected, asm_prefetch
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"Pass injected count:\s*([0-9,]+)", text)
    if m:
        pass_injected = int(m.group(1).replace(",", ""))
    m = re.search(rf"Assembly `{re.escape(kind)}` count:\s*([0-9,]+)", text)
    if m:
        asm_prefetch = int(m.group(1).replace(",", ""))
    return pass_injected, asm_prefetch


def discover_aggregates(args: argparse.Namespace) -> list[Path]:
    if args.aggregate:
        return [Path(x) for x in args.aggregate]
    return sorted(Path(args.results_root).glob("**/aggregate.csv"))


def add_baseline(rows: list[dict[str, Any]], baseline_summary: Path) -> None:
    metrics = read_summary(baseline_summary)
    if not metrics:
        return
    rows.append(
        {
            "kind": "baseline",
            "source": str(baseline_summary),
            "variant": "baseline",
            "run_dir": "",
            "pass_injected": 0,
            "planned_injections": 0,
            "asm_prefetch": 0,
            "elapsed_sec": metrics.get("elapsed_sec", float("nan")),
            "instructions": metrics.get("instructions", float("nan")),
            "l1i_mpki": metrics.get("l1i_mpki", float("nan")),
            "l2i_mpki": metrics.get("l2i_mpki", float("nan")),
            "target_coverage_pct": 0.0,
            "selection_mode": "baseline",
            "depth_min": "",
            "depth": "",
            "site_budget": "",
            "prefetch_byte_offsets": "",
            "note": "baseline",
            **metric_stat_fields(metrics),
        }
    )


def load_prefetcht1_rows(args: argparse.Namespace, rows: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for aggregate in discover_aggregates(args):
        if not aggregate.exists():
            continue
        with aggregate.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") != "ok":
                    continue
                run_dir = row.get("run_dir", "")
                if not run_dir or run_dir in seen:
                    continue
                seen.add(run_dir)
                summary = Path(run_dir) / "detailed_profile" / f"prefetcht1_qsort_{args.max_cycles}" / "summary.csv"
                metrics = read_summary(summary)
                if not metrics:
                    continue
                pass_injected = as_int(row.get("pass_injected"))
                if pass_injected <= 0:
                    continue
                rows.append(
                    {
                        "kind": "prefetcht1",
                        "source": str(aggregate),
                        "variant": row.get("variant", Path(run_dir).name),
                        "run_dir": run_dir,
                        "pass_injected": pass_injected,
                        "planned_injections": as_int(row.get("planned_injections")),
                        "asm_prefetch": as_int(row.get("asm_prefetch")),
                        "elapsed_sec": metrics.get("elapsed_sec", as_float(row.get("elapsed_sec"))),
                        "instructions": metrics.get("instructions", as_float(row.get("instructions"))),
                        "l1i_mpki": metrics.get("l1i_mpki", float("nan")),
                        "l2i_mpki": metrics.get("l2i_mpki", as_float(row.get("l2i_mpki"))),
                        "target_coverage_pct": as_float(row.get("target_coverage_pct")),
                        "selection_mode": row.get("selection_mode", ""),
                        "depth_min": row.get("depth_min", ""),
                        "depth": row.get("depth", ""),
                        "site_budget": row.get("site_budget", ""),
                        "prefetch_byte_offsets": row.get("prefetch_byte_offsets", ""),
                        "note": row.get("note", ""),
                        **metric_stat_fields(metrics),
                    }
                )


def extract_prefetcht1_run_dir_from_report(compare_dir: Path) -> tuple[str, Path | None]:
    for report in [compare_dir.parent / "exact_prefetch_compare_report.md", compare_dir.parent / "compare.log"]:
        if not report.exists():
            continue
        text = report.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"Prefetcht1 binary:\s*`([^`]+)`", text)
        if not m:
            m = re.search(r"best exact prefetcht1: ([^ ]+) .*? bin=([^\s]+)", text)
        if not m:
            continue
        if len(m.groups()) == 2:
            variant = m.group(1)
            binary = Path(m.group(2))
        else:
            binary = Path(m.group(1))
            variant = ""
        run_dir = binary.parent.parent if binary.parent.name == "bin" else None
        if run_dir is not None:
            if not variant:
                variant = run_dir.name
            return variant, run_dir
    return "", None


def load_final_compare_prefetcht1_rows(args: argparse.Namespace, rows: list[dict[str, Any]]) -> None:
    for profile_summary in sorted(
        Path(args.results_root).glob(f"**/final_compare/profiles/prefetcht1_qsort_{args.max_cycles}/summary.csv")
    ):
        metrics = read_summary(profile_summary)
        if not metrics:
            continue
        compare_dir = profile_summary.parents[2]
        variant, run_dir = extract_prefetcht1_run_dir_from_report(compare_dir)
        if run_dir is None:
            continue
        validation = run_dir / "assembly_validation" / "prefetch_asm_validation.md"
        pass_injected, asm_prefetch = parse_validation_counts(validation, "prefetcht1")
        plan_candidates = sorted((run_dir / "plan").glob("*.plan.json"))
        plan = {}
        if plan_candidates:
            try:
                plan = json.loads(plan_candidates[0].read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                plan = {}
        stats = plan.get("stats", {}) if isinstance(plan, dict) else {}
        opts = plan.get("options", {}) if isinstance(plan, dict) else {}
        pass_injected = pass_injected or as_int(stats.get("pass_injected")) or as_int(stats.get("selected_injections"))
        if pass_injected <= 0:
            continue
        run_dir_s = str(run_dir)
        # Replace the single-iteration sweep row for this exact binary with
        # the final compare row, which has the repeated samples needed for
        # visible error bars.
        rows[:] = [
            row
            for row in rows
            if not (row.get("kind") == "prefetcht1" and row.get("run_dir") == run_dir_s)
        ]
        rows.append(
            {
                "kind": "prefetcht1",
                "source": str(profile_summary),
                "variant": f"{variant}_final_n{as_int(metrics.get('elapsed_sec_n'))}",
                "run_dir": run_dir_s,
                "pass_injected": pass_injected,
                "planned_injections": as_int(stats.get("selected_injections")),
                "asm_prefetch": asm_prefetch,
                "elapsed_sec": metrics.get("elapsed_sec", float("nan")),
                "instructions": metrics.get("instructions", float("nan")),
                "l1i_mpki": metrics.get("l1i_mpki", float("nan")),
                "l2i_mpki": metrics.get("l2i_mpki", float("nan")),
                "target_coverage_pct": as_float(opts.get("target_coverage_pct")),
                "selection_mode": opts.get("selection_mode", ""),
                "depth_min": opts.get("depth_min", ""),
                "depth": opts.get("depth", ""),
                "site_budget": opts.get("site_budget", ""),
                "prefetch_byte_offsets": ",".join(str(x) for x in opts.get("prefetch_byte_offsets", [])),
                "note": "final compare repeated prefetcht1 profile",
                **metric_stat_fields(metrics),
            }
        )


def find_prefetchit_summary(plan_path: Path, args: argparse.Namespace) -> dict[str, float]:
    run_dir = plan_path.parents[1]
    direct = run_dir / "detailed_profile" / f"prefetchit1_qsort_{args.max_cycles}" / "summary.csv"
    metrics = read_summary(direct)
    if metrics:
        return metrics

    # Exact compare runs keep the measured profiles next to, not inside, the build dir.
    for parent in [run_dir, *run_dir.parents]:
        profile = parent / "final_compare" / "profiles" / f"prefetchit1_qsort_{args.max_cycles}" / "summary.csv"
        metrics = read_summary(profile)
        if metrics:
            return metrics
        compare = parent / "final_compare" / "prefetch_compare_summary.csv"
        metrics = read_compare_summary(compare, "prefetchit1")
        if metrics:
            return metrics
    return {}


def load_prefetchit1_rows(args: argparse.Namespace, rows: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for plan_path in sorted(Path(args.results_root).glob("**/prefetchit1.plan.json")):
        run_dir = plan_path.parents[1]
        key = str(run_dir.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        metrics = find_prefetchit_summary(plan_path, args)
        if not metrics:
            continue
        validation = run_dir / "assembly_validation" / "prefetch_asm_validation.md"
        pass_injected, asm_prefetch = parse_validation_counts(validation, "prefetchit1")
        stats = plan.get("stats", {}) if isinstance(plan, dict) else {}
        opts = plan.get("options", {}) if isinstance(plan, dict) else {}
        pass_injected = pass_injected or as_int(stats.get("pass_injected")) or as_int(stats.get("selected_injections"))
        rows.append(
            {
                "kind": "prefetchit1",
                "source": str(plan_path),
                "variant": run_dir.name,
                "run_dir": str(run_dir),
                "pass_injected": pass_injected,
                "planned_injections": as_int(stats.get("selected_injections")),
                "asm_prefetch": asm_prefetch,
                "elapsed_sec": metrics.get("elapsed_sec", float("nan")),
                "instructions": metrics.get("instructions", float("nan")),
                "l1i_mpki": metrics.get("l1i_mpki", float("nan")),
                "l2i_mpki": metrics.get("l2i_mpki", float("nan")),
                "target_coverage_pct": as_float(opts.get("target_coverage_pct")),
                "selection_mode": opts.get("selection_mode", ""),
                "depth_min": opts.get("depth_min", ""),
                "depth": opts.get("depth", ""),
                "site_budget": opts.get("site_budget", ""),
                "prefetch_byte_offsets": ",".join(str(x) for x in opts.get("prefetch_byte_offsets", [])),
                "note": "prefetchit same-position result",
                **metric_stat_fields(metrics),
            }
        )


def finite_rows(rows: list[dict[str, Any]], kind: str, key: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        if row.get("kind") != kind:
            continue
        x = as_float(row.get("pass_injected"))
        y = as_float(row.get(key))
        if math.isfinite(x) and math.isfinite(y):
            out.append(row)
    out.sort(key=lambda r: (as_int(r.get("pass_injected")), str(r.get("variant", ""))))
    return out


def human_count(x: float, _pos: int) -> str:
    if abs(x) >= 1_000_000:
        return f"{x / 1_000_000:.1f}M"
    if abs(x) >= 1_000:
        return f"{x / 1_000:.0f}k"
    return str(int(x))


def plot(path: Path, rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    plt.rcParams.update(
        {
            "font.size": 15,
            "axes.labelsize": 16,
            "xtick.labelsize": 13,
            "ytick.labelsize": 13,
            "legend.fontsize": 12,
        }
    )
    colors = {"prefetcht1": "#1f77b4", "prefetchit1": "#ff7f0e"}
    fig, axes = plt.subplots(2, 2, figsize=(16, 10.5))
    baseline = next((r for r in rows if r.get("kind") == "baseline"), None)
    min_x = None
    max_x = 0
    for kind in ["prefetcht1", "prefetchit1"]:
        for row in finite_rows(rows, kind, "elapsed_sec"):
            x = as_int(row.get("pass_injected"))
            if x <= 0:
                continue
            min_x = x if min_x is None else min(min_x, x)
            max_x = max(max_x, x)
    for ax, (key, ylabel) in zip(axes.flat, METRIC_KEYS):
        for kind in ["prefetcht1", "prefetchit1"]:
            series = finite_rows(rows, kind, key)
            if not series:
                continue
            xs = [as_int(r.get("pass_injected")) for r in series]
            ys = [as_float(r.get(key)) for r in series]
            yerr = None
            if args.errorbar != "none":
                stat_key = f"{key}_{args.errorbar}"
                errs = []
                have_err = False
                for r in series:
                    n = as_float(r.get(f"{key}_n"), 1.0)
                    err = as_float(r.get(stat_key), 0.0)
                    if n > 1 and math.isfinite(err) and err > 0:
                        have_err = True
                        errs.append(err)
                    else:
                        errs.append(0.0)
                if have_err:
                    yerr = errs
            ax.errorbar(
                xs,
                ys,
                yerr=yerr,
                marker="o",
                linewidth=2.0,
                markersize=6.8 if kind == "prefetchit1" else 5.0,
                capsize=3.0 if yerr is not None else 0.0,
                elinewidth=1.0,
                color=colors[kind],
                label=KIND_LABELS[kind],
                alpha=0.92,
            )
        if baseline is not None:
            y = as_float(baseline.get(key))
            if math.isfinite(y):
                ax.axhline(y, color="#666666", linestyle="--", linewidth=1.2, label="baseline")
                if args.errorbar != "none":
                    err = as_float(baseline.get(f"{key}_{args.errorbar}"), 0.0)
                    if err > 0:
                        ax.axhspan(y - err, y + err, color="#666666", alpha=0.10, linewidth=0)
        ax.set_xlabel("Injected Prefetch Count")
        ax.set_ylabel(ylabel)
        ax.set_ylim(bottom=0)
        if args.x_scale == "symlog":
            ax.set_xscale("symlog", linthresh=args.x_linthresh)
        if max_x > 0:
            left = max(1.0, (min_x or 1) * 0.8)
            ax.set_xlim(left=left, right=max_x * 1.08)
        ax.grid(True, alpha=0.25)
        ax.xaxis.set_major_formatter(FuncFormatter(human_count))
        handles, labels = ax.get_legend_handles_labels()
        dedup = dict(zip(labels, handles))
        ax.legend(dedup.values(), dedup.keys(), loc="best")
    fig.suptitle("Prefetch Injection Effects", fontsize=18)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "kind",
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
        "target_coverage_pct",
        "selection_mode",
        "depth_min",
        "depth",
        "site_budget",
        "prefetch_byte_offsets",
        "note",
    ]
    for metric, _label in METRIC_KEYS:
        fields.extend([f"{metric}_n", f"{metric}_std", f"{metric}_sem"])
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: (str(r.get("kind", "")), as_int(r.get("pass_injected")), str(r.get("variant", "")))):
            writer.writerow({field: row.get(field, "") for field in fields})


def write_report(path: Path, rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    lines = ["# Prefetch Injection Effects by Kind", ""]
    baseline = next((r for r in rows if r.get("kind") == "baseline"), None)
    if baseline is not None:
        runtime = as_float(baseline.get("elapsed_sec"))
        runtime_std = as_float(baseline.get("elapsed_sec_std"))
        runtime_sem = as_float(baseline.get("elapsed_sec_sem"))
        runtime_n = as_int(baseline.get("elapsed_sec_n"))
        if math.isfinite(runtime):
            cv = 100.0 * runtime_std / runtime if runtime and math.isfinite(runtime_std) else float("nan")
            lines.extend(
                [
                    "## Baseline Noise",
                    "",
                    f"- Runtime n: {runtime_n}",
                    f"- Runtime mean: {runtime:.6f}s",
                    f"- Runtime stddev: {runtime_std:.6f}s ({cv:.4f}%)",
                    f"- Runtime SEM: {runtime_sem:.6f}s",
                    "",
                ]
            )
    for kind in ["prefetcht1", "prefetchit1"]:
        kind_rows = [r for r in rows if r.get("kind") == kind]
        measured = [r for r in kind_rows if math.isfinite(as_float(r.get("elapsed_sec")))]
        lines.append(f"- `{kind}` measured rows: {len(measured)}")
        if measured:
            best = min(measured, key=lambda r: as_float(r.get("elapsed_sec")))
            lines.append(
                f"- `{kind}` best runtime row: `{best.get('variant')}`, "
                f"injected={as_int(best.get('pass_injected')):,}, "
                f"runtime={as_float(best.get('elapsed_sec')):.6f}s, "
                f"L2I MPKI={as_float(best.get('l2i_mpki')):.6f}"
            )
    lines.extend(
        [
            "",
            "Notes:",
            "- All y-axes in the PNG are forced to start at 0.",
            f"- X-axis scale: `{args.x_scale}`.",
            f"- Error display: `{args.errorbar}`; baseline is shown as a shaded band when repeated samples are available.",
            "- `prefetchit1` has fewer measured data points than `prefetcht1`; use it as a sparse comparison line, not as a dense sweep.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    add_baseline(rows, Path(args.baseline_summary))
    load_prefetcht1_rows(args, rows)
    load_final_compare_prefetcht1_rows(args, rows)
    load_prefetchit1_rows(args, rows)
    write_csv(out_dir / "prefetch_kind_injection_effects.csv", rows)
    plot(out_dir / "prefetch_kind_injection_effects.png", rows, args)
    write_report(out_dir / "prefetch_kind_injection_effects.md", rows, args)


if __name__ == "__main__":
    main()
