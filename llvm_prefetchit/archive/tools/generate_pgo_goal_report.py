#!/usr/bin/env python3
"""Generate the audited report for the 2026-07-13 corrected-LBR PGO goal."""

from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "results/pgo_goal_20260713"
OUT = CAMPAIGN / "final_report"

PROFILE_DIRS = {
    "Router": CAMPAIGN / "profiles/router4_grpc4_fixed60k_n3/repetition_summary",
    "SetAlgebra": CAMPAIGN / "profiles/setalgebra_highmpki_p4d4/repetition_summary",
    "Recommend": CAMPAIGN / "recommend/profiles_deterministic_sync_d1_n3_p20000/repetition_summary",
    "HDSearch": CAMPAIGN / "hdsearch/profiles_fixed_d1_h16_p2_n3_p20000/repetition_summary",
    "memcached": ROOT / "results/pgo_lbr_path_20260712/profiles/memcached/repetition_summary",
    "PostgreSQL": CAMPAIGN / "profiles/postgresql_simple_c8_corrected_n3/repetition_summary",
    "Proto arena": CAMPAIGN / "profiles/proto_arena_corrected_n3/repetition_summary",
}

BRANCH_TYPES = ("COND", "CALL", "RET", "IND", "IND_CALL", "UNCOND")


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def mean_sem(values: list[float]) -> tuple[float, float]:
    if not values:
        return math.nan, math.nan
    if len(values) == 1:
        return values[0], math.nan
    return statistics.mean(values), statistics.stdev(values) / math.sqrt(len(values))


def profile(benchmark: str) -> dict[str, object]:
    directory = PROFILE_DIRS[benchmark]
    summary = read_json(directory / "summary.json")
    mix = {
        row["branch_type"]: float(row["ratio_pct"])
        for row in read_csv(directory / "branch_type_summary.csv")
    }
    return {
        "profile_reps": summary["rep_count"],
        "lbr_branch_samples": summary["branch_samples"],
        "lbr_target_samples": summary["target_samples"],
        "top10_jaccard": summary["top10_mean_jaccard"],
        "top10_sample_overlap": summary["top10_mean_sample_overlap"],
        **{kind: mix.get(kind, 0.0) for kind in BRANCH_TYPES},
        "profile_evidence": str((directory / "summary.json").relative_to(ROOT)),
    }


def paired_result(
    *,
    suite: str,
    benchmark: str,
    path: Path,
    metric: str,
    variant: str,
    target_policy: str,
    plan_targets: int | str,
    plan_prefetches: int | str,
    result_status: str,
    explanation: str,
    evidence_note: str = "",
) -> dict[str, object]:
    data = read_json(path)
    baseline_key = "baseline_qps" if "baseline_qps" in data else "baseline_tps"
    prefetch_key = "prefetch_qps" if "prefetch_qps" in data else "prefetch_tps"
    row = {
        "benchmark_suite": suite,
        "benchmark": benchmark,
        "injection_method": "PGO compiler injection",
        "performance_metric": metric,
        "baseline_performance": data[baseline_key]["mean"],
        "prefetch_performance": data[prefetch_key]["mean"],
        "speedup": data["speedup"]["mean"],
        "speedup_sem": data["speedup"]["sem"],
        "performance_repetitions": data["speedup"]["n"],
        "l2i_mpki_baseline": data["baseline_l2i_mpki"]["mean"],
        "l2i_mpki_prefetch": data["prefetch_l2i_mpki"]["mean"],
        "l2i_reduction_pct": data["l2i_reduction_pct"]["mean"],
        "l2i_reduction_sem": data["l2i_reduction_pct"]["sem"],
        "pgo_variant": variant,
        "plan_targets": plan_targets,
        "plan_prefetches": plan_prefetches,
        "target_policy": target_policy,
        "result_status": result_status,
        "minimum_5pct_met": data["speedup"]["mean"] >= 1.05,
        "explanation": explanation,
        "performance_evidence": str(path.relative_to(ROOT)),
        "evidence_note": evidence_note,
    }
    row.update(profile(benchmark))
    return row


