#!/usr/bin/env python3
import argparse
import csv
import math
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def safe_float(v: str, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def canonical_event(ev: str) -> str:
    return ev.strip().lower().replace(" ", "")


def strip_modifiers(ev: str) -> str:
    return re.sub(r"(?::[A-Za-z0-9_]+)+$", "", ev)


def parse_event_file(path: Path):
    events = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line or "|" not in line:
                continue
            alias, spec = line.split("|", 1)
            alias = alias.strip()
            spec = spec.strip()
            if alias and spec:
                events.append((alias, spec))
    if len(events) < 2:
        raise RuntimeError(f"Need at least 2 events in {path}")
    return events


def parse_perf_raw(path: Path):
    parsed = []
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
                cnt = 0.0
            else:
                cnt = safe_float(value.replace(" ", ""), 0.0)
            ce = canonical_event(event)
            parsed.append((ce, strip_modifiers(ce), cnt))
    return parsed


def event_count(parsed_rows, target_event: str) -> float:
    tc = canonical_event(target_event)
    tb = strip_modifiers(tc)
    exact = [v for c, _, v in parsed_rows if c == tc]
    if exact:
        return sum(exact)
    base = [v for _, b, v in parsed_rows if b == tb]
    if base:
        return sum(base)
    contains = [v for c, b, v in parsed_rows if tb in c or tb in b]
    if contains:
        return sum(contains)
    return 0.0


def is_timeout_log(path: Path) -> bool:
    txt = path.read_text(encoding="utf-8", errors="replace")
    return "*** FAILED ***" in txt and "(timeout)" in txt


def run_one(
    idx: int,
    bench: str,
    cycle: int,
    emu: Path,
    bench_dir: Path,
    core_base: int,
    core_count: int,
    perf_bin: str,
    event_specs_csv: str,
    l2_event_alias: str,
    out_dir: Path,
    phase: str,
):
    core = core_base + (idx % core_count)
    bench_bin = bench_dir / f"{bench}.riscv"
    run_dir = out_dir / "raw" / phase / bench
    run_dir.mkdir(parents=True, exist_ok=True)
    perfraw = run_dir / f"cycle_{cycle}.perfraw"
    runlog = run_dir / f"cycle_{cycle}.log"

    cmd = [
        perf_bin,
        "stat",
        "--no-big-num",
        "-x,",
        "--all-user",
        "-C",
        str(core),
        "-o",
        str(perfraw),
        "-e",
        event_specs_csv,
        "--",
        "taskset",
        "-c",
        str(core),
        str(emu),
        str(bench_bin),
        f"+max-cycles={cycle}",
    ]
    start = time.monotonic()
    with runlog.open("w", encoding="utf-8") as lf:
        proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, check=False)
    elapsed = time.monotonic() - start

    parsed = parse_perf_raw(perfraw)
    inst = event_count(parsed, "instructions")
    l2_count = event_count(parsed, l2_event_alias)
    l2_mpki = (l2_count * 1000.0 / inst) if inst > 0 else 0.0
    timeout = is_timeout_log(runlog)
    # In this workflow, max-cycles timeout is expected and still a valid sample.
    status = "max_cycles" if timeout else ("finished" if proc.returncode == 0 else "failed")

    return {
        "bench": bench,
        "cycle": int(cycle),
        "elapsed_sec": float(elapsed),
        "return_code": int(proc.returncode),
        "status": status,
        "instructions": float(inst),
        "l2_count": float(l2_count),
        "l2_mpki": float(l2_mpki),
        "core": int(core),
        "perfraw": str(perfraw),
        "runlog": str(runlog),
    }


def run_round(
    benches,
    cycles_by_bench,
    emu: Path,
    bench_dir: Path,
    core_base: int,
    core_count: int,
    perf_bin: str,
    event_specs_csv: str,
    l2_event_alias: str,
    out_dir: Path,
    phase: str,
):
    out = {}
    with ThreadPoolExecutor(max_workers=core_count) as ex:
        futs = []
        for idx, bench in enumerate(benches):
            futs.append(
                ex.submit(
                    run_one,
                    idx,
                    bench,
                    int(cycles_by_bench[bench]),
                    emu,
                    bench_dir,
                    core_base,
                    core_count,
                    perf_bin,
                    event_specs_csv,
                    l2_event_alias,
                    out_dir,
                    phase,
                )
            )
        for fut in as_completed(futs):
            r = fut.result()
            out[r["bench"]] = r
    return out


