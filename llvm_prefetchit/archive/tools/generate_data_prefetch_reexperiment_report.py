#!/usr/bin/env python3
"""Build the audited report for the 2026-07-12 data-prefetch reruns."""

from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results/data_prefetch_reexperiment_20260712"
OUT = RESULTS / "final_report"
OLD_REPORT = ROOT / "results/final_campaign_20260711/final_report/final_results.csv"


CASES = [
    {
        "suite": "MicroSuite",
        "benchmark": "Router",
        "repeat": RESULTS / "router_tag4_l1_depth16_final_20s/screen_summary.csv",
        "screen": RESULTS / "router_depth16_extended_data/screen_summary.csv",
        "variant": "producer_tag4_l1",
        "method": "manual",
        "lines": 33,
        "policy": "data target only: CallData tag, 4 cache lines, L1 locality, depth 16",
        "explanation": (
            "Prefetch four 64 B lines of the producer-side gRPC CallData/tag object "
            "before the completion-queue handoff."
        ),
        "accepted": True,
        "reason": "Repeated mean is positive but below 10%; 95% CI includes 1.0x.",
    },
    {
        "suite": "MicroSuite",
        "benchmark": "SetAlgebra",
        "repeat": RESULTS / "setalgebra_nta_paired_20s/screen_summary.csv",
        "screen": RESULTS / "setalgebra_continuous_data_screen_v2/screen_summary.csv",
        "variant": "producer_tag2_nta",
        "method": "manual",
        "lines": 33,
        "policy": "data target only: CallData tag, 2 cache lines, NTA, depth 32",
        "explanation": (
            "Prefetch two 64 B lines of the producer-side gRPC CallData/tag object "
            "before the completion-queue handoff."
        ),
        "accepted": True,
        "reason": "Repeated mean is positive but below 10%; 95% CI includes 1.0x.",
    },
    {
        "suite": "MicroSuite",
        "benchmark": "HDSearch",
        "repeat": RESULTS / "hdsearch_rq8_tag4l2_depth8_final5/screen_summary.csv",
        "screen": RESULTS / "hdsearch_rq8_handoff_depth8/screen_summary.csv",
        "variant": "producer_tag4_l2",
        "method": "manual",
        "lines": 33,
        "policy": "data target only: CallData tag, 4 cache lines, L2 locality, depth 8",
        "explanation": (
            "Prefetch four 64 B lines of the producer-side gRPC CallData/tag object; "
            "LSH bucket/candidate prefetch variants were also screened."
        ),
        "accepted": False,
        "reason": (
            "No accepted positive result: the server alternated between distinct "
            "throughput/MPKI modes, and the paired aggregate regressed."
        ),
    },
    {
        "suite": "Standalone DB",
        "benchmark": "memcached",
        "repeat": RESULTS / "memcached_data_all8_1k_final_20s/screen_summary.csv",
        "screen": RESULTS / "memcached_data_1k/screen_summary.csv",
        "variant": "data_all8",
        "method": "manual",
        "lines": 38,
        "policy": "data target only: hash bucket/current+next item and 8 value lines",
        "explanation": (
            "Prefetch the assoc bucket head, hash-chain successor, and the first "
            "eight 64 B lines of the matched 1 KiB item value."
        ),
        "accepted": True,
        "reason": "Repeated result is statistically neutral and well below 10%.",
    },
]


def mean_sem(values: list[float]) -> tuple[float, float]:
    mean = statistics.mean(values)
    sem = statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return mean, sem


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def is_valid(row: dict[str, str]) -> bool:
    return (
        int(float(row["valid"])) == 1
        and int(float(row["cpu_migrations"])) == 0
        and int(float(row.get("failed_responses", "0") or 0)) == 0
    )


