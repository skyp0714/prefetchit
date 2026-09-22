#!/usr/bin/env python3
import argparse
import csv
import math
import re
from pathlib import Path


LBR_SAMPLES_RE = re.compile(r"^- LBR samples parsed(?: \(raw\))?:\s*([0-9]+)\s*$")
TOP_TARGET_RE = re.compile(r"^- Top miss target function:\s*`(.+?)`\s+\(([0-9]+(?:\.[0-9]+)?)%\)\s*$")


def parse_trace_summary(path: Path):
    out = {"lbr_samples": 0, "top_target": "N/A", "top_target_pct": 0.0}
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            m = LBR_SAMPLES_RE.match(line)
            if m:
                out["lbr_samples"] = int(m.group(1))
                continue
            m = TOP_TARGET_RE.match(line)
            if m:
                out["top_target"] = m.group(1).strip()
                out["top_target_pct"] = float(m.group(2))
                continue
    return out


def parse_branch_csv(path: Path):
    dist = {}
    total = 0
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            bt = row["branch_type"].strip()
            cnt = int(float(row["count"]))
            ratio = float(row["ratio_pct"])
            dist[bt] = {"count": cnt, "ratio_pct": ratio}
            total += cnt
    return dist, total


def safe_ratio(n, d):
    return (100.0 * n / d) if d > 0 else 0.0


def js_divergence(p, q):
    keys = set(p.keys()) | set(q.keys())
    m = {k: 0.5 * (p.get(k, 0.0) + q.get(k, 0.0)) for k in keys}

    def kl(a, b):
        s = 0.0
        for k in keys:
            av = a.get(k, 0.0)
            bv = b.get(k, 0.0)
            if av > 0 and bv > 0:
                s += av * math.log2(av / bv)
        return s

    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