def recommend_fixed_work() -> dict[str, object]:
    directory = CAMPAIGN / "recommend/combined_best_paired_n5"
    speedups: list[float] = []
    reductions: list[float] = []
    baseline_qps: list[float] = []
    prefetch_qps: list[float] = []
    baseline_mpki: list[float] = []
    prefetch_mpki: list[float] = []
    pair = 1
    while True:
        baseline_path = directory / f"p{pair}_baseline/summary.json"
        prefetch_path = directory / f"p{pair}_pgo/summary.json"
        if not baseline_path.exists() or not prefetch_path.exists():
            break
        baseline = read_json(baseline_path)
        prefetch = read_json(prefetch_path)
        assert baseline["valid"] == 1 and prefetch["valid"] == 1
        assert baseline["cpu_migrations"] == 0 and prefetch["cpu_migrations"] == 0
        baseline_qps.append(float(baseline["qps"]))
        prefetch_qps.append(float(prefetch["qps"]))
        baseline_mpki.append(float(baseline["l2i_mpki"]))
        prefetch_mpki.append(float(prefetch["l2i_mpki"]))
        speedups.append(float(prefetch["qps"]) / float(baseline["qps"]))
        reductions.append(
            100.0
            * (float(baseline["l2i_mpki"]) - float(prefetch["l2i_mpki"]))
            / float(baseline["l2i_mpki"])
        )
        pair += 1
    assert len(speedups) == 10
    speedup, speedup_sem = mean_sem(speedups)
    reduction, reduction_sem = mean_sem(reductions)
    row = {
        "benchmark_suite": "MicroSuite",
        "benchmark": "Recommend",
        "injection_method": "PGO compiler injection",
        "performance_metric": "fixed-work QPS (10k requests)",
        "baseline_performance": statistics.mean(baseline_qps),
        "prefetch_performance": statistics.mean(prefetch_qps),
        "speedup": speedup,
        "speedup_sem": speedup_sem,
        "performance_repetitions": len(speedups),
        "l2i_mpki_baseline": statistics.mean(baseline_mpki),
        "l2i_mpki_prefetch": statistics.mean(prefetch_mpki),
        "l2i_reduction_pct": reduction,
        "l2i_reduction_sem": reduction_sem,
        "pgo_variant": "cov100_d1-32_b1_o064",
        "plan_targets": 539,
        "plan_prefetches": 989,
        "target_policy": "target+next line",
        "result_status": "repeated fixed-work negative (<5%)",
        "minimum_5pct_met": False,
        "explanation": (
            "The prefetch binary reproducibly lowers L2I MPKI, but fixed completed work is flat. "
            "Earlier 1.04-1.05x open-window QPS did not survive fixed-work validation."
        ),
        "performance_evidence": str(directory.relative_to(ROOT)),
        "evidence_note": "AB/BA-style interleaving; all runs valid with zero migrations",
    }
    row.update(profile("Recommend"))
    return row


def memcached_screen() -> dict[str, object]:
    directory = CAMPAIGN / "screens/memcached_target_groups_h14_v1"
    candidate = read_json(directory / "run10_t06_assoc74_g4_o0/summary.json")
    before = read_json(directory / "run09_baseline/summary.json")
    after = read_json(directory / "run13_baseline/summary.json")
    baseline_qps = statistics.mean([before["qps"], after["qps"]])
    baseline_mpki = statistics.mean([before["l2i_mpki"], after["l2i_mpki"]])
    speedup = candidate["qps"] / baseline_qps
    reduction = 100.0 * (baseline_mpki - candidate["l2i_mpki"]) / baseline_mpki
    row = {
        "benchmark_suite": "Standalone DB",
        "benchmark": "memcached",
        "injection_method": "PGO compiler injection",
        "performance_metric": "memtier ops/s",
        "baseline_performance": baseline_qps,
        "prefetch_performance": candidate["qps"],
        "speedup": speedup,
        "speedup_sem": math.nan,
        "performance_repetitions": 1,
        "l2i_mpki_baseline": baseline_mpki,
        "l2i_mpki_prefetch": candidate["l2i_mpki"],
        "l2i_reduction_pct": reduction,
        "l2i_reduction_sem": math.nan,
        "pgo_variant": "target group 6, four sites, o0",
        "plan_targets": 1,
        "plan_prefetches": 4,
        "target_policy": "target-only",
        "result_status": "best bracketed screen; no >=5% candidate",
        "minimum_5pct_met": False,
        "explanation": (
            "The reproducible saturated configuration has only about 1.2 L2I MPKI. "
            "The old 7.7 MPKI point was not reproducible; high-MPKI underload was client/sleep-wake limited."
        ),
        "performance_evidence": str(directory.relative_to(ROOT)),
        "evidence_note": "single bracketed candidate; all service/client migrations zero",
    }
    row.update(profile("memcached"))
    return row


