#!/usr/bin/env python3
"""Summarize baseline, PGO-best, and static-prefetch speedup results."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path


METRICS = ("elapsed_sec", "instructions", "l1i_mpki", "l2i_mpki", "itlb_mpki", "stlb_mpki")


def read_rows(path: Path) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            parsed: dict[str, float] = {}
            for key in METRICS:
                try:
                    parsed[key] = float(row[key])
                except (KeyError, ValueError):
                    parsed[key] = float("nan")
            out.append(parsed)
    if not out:
        raise SystemExit(f"no rows in {path}")
    return out


def mean(rows: list[dict[str, float]], metric: str) -> float:
    vals = [r[metric] for r in rows if math.isfinite(r[metric])]
    return statistics.mean(vals) if vals else float("nan")


def stdev(rows: list[dict[str, float]], metric: str) -> float:
    vals = [r[metric] for r in rows if math.isfinite(r[metric])]
    return statistics.stdev(vals) if len(vals) > 1 else 0.0


def fmt(x: float, digits: int = 6) -> str:
    if not math.isfinite(x):
        return "nan"
    return f"{x:.{digits}f}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--pgo-best", type=Path, required=True)
    ap.add_argument("--static", type=Path, action="append", required=True)
    ap.add_argument("--static-label", action="append", required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    if len(args.static) != len(args.static_label):
        raise SystemExit("--static and --static-label counts must match")

    series = [("baseline", args.baseline), ("pgo_best_prefetcht1", args.pgo_best)]
    series.extend(zip(args.static_label, args.static))
    rows_by_label = [(label, read_rows(path)) for label, path in series]
    baseline_rows = rows_by_label[0][1]
    baseline_elapsed = mean(baseline_rows, "elapsed_sec")
    baseline_l2 = mean(baseline_rows, "l2i_mpki")
    baseline_inst = mean(baseline_rows, "instructions")

    summary_rows = []
    for label, rows in rows_by_label:
        elapsed = mean(rows, "elapsed_sec")
        l2 = mean(rows, "l2i_mpki")
        inst = mean(rows, "instructions")
        item = {
            "label": label,
            "n": len(rows),
            "elapsed_sec_mean": elapsed,
            "elapsed_sec_stdev": stdev(rows, "elapsed_sec"),
            "speedup_vs_baseline_pct": (baseline_elapsed / elapsed - 1.0) * 100.0 if elapsed else float("nan"),
            "elapsed_delta_vs_baseline_pct": (elapsed / baseline_elapsed - 1.0) * 100.0 if baseline_elapsed else float("nan"),
            "l2i_mpki_mean": l2,
            "l2i_mpki_stdev": stdev(rows, "l2i_mpki"),
            "l2i_mpki_delta_vs_baseline_pct": (l2 / baseline_l2 - 1.0) * 100.0 if baseline_l2 else float("nan"),
            "l1i_mpki_mean": mean(rows, "l1i_mpki"),
            "instructions_mean": inst,
            "instructions_delta_vs_baseline_pct": (inst / baseline_inst - 1.0) * 100.0 if baseline_inst else float("nan"),
        }
        summary_rows.append(item)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "speedup_compare_summary.csv"
    fields = list(summary_rows[0].keys())
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(summary_rows)

    md = ["# Static Prefetch Speedup Compare", ""]
    md.append("| Binary | N | Runtime mean (s) | Runtime stdev | Speedup vs baseline | L2I MPKI | L2I delta | Inst delta |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in summary_rows:
        md.append(
            f"| {r['label']} | {r['n']} | {fmt(r['elapsed_sec_mean'])} | "
            f"{fmt(r['elapsed_sec_stdev'])} | {fmt(r['speedup_vs_baseline_pct'], 3)}% | "
            f"{fmt(r['l2i_mpki_mean'])} | {fmt(r['l2i_mpki_delta_vs_baseline_pct'], 3)}% | "
            f"{fmt(r['instructions_delta_vs_baseline_pct'], 3)}% |"
        )
    md.append("")
    md.append("Notes:")
    md.append("- `pgo_best_prefetcht1` is the existing profile-guided best result.")
    md.append("- Static variants use profile-free target/site selection; profiling data is used only for offline validation.")
    md_path = args.out_dir / "speedup_compare_summary.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"[ok] wrote {csv_path}")
    print(f"[ok] wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