def main():
    ap = argparse.ArgumentParser(description="Build A/B comparison + validation report across PEBS traces")
    ap.add_argument("--trace-root", required=True, help="root dir containing per-trace subdirs")
    ap.add_argument("--trace-names", default="l2_miss,dsb_miss,itlb_miss,stlb_miss")
    ap.add_argument("--out-md", required=True)
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--out-validation-md", required=True)
    args = ap.parse_args()

    trace_root = Path(args.trace_root)
    traces = [x.strip() for x in args.trace_names.split(",") if x.strip()]

    rows = []
    validation_lines = []
    validation_lines.append("# Trace Validation")
    validation_lines.append("")
    validation_lines.append("| Trace | Check | Value | Status |")
    validation_lines.append("|---|---|---:|---|")
    fail_cnt = 0

    for tr in traces:
        td = trace_root / tr
        f_br = td / "branch_type_distribution.csv"
        f_sum = td / "trace_summary.md"
        f_data = td / "l2miss_profile.data"

        br_dist, br_total = parse_branch_csv(f_br) if f_br.exists() else ({}, 0)
        ts = parse_trace_summary(f_sum) if f_sum.exists() else {"lbr_samples": 0}

        top1_func = ts.get("top_target", "N/A")
        top1_func_pct = float(ts.get("top_target_pct", 0.0))
        top1_sym = top1_func
        top1_sym_pct = top1_func_pct

        top_branch = "N/A"
        top_branch_pct = 0.0
        if br_dist:
            top_branch = max(br_dist.keys(), key=lambda k: br_dist[k]["count"])
            top_branch_pct = br_dist[top_branch]["ratio_pct"]

        cond_pct = br_dist.get("COND", {}).get("ratio_pct", 0.0)
        call_pct = br_dist.get("CALL", {}).get("ratio_pct", 0.0)
        unknown_pct = br_dist.get("UNKNOWN", {}).get("ratio_pct", 0.0)

        rows.append(
            {
                "trace": tr,
                "lbr_samples": ts["lbr_samples"],
                "top_function": top1_func,
                "top_function_pct": top1_func_pct,
                "top_symbol": top1_sym,
                "top_symbol_pct": top1_sym_pct,
                "top_branch_type": top_branch,
                "top_branch_pct": top_branch_pct,
                "cond_pct": cond_pct,
                "call_pct": call_pct,
                "unknown_pct": unknown_pct,
                "branch_total": br_total,
            }
        )

        checks = []
        checks.append(("perf_data_size", f_data.stat().st_size if f_data.exists() else 0, lambda v: v > 0))
        checks.append(("lbr_samples", ts["lbr_samples"], lambda v: v > 0))
        checks.append(("branch_total", br_total, lambda v: v > 0))
        checks.append(("top_function_pct", top1_func_pct, lambda v: math.isfinite(v) and v > 0.0))
        checks.append(("top_branch_pct", top_branch_pct, lambda v: math.isfinite(v) and v > 0.0))
        checks.append(("dummy_in_top_function", 1 if "dummy" in top1_func.lower() else 0, lambda v: v == 0))
        checks.append(("dummy_in_top_symbol", 1 if "dummy" in top1_sym.lower() else 0, lambda v: v == 0))
        checks.append(("nan_in_branch_ratios", 1 if any(not math.isfinite(x.get("ratio_pct", 0.0)) for x in br_dist.values()) else 0, lambda v: v == 0))
        ratio_sum = sum(x.get("ratio_pct", 0.0) for x in br_dist.values())
        checks.append(("branch_ratio_sum_pct", f"{ratio_sum:.6f}", lambda v: math.isfinite(float(v)) and (99.0 <= float(v) <= 101.0)))
        checks.append(("min_lbr_samples", ts["lbr_samples"], lambda v: v >= 100))

        for name, value, pred in checks:
            ok = pred(value)
            if not ok:
                fail_cnt += 1
            validation_lines.append(f"| {tr} | {name} | {value} | {'OK' if ok else 'FAIL'} |")

    validation_lines.append("")
    if fail_cnt == 0:
        validation_lines.append("Result: PASS (no NaN/0/dummy contamination in A/B key metrics)")
    else:
        validation_lines.append(f"Result: FAIL ({fail_cnt} checks failed)")

    # Cross-trace branch divergence against l2_miss baseline.
    row_map = {r["trace"]: r for r in rows}
    branch_map = {}
    for tr in traces:
        br_csv = trace_root / tr / "branch_type_distribution.csv"
        if not br_csv.exists():
            branch_map[tr] = {}
            continue
        dist, total = parse_branch_csv(br_csv)
        branch_map[tr] = {k: (v["count"] / total if total > 0 else 0.0) for k, v in dist.items()}

    js_rows = []
    base = branch_map.get("l2_miss", {})
    for tr in traces:
        if tr == "l2_miss":
            continue
        cur = branch_map.get(tr, {})
        js = js_divergence(base, cur) if base and cur else 0.0
        js_rows.append((tr, js))

    # Write CSV summary.
    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        fields = [
            "trace",
            "lbr_samples",
            "top_function",
            "top_function_pct",
            "top_symbol",
            "top_symbol_pct",
            "top_branch_type",
            "top_branch_pct",
            "cond_pct",
            "call_pct",
            "unknown_pct",
            "branch_total",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    # Build markdown report.
    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("# A/B Cross-Trace Analysis")
    lines.append("")
    lines.append("## Analysis A (Miss Target)")
    lines.append("")
    lines.append("| Trace | LBR Samples | Top Target Function | Top Target % |")
    lines.append("|---|---:|---|---:|")
    for r in rows:
        lines.append(
            f"| {r['trace']} | {r['lbr_samples']} | {r['top_function']} | "
            f"{r['top_function_pct']:.2f} |"
        )

    lines.append("")
    lines.append("## Analysis B (LBR Branch Type)")
    lines.append("")
    lines.append("| Trace | Top Branch | Top Branch % | COND % | CALL % | UNKNOWN % |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for r in rows:
        lines.append(
            f"| {r['trace']} | {r['top_branch_type']} | {r['top_branch_pct']:.2f} | "
            f"{r['cond_pct']:.2f} | {r['call_pct']:.2f} | {r['unknown_pct']:.2f} |"
        )

    lines.append("")
    lines.append("## Cause-Difference View (L2 vs DSB/L3 vs TLB)")
    lines.append("")
    lines.append("- `l2_miss` vs `dsb_miss/l3_miss`: compare front-end miss vs decode-stream miss behavior.")
    lines.append("- `itlb_miss` and `stlb_miss`: grouped as TLB miss causes.")
    lines.append("- Larger top-function share means hotter concentration on fewer simulator paths.")
    lines.append("- Branch divergence from `l2_miss` baseline (Jensen-Shannon):")
    for tr, js in js_rows:
        lines.append(f"  - {tr}: {js:.6f}")

    # Simple auto findings.
    lines.append("")
    lines.append("## Auto Findings")
    lines.append("")
    if rows:
        most_concentrated = max(rows, key=lambda r: r["top_function_pct"])
        most_cond = max(rows, key=lambda r: r["cond_pct"])
        most_call = max(rows, key=lambda r: r["call_pct"])
        smallest_samples = min(rows, key=lambda r: r["lbr_samples"])
        lines.append(
            f"- Most concentrated target path: `{most_concentrated['trace']}` "
            f"({most_concentrated['top_function_pct']:.2f}% in top function)."
        )
        lines.append(
            f"- Highest conditional-branch dominance: `{most_cond['trace']}` "
            f"(COND {most_cond['cond_pct']:.2f}%)."
        )
        lines.append(
            f"- Highest call-branch dominance: `{most_call['trace']}` "
            f"(CALL {most_call['call_pct']:.2f}%)."
        )
        lines.append(
            f"- Smallest trace sample pool: `{smallest_samples['trace']}` "
            f"({smallest_samples['lbr_samples']} samples)."
        )

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out_val = Path(args.out_validation_md)
    out_val.parent.mkdir(parents=True, exist_ok=True)
    out_val.write_text("\n".join(validation_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