def paired_stats(path: Path, variant: str) -> dict[str, object]:
    rows = read_rows(path)
    assert rows and all(is_valid(row) for row in rows), path
    assert len(rows) % 2 == 0, path

    pairs: list[tuple[dict[str, str], dict[str, str]]] = []
    for index in range(0, len(rows), 2):
        base, pref = rows[index:index + 2]
        assert base["label"].endswith("_baseline"), (path, base["label"])
        assert pref["label"].endswith(f"_{variant}"), (path, pref["label"])
        pairs.append((base, pref))

    speedups = [float(pref["qps"]) / float(base["qps"]) for base, pref in pairs]
    reductions = [
        100.0 * (float(base["l2i_mpki"]) - float(pref["l2i_mpki"]))
        / float(base["l2i_mpki"])
        for base, pref in pairs
    ]
    speedup, speedup_sem = mean_sem(speedups)
    reduction, reduction_sem = mean_sem(reductions)
    return {
        "repeat_pairs": len(pairs),
        "speedup": speedup,
        "speedup_sem": speedup_sem,
        "l2i_reduction_pct": reduction,
        "l2i_reduction_sem": reduction_sem,
        "qps_baseline": statistics.mean(float(base["qps"]) for base, _ in pairs),
        "qps_prefetch": statistics.mean(float(pref["qps"]) for _, pref in pairs),
        "l2i_mpki_baseline": statistics.mean(float(base["l2i_mpki"]) for base, _ in pairs),
        "l2i_mpki_prefetch": statistics.mean(float(pref["l2i_mpki"]) for _, pref in pairs),
        "pair_speedups": ";".join(f"{value:.6f}" for value in speedups),
        "pair_l2i_reductions_pct": ";".join(f"{value:.6f}" for value in reductions),
        "max_cpu_migrations": max(int(float(row["cpu_migrations"])) for row in rows),
        "max_failed_responses": max(int(float(row.get("failed_responses", "0") or 0)) for row in rows),
    }


def screen_stats(path: Path, variant: str) -> dict[str, float]:
    rows = read_rows(path)
    valid = [row for row in rows if is_valid(row)]
    baselines = [row for row in valid if row["label"].endswith("_baseline")]
    selected = [row for row in valid if row["label"].endswith(f"_{variant}")]
    assert baselines and len(selected) == 1, (path, variant)
    base_qps = statistics.mean(float(row["qps"]) for row in baselines)
    base_mpki = statistics.mean(float(row["l2i_mpki"]) for row in baselines)
    pref_qps = float(selected[0]["qps"])
    pref_mpki = float(selected[0]["l2i_mpki"])
    return {
        "best_screen_speedup": pref_qps / base_qps,
        "best_screen_l2i_reduction_pct": 100.0 * (base_mpki - pref_mpki) / base_mpki,
        "screen_qps_baseline": base_qps,
        "screen_qps_prefetch": pref_qps,
        "screen_l2i_mpki_baseline": base_mpki,
        "screen_l2i_mpki_prefetch": pref_mpki,
    }


