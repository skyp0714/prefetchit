#!/usr/bin/env python3
"""Generate the final audited prefetch campaign table, plots, and report."""

from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
FINAL = RESULTS / "final_campaign_20260711"
OUT = FINAL / "final_report"

OTHER_ATTEMPTS = [
    {
        "suite": "FleetBench",
        "benchmark": "Proto arena",
        "method": "manual/static source",
        "speedup": 1.0109213158,
        "base_mpki": 17.958980,
        "pref_mpki": 17.896055,
        "status": "single-run small positive; outside the agreed final suite set",
        "evidence": "datacenter_goal_20260708/fleet_proto_static_sweep/summary.csv",
    },
    {
        "suite": "Standalone service",
        "benchmark": "HAProxy",
        "method": "manual",
        "speedup": 1.0010480669,
        "base_mpki": 3.367791,
        "pref_mpki": 4.183963,
        "status": "neutral",
        "evidence": "datacenter_goal_20260708/haproxy_taskpf_real_r200k_120s/summary.csv",
    },
    {
        "suite": "DeathStarBench",
        "benchmark": "UrlShorten",
        "method": "manual",
        "speedup": 0.959,
        "base_mpki": None,
        "pref_mpki": None,
        "status": "negative dispatch-prefetch smoke result; not promoted",
        "evidence": "datacenter_goal_20260708/dsb_url_eval_smoke/summary.csv",
    },
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stats(values: list[float]) -> tuple[float, float]:
    mean = statistics.mean(values)
    sem = statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return mean, sem


def paired_tailbench(dirname: str) -> dict[str, float]:
    root = FINAL / dirname
    base = [read_json(root / f"baseline_r{i}" / "summary.json") for i in range(1, 4)]
    pref = [read_json(root / f"manual_r{i}" / "summary.json") for i in range(1, 4)]
    speedups = [pref[i]["derived_qps"] / base[i]["derived_qps"] for i in range(3)]
    reductions = [
        100.0 * (base[i]["l2i_mpki"] - pref[i]["l2i_mpki"]) / base[i]["l2i_mpki"]
        for i in range(3)
    ]
    speedup, speedup_sem = stats(speedups)
    reduction, reduction_sem = stats(reductions)
    return {
        "speedup": speedup,
        "speedup_sem": speedup_sem,
        "base_mpki": statistics.mean(row["l2i_mpki"] for row in base),
        "pref_mpki": statistics.mean(row["l2i_mpki"] for row in pref),
        "reduction": reduction,
        "reduction_sem": reduction_sem,
    }


def feed_stats() -> dict[str, float]:
    rows = list(
        csv.DictReader(
            (FINAL / "feedsim_seed2_fixed2ghz_c4_final_rep3" / "runs.csv").open()
        )
    )
    pairs: dict[int, dict[str, dict]] = {}
    for row in rows:
        if row["label"] == "seed2_base":
            pairs.setdefault(int(row["rep"]), {})["base"] = row
        elif row["label"] == "seed2_d16_target_next":
            pairs.setdefault(int(row["rep"]), {})["pref"] = row
    speedups = []
    qps_speedups = []
    reductions = []
    base_mpki = []
    pref_mpki = []
    for pair in pairs.values():
        base_qps = float(pair["base"]["completed_qps"])
        pref_qps = float(pair["pref"]["completed_qps"])
        base_latency = float(pair["base"]["avg_ms"])
        pref_latency = float(pair["pref"]["avg_ms"])
        base_l2 = float(pair["base"]["l2i_mpki"])
        pref_l2 = float(pair["pref"]["l2i_mpki"])
        speedups.append(base_latency / pref_latency)
        qps_speedups.append(pref_qps / base_qps)
        reductions.append(100.0 * (base_l2 - pref_l2) / base_l2)
        base_mpki.append(base_l2)
        pref_mpki.append(pref_l2)
    speedup, speedup_sem = stats(speedups)
    reduction, reduction_sem = stats(reductions)
    return {
        "speedup": speedup,
        "speedup_sem": speedup_sem,
        "qps_speedup": statistics.mean(qps_speedups),
        "base_mpki": statistics.mean(base_mpki),
        "pref_mpki": statistics.mean(pref_mpki),
        "reduction": reduction,
        "reduction_sem": reduction_sem,
    }


def row(
    suite: str,
    benchmark: str,
    method: str,
    *,
    speedup: float | None = None,
    speedup_sem: float = 0.0,
    pgo_speedup: float | None = None,
    lines: int | None = None,
    base_mpki: float | None = None,
    pref_mpki: float | None = None,
    reduction: float | None = None,
    reduction_sem: float = 0.0,
    policy: str = "N/A",
    reason: str = "",
    explanation: str = "",
    confidence: str = "screen",
    evidence: str = "",
    graph: bool = False,
) -> dict:
    if reduction is None and base_mpki is not None and pref_mpki is not None and base_mpki:
        reduction = 100.0 * (base_mpki - pref_mpki) / base_mpki
    return {
        "benchmark_suite": suite,
        "benchmark": benchmark,
        "injection_method": method,
        "speedup": speedup,
        "speedup_sem": speedup_sem,
        "pgo_speedup": pgo_speedup,
        "code_line_change": lines,
        "l2i_mpki_baseline": base_mpki,
        "l2i_mpki_prefetch": pref_mpki,
        "l2i_reduction_pct": reduction,
        "l2i_reduction_sem": reduction_sem,
        "target_policy": policy,
        "reason_cannot_inject": reason,
        "code_change_explanation": explanation,
        "confidence": confidence,
        "evidence": evidence,
        "include_graph": graph,
    }


def build_rows() -> list[dict]:
    feed = feed_stats()
    django = read_json(
        FINAL
        / "django_d4next_fixed2ghz_preload_warm90_final_rep3"
        / "paired_summary.json"
    )
    set_static = read_json(
        FINAL / "microsuite_set_stable_v2_static_top4_final_rep3" / "paired_summary.json"
    )
    set_pgo = read_json(
        FINAL / "microsuite_set_stable_v2_pgo_policy_final_rep3" / "paired_summary.json"
    )
    rec_base = read_json(FINAL / "microsuite_recommend_strict_screen" / "baseline" / "summary.json")
    rec_static = read_json(FINAL / "microsuite_recommend_strict_screen" / "static" / "summary.json")
    rec_pgo = read_json(FINAL / "microsuite_recommend_strict_screen" / "pgo50" / "summary.json")
    xapian = paired_tailbench("tailbench_xapian_cf8_o064_final_rep3")
    moses = paired_tailbench("tailbench_moses_cf8_o0_final_rep3")
    memcached = read_json(FINAL / "memcached_manual_strict_c2048_rep3_v2" / "paired_summary.json")
    pg_base = read_json(FINAL / "postgres_expr_func_concurrency_screen/c16/baseline/summary.json")
    pg_manual = read_json(FINAL / "postgres_expr_func_concurrency_screen/c16/expr_func/summary.json")
    pg_pgo_base = read_json(FINAL / "postgres_strict_baseline_30s_backendonly/summary.json")
    pg_pgo = read_json(FINAL / "postgres_strict_pgo25_30s/summary.json")

    verilator_rows = {
        item["variant"]: item
        for item in csv.DictReader(
            (RESULTS / "static_cond_autotune/static_cond_autotune_20260628_212242/summary.csv").open()
        )
    }
    ver = verilator_rows["static_gap100k_cur0_skip"]
    ver_base = verilator_rows["baseline"]
    ver_pgo = verilator_rows["pgo_cond_cov50"]
    ver_speed = 1.0 + float(ver["speedup_pct"]) / 100.0
    ver_pgo_speed = 1.0 + float(ver_pgo["speedup_pct"]) / 100.0

    rows = [
        row(
            "DCPerf", "FeedSim", "manual", speedup=feed["speedup"],
            speedup_sem=feed["speedup_sem"], lines=4, base_mpki=feed["base_mpki"],
            pref_mpki=feed["pref_mpki"], reduction=feed["reduction"],
            reduction_sem=feed["reduction_sem"], policy="target+next line, depth 16",
            explanation=(
                "Prefetch the future function target stored in the permuted methods_ vector "
                f"and its +64 B line; completed-QPS reference is {feed['qps_speedup']:.3f}x."
            ),
            confidence="3 paired x 120 s, fixed 2.0 GHz, migration=0",
            evidence="final_campaign_20260711/feedsim_seed2_fixed2ghz_c4_final_rep3/runs.csv",
            graph=True,
        ),
        row(
            "DCPerf", "Django", "manual", speedup=django["speedup_mean"],
            speedup_sem=django["speedup_sem"], lines=4,
            base_mpki=django["baseline_mpki_mean"], pref_mpki=django["prefetch_mpki_mean"],
            reduction=django["l2i_reduction_pct_mean"],
            reduction_sem=django["l2i_reduction_pct_sem"], policy="target+next line, depth 4",
            explanation="Prefetch the future ICacheBuster methods_ function pointer and its +64 B line.",
            confidence="3 paired HTTP runs, 90 s warmup, fixed 2.0 GHz, migration=0",
            evidence=(
                "final_campaign_20260711/"
                "django_d4next_fixed2ghz_preload_warm90_final_rep3/paired_summary.json"
            ),
            graph=True,
        ),
        row("DCPerf", "TAO Bench", "N/A", base_mpki=0.362,
            reason="Maximum valid native screen was only 0.362 L2I MPKI.",
            confidence="single-core exclusion screen",
            evidence="dcperf_screening_20260706/official_rootless_single_core/summary.md"),
        row("DCPerf", "Video Transcode", "N/A", base_mpki=0.752,
            reason="SVT level-13 was only 0.752 L2I MPKI; x264 was 0.348.",
            confidence="exclusion screen", evidence="datacenter_goal_20260708/video_transcode_l2_screen/summary.csv"),
        row("DCPerf", "WDL lzbench", "N/A", base_mpki=0.043,
            reason="Highest completed WDL subtest was only 0.043 L2I MPKI.",
            confidence="exclusion screen",
            evidence="datacenter_goal_20260708/wdl_lzbench_dickens_algo_l2_screen/runs.csv"),
        row("DCPerf", "MediaWiki", "N/A",
            reason="HHVM/JIT generates hot code at runtime, outside the native LLVM pass."),
        row("DCPerf", "SparkBench", "N/A", reason="JVM workload; intentionally not profiled or patched."),

        row("MicroSuite", "Router", "static", pgo_speedup=3086.0 / 3087.0,
            base_mpki=115.6615, reason="Static runs were not validity-clean: asynchronous gRPC executor threads were created during the ROI. PGO was neutral.",
            policy="target-only", confidence="PGO valid; static invalidated",
            evidence="final_campaign_20260711/microsuite_strict/router_pgo100/summary.json"),
        row(
            "MicroSuite", "SetAlgebra", "static", speedup=set_static["speedup"]["mean"],
            speedup_sem=set_static["speedup"]["sem"], pgo_speedup=set_pgo["speedup"]["mean"],
            base_mpki=set_static["baseline_l2i_mpki"]["mean"],
            pref_mpki=set_static["prefetch_l2i_mpki"]["mean"],
            reduction=set_static["l2i_reduction_pct"]["mean"],
            reduction_sem=set_static["l2i_reduction_pct"]["sem"], policy="target-only, static top-4",
            explanation="General-v5 structural branch-target plan; no source-level manual change.",
            confidence="3 paired strict runs, migration=0",
            evidence="final_campaign_20260711/microsuite_set_stable_v2_static_top4_final_rep3/paired_summary.json",
        ),
        row(
            "MicroSuite", "Recommend", "static", speedup=rec_static["qps"] / rec_base["qps"],
            pgo_speedup=rec_pgo["qps"] / rec_base["qps"], base_mpki=rec_base["l2i_mpki"],
            pref_mpki=rec_static["l2i_mpki"], policy="target-only",
            explanation="Static service-body target plan; no source-level manual change.",
            confidence="negative strict screen; no repeat promoted",
            evidence="final_campaign_20260711/microsuite_recommend_strict_screen",
        ),
        row("MicroSuite", "HDSearch", "N/A", base_mpki=85.273,
            reason="Load generator produced failed responses in baseline and injected runs; throughput comparison is invalid.",
            confidence="excluded for workload correctness",
            evidence="datacenter_goal_20260708/hdsearch_pgo_eval_w8_rep23_120s/summary.csv"),

        row(
            "TailBench", "xapian", "manual", speedup=xapian["speedup"],
            speedup_sem=xapian["speedup_sem"], lines=41, base_mpki=xapian["base_mpki"],
            pref_mpki=xapian["pref_mpki"], reduction=xapian["reduction"],
            reduction_sem=xapian["reduction_sem"], policy="target+next line, depth 8",
            explanation="Prefetch BranchPostList/PostList/SubMatch polymorphic control objects before virtual dispatch.",
            confidence="3 paired saturation runs, migration=0",
            evidence="final_campaign_20260711/tailbench_xapian_cf8_o064_final_rep3",
        ),
        row("TailBench", "img-dnn", "N/A", base_mpki=1.093,
            reason="25/50/75/100% PGO sweep was performance-neutral; no useful static upper bound.",
            confidence="5-profile coverage screen",
            evidence="tailbench_rtc_pgo_20260706_s10k_r5/summary.md"),
        row(
            "TailBench", "moses", "manual", speedup=moses["speedup"],
            speedup_sem=moses["speedup_sem"], lines=43, base_mpki=moses["base_mpki"],
            pref_mpki=moses["pref_mpki"], reduction=moses["reduction"],
            reduction_sem=moses["reduction_sem"], policy="target-only, depth 8",
            explanation="Prefetch DecodeStep and feature-function objects held in decoder vectors before virtual calls.",
            confidence="3 paired saturation runs, migration=0",
            evidence="final_campaign_20260711/tailbench_moses_cf8_o0_final_rep3",
        ),
        row("TailBench", "sphinx", "N/A", base_mpki=0.021,
            reason="Very low L2I MPKI; all PGO coverages were neutral.",
            confidence="5-profile coverage screen", evidence="tailbench_rtc_pgo_20260706_s10k_r5/summary.md"),
        row("TailBench", "masstree", "N/A", base_mpki=3.859,
            reason="PGO reduced MPKI as far as 2.713 but did not improve completed runtime/QPS.",
            confidence="5-profile coverage screen", evidence="tailbench_rtc_pgo_20260706_s10k_r5/summary.md"),
        row("TailBench", "silo", "N/A", base_mpki=11.579,
            reason="Strict fixed-work PGO was neutral; aggressive target+next reduced MPKI but slowed runtime.",
            confidence="strict saturation screen, migration=0",
            evidence="final_campaign_20260711/tailbench_saturation_calibration"),
        row("TailBench", "shore", "N/A", base_mpki=9.752,
            reason="All PGO coverages were effectively throughput-neutral.",
            confidence="5-profile coverage screen", evidence="tailbench_rtc_pgo_20260706_s10k_r5/summary.md"),
        row("TailBench", "SPECjbb", "N/A", reason="JVM workload; intentionally not profiled or patched."),

        row(
            "Verilator", "Chipyard qsort", "static", speedup=ver_speed, speedup_sem=0.003,
            pgo_speedup=ver_pgo_speed, base_mpki=float(ver_base["l2i_mpki"]),
            pref_mpki=float(ver["l2i_mpki"]), policy="target-only, fetch-gap top 100k",
            explanation="Compiler-pass static fetch-gap analysis injects direct branch-target prefetches.",
            confidence="3 runs; existing audited legacy-frequency result, not rerun",
            evidence="static_cond_autotune/static_cond_autotune_20260628_212242/summary.csv",
            graph=True,
        ),

        row(
            "Standalone DB", "memcached", "manual", speedup=memcached["speedup"]["mean"],
            speedup_sem=memcached["speedup"]["sem"], lines=4,
            base_mpki=memcached["baseline_mpki"]["mean"],
            pref_mpki=memcached["prefetch_mpki"]["mean"],
            reduction=memcached["l2i_reduction_pct"]["mean"],
            reduction_sem=memcached["l2i_reduction_pct"]["sem"], policy="target-only",
            explanation="Prefetch four connection-state callbacks: try_read_command, read, sendmsg, and write.",
            confidence="3 paired official memtier runs, migration=0",
            evidence="final_campaign_20260711/memcached_manual_strict_c2048_rep3_v2/paired_summary.json",
        ),
        row(
            "Standalone DB", "PostgreSQL", "manual", speedup=pg_manual["tps"] / pg_base["tps"],
            lines=25, base_mpki=pg_base["l2i_mpki"], pref_mpki=pg_manual["l2i_mpki"],
            policy="target-only",
            explanation="Prefetch ExprEvalStep function targets before PostgreSQL expression-dispatch calls.",
            confidence="highest-MPKI concurrency screen, migration=0",
            evidence="final_campaign_20260711/postgres_expr_func_concurrency_screen/c16",
        ),
        row(
            "Standalone DB", "Redis", "manual", speedup=1.0046500447, lines=1,
            base_mpki=0.357317912, pref_mpki=0.329905722, policy="target-only",
            explanation="Prefetch the command-table function pointer before command dispatch.",
            confidence="low-MPKI screen; no repeat promoted",
            evidence="datacenter_goal_20260708/redis_cmdmix_cmdpf_screen_30s/summary.csv",
        ),
        row("Standalone DB", "MariaDB", "N/A", base_mpki=0.0942,
            reason="System build screen was low-MPKI; an LLVM rebuild was not justified.",
            confidence="exclusion screen", evidence="datacenter_goal_20260708/mariadb_screen/run1/perf.csv"),
        row("Standalone DB", "LevelDB", "N/A", base_mpki=0.25553,
            reason="Highest screened operation was only 0.256 L2I MPKI.",
            confidence="exclusion screen", evidence="datacenter_goal_20260708/leveldb_l2_screen/summary.csv"),
        row("Standalone DB", "RocksDB", "N/A", base_mpki=0.08283,
            reason="Highest screened operation was only 0.083 L2I MPKI.",
            confidence="exclusion screen", evidence="datacenter_goal_20260708/rocksdb_l2_screen/summary.csv"),
        row("Standalone DB", "SQLite", "N/A", base_mpki=0.00420,
            reason="Interpreter workload was only 0.004 L2I MPKI.",
            confidence="exclusion screen", evidence="datacenter_goal_20260708/interpreter_l2_screen_233706/summary.csv"),
    ]

    # Keep the valid PGO reference for PostgreSQL in the report without
    # mislabeling the selected source-level experiment as static injection.
    rows[-6]["postgres_pgo_reference"] = pg_pgo["tps"] / pg_pgo_base["tps"]
    return rows


def display_number(value: float | None, digits: int = 3) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def write_results(rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0])
    with (OUT / "final_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def profile_rows() -> list[dict]:
    sources = {
        "FeedSim": FINAL / "feedsim_seed2_profiles/repetition_summary",
        "Django": FINAL / "django_base_profiles_rep3/repetition_summary",
        "Router": FINAL / "existing_profile_summary/router",
        "SetAlgebra": FINAL / "microsuite_set_stable_v2_profiles/rep5/repetition_summary",
        "Recommend": FINAL / "existing_profile_summary/recommend",
        "xapian": FINAL / "existing_profile_summary/xapian",
        "img-dnn": FINAL / "existing_profile_summary/img_dnn",
        "moses": FINAL / "existing_profile_summary/moses",
        "sphinx": FINAL / "existing_profile_summary/sphinx",
        "masstree": FINAL / "existing_profile_summary/masstree",
        "silo": FINAL / "existing_profile_summary/silo",
        "shore": FINAL / "existing_profile_summary/shore",
        "Verilator": FINAL / "existing_profile_summary/verilator",
        "memcached": FINAL / "existing_profile_summary/memcached",
        "PostgreSQL": FINAL / "existing_profile_summary/postgresql",
    }
    output = []
    branch_types = ("COND", "CALL", "RET", "IND", "IND_CALL", "UNCOND")
    for benchmark, directory in sources.items():
        summary = read_json(directory / "summary.json")
        ratios = {name: 0.0 for name in branch_types}
        for item in csv.DictReader((directory / "branch_type_summary.csv").open()):
            if item["branch_type"] in ratios:
                ratios[item["branch_type"]] = float(item["ratio_pct"])
        output.append({
            "benchmark": benchmark,
            "profile_reps": summary["rep_count"],
            "lbr_samples": summary["branch_samples"],
            "top10_jaccard": summary["top10_mean_jaccard"],
            "top10_sample_overlap": summary.get("top10_mean_sample_overlap", ""),
            **{name: ratios[name] for name in branch_types},
        })
    with (OUT / "branch_profile_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=output[0])
        writer.writeheader()
        writer.writerows(output)
    return output


def plot(rows: list[dict], metric: str, error: str, ylabel: str, filename: str) -> None:
    plotted = [item for item in rows if item["include_graph"]]
    labels = [f'{item["benchmark_suite"]}\n{item["benchmark"]}' for item in plotted]
    colors = {"manual": "#2878B5", "static": "#E68632", "both": "#4C9F70"}
    values = [item[metric] for item in plotted]
    errors = [item[error] for item in plotted]
    fig, ax = plt.subplots(figsize=(8.5, 4.8), constrained_layout=True)
    positions = list(range(len(plotted)))
    ax.bar(
        positions, values, yerr=errors, capsize=4,
        color=[colors[item["injection_method"]] for item in plotted],
        edgecolor="#252525", linewidth=0.7,
    )
    if metric == "speedup":
        ax.axhline(1.0, color="#555555", linewidth=1.0)
        pgo = [None, None, 1.0 + 25.65071691581511 / 100.0]
    else:
        ax.axhline(0.0, color="#555555", linewidth=1.0)
        pgo = [None, None, 100.0 * (58.688463 - 51.066222) / 58.688463]
    for index, value in enumerate(pgo):
        if value is not None:
            ax.scatter(index, value, color="#C73E3A", marker="o", s=55, zorder=4, label="PGO reference")
    ax.set_xticks(positions, labels)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", color="#D7D7D7", linewidth=0.7)
    ax.set_axisbelow(True)
    from matplotlib.patches import Patch
    handles = [Patch(facecolor=colors["manual"], edgecolor="#252525", label="Manual control-flow")]
    handles.append(Patch(facecolor=colors["static"], edgecolor="#252525", label="Static compiler"))
    handles.append(plt.Line2D([], [], marker="o", linestyle="", color="#C73E3A", label="PGO reference"))
    ax.legend(handles=handles, frameon=False, ncol=1, loc="upper right")
    fig.savefig(OUT / filename, dpi=220)
    fig.savefig(OUT / filename.replace(".png", ".svg"))
    plt.close(fig)


def fmt_speed(item: dict, key: str = "speedup") -> str:
    value = item.get(key)
    if value is None:
        return "N/A"
    sem = item.get("speedup_sem", 0.0) if key == "speedup" else 0.0
    return f"{value:.3f}x" + (f" +/- {sem:.3f}" if sem else "")


def markdown_table(rows: list[dict]) -> str:
    headers = [
        "benchmark suite", "benchmark", "injection method", "speedup", "PGO speedup (if static)",
        "# code line change", "L2I MPKI baseline", "L2I MPKI prefetch",
        "target-only or target+next line", "reason why can't inject prefetch", "code change explanation",
    ]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for item in rows:
        cells = [
            item["benchmark_suite"], item["benchmark"], item["injection_method"], fmt_speed(item),
            fmt_speed(item, "pgo_speedup") if item["injection_method"] == "static" else "N/A",
            str(item["code_line_change"]) if item["code_line_change"] is not None else "N/A",
            display_number(item["l2i_mpki_baseline"]), display_number(item["l2i_mpki_prefetch"]),
            item["target_policy"], item["reason_cannot_inject"] or "-", item["code_change_explanation"] or "-",
        ]
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |")
    return "\n".join(lines)


def write_other_attempts() -> str:
    with (OUT / "other_attempted_workloads.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OTHER_ATTEMPTS[0])
        writer.writeheader()
        writer.writerows(OTHER_ATTEMPTS)
    lines = [
        "| suite | benchmark | method | best observed speedup | L2I MPKI baseline | L2I MPKI prefetch | status |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for item in OTHER_ATTEMPTS:
        lines.append(
            f'| {item["suite"]} | {item["benchmark"]} | {item["method"]} | '
            f'{item["speedup"]:.3f}x | {display_number(item["base_mpki"])} | '
            f'{display_number(item["pref_mpki"])} | {item["status"]} |'
        )
    return "\n".join(lines)


def write_report(rows: list[dict], profiles: list[dict]) -> None:
    graphed = [item for item in rows if item["include_graph"]]
    average_reduction = statistics.mean(item["l2i_reduction_pct"] for item in graphed)
    arithmetic_speedup = statistics.mean(item["speedup"] for item in graphed)
    geometric_speedup = math.prod(item["speedup"] for item in graphed) ** (1.0 / len(graphed))
    valid_injected = [item for item in rows if item["speedup"] is not None and item["injection_method"] != "N/A"]
    full_speedup = statistics.mean(item["speedup"] for item in valid_injected)
    full_reduction = statistics.mean(item["l2i_reduction_pct"] for item in valid_injected)
    other_table = write_other_attempts()

    profile_header = (
        "| benchmark | reps | samples | top-10 Jaccard | sample-mass overlap | COND | CALL | RET | IND | IND_CALL | UNCOND |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    profile_lines = [profile_header]
    for item in profiles:
        overlap = item["top10_sample_overlap"]
        overlap_text = "N/A" if overlap == "" else f"{100.0 * float(overlap):.1f}%"
        profile_lines.append(
            f'| {item["benchmark"]} | {item["profile_reps"]} | {item["lbr_samples"]:,} | '
            f'{item["top10_jaccard"]:.3f} | {overlap_text} | '
            + " | ".join(f'{item[name]:.1f}%' for name in ("COND", "CALL", "RET", "IND", "IND_CALL", "UNCOND"))
            + " |"
        )

    report = f"""# Final L2I Prefetch Campaign

Date: 2026-07-11

## Result Boundary

- New FeedSim and Django rows use fixed 2.0 GHz with turbo disabled, one workload at a time, and migration-free measured native threads. Verilator is the existing audited result and was not rerun, so its legacy frequency condition is reported separately rather than relabeled as 2.0 GHz.
- FeedSim uses mean request runtime as the primary metric and completed-response QPS as a cross-check; Django uses successful HTTP QPS; Verilator uses runtime.
- Graph error bars are the standard error of the mean across the retained repeated runs.
- Earlier memcached, Router, SetAlgebra, and HDSearch high claims were rejected after strict reruns exposed failed requests, cold/order effects, migrations, or non-reproduction.
- Suites with no material final speedup (MicroSuite, TailBench, standalone DB) remain in the table but are omitted from the two requested graphs.

## Final Table

{markdown_table(rows)}

## Repeated LBR Profiles

{chr(10).join(profile_lines)}

## Main Findings

- **FeedSim:** `methods_` is a permuted `vector<void (*)()>` containing exact future control-flow targets. At strict fixed 2.0 GHz, depth-16 target+next gives **{rows[0]['speedup']:.3f}x +/- {rows[0]['speedup_sem']:.3f}** request-runtime speedup, **{feed_qps_from_rows(rows):.3f}x** completed-QPS speedup, and **{rows[0]['l2i_reduction_pct']:.2f}%** L2I-MPKI reduction. The five-profile sample-mass overlap is 93.76%. The earlier depth-64 **1.218x** QPS result remains in `feedsim_seed2_final_rep5`, but is superseded because its HWP/turbo state was not actually fixed and 64 queued requests had not reached steady state after a 20 s warmup.
- **Django:** its generated ICacheBuster has the same future-target vector. Three new profiles put 98.51% of miss samples at the dispatch site, with 99.30% top-10 sample-mass overlap. Depth-4 target+next gives **{rows[1]['speedup']:.3f}x +/- {rows[1]['speedup_sem']:.3f}** successful-HTTP-QPS speedup at fixed 2.0 GHz.
- **Verilator:** static fetch-gap selection gives **{ver_speed_from_rows(rows):.3f}x** versus **{ver_pgo_from_rows(rows):.3f}x** PGO. At top-100k, the static predictor has 68.85% sample-weighted PGO recall and 14.12% precision. The original Verilator-fitted scripts are preserved in `results/static_algorithm_snapshots/verilator_fit_20260710_232418`.
- **MicroSuite:** Router, SetAlgebra, and Recommend all have high aggregate MPKI, but most misses resolve into gRPC/protobuf/allocator code. SetAlgebra exposes only about 6.5% app-resolvable targets; its selected static plan overlaps 0/5 PGO target cache lines and is neutral. Recommend PGO25/75 crashed, PGO100 failed to link, and valid PGO50/static runs were slower. HDSearch was excluded because requests failed.
- **TailBench:** Xapian and Moses do contain useful control-flow objects, but strict saturation MPKI is only 0.35 and 0.63; manual prefetch is correspondingly neutral or negative. Silo demonstrates that MPKI reduction alone is insufficient: aggressive PGO reduced MPKI substantially while code-size/instruction overhead slowed runtime. All seven native workloads were built/profiled; SPECjbb is the sole JVM exclusion.
- **PostgreSQL:** MPKI reaches 96.6 at 16 clients, but three profiles have top-10 target Jaccard 0.278. PGO25 is 1.002x and manual expression-function prefetch is 0.999x, indicating a diffuse/non-deterministic frontend miss stream rather than one controllable dispatch target.
- **memcached and smaller DBs:** corrected official-memtier memcached is 0.995x at 0.22 MPKI. Redis, MariaDB, LevelDB, RocksDB, and SQLite are too low-MPKI to support a meaningful L2I-prefetch claim.

## Static Algorithm Conclusion

The static compiler result generalizes cleanly only to Verilator in this campaign. The current general-v5 structural rules did not recover MicroSuite's runtime-library targets and therefore did not approach a nonexistent positive PGO upper bound. This is a target-accessibility problem first, not merely a static cost threshold problem. No PGO-positive strict native workload was left with a missing static counterpart: the only robust PGO-positive static case is Verilator.

## Other Attempted Workloads

These completed experiments are retained for transparency but are outside the agreed DCPerf/MicroSuite/TailBench/Verilator/standalone-DB final set.

{other_table}

## Aggregate Statistics

- Plotted positive rows: average L2I-MPKI reduction **{average_reduction:.2f}%**.
- Plotted positive rows: arithmetic mean speedup **{arithmetic_speedup:.3f}x**; geometric mean **{geometric_speedup:.3f}x**.
- All valid injected rows, including neutral/negative screens: arithmetic mean speedup **{full_speedup:.3f}x**, mean L2I-MPKI reduction **{full_reduction:.2f}%**.

## Artifacts

- `final_results.csv`: machine-readable complete table.
- `branch_profile_summary.csv`: profile repetition and branch-type percentages.
- `other_attempted_workloads.csv`: FleetBench and standalone/service appendix.
- `final_speedup.png` / `.svg`: final speedup graph with PGO reference point.
- `final_l2i_reduction.png` / `.svg`: final L2I-MPKI reduction graph with PGO reference point.
- `/home/hnpark2/feedsim_prefetch_methodology_20260711.md`: paper-oriented FeedSim methodology and layout-sensitivity note.
"""
    (OUT / "final_report.md").write_text(report, encoding="utf-8")


def ver_speed_from_rows(rows: list[dict]) -> float:
    return next(item["speedup"] for item in rows if item["benchmark"] == "Chipyard qsort")


def feed_qps_from_rows(rows: list[dict]) -> float:
    explanation = next(item["code_change_explanation"] for item in rows if item["benchmark"] == "FeedSim")
    marker = "completed-QPS reference is "
    return float(explanation.split(marker, 1)[1].split("x", 1)[0])


def ver_pgo_from_rows(rows: list[dict]) -> float:
    return next(item["pgo_speedup"] for item in rows if item["benchmark"] == "Chipyard qsort")


def main() -> None:
    rows = build_rows()
    write_results(rows)
    profiles = profile_rows()
    plot(rows, "speedup", "speedup_sem", "Speedup (x)", "final_speedup.png")
    plot(rows, "l2i_reduction_pct", "l2i_reduction_sem", "L2I MPKI reduction (%)", "final_l2i_reduction.png")
    write_report(rows, profiles)
    print(OUT)


if __name__ == "__main__":
    main()