def proto_screen() -> dict[str, object]:
    directory = CAMPAIGN / "screens/proto_run_subset_clean_v1"
    candidate = read_json(directory / "run_top10_s4_o0/summary.json")
    before = read_json(directory / "baseline_pre/summary.json")
    after = read_json(directory / "baseline_post/summary.json")
    baseline_time = statistics.mean([before["real_time_ns"], after["real_time_ns"]])
    baseline_mpki = statistics.mean([before["l2i_mpki"], after["l2i_mpki"]])
    speedup = baseline_time / candidate["real_time_ns"]
    reduction = 100.0 * (baseline_mpki - candidate["l2i_mpki"]) / baseline_mpki
    row = {
        "benchmark_suite": "FleetBench",
        "benchmark": "Proto arena",
        "injection_method": "PGO compiler injection",
        "performance_metric": "runtime (ns/iteration)",
        "baseline_performance": baseline_time,
        "prefetch_performance": candidate["real_time_ns"],
        "speedup": speedup,
        "speedup_sem": math.nan,
        "performance_repetitions": 1,
        "l2i_mpki_baseline": baseline_mpki,
        "l2i_mpki_prefetch": candidate["l2i_mpki"],
        "l2i_reduction_pct": reduction,
        "l2i_reduction_sem": math.nan,
        "pgo_variant": "cov50 Run-target top10, four sites each",
        "plan_targets": 10,
        "plan_prefetches": 38,
        "target_policy": "target-only",
        "result_status": "best clean-layout screen; no >=5% candidate",
        "minimum_5pct_met": False,
        "explanation": (
            "Misses are spread over 6,970 resolved target cache lines in generated protobuf code. "
            "Broad plans reduce MPKI but add enough executed prefetch/code-footprint cost to lose runtime."
        ),
        "performance_evidence": str(directory.relative_to(ROOT)),
        "evidence_note": "single bracketed candidate; 120 iterations, zero migrations",
    }
    row.update(profile("Proto arena"))
    return row


def build_rows() -> list[dict[str, object]]:
    rows = [
        paired_result(
            suite="MicroSuite",
            benchmark="Router",
            path=CAMPAIGN / "paired/router4_grpc4_cov50_d8_b1_o064_n3_30s/paired_summary.json",
            metric="QPS",
            variant="cov50_d8-32_b1_o064",
            target_policy="target+next line",
            plan_targets=7,
            plan_prefetches=14,
            result_status="repeated matched-thread negative (<5%)",
            explanation=(
                "Top targets are deterministic, but gRPC/runtime dispatch dominates and the 14-prefetch plan "
                "does not change the service bottleneck."
            ),
            evidence_note="3 pairs, matched 20 mid-tier TIDs, zero migrations",
        ),
        paired_result(
            suite="MicroSuite",
            benchmark="SetAlgebra",
            path=CAMPAIGN / "paired/setalgebra_globalsamples_d8_n10_abba_n4_30s/paired_summary.json",
            metric="QPS",
            variant="cov100 global-sample d8, top10 injections",
            target_policy="target-aware target+next line",
            plan_targets=10,
            plan_prefetches=14,
            result_status="repeated matched-thread negative (<5%)",
            explanation=(
                "A one-run 1.058x screen regressed to 1.002x in AB/BA repetition. "
                "The dominant gRPC/OpenMP/runtime paths are shared and prefetch overhead offsets any hit-rate gain."
            ),
            evidence_note="4 AB/BA pairs, matched 11 TIDs, zero migrations",
        ),
        recommend_fixed_work(),
        paired_result(
            suite="MicroSuite",
            benchmark="HDSearch",
            path=CAMPAIGN / "hdsearch/paired_same_layout_s05_fixed5k_n10/paired_summary.json",
            metric="fixed-work QPS (5k requests)",
            variant="cov50 s05 dispatch-entry same-layout subset",
            target_policy="target-only",
            plan_targets=1,
            plan_prefetches=1,
            result_status="repeated but outlier-sensitive; no >=5% claim",
            explanation=(
                "Nine of ten pairs are approximately neutral; one 1.212x execution creates the positive mean. "
                "The broader same-layout n=5 validation was 0.972x, so no speedup is accepted."
            ),
            evidence_note="10 AB/BA pairs, matched 7 TIDs, zero migrations; one mode outlier",
        ),
        memcached_screen(),
        paired_result(
            suite="Standalone DB",
            benchmark="PostgreSQL",
            path=CAMPAIGN / "paired/postgresql_simple_c8_cov25_d8_b1_prefetch_vs_nop_n5/paired_summary.json",
            metric="pgbench TPS",
            variant="cov25_d8-32_b1_o0",
            target_policy="target-only",
            plan_targets=84,
            plan_prefetches=73,
            result_status="accepted repeated >=5% PGO gain",
            explanation=(
                "Simple-protocol tpcb-like execution keeps the backend instruction path on the critical path. "
                "A low-budget target-only plan produces the only repeated >=5% gain in this goal."
            ),
            evidence_note="5 AB/BA pairs, 8 clients/threads, same-layout prefetch-vs-NOP, zero migrations",
        ),
        proto_screen(),
    ]
    return rows