def build_rows() -> list[dict[str, object]]:
    output = []
    for case in CASES:
        row = dict(case)
        row.update(paired_stats(case["repeat"], case["variant"]))
        row.update(screen_stats(case["screen"], case["variant"]))
        row["repeat_evidence"] = str(Path(case["repeat"]).relative_to(ROOT))
        row["screen_evidence"] = str(Path(case["screen"]).relative_to(ROOT))
        row.pop("repeat")
        row.pop("screen")
        output.append(row)
    return output


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def update_final_csv(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    old = read_rows(OLD_REPORT)
    by_name = {str(row["benchmark"]): row for row in rows}
    extra_fields = [
        "best_screen_speedup", "best_screen_l2i_reduction_pct", "repeat_pair_count",
        "data_prefetch_status", "prior_pgo_speedup",
    ]
    for item in old:
        for field in extra_fields:
            item[field] = ""
        selected = by_name.get(item["benchmark"])
        if selected is None:
            continue
        item["best_screen_speedup"] = selected["best_screen_speedup"]
        item["best_screen_l2i_reduction_pct"] = selected["best_screen_l2i_reduction_pct"]
        item["repeat_pair_count"] = selected["repeat_pairs"]
        item["data_prefetch_status"] = selected["reason"]
        item["prior_pgo_speedup"] = item.get("pgo_speedup", "")
        if not selected["accepted"]:
            item.update({
                "injection_method": selected["method"],
                "speedup": selected["speedup"],
                "speedup_sem": selected["speedup_sem"],
                "pgo_speedup": "",
                "code_line_change": selected["lines"],
                "l2i_mpki_baseline": selected["l2i_mpki_baseline"],
                "l2i_mpki_prefetch": selected["l2i_mpki_prefetch"],
                "l2i_reduction_pct": selected["l2i_reduction_pct"],
                "l2i_reduction_sem": selected["l2i_reduction_sem"],
                "target_policy": selected["policy"],
                "reason_cannot_inject": selected["reason"],
                "code_change_explanation": selected["explanation"],
                "confidence": (
                    f'{selected["repeat_pairs"]} paired x 20 s, fixed 2.0 GHz, '
                    "migration=0, failed responses=0; rejected for mode instability"
                ),
                "evidence": selected["repeat_evidence"],
                "include_graph": "False",
            })
            continue
        item.update({
            "injection_method": selected["method"],
            "speedup": selected["speedup"],
            "speedup_sem": selected["speedup_sem"],
            "pgo_speedup": "",
            "code_line_change": selected["lines"],
            "l2i_mpki_baseline": selected["l2i_mpki_baseline"],
            "l2i_mpki_prefetch": selected["l2i_mpki_prefetch"],
            "l2i_reduction_pct": selected["l2i_reduction_pct"],
            "l2i_reduction_sem": selected["l2i_reduction_sem"],
            "target_policy": selected["policy"],
            "reason_cannot_inject": "",
            "code_change_explanation": selected["explanation"],
            "confidence": (
                f'{selected["repeat_pairs"]} paired x 20 s, fixed 2.0 GHz, '
                "migration=0, failed responses=0; see data_prefetch_status"
            ),
            "evidence": selected["repeat_evidence"],
            "include_graph": "True",
        })
    path = OUT / "updated_final_results.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(old[0]))
        writer.writeheader()
        writer.writerows(old)
    return old


def plot_focused(rows: list[dict[str, object]], metric: str, error: str,
                 screen_metric: str, ylabel: str, filename: str) -> None:
    positions = list(range(len(rows)))
    values = [float(row[metric]) for row in rows]
    errors = [float(row[error]) for row in rows]
    screens = [float(row[screen_metric]) for row in rows]
    labels = [f'{row["suite"]}\n{row["benchmark"]}' for row in rows]
    colors = ["#2878B5" if row["accepted"] else "#A7A7A7" for row in rows]

    fig, ax = plt.subplots(figsize=(8.8, 4.8), constrained_layout=True)
    bars = ax.bar(positions, values, yerr=errors, capsize=4, color=colors,
                  edgecolor="#252525", linewidth=0.7)
    for bar, row in zip(bars, rows):
        if not row["accepted"]:
            bar.set_hatch("//")
    ax.scatter(positions, screens, marker="D", facecolors="white", edgecolors="#252525",
               linewidths=1.1, s=48, zorder=4)
    ax.axhline(1.0 if metric == "speedup" else 0.0, color="#555555", linewidth=1.0)
    ax.set_xticks(positions, labels)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", color="#D7D7D7", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.legend(handles=[
        Patch(facecolor="#2878B5", edgecolor="#252525", label="Paired repeat mean"),
        Patch(facecolor="#A7A7A7", edgecolor="#252525", hatch="//", label="Rejected/unstable"),
        Line2D([], [], marker="D", markerfacecolor="white", markeredgecolor="#252525",
               linestyle="", label="Best exploratory screen"),
    ], frameon=False, loc="best")
    fig.savefig(OUT / filename, dpi=220)
    fig.savefig(OUT / filename.replace(".png", ".svg"))
    plt.close(fig)


