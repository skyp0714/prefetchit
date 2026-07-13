#!/usr/bin/env python3
"""Generate the audited in-progress report for the corrected LBR-PGO campaign."""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "results/data_prefetch_reexperiment_20260712/final_report/updated_final_results.csv"
OLD_BRANCH = ROOT / "results/final_campaign_20260711/final_report/branch_profile_summary.csv"
OTHER = ROOT / "results/final_campaign_20260711/final_report/other_attempted_workloads.csv"
CAMPAIGN = ROOT / "results/pgo_lbr_path_20260712"
OUT = CAMPAIGN / "current_report"

PROFILE_DIRS = {
    "Router": "router_exact",
    "SetAlgebra": "setalgebra_exact",
    "Recommend": "recommend",
    "HDSearch": "hdsearch_clang_exact",
    "memcached": "memcached",
    "PostgreSQL": "postgresql",
}

PGO_UPDATES = {
    "Router": {
        "pgo_screen_speedup": 1.057560,
        "pgo_screen_sem": 0.0632,
        "pgo_mpki_baseline": 140.454043,
        "pgo_mpki_prefetch": 132.365044,
        "pgo_mpki_reduction_pct": 5.759178,
        "pgo_variant": "cov100, depth 1-32, budget 16, target+next",
        "pgo_status": "invalid: n=2, variable gRPC worker count / throughput mode",
        "pgo_evidence": "results/pgo_lbr_path_20260712/screens/router_pinnerfix_recheck/screen_summary.csv",
    },
    "SetAlgebra": {
        "pgo_screen_speedup": 1.031375,
        "pgo_screen_sem": math.nan,
        "pgo_mpki_baseline": 119.312085,
        "pgo_mpki_prefetch": 114.658916,
        "pgo_mpki_reduction_pct": 3.899998,
        "pgo_variant": "cov25, depth 1-32, budget 16, target-only",
        "pgo_status": "provisional: exploratory n=1; repeat not promoted",
        "pgo_evidence": "results/pgo_lbr_path_20260712/screens/setalgebra_cov_offset_v3/screen_summary.csv",
    },
    "Recommend": {
        "pgo_screen_speedup": 1.0608049,
        "pgo_screen_sem": 0.0356122,
        "pgo_mpki_baseline": 82.985768,
        "pgo_mpki_prefetch": 72.751684,
        "pgo_mpki_reduction_pct": 12.332337,
        "pgo_variant": "cov100, depth 1-32, budget 16, target-only",
        "pgo_status": "accepted upper bound: candidate n=5, baseline n=6",
        "pgo_evidence": "results/pgo_lbr_path_20260712/screens/recommend_cov100_n5/screen_summary.csv",
    },
    "HDSearch": {
        "pgo_screen_speedup": 1.085530,
        "pgo_screen_sem": 0.0508551,
        "pgo_mpki_baseline": 47.977059,
        "pgo_mpki_prefetch": 44.945456,
        "pgo_mpki_reduction_pct": 6.318859,
        "pgo_variant": "cov50, depth 1-32, budget 16, target-only",
        "pgo_status": "provisional: high variance before deterministic query reset",
        "pgo_evidence": "results/pgo_lbr_path_20260712/screens/hdsearch_cap1_pgo_n3/screen_summary.csv",
    },
    "memcached": {
        "pgo_screen_speedup": 1.004315,
        "pgo_screen_sem": math.nan,
        "pgo_mpki_baseline": 7.945000,
        "pgo_mpki_prefetch": 7.455270,
        "pgo_mpki_reduction_pct": 6.164,
        "pgo_variant": "cov75, depth 1-32, budget 16, target-only",
        "pgo_status": "provisional: exploratory n=1; cov100 reduced MPKI but hurt QPS",
        "pgo_evidence": "results/pgo_lbr_path_20260712/screens/memcached_cov_offset/screen_summary.csv",
    },
    "PostgreSQL": {
        "pgo_screen_speedup": math.nan,
        "pgo_screen_sem": math.nan,
        "pgo_mpki_baseline": math.nan,
        "pgo_mpki_prefetch": math.nan,
        "pgo_mpki_reduction_pct": math.nan,
        "pgo_variant": "40-plan cov25/50/75/100, budget 4/8/16/32, target-only/+next matrix",
        "pgo_status": "matrix complete with layout-matched DWARF companion; performance pending",
        "pgo_evidence": "results/pgo_lbr_path_20260712/matrices/postgresql/audit_summary.json",
    },
}