def plot(rows: list[dict[str, object]], field: str, sem_field: str, ylabel: str, output: Path) -> None:
    labels = [str(row["benchmark"]) for row in rows]
    values = [float(row[field]) for row in rows]
    errors = [
        0.0 if not math.isfinite(float(row[sem_field])) else float(row[sem_field])
        for row in rows
    ]
    colors = ["#D97706" if row["minimum_5pct_met"] else "#64748B" for row in rows]
    hatches = ["" if int(row["performance_repetitions"]) >= 3 else "///" for row in rows]

    fig, ax = plt.subplots(figsize=(11.2, 5.4), constrained_layout=True)
    x = list(range(len(rows)))
    bars = ax.bar(x, values, color=colors, edgecolor="#1F2937", linewidth=0.7)
    for bar, hatch in zip(bars, hatches):
        bar.set_hatch(hatch)
    ax.errorbar(x, values, yerr=errors, fmt="none", ecolor="#111827", capsize=4, linewidth=1.2)
    ax.set_xticks(x, labels, rotation=22, ha="right")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", color="#D1D5DB", linewidth=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    if field == "speedup":
        ax.axhline(1.0, color="#111827", linewidth=1.0)
        ax.axhline(1.05, color="#B91C1C", linewidth=1.0, linestyle="--")
        ax.set_ylim(min(0.95, min(values) - 0.02), max(1.10, max(v + e for v, e in zip(values, errors)) + 0.02))
    else:
        ax.axhline(0.0, color="#111827", linewidth=1.0)
    ax.legend(
        handles=[
            Patch(facecolor="#D97706", edgecolor="#1F2937", label=">=5% repeated gain"),
            Patch(facecolor="#64748B", edgecolor="#1F2937", label="No accepted >=5% gain"),
            Patch(facecolor="white", edgecolor="#1F2937", hatch="///", label="Exploratory n=1"),
        ],
        loc="best",
        frameon=False,
    )
    fig.savefig(output, dpi=180)
    plt.close(fig)


def fmt(value: object, digits: int = 3) -> str:
    number = float(value)
    if not math.isfinite(number):
        return "N/A"
    return f"{number:.{digits}f}"