def plot_updated(rows: list[dict[str, object]], metric: str, error: str,
                 ylabel: str, filename: str) -> None:
    selected = []
    order = {"DCPerf": 0, "MicroSuite": 1, "Verilator": 2, "Standalone DB": 3}
    for row in rows:
        try:
            value = float(row[metric])
        except (TypeError, ValueError):
            continue
        if row.get("include_graph") != "True":
            continue
        selected.append((row, value))
    selected.sort(key=lambda pair: order.get(str(pair[0]["benchmark_suite"]), 99))

    positions = list(range(len(selected)))
    labels = [f'{row["benchmark_suite"]}\n{row["benchmark"]}' for row, _ in selected]
    values = [value for _, value in selected]
    errors = [float(row.get(error) or 0.0) for row, _ in selected]
    colors = {"manual": "#2878B5", "static": "#E68632", "both": "#4C9F70"}

    fig, ax = plt.subplots(figsize=(11.4, 5.3), constrained_layout=True)
    ax.bar(positions, values, yerr=errors, capsize=4,
           color=[colors.get(str(row["injection_method"]), "#A7A7A7") for row, _ in selected],
           edgecolor="#252525", linewidth=0.7)
    ax.axhline(1.0 if metric == "speedup" else 0.0, color="#555555", linewidth=1.0)
    for index, (row, _) in enumerate(selected):
        pgo = row.get("pgo_speedup")
        if metric == "speedup" and pgo not in (None, ""):
            ax.scatter(index, float(pgo), color="#C73E3A", s=50, zorder=4)
    ax.set_xticks(positions, labels, rotation=20, ha="right")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", color="#D7D7D7", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.legend(handles=[
        Patch(facecolor=colors["manual"], edgecolor="#252525", label="Manual"),
        Patch(facecolor=colors["static"], edgecolor="#252525", label="Static compiler"),
        Line2D([], [], marker="o", color="#C73E3A", linestyle="", label="PGO reference"),
    ], frameon=False, loc="best")
    fig.savefig(OUT / filename, dpi=220)
    fig.savefig(OUT / filename.replace(".png", ".svg"))
    plt.close(fig)


def fmt(value: object, digits: int = 3) -> str:
    return f"{float(value):.{digits}f}"