RESULT_STATUS = {
    "FeedSim": "accepted repeated",
    "Django": "accepted repeated",
    "Router": "accepted repeated manual; below 10% and CI includes 1.0",
    "SetAlgebra": "accepted repeated manual; below 10% and CI includes 1.0",
    "Recommend": "static result negative; corrected PGO upper bound accepted, static retune pending",
    "HDSearch": "manual rejected for mode instability; deterministic PGO confirmation pending",
    "Chipyard qsort": "accepted existing repeated result",
    "memcached": "accepted repeated manual is neutral; corrected PGO screen provisional",
    "PostgreSQL": "manual screen neutral; corrected PGO work in progress",
    "Redis": "low-MPKI exploratory result; not promoted",
}

GRAPH_ORDER = [
    "FeedSim", "Django", "Router", "SetAlgebra", "Recommend", "HDSearch",
    "Chipyard qsort", "memcached", "PostgreSQL",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def number(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def finite(value: object) -> bool:
    return math.isfinite(number(value))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_branch_profiles() -> dict[str, dict[str, object]]:
    profiles: dict[str, dict[str, object]] = {}
    for row in read_csv(OLD_BRANCH):
        profiles[row["benchmark"]] = {
            "benchmark": row["benchmark"],
            "profile_reps": row["profile_reps"],
            "lbr_samples": row["lbr_samples"],
            "lbr_target_samples": "",
            "top10_jaccard": row["top10_jaccard"],
            "top10_sample_overlap": row["top10_sample_overlap"],
            **{kind: row[kind] for kind in ["COND", "CALL", "RET", "IND", "IND_CALL", "UNCOND"]},
            "profile_evidence": "results/final_campaign_20260711/final_report/branch_profile_summary.csv",
        }

    for benchmark, directory in PROFILE_DIRS.items():
        base = CAMPAIGN / "profiles" / directory / "repetition_summary"
        with (base / "summary.json").open(encoding="utf-8") as handle:
            summary = json.load(handle)
        ratios = {
            row["branch_type"]: row["ratio_pct"]
            for row in read_csv(base / "branch_type_summary.csv")
        }
        profiles[benchmark] = {
            "benchmark": benchmark,
            "profile_reps": summary["rep_count"],
            "lbr_samples": summary["branch_samples"],
            "lbr_target_samples": summary["target_samples"],
            "top10_jaccard": summary["top10_mean_jaccard"],
            "top10_sample_overlap": summary["top10_mean_sample_overlap"],
            **{kind: number(ratios.get(kind)) for kind in ["COND", "CALL", "RET", "IND", "IND_CALL", "UNCOND"]},
            "profile_evidence": str(base.relative_to(ROOT) / "summary.json"),
        }
    return profiles


def extra_rows() -> list[dict[str, object]]:
    rows = []
    for source in read_csv(OTHER):
        rows.append({
            "benchmark_suite": source["suite"],
            "benchmark": source["benchmark"],
            "injection_method": "manual" if "manual" in source["method"] else "N/A",
            "speedup": source["speedup"],
            "speedup_sem": "",
            "pgo_speedup": "",
            "code_line_change": "",
            "l2i_mpki_baseline": source["base_mpki"],
            "l2i_mpki_prefetch": source["pref_mpki"],
            "l2i_reduction_pct": (
                100.0 * (number(source["base_mpki"]) - number(source["pref_mpki"]))
                / number(source["base_mpki"])
                if finite(source["base_mpki"]) and number(source["base_mpki"]) != 0 else ""
            ),
            "l2i_reduction_sem": "",
            "target_policy": source["method"],
            "reason_cannot_inject": source["status"],
            "code_change_explanation": "",
            "confidence": "outside agreed final suite; retained for completeness",
            "evidence": source["evidence"],
            "include_graph": "False",
            "result_status": source["status"],
        })
    return rows


def build_results() -> list[dict[str, object]]:
    profiles = load_branch_profiles()
    rows: list[dict[str, object]] = [dict(row) for row in read_csv(BASE)]
    rows.extend(extra_rows())
    for row in rows:
        benchmark = str(row["benchmark"])
        row["injection_method"] = row.get("injection_method") or "N/A"
        row["result_status"] = RESULT_STATUS.get(
            benchmark,
            row.get("reason_cannot_inject") or row.get("data_prefetch_status") or "screened",
        )
        row["pgo_screen_speedup"] = ""
        row["pgo_screen_sem"] = ""
        row["pgo_mpki_baseline"] = ""
        row["pgo_mpki_prefetch"] = ""
        row["pgo_mpki_reduction_pct"] = ""
        row["pgo_variant"] = ""
        row["pgo_status"] = ""
        row["pgo_evidence"] = ""
        if benchmark in PGO_UPDATES:
            row.update(PGO_UPDATES[benchmark])
        if benchmark == "Recommend":
            row["pgo_speedup"] = PGO_UPDATES[benchmark]["pgo_screen_speedup"]
        if benchmark in profiles:
            row.update(profiles[benchmark])
        else:
            for field in [
                "profile_reps", "lbr_samples", "lbr_target_samples", "top10_jaccard",
                "top10_sample_overlap", "COND", "CALL", "RET", "IND", "IND_CALL",
                "UNCOND", "profile_evidence",
            ]:
                row.setdefault(field, "")
    return rows


def coverage_from_aggregate(path: Path, benchmark: str, status: str) -> list[dict[str, object]]:
    rows = []
    for source in read_csv(path):
        label = source["label"]
        match = re.search(r"cov(\d+)_d(.+)_b(\d+)_o(\d+)$", label)
        rows.append({
            "benchmark": benchmark,
            "label": label,
            "coverage_pct": match.group(1) if match else "",
            "history_depth": match.group(2).replace("_", "-") if match else "",
            "site_budget": match.group(3) if match else "",
            "target_policy": "target+next" if match and int(match.group(4)) else "target-only",
            "n": source["n"],
            "qps_mean": source["qps_mean"],
            "qps_stdev": source["qps_stdev"],
            "speedup": source["speedup"],
            "l2i_mpki": source["l2i_mpki_mean"],
            "l2i_mpki_stdev": source["l2i_mpki_stdev"],
            "l2i_reduction_pct": source["l2i_reduction_pct"],
            "evidence_status": "accepted baseline" if label == "baseline" else status,
            "evidence": str(path.relative_to(ROOT)),
        })
    return rows


def build_coverage_details() -> list[dict[str, object]]:
    screens = CAMPAIGN / "screens"
    cases = [
        ("Router", "router_pinnerfix_recheck/screen_summary.csv", "invalid: worker-count mode confound"),
        ("SetAlgebra", "setalgebra_cov_offset_v3/screen_summary.csv", "exploratory n=1"),
        ("Recommend", "recommend_cov_offset/screen_summary.csv", "exploratory n=1"),
        ("Recommend", "recommend_cov100_n5/screen_summary.csv", "accepted repeat"),
        ("HDSearch", "hdsearch_cov_offset/screen_summary.csv", "invalid: time-based query stream"),
        ("HDSearch", "hdsearch_cap1_pgo_n3/screen_summary.csv", "provisional: high variance"),
        ("HDSearch", "hdsearch_deterministic_baseline_n3/screen_summary.csv", "accepted baseline only"),
    ]
    rows: list[dict[str, object]] = []
    for benchmark, relative, status in cases:
        rows.extend(coverage_from_aggregate(screens / relative, benchmark, status))

    path = screens / "memcached_cov_offset/screen_summary.csv"
    source_rows = read_csv(path)
    baselines = [number(row["qps"]) for row in source_rows if "baseline" in row["label"]]
    base_qps = statistics.mean(baselines)
    base_mpkis = [number(row["l2i_mpki"]) for row in source_rows if "baseline" in row["label"]]
    base_mpki = statistics.mean(base_mpkis)
    for source in source_rows:
        label = source["label"].split("_", 1)[-1]
        match = re.search(r"cov(\d+)_d(.+)_b(\d+)_o(\d+)$", label)
        rows.append({
            "benchmark": "memcached",
            "label": label,
            "coverage_pct": match.group(1) if match else "",
            "history_depth": match.group(2).replace("_", "-") if match else "",
            "site_budget": match.group(3) if match else "",
            "target_policy": "target+next" if match and int(match.group(4)) else "target-only",
            "n": 1,
            "qps_mean": source["qps"],
            "qps_stdev": "",
            "speedup": number(source["qps"]) / base_qps,
            "l2i_mpki": source["l2i_mpki"],
            "l2i_mpki_stdev": "",
            "l2i_reduction_pct": 100.0 * (base_mpki - number(source["l2i_mpki"])) / base_mpki,
            "evidence_status": "accepted baseline" if "baseline" in label else "exploratory n=1",
            "evidence": str(path.relative_to(ROOT)),
        })
    return rows


def build_plan_audit() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for benchmark, directory in PROFILE_DIRS.items():
        path = CAMPAIGN / "matrices" / directory.replace("_exact", "") / "audit_summary.json"
        if not path.exists():
            path = CAMPAIGN / "matrices" / benchmark.lower() / "audit_summary.json"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            audit = json.load(handle)
        for coverage in [25, 50, 75, 100]:
            item = audit.get(f"cov{coverage}")
            if not item:
                continue
            internal = item["internal"]
            external = item["external"]
            combined = item["combined"]
            rows.append({
                "benchmark": benchmark,
                "coverage_pct": coverage,
                "internal_targets": internal.get("selected_targets", 0),
                "internal_targets_with_injections": internal.get("selected_targets_with_injections", 0),
                "internal_source_resolved_sites": internal.get("candidate_sites_after_source_resolution", 0),
                "internal_injections": internal.get("selected_injections", 0),
                "external_targets": external.get("selected_targets", 0),
                "external_injections": external.get("selected_injections", 0),
                "combined_targets": combined.get("selected_targets", 0),
                "combined_injections": combined.get("selected_injections", 0),
                "selected_site_dynamic_coverage_pct": internal.get("selected_site_dynamic_coverage_pct", ""),
                "evidence": str(path.relative_to(ROOT)),
            })
    return rows


def plot(rows: list[dict[str, object]], metric: str, error: str, ylabel: str, filename: str) -> None:
    by_name = {str(row["benchmark"]): row for row in rows}
    selected = [by_name[name] for name in GRAPH_ORDER]
    positions = list(range(len(selected)))
    values = [number(row[metric]) for row in selected]
    errors = [number(row.get(error)) if finite(row.get(error)) else 0.0 for row in selected]
    colors = {"manual": "#2878B5", "static": "#E68632", "both": "#4C9F70", "N/A": "#A7A7A7"}

    fig, ax = plt.subplots(figsize=(14.2, 5.8), constrained_layout=True)
    bars = ax.bar(
        positions,
        values,
        yerr=errors,
        capsize=4,
        color=[colors.get(str(row["injection_method"]), "#A7A7A7") for row in selected],
        edgecolor="#252525",
        linewidth=0.8,
    )
    for bar, row in zip(bars, selected):
        if any(word in str(row["result_status"]) for word in ["rejected", "pending", "negative", "progress"]):
            bar.set_hatch("//")

    if metric == "speedup":
        for index, row in enumerate(selected):
            value = number(row.get("pgo_screen_speedup"))
            if not math.isfinite(value) and row["benchmark"] == "Chipyard qsort":
                value = number(row.get("pgo_speedup"))
            if not math.isfinite(value):
                continue
            accepted = str(row.get("pgo_status", "")).startswith("accepted") or row["benchmark"] == "Chipyard qsort"
            ax.scatter(
                index,
                value,
                s=58,
                marker="o" if accepted else "D",
                facecolors="#C73E3A" if accepted else "white",
                edgecolors="#C73E3A",
                linewidths=1.4,
                zorder=5,
            )
            sem = number(row.get("pgo_screen_sem"))
            if math.isfinite(sem):
                ax.errorbar(index, value, yerr=sem, color="#C73E3A", capsize=3, linewidth=1.0, zorder=4)
    else:
        for index, row in enumerate(selected):
            value = number(row.get("pgo_mpki_reduction_pct"))
            if not math.isfinite(value):
                continue
            accepted = str(row.get("pgo_status", "")).startswith("accepted")
            ax.scatter(
                index,
                value,
                s=58,
                marker="o" if accepted else "D",
                facecolors="#C73E3A" if accepted else "white",
                edgecolors="#C73E3A",
                linewidths=1.4,
                zorder=5,
            )

    ax.axhline(1.0 if metric == "speedup" else 0.0, color="#555555", linewidth=1.0)
    labels = [f'{row["benchmark_suite"]}\n{row["benchmark"]}' for row in selected]
    ax.set_xticks(positions, labels, rotation=20, ha="right")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", color="#D7D7D7", linewidth=0.7)
    ax.set_axisbelow(True)
    handles = [
        Patch(facecolor=colors["manual"], edgecolor="#252525", label="Manual control/data-flow"),
        Patch(facecolor=colors["static"], edgecolor="#252525", label="Static compiler"),
        Patch(facecolor="white", edgecolor="#252525", hatch="//", label="Negative/rejected/pending bar"),
        Line2D([], [], marker="o", markerfacecolor="#C73E3A", markeredgecolor="#C73E3A", linestyle="", label="Accepted PGO"),
        Line2D([], [], marker="D", markerfacecolor="white", markeredgecolor="#C73E3A", linestyle="", label="Provisional/invalid PGO screen"),
    ]
    ax.legend(handles=handles, frameon=False, ncol=2, loc="best")
    fig.savefig(OUT / filename, dpi=220)
    fig.savefig(OUT / filename.replace(".png", ".svg"))
    plt.close(fig)


def fmt(value: object, digits: int = 3, suffix: str = "") -> str:
    return f"{number(value):.{digits}f}{suffix}" if finite(value) else "-"


def write_report(
    rows: list[dict[str, object]],
    coverage: list[dict[str, object]],
    plan_audit: list[dict[str, object]],
) -> None:
    table = [
        "| suite | benchmark | method | speedup | PGO speedup | lines | L2I MPKI base -> pref | target policy | cannot inject / status | manual code change |",
        "|---|---|---|---:|---:|---:|---:|---|---|---|",
    ]
    for row in rows:
        pgo = row.get("pgo_speedup") if row["injection_method"] == "static" else ""
        reason = row.get("reason_cannot_inject") or row.get("result_status") or ""
        table.append(
            f'| {row["benchmark_suite"]} | {row["benchmark"]} | {row["injection_method"]} | '
            f'{fmt(row.get("speedup"), 3, "x")} | {fmt(pgo, 3, "x")} | '
            f'{fmt(row.get("code_line_change"), 0)} | '
            f'{fmt(row.get("l2i_mpki_baseline"))} -> {fmt(row.get("l2i_mpki_prefetch"))} | '
            f'{row.get("target_policy") or "-"} | {str(reason).replace("|", "/")} | '
            f'{str(row.get("code_change_explanation") or "-").replace("|", "/")} |'
        )

    corrected = [row for row in rows if row["benchmark"] in PGO_UPDATES]
    pgo_table = [
        "| benchmark | profiles | LBR branch / target samples | top-10 Jaccard / weighted overlap | branch mix COND/CALL/RET/IND/IND_CALL/UNCOND (%) | best corrected PGO | L2I reduction | status |",
        "|---|---:|---:|---:|---|---:|---:|---|",
    ]
    for row in corrected:
        branch_mix = "/".join(fmt(row.get(kind), 1) for kind in ["COND", "CALL", "RET", "IND", "IND_CALL", "UNCOND"])
        pgo_table.append(
            f'| {row["benchmark"]} | {fmt(row.get("profile_reps"), 0)} | '
            f'{fmt(row.get("lbr_samples"), 0)} / {fmt(row.get("lbr_target_samples"), 0)} | '
            f'{fmt(row.get("top10_jaccard"))} / {fmt(row.get("top10_sample_overlap"))} | '
            f'{branch_mix} | {fmt(row.get("pgo_screen_speedup"), 3, "x")} | '
            f'{fmt(row.get("pgo_mpki_reduction_pct"), 2, "%")} | {row.get("pgo_status")} |'
        )

    plan_by_benchmark: dict[str, list[dict[str, object]]] = {}
    for row in plan_audit:
        plan_by_benchmark.setdefault(str(row["benchmark"]), []).append(row)
    plan_table = [
        "| benchmark | combined targets at 25/50/75/100% | combined injections at 25/50/75/100% | source-resolved sites at 100% |",
        "|---|---:|---:|---:|",
    ]
    for benchmark in ["Router", "SetAlgebra", "Recommend", "HDSearch", "memcached", "PostgreSQL"]:
        items = sorted(plan_by_benchmark.get(benchmark, []), key=lambda item: int(item["coverage_pct"]))
        if not items:
            continue
        targets = "/".join(str(item["combined_targets"]) for item in items)
        injections = "/".join(str(item["combined_injections"]) for item in items)
        plan_table.append(
            f'| {benchmark} | {targets} | {injections} | {items[-1]["internal_source_resolved_sites"]} |'
        )

    accepted = [
        row for row in rows
        if row["benchmark"] in {"FeedSim", "Django", "Router", "SetAlgebra", "Chipyard qsort", "memcached"}
    ]
    mean_speedup = statistics.mean(number(row["speedup"]) for row in accepted)
    mean_reduction = statistics.mean(number(row["l2i_reduction_pct"]) for row in accepted)
    report = f"""# Corrected LBR-PGO Campaign: Current Audited State

Date: 2026-07-12

## Goal state

The goal API reports only `status=blocked`; it contains no blocker reason. CPU pinning, frequency control, builds, profiling, and disk capacity are operational. The API refuses a replacement goal while this blocked goal remains unfinished, so this is a goal-state bookkeeping block rather than an experiment block.

## Evidence policy

- Solid bars are repeated implementation results. Hatched bars are negative, rejected, or still pending.
- Filled red circles are repeated PGO upper bounds. Hollow red diamonds are single-screen or confounded PGO values and are not performance claims.
- Every retained profile used fixed 2.0 GHz settings, disjoint core sets, singleton affinity per thread, one workload at a time, and no runtime repinning during the measurement interval.
- Raw `cpu-migrations` from pthread creation placement is not treated as execution migration; any correction after `MEASUREMENT_START` invalidates a run.

## Requested complete table

{chr(10).join(table)}

## Corrected newest-LBR PGO audit

`LBR[0].to` is the sampled L2I miss target. Older `LBR[d].from` addresses are candidate injection sites.

{chr(10).join(pgo_table)}

## PGO plan size audit

{chr(10).join(plan_table)}

The complete {len(coverage)}-row coverage/offset screen, including every baseline and 25/50/75/100 target-only/target+next candidate that has run, is in `pgo_coverage_details.csv`.
The complete {len(plan_audit)}-row plan audit, including internal/DSO/combined target and injection counts at each coverage, is in `pgo_plan_summary.csv`.

## Current arithmetic summary

Across the six repeated implementation rows currently eligible for a bar (FeedSim, Django, Router, SetAlgebra, Verilator, and memcached), arithmetic mean speedup is **{mean_speedup:.3f}x** and mean L2I-MPKI reduction is **{mean_reduction:.2f}%**. This heterogeneous-workload average is descriptive, not a confidence-weighted estimator.

Recommend is the only newly corrected MicroSuite PGO result promoted so far: **1.061x** over five candidate and six baseline runs, with **12.33%** lower L2I MPKI. Router's 1.058x, SetAlgebra's 1.031x, HDSearch's 1.086x, and memcached's 1.004x are retained as provisional/invalid screens for transparency. PostgreSQL has three valid profiles and a complete corrected plan matrix, but no corrected injection performance result yet. Its original `-g0` baseline resolved zero source sites; a DWARF companion with matching `.text` address/size and text-symbol map restored 3,111 source-resolved sites already at 25% coverage.

## Artifacts

- `current_results.csv`: all final-suite rows plus FleetBench, HAProxy, and DeathStarBench attempts.
- `branch_profile_summary.csv`: prior and corrected profile determinism and branch-type ratios.
- `pgo_coverage_details.csv`: every corrected PGO screen row and validity status.
- `pgo_plan_summary.csv`: coverage-wise target, source-resolution, and injection counts.
- `current_speedup.png` / `.svg`: speedup bars and accepted/provisional PGO markers.
- `current_l2i_reduction.png` / `.svg`: positive-is-good L2I-MPKI reduction.
"""
    (OUT / "current_report.md").write_text(report, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = build_results()
    coverage = build_coverage_details()
    plan_audit = build_plan_audit()
    write_csv(OUT / "current_results.csv", rows)
    write_csv(OUT / "branch_profile_summary.csv", list(load_branch_profiles().values()))
    write_csv(OUT / "pgo_coverage_details.csv", coverage)
    write_csv(OUT / "pgo_plan_summary.csv", plan_audit)
    plot(rows, "speedup", "speedup_sem", "Speedup (x)", "current_speedup.png")
    plot(rows, "l2i_reduction_pct", "l2i_reduction_sem", "L2I MPKI reduction (%)", "current_l2i_reduction.png")
    write_report(rows, coverage, plan_audit)
    print(OUT)


if __name__ == "__main__":
    main()