def write_report(rows: list[dict[str, object]]) -> None:
    repeated = [row for row in rows if int(row["performance_repetitions"]) >= 3]
    repeated_speedup = statistics.mean(float(row["speedup"]) for row in repeated)
    repeated_reduction = statistics.mean(float(row["l2i_reduction_pct"]) for row in repeated)
    accepted = [row for row in rows if row["minimum_5pct_met"]]

    lines = [
        "# Corrected-LBR PGO Goal Report",
        "",
        "Generated from the 2026-07-13 campaign artifacts. LBR[0].to is the miss target; older LBR entries are candidate injection sites.",
        "",
        "## Audited results",
        "",
        "| Suite | Benchmark | Metric | Best audited PGO | Speedup | L2I MPKI base -> pref | L2I reduction | n | Policy | Status |",
        "|---|---|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        display = dict(row)
        display.update({
            "speedup": fmt(row["speedup"], 4),
            "speedup_sem": fmt(row["speedup_sem"], 4),
            "base": fmt(row["l2i_mpki_baseline"], 2),
            "pref": fmt(row["l2i_mpki_prefetch"], 2),
            "reduction": fmt(row["l2i_reduction_pct"], 2),
            "reduction_sem": fmt(row["l2i_reduction_sem"], 2),
        })
        lines.append(
            "| {benchmark_suite} | {benchmark} | {performance_metric} | {pgo_variant} | "
            "{speedup}x +/- {speedup_sem} | {base} -> {pref} | {reduction}% +/- {reduction_sem} | "
            "{performance_repetitions} | {target_policy} | {result_status} |".format(**display)
        )

    lines.extend([
        "",
        "## Profile determinism and branch mix",
        "",
        "| Benchmark | Reps | Branch samples | Miss-target samples | Top-10 Jaccard | COND | CALL | RET | IND | IND_CALL | UNCOND |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in rows:
        display = dict(row)
        display["jaccard"] = fmt(row["top10_jaccard"], 3)
        display.update({kind: fmt(row[kind], 2) + "%" for kind in BRANCH_TYPES})
        lines.append(
            "| {benchmark} | {profile_reps} | {lbr_branch_samples} | {lbr_target_samples} | "
            "{jaccard} | {COND} | {CALL} | {RET} | {IND} | {IND_CALL} | {UNCOND} |".format(**display)
        )

    lines.extend([
        "",
        "## Interpretation",
        "",
        f"- Accepted repeated >=5% results: {len(accepted)}/{len(rows)} ({', '.join(str(row['benchmark']) for row in accepted) or 'none'}).",
        f"- Arithmetic mean over repeated rows only: {repeated_speedup:.4f}x speedup and {repeated_reduction:.2f}% L2I MPKI reduction.",
        "- High L2I MPKI is not sufficient for throughput gain. The miss must be on the critical path, the selected history site must be early and specific enough, and prefetch/code-footprint cost must stay below the avoided stall cost.",
        "- Recommend is the clearest counterexample: fixed-work PGO reduces MPKI by 13.54% but changes QPS by only 0.07%.",
        "- HDSearch's positive mean is caused by one execution-mode outlier. It is retained in raw statistics but rejected as a speedup claim.",
        "- Proto arena has deterministic hot targets but a 6,970-cache-line target footprint. Narrow plans cover too little; broad plans pay excessive dynamic and code-footprint overhead.",
        "- memcached's high-MPKI underloaded mode is client/sleep-wake limited. Saturating the service makes the performance metric valid but lowers L2I MPKI to about 1.2.",
        "",
        "## Experimental controls",
        "",
        "- One workload at a time; turbo disabled and benchmark cores fixed at 2.0 GHz.",
        "- Service and client threads are assigned to distinct singleton CPU sets by the campaign pinner.",
        "- Audited runs report zero CPU migrations. Router and SetAlgebra repeated rows additionally enforce matched server-thread counts.",
        "- Coverage 25/50/75/100, history depth, site budgets, and target-only/target+next-line plans were screened before the reported candidates.",
        "- Same-layout prefetch-vs-NOP validation was used where layout sensitivity was observed.",
        "",
        "## Per-benchmark notes",
        "",
    ])
    for row in rows:
        lines.append(f"### {row['benchmark']}")
        lines.append("")
        lines.append(str(row["explanation"]))
        lines.append("")
        lines.append(f"Evidence: `{row['performance_evidence']}`. {row['evidence_note']}")
        lines.append("")

    lines.extend([
        "## Figures",
        "",
        "![Speedup](speedup.png)",
        "",
        "![L2I MPKI reduction](l2i_mpki_reduction.png)",
        "",
    ])
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = build_rows()
    write_csv(OUT / "pgo_results.csv", rows)
    write_csv(
        OUT / "profile_branch_mix.csv",
        [
            {
                field: row[field]
                for field in (
                    "benchmark_suite",
                    "benchmark",
                    "profile_reps",
                    "lbr_branch_samples",
                    "lbr_target_samples",
                    "top10_jaccard",
                    "top10_sample_overlap",
                    *BRANCH_TYPES,
                    "profile_evidence",
                )
            }
            for row in rows
        ],
    )
    plot(rows, "speedup", "speedup_sem", "Throughput/runtime speedup (x)", OUT / "speedup.png")
    plot(
        rows,
        "l2i_reduction_pct",
        "l2i_reduction_sem",
        "L2I MPKI reduction (%)",
        OUT / "l2i_mpki_reduction.png",
    )
    write_report(rows)
    print(OUT)


if __name__ == "__main__":
    main()
