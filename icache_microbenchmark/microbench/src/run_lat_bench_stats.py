#!/usr/bin/env python3
import argparse
import subprocess
import sys
import re
import shlex
from statistics import mean, variance, stdev
from collections import defaultdict

# Regex patterns for metrics we want to aggregate
RE_TIME_TSC = re.compile(r"Time\(monotonic\):\s*(\d+)\s*ns,\s*TSC:\s*(\d+)\s*cycles")
RE_RAW      = re.compile(r"Raw\s+Cycles/ns:\s*([0-9]*\.?[0-9]+)\s*\|\s*ns/task\(raw\):\s*([0-9]*\.?[0-9]+)")
RE_FIXED    = re.compile(r"Time\(from fixed freq\):\s*(\d+)\s*ns\s*\|\s*ns/task\(fixed\):\s*([0-9]*\.?[0-9]+)")
RE_FREQ     = re.compile(r"Fixed\s+CPU\s+freq:\s*([0-9]*\.?[0-9]+)\s*MHz")

METRIC_KEYS = [
    "time_ns",
    "tsc_cycles",
    "cycles_per_ns_raw",
    "ns_per_task_raw",
    "time_ns_fixed",
    "ns_per_task_fixed",
    "fixed_mhz",
]


def run_once(cmd: str):
    # Run one iteration, capture combined stdout+stderr (bench prints to both)
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out, _ = proc.communicate()
    rc = proc.returncode
    if rc != 0:
        print(f"WARN: command exited with {rc}")
    return out


def parse_metrics(output: str):
    m = {}
    m_time = RE_TIME_TSC.search(output)
    if m_time:
        m["time_ns"] = int(m_time.group(1))
        m["tsc_cycles"] = int(m_time.group(2))
    m_raw = RE_RAW.search(output)
    if m_raw:
        m["cycles_per_ns_raw"] = float(m_raw.group(1))
        m["ns_per_task_raw"] = float(m_raw.group(2))
    m_fixed = RE_FIXED.search(output)
    if m_fixed:
        m["time_ns_fixed"] = int(m_fixed.group(1))
        m["ns_per_task_fixed"] = float(m_fixed.group(2))
    m_freq = RE_FREQ.search(output)
    if m_freq:
        m["fixed_mhz"] = float(m_freq.group(1))
    return m


def compute_stats(records):
    # records: list of dicts
    cols = defaultdict(list)
    for r in records:
        for k, v in r.items():
            cols[k].append(v)
    stats = {}
    for k, arr in cols.items():
        if len(arr) == 0:
            continue
        if len(arr) == 1:
            stats[k] = {"mean": float(arr[0]), "variance": 0.0, "stdev": 0.0, "count": 1}
        else:
            try:
                stats[k] = {"mean": float(mean(arr)),
                            "variance": float(variance(arr)),  # sample variance
                            "stdev": float(stdev(arr)),        # sample standard deviation
                            "count": len(arr)}
            except Exception:
                mu = sum(arr)/len(arr)
                var = float(sum((x-mu)**2 for x in arr)/(len(arr)-1))
                stats[k] = {"mean": float(mu), "variance": var, "stdev": var ** 0.5, "count": len(arr)}
    return stats


def main():
    ap = argparse.ArgumentParser(description="Run lat_bench multiple times and compute mean/stdev/variance of metrics")
    ap.add_argument("--cmd", default="./lat_bench 1 256 28 0", help="Command to execute per run (use quotes). Include 'sudo ' if needed.")
    ap.add_argument("--iters", type=int, default=100, help="Number of iterations")
    ap.add_argument("--print-each", action="store_true", help="Print raw output of each run")
    args = ap.parse_args()

    records = []
    for i in range(args.iters):
        out = run_once(args.cmd)
        if args.print_each:
            sys.stdout.write(f"===== RUN {i+1}/{args.iters} =====\n")
            sys.stdout.write(out)
            if not out.endswith("\n"): sys.stdout.write("\n")
        rec = parse_metrics(out)
        if not rec:
            sys.stderr.write(f"WARN: no metrics parsed on iter {i+1}\n")
        records.append(rec)

    stats = compute_stats(records)

    # Summary
    print("\nSummary (mean, stdev, variance) over", args.iters, "runs")
    def pr(key, unit=""):
        if key in stats:
            s = stats[key]
            print(f"- {key}: mean={s['mean']:.2f}{unit}, stdev={s['stdev']:.2f}{unit}")
        else:
            print(f"- {key}: n/a")

    pr("time_ns", " ns")
    pr("tsc_cycles", " cycles")
    pr("cycles_per_ns_raw", " cyc/ns")
    pr("ns_per_task_raw", " ns/task")
    pr("time_ns_fixed", " ns")
    pr("ns_per_task_fixed", " ns/task")
    pr("fixed_mhz", " MHz")

if __name__ == "__main__":
    main()
