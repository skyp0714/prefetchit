#!/usr/bin/env python3
import argparse
import csv
import math
import re
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def safe_float(v: str, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def strip_modifiers(ev: str) -> str:
    return re.sub(r"(?::[A-Za-z0-9_]+)+$", "", ev)


def canonical_event(ev: str) -> str:
    return ev.strip().lower().replace(" ", "")


def parse_perf_raw(path: Path):
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue
            value = parts[0].strip()
            event = parts[2].strip()
            if not event:
                continue
            if value.startswith("<") or value in ("not counted", "not supported", ""):
                parsed = 0.0
            else:
                value = value.replace(" ", "")
                parsed = safe_float(value, 0.0)
            ce = canonical_event(event)
            rows.append((ce, strip_modifiers(ce), parsed))
    return rows


def event_count(parsed_rows, target_event: str) -> float:
    target_c = canonical_event(target_event)
    target_b = strip_modifiers(target_c)
    exact = [v for c, _, v in parsed_rows if c == target_c]
    if exact:
        return sum(exact)
    base = [v for _, b, v in parsed_rows if b == target_b]
    if base:
        return sum(base)
    contains = [v for c, b, v in parsed_rows if target_b in c or target_b in b]
    if contains:
        return sum(contains)
    return 0.0


def mpki(instructions: float, count: float) -> float:
    if instructions <= 0.0:
        return 0.0
    return (count * 1000.0) / instructions


def fmt(v: float, digits: int = 6) -> str:
    return f"{v:.{digits}f}"


def main():
    ap = argparse.ArgumentParser(description="Build detailed profile CSV/plot outputs from perf raw logs")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out-per-iter", required=True)
    ap.add_argument("--out-summary", required=True)
    ap.add_argument("--out-latency", required=True)
    ap.add_argument("--out-latency-png", required=True)
    ap.add_argument("--out-table", required=True)
    ap.add_argument("--workload-name", required=True)
    ap.add_argument("--event0-alias", required=True)
    ap.add_argument("--event1-alias", required=True)
    ap.add_argument("--event2-alias", required=True)
    ap.add_argument("--event3-alias", required=True)
    ap.add_argument("--latency-events", required=True, help="Comma-separated latency events (GE_2..GE_128)")
    ap.add_argument("--strict-nonzero", action="store_true", help="Fail if key numeric metrics are NaN/inf/<=0")
    ap.add_argument("--validation-report", default="", help="Optional markdown validation report path")
    args = ap.parse_args()

    manifest = Path(args.manifest)
    out_per_iter = Path(args.out_per_iter)
    out_summary = Path(args.out_summary)
    out_latency = Path(args.out_latency)
    out_latency_png = Path(args.out_latency_png)
    out_table = Path(args.out_table)
    latency_events = [x.strip() for x in args.latency_events.split(",") if x.strip()]

    rows = []
    with manifest.open("r", encoding="utf-8", newline="") as f:
        for m in csv.DictReader(f):
            iter_idx = int(m["iteration"])
            perfraw = Path(m["perfraw"])
            elapsed = safe_float(m["elapsed_sec"], 0.0)
            rc = int(float(m["return_code"]))
            parsed = parse_perf_raw(perfraw)

            inst = event_count(parsed, "instructions")
            e0 = event_count(parsed, args.event0_alias)
            e1 = event_count(parsed, args.event1_alias)
            e2 = event_count(parsed, args.event2_alias)
            e3 = event_count(parsed, args.event3_alias)

            lats = {evt: event_count(parsed, evt) for evt in latency_events}

            row = {
                "iteration": iter_idx,
                "elapsed_sec": elapsed,
                "return_code": rc,
                "instructions": inst,
                "event0": e0,
                "event1": e1,
                "event2": e2,
                "event3": e3,
                "l1i_mpki": mpki(inst, e0),
                "l2i_mpki": mpki(inst, e1),
                "itlb_mpki": mpki(inst, e2 + e3),
                "stlb_mpki": mpki(inst, e2),
            }
            row.update({f"lat_{evt}": lats[evt] for evt in latency_events})
            rows.append(row)

    rows.sort(key=lambda x: x["iteration"])
    if not rows:
        raise RuntimeError("No rows parsed from manifest.")

    def is_bad(v: float) -> bool:
        return (not math.isfinite(v)) or (v <= 0.0)

    validation_lines = []
    validation_lines.append("# Number Validation")
    validation_lines.append("")
    validation_lines.append("| Iteration | Field | Value | Status |")
    validation_lines.append("|---:|---|---:|---|")
    bad_count = 0

    key_fields = [
        "elapsed_sec",
        "instructions",
        "event0",
        "event1",
        "event2",
        "event3",
        "l1i_mpki",
        "l2i_mpki",
        "itlb_mpki",
        "stlb_mpki",
    ]
    key_fields += [f"lat_{evt}" for evt in latency_events]

    for r in rows:
        it = int(r["iteration"])
        for fld in key_fields:
            val = float(r[fld])
            bad = is_bad(val)
            status = "FAIL" if bad else "OK"
            if bad:
                bad_count += 1
            validation_lines.append(f"| {it} | {fld} | {val:.6f} | {status} |")

    validation_lines.append("")
    if bad_count == 0:
        validation_lines.append("Result: PASS (no NaN/inf/0 found in key metrics)")
    else:
        validation_lines.append(f"Result: FAIL ({bad_count} invalid values found)")
    validation_md = "\n".join(validation_lines) + "\n"

    if args.validation_report:
        Path(args.validation_report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.validation_report).write_text(validation_md, encoding="utf-8")

    if args.strict_nonzero and bad_count > 0:
        raise RuntimeError(f"Validation failed: found {bad_count} key metrics that are NaN/inf/<=0.")

    out_per_iter.parent.mkdir(parents=True, exist_ok=True)
    out_summary.parent.mkdir(parents=True, exist_ok=True)
    out_latency.parent.mkdir(parents=True, exist_ok=True)
    out_latency_png.parent.mkdir(parents=True, exist_ok=True)
    out_table.parent.mkdir(parents=True, exist_ok=True)

    per_iter_fields = [
        "iteration",
        "elapsed_sec",
        "return_code",
        "instructions",
        "event0",
        "event1",
        "event2",
        "event3",
        "l1i_mpki",
        "l2i_mpki",
        "itlb_mpki",
        "stlb_mpki",
    ] + [f"lat_{evt}" for evt in latency_events]

    with out_per_iter.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=per_iter_fields)
        w.writeheader()
        for r in rows:
            out_r = {}
            for k in per_iter_fields:
                v = r[k]
                if isinstance(v, float):
                    out_r[k] = fmt(v)
                else:
                    out_r[k] = str(v)
            w.writerow(out_r)

    metric_names = [
        "elapsed_sec",
        "l1i_mpki",
        "l2i_mpki",
        "itlb_mpki",
        "stlb_mpki",
        "instructions",
    ]
    with out_summary.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["metric", "mean", "min", "max"])
        w.writeheader()
        for metric in metric_names:
            vals = [float(r[metric]) for r in rows]
            w.writerow(
                {
                    "metric": metric,
                    "mean": fmt(mean(vals)),
                    "min": fmt(min(vals)),
                    "max": fmt(max(vals)),
                }
            )

    ge_map = {}
    for evt in latency_events:
        m = re.search(r"latency_ge_([0-9]+)", evt, re.IGNORECASE)
        if not m:
            continue
        ge_map[int(m.group(1))] = sum(float(r[f"lat_{evt}"]) for r in rows)

    thresholds = [2, 4, 8, 16, 32, 64, 128]
    for t in thresholds:
        ge_map.setdefault(t, 0.0)

    bucket_defs = [
        ("[2,4)", max(0.0, ge_map[2] - ge_map[4])),
        ("[4,8)", max(0.0, ge_map[4] - ge_map[8])),
        ("[8,16)", max(0.0, ge_map[8] - ge_map[16])),
        ("[16,32)", max(0.0, ge_map[16] - ge_map[32])),
        ("[32,64)", max(0.0, ge_map[32] - ge_map[64])),
        ("[64,128)", max(0.0, ge_map[64] - ge_map[128])),
        ("[128,+)", max(0.0, ge_map[128])),
    ]
    total = max(ge_map[2], 0.0)
    with out_latency.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["bucket", "events", "ratio_pct"])
        w.writeheader()
        for bucket, count in bucket_defs:
            ratio = (count * 100.0 / total) if total > 0 else 0.0
            w.writerow({"bucket": bucket, "events": fmt(count), "ratio_pct": fmt(ratio)})

    xs = [b for b, _ in bucket_defs]
    ys = [((c * 100.0 / total) if total > 0 else 0.0) for _, c in bucket_defs]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    bars = ax.bar(xs, ys, color="#2f6db3")
    ax.set_ylabel("Ratio (%)")
    ax.set_xlabel("Frontend Stall Latency Bucket")
    ax.set_title(f"Frontend Stall Latency Distribution ({args.workload_name})")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    for b, y in zip(bars, ys):
        ax.text(b.get_x() + b.get_width() / 2.0, y, f"{y:.1f}", ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_latency_png, dpi=180)
    plt.close(fig)

    avg_runtime = mean([float(r["elapsed_sec"]) for r in rows])
    avg_l1 = mean([float(r["l1i_mpki"]) for r in rows])
    avg_l2 = mean([float(r["l2i_mpki"]) for r in rows])
    avg_itlb = mean([float(r["itlb_mpki"]) for r in rows])
    avg_stlb = mean([float(r["stlb_mpki"]) for r in rows])

    lines = []
    lines.append("| Iteration | Runtime (s) | L1I MPKI | L2I MPKI | iTLB MPKI | sTLB MPKI |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for r in rows:
        lines.append(
            f"| {r['iteration']} | {float(r['elapsed_sec']):.6f} | "
            f"{float(r['l1i_mpki']):.6f} | {float(r['l2i_mpki']):.6f} | "
            f"{float(r['itlb_mpki']):.6f} | {float(r['stlb_mpki']):.6f} |"
        )
    lines.append(
        f"| avg | {avg_runtime:.6f} | {avg_l1:.6f} | {avg_l2:.6f} | {avg_itlb:.6f} | {avg_stlb:.6f} |"
    )
    out_table.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
