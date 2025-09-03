#!/usr/bin/env python3
import argparse
import subprocess
import sys
import re
import shlex
from statistics import mean, variance, stdev
from collections import defaultdict

# Regex patterns for metrics we want to aggregate
RE_L1I_MISS = re.compile(r"L1I-load-misses:\s*(\d+)")
RE_ITLB_MISS = re.compile(r"iTLB-load-misses:\s*(\d+)")
RE_INSTRUCTIONS = re.compile(r"Instructions:\s*(\d+)")
RE_FIXED = re.compile(r"Time\(from fixed freq\):\s*(\d+)\s*ns\s*\|\s*ns/task\(fixed\):\s*([0-9]*\.?[0-9]+)")
RE_FREQ = re.compile(r"Fixed\s+CPU\s+freq:\s*([0-9]*\.?[0-9]+)\s*MHz")


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
    
    # L1I cache misses
    m_l1i = RE_L1I_MISS.search(output)
    if m_l1i:
        m["l1i_misses"] = int(m_l1i.group(1))
    
    # iTLB misses
    m_itlb = RE_ITLB_MISS.search(output)
    if m_itlb:
        m["itlb_misses"] = int(m_itlb.group(1))
    
    # Instructions
    m_insts = RE_INSTRUCTIONS.search(output)
    if m_insts:
        m["instructions"] = int(m_insts.group(1))
    
    # Fixed frequency timing
    m_fixed = RE_FIXED.search(output)
    if m_fixed:
        m["time_ns_fixed"] = int(m_fixed.group(1))
        m["ns_per_task_fixed"] = float(m_fixed.group(2))
    
    # CPU frequency
    m_freq = RE_FREQ.search(output)
    if m_freq:
        m["freq_mhz"] = float(m_freq.group(1))
    
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

    # Print command being executed
    print(f"Command: {args.cmd}")
    print(f"Iterations: {args.iters}")
    print()

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

    # Summary - only report the requested fields
    print(f"Summary (mean ± stdev) over {args.iters} runs:")
    def pr(key, unit="", name=None):
        display_name = name or key
        if key in stats:
            s = stats[key]
            print(f"  {display_name}: {s['mean']:.2f} ± {s['stdev']:.2f}{unit}")
        else:
            print(f"  {display_name}: n/a")

    pr("l1i_misses", "", "L1I cache misses")
    pr("itlb_misses", "", "iTLB misses") 
    pr("instructions", "", "Instructions")
    pr("freq_mhz", " MHz", "CPU frequency")
    pr("time_ns_fixed", " ns", "Time (fixed freq)")
    pr("ns_per_task_fixed", " ns/task", "ns/task (fixed freq)")

if __name__ == "__main__":
    main()