def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def main():
    ap = argparse.ArgumentParser(description="Explore verilator benchmarks for ~target runtime and L2 MPKI")
    ap.add_argument("--emu", required=True)
    ap.add_argument("--bench-dir", required=True)
    ap.add_argument("--event-file", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--perf-bin", default="perf")
    ap.add_argument("--parallel", type=int, default=32)
    ap.add_argument("--core-base", type=int, default=0)
    ap.add_argument("--target-runtime-sec", type=float, default=300.0)
    ap.add_argument("--base-cycles", type=int, default=20000)
    ap.add_argument("--min-cycles", type=int, default=2000)
    ap.add_argument("--max-cycles", type=int, default=5000000)
    ap.add_argument("--runtime-low-ratio", type=float, default=0.8)
    ap.add_argument("--runtime-high-ratio", type=float, default=1.2)
    args = ap.parse_args()

    emu = Path(args.emu)
    bench_dir = Path(args.bench_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    events = parse_event_file(Path(args.event_file))
    e0_spec = events[0][1]
    e1_alias = events[1][0]
    e1_spec = events[1][1]
    e2_spec = events[2][1] if len(events) > 2 else ""
    e3_spec = events[3][1] if len(events) > 3 else ""
    specs = [s for s in (e0_spec, e1_spec, e2_spec, e3_spec) if s]
    specs.append("instructions")
    event_specs_csv = ",".join(specs)

    benches = sorted(p.stem for p in bench_dir.glob("*.riscv"))
    if not benches:
        raise RuntimeError(f"No *.riscv benchmarks found under {bench_dir}")

    base_cycles = {b: int(args.base_cycles) for b in benches}
    r1 = run_round(
        benches,
        base_cycles,
        emu,
        bench_dir,
        args.core_base,
        args.parallel,
        args.perf_bin,
        event_specs_csv,
        e1_alias,
        out_dir,
        "phase1_base",
    )

    target_cycles = {}
    for b in benches:
        elapsed = max(r1[b]["elapsed_sec"], 0.001)
        scaled = int(round(args.base_cycles * (args.target_runtime_sec / elapsed)))
        target_cycles[b] = clamp(scaled, args.min_cycles, args.max_cycles)

    r2 = run_round(
        benches,
        target_cycles,
        emu,
        bench_dir,
        args.core_base,
        args.parallel,
        args.perf_bin,
        event_specs_csv,
        e1_alias,
        out_dir,
        "phase2_target",
    )

    r3_cycles = {}
    for b in benches:
        elapsed = r2[b]["elapsed_sec"]
        low = args.target_runtime_sec * args.runtime_low_ratio
        high = args.target_runtime_sec * args.runtime_high_ratio
        if elapsed < low or elapsed > high:
            scaled = int(round(target_cycles[b] * (args.target_runtime_sec / max(elapsed, 0.001))))
            r3_cycles[b] = clamp(scaled, args.min_cycles, args.max_cycles)

    r3 = {}
    if r3_cycles:
        r3 = run_round(
            sorted(r3_cycles.keys()),
            r3_cycles,
            emu,
            bench_dir,
            args.core_base,
            args.parallel,
            args.perf_bin,
            event_specs_csv,
            e1_alias,
            out_dir,
            "phase3_adjust",
        )

    final = {}
    for b in benches:
        if b in r3:
            final[b] = r3[b]
        else:
            final[b] = r2[b]

    csv_path = out_dir / "exploration_results.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "benchmark",
                "selected_cycle",
                "runtime_sec",
                "return_code",
                "status",
                "instructions",
                "l2_count",
                "l2_mpki",
                "runlog",
                "perfraw",
            ],
        )
        w.writeheader()
        for b in benches:
            r = final[b]
            w.writerow(
                {
                    "benchmark": b,
                    "selected_cycle": int(r["cycle"]),
                    "runtime_sec": f"{r['elapsed_sec']:.6f}",
                    "return_code": int(r["return_code"]),
                    "status": r["status"],
                    "instructions": f"{r['instructions']:.6f}",
                    "l2_count": f"{r['l2_count']:.6f}",
                    "l2_mpki": f"{r['l2_mpki']:.6f}",
                    "runlog": r["runlog"],
                    "perfraw": r["perfraw"],
                }
            )

    valid = []
    for b in benches:
        r = final[b]
        if (
            math.isfinite(r["l2_mpki"])
            and r["l2_mpki"] > 0.0
            and r["instructions"] > 0.0
            and r["status"] in ("finished", "max_cycles")
        ):
            valid.append(r)
    best = max(valid, key=lambda x: x["l2_mpki"]) if valid else None

    md_path = out_dir / "exploration.md"
    lines = []
    lines.append("# Verilator Benchmark Runtime/L2 MPKI Exploration")
    lines.append("")
    lines.append(f"- target_runtime_sec: {args.target_runtime_sec:.1f}")
    lines.append(f"- parallel_cores_used: {args.parallel}")
    lines.append(f"- event_file: {args.event_file}")
    lines.append("")
    if best is not None:
        lines.append(
            f"- highest_l2_mpki: `{best['bench']}` at `+max-cycles={best['cycle']}` -> `{best['l2_mpki']:.6f}`"
        )
    else:
        lines.append("- highest_l2_mpki: none (no valid non-zero L2 MPKI rows)")
    lines.append("")
    lines.append("| Benchmark | Selected Cycles | Runtime (s) | Status | L2 MPKI | Instructions |")
    lines.append("|---|---:|---:|---|---:|---:|")
    for b in benches:
        r = final[b]
        lines.append(
            f"| {b} | {int(r['cycle'])} | {r['elapsed_sec']:.3f} | {r['status']}(rc={int(r['return_code'])}) | "
            f"{r['l2_mpki']:.6f} | {r['instructions']:.0f} |"
        )
    lines.append("")
    lines.append("## Run Logs")
    for b in benches:
        r = final[b]
        lines.append(f"- {b}: {r['runlog']}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    selected_txt = out_dir / "selected_best.txt"
    if best is None:
        selected_txt.write_text("", encoding="utf-8")
    else:
        selected_txt.write_text(f"{best['bench']},{int(best['cycle'])},{best['l2_mpki']:.6f}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