def write_report(rows: list[dict[str, object]]) -> None:
    table = [
        "| suite | benchmark | method | source lines | repeated speedup | best screen | QPS base -> prefetch | "
        "L2I MPKI base -> prefetch | MPKI reduction | data-prefetch policy | status |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        table.append(
            f'| {row["suite"]} | {row["benchmark"]} | {row["method"]} | {row["lines"]} | '
            f'{fmt(row["speedup"])}x +/- {fmt(row["speedup_sem"])} | '
            f'{fmt(row["best_screen_speedup"])}x | '
            f'{fmt(row["qps_baseline"], 1)} -> {fmt(row["qps_prefetch"], 1)} | '
            f'{fmt(row["l2i_mpki_baseline"])} -> {fmt(row["l2i_mpki_prefetch"])} | '
            f'{fmt(row["l2i_reduction_pct"], 2)}% +/- {fmt(row["l2i_reduction_sem"], 2)} | '
            f'{row["policy"]} | {row["reason"]} |'
        )

    accepted = [row for row in rows if row["accepted"]]
    mean_speedup = statistics.mean(float(row["speedup"]) for row in accepted)
    mean_reduction = statistics.mean(float(row["l2i_reduction_pct"]) for row in accepted)
    report = f"""# High-L2I Data-Prefetch Reexperiment

Date: 2026-07-12

## Measurement boundary

- All retained runs used a fixed 2.0 GHz policy with turbo disabled, one workload at a time, explicit process/thread core sets, zero measured CPU migrations, and zero failed responses.
- All four workloads use five alternating baseline/prefetch pairs. Each measured interval is 20 s after application warmup/settling.
- The repeated paired mean is the final result. `Best screen` is shown only to document tuning behavior and is not used as the performance claim.
- Error bars are SEM across paired ratios. None of the new positive means has a 95% confidence interval that excludes 1.0x.

## Audited results

{chr(10).join(table)}

## Workload findings

- **Router:** depth 16 maximized baseline pressure (about 140 L2I MPKI). Prefetching four CallData/tag cache lines before producer-to-gRPC handoff reached 1.181x in the exploratory screen, but the five-pair mean was only **{fmt(rows[0]['speedup'])}x**. Pair 1 was 1.107x and later pairs converged to 1.000-1.016x, so the large screen result is a transient mode/order effect rather than a repeatable 18% gain.
- **SetAlgebra:** the best policy was two CallData/tag lines with NTA at depth 32. The screen maximum was 1.079x and the five-pair mean was **{fmt(rows[1]['speedup'])}x**. The direction is positive, but run-to-run variation is larger than the mean gain.
- **HDSearch:** CallData handoff and LSH bucket/candidate-vector prefetches were tested over locality, line count, depth, and gRPC thread caps. A depth-8 screen showed 1.052x and a large MPKI drop, but five depth-8 pairs ranged from -11.8% to +5.1%, with baseline MPKI ranging from 31 to 53. The aggregate was **{fmt(rows[2]['speedup'])}x**. It is therefore excluded from accepted positive results.
- **memcached:** the true data-prefetch path covers the assoc bucket head, hash-chain successor, matched item, and value lines. With 1 KiB values, the best screen was 1.016x and five pairs were **{fmt(rows[3]['speedup'])}x**. Under valid pinning its baseline was only {fmt(rows[3]['l2i_mpki_baseline'])} L2I MPKI, so it is effectively neutral.

## Search space exercised

- **Router / SetAlgebra:** producer, consumer, and both handoff sites; tag-data and code-target combinations; 1/2/4/8 cache lines; L1/L2/L3/NTA locality; closed-loop depths 16 and 32; gRPC caps 2/4/6/8. The final source-line count covers the selected prefetch helper, compile-time knobs, and producer call site; thread-cap test harness changes are excluded.
- **HDSearch:** the same handoff matrix plus LSH bucket data, candidate-vector first lines, candidate lookahead, depths 4/8, and gRPC caps 4/6/8. Startup crashes were retried only to obtain valid rows and were never counted as performance results.
- **memcached:** function-code controls and true data variants for bucket/chain/match/all, 1/2/4/8/16/32 lines, L1/L2/L3/NTA locality, 64 B and 1 KiB values, hash powers 13/14, and service/client concurrency changes.

## Core and frequency audit

- MicroSuite reserved core 0 for perf control, cores 1-8 for the memory tier, 9-20 for the leaf tier, 21-55 for the mid tier, and 56-70 for the client. The preload pinner assigned each created thread a distinct core inside its tier set.
- memcached reserved core 0 for perf control, cores 1-24 for eight service threads, and cores 25-40 for eight memtier threads. Service and client sets did not overlap.
- A final audit re-read all 40 retained run summaries plus both frequency snapshots per run: `valid=1`, migrations=0, failed responses=0, governor=`performance`, min=max=2,000,000 kHz, turbo disabled, and no pinner errors.

## Prior large memcached result

The historical 1.153x memcached number is not valid evidence. Its Python client created 2,048 OS threads, emitted connection-reset/broken-pipe errors, and the server perf records contained 41-105 CPU migrations. The corrected pinned runs above supersede it.

## Interpretation

Data prefetch is not a direct treatment for instruction-cache misses. These variants can help only when the same handoff also stalls on request metadata or pointer chasing. That explains why a high L2I MPKI did not imply a repeatable 10% QPS gain. The campaign did find positive repeated means for Router and SetAlgebra, but **no new migration-free data-prefetch result met 10%**, and it would be incorrect to report the exploratory maxima as final speedups.

Across the three accepted/non-crashing rows, arithmetic mean speedup is **{mean_speedup:.3f}x** and mean L2I-MPKI reduction is **{mean_reduction:.2f}%**.

## Artifacts

- `data_prefetch_results.csv`: paired values, means, SEM, screen maxima, and evidence paths.
- `updated_final_results.csv`: the previous complete table with Router, SetAlgebra, and memcached updated; HDSearch remains excluded.
- `data_prefetch_speedup.png` / `.svg`: focused repeated speedup with screen maxima.
- `data_prefetch_l2i_reduction.png` / `.svg`: focused MPKI reduction with screen maxima.
- `updated_final_speedup.png` / `.svg`: prior final graph plus accepted data-prefetch rows.
- `updated_final_l2i_reduction.png` / `.svg`: prior final MPKI graph plus accepted data-prefetch rows.
"""
    (OUT / "data_prefetch_report.md").write_text(report, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = build_rows()
    write_csv(OUT / "data_prefetch_results.csv", rows)
    updated = update_final_csv(rows)
    plot_focused(rows, "speedup", "speedup_sem", "best_screen_speedup",
                 "QPS speedup (x)", "data_prefetch_speedup.png")
    plot_focused(rows, "l2i_reduction_pct", "l2i_reduction_sem",
                 "best_screen_l2i_reduction_pct", "L2I MPKI reduction (%)",
                 "data_prefetch_l2i_reduction.png")
    plot_updated(updated, "speedup", "speedup_sem", "Speedup (x)",
                 "updated_final_speedup.png")
    plot_updated(updated, "l2i_reduction_pct", "l2i_reduction_sem",
                 "L2I MPKI reduction (%)", "updated_final_l2i_reduction.png")
    write_report(rows)
    print(OUT)


if __name__ == "__main__":
    main()
