#!/usr/bin/env python3
import argparse
import subprocess
import sys
import re
import shlex
from statistics import mean, variance, stdev
from collections import defaultdict

# Flexible metric patterns - order independent parsing
METRIC_PATTERNS = {
    # Cache and instruction metrics
    'l1i_misses': re.compile(r"L1I-load-misses:\s*(\d+)"),
    'itlb_misses': re.compile(r"iTLB-load-misses:\s*(\d+)"),
    'instructions': re.compile(r"Instructions:\s*(\d+)"),
    
    # MPKI metrics (optional)
    'l1i_mpki': re.compile(r"L1I-load-misses:.*MPKI=([0-9]*\.?[0-9]+)"),
    'itlb_mpki': re.compile(r"iTLB-load-misses:.*MPKI=([0-9]*\.?[0-9]+)"),
    
    # Timing metrics  
    'time_monotonic_ns': re.compile(r"Time\(monotonic\):\s*(\d+)\s*ns"),
    'tsc_cycles': re.compile(r"TSC:\s*(\d+)\s*cycles"),
    'cycles_per_ns_raw': re.compile(r"Raw\s+Cycles/ns:\s*([0-9]*\.?[0-9]+)"),
    'ns_per_task_raw': re.compile(r"ns/task\(raw\):\s*([0-9]*\.?[0-9]+)"),
    
    # Fixed frequency metrics (optional)
    'time_ns_fixed': re.compile(r"Time\(from fixed freq\):\s*(\d+)\s*ns"),
    'ns_per_task_fixed': re.compile(r"ns/task\(fixed\):\s*([0-9]*\.?[0-9]+)"),
    'freq_mhz': re.compile(r"Fixed\s+CPU\s+freq:\s*([0-9]*\.?[0-9]+)\s*MHz"),
}


def run_once(cmd: str):
    # Run one iteration, capture combined stdout+stderr (bench prints to both)
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out, _ = proc.communicate()
    rc = proc.returncode
    if rc != 0:
        print(f"WARN: command exited with {rc}")
    return out


def parse_metrics(output: str):
    """Parse all available metrics from output using flexible regex patterns"""
    metrics = {}
    
    # Try to match each metric pattern
    for metric_name, pattern in METRIC_PATTERNS.items():
        match = pattern.search(output)
        if match:
            try:
                # Convert to appropriate type
                value = match.group(1)
                if '.' in value or 'mpki' in metric_name or 'cycles_per_ns' in metric_name or 'ns_per_task' in metric_name:
                    metrics[metric_name] = float(value)
                else:
                    metrics[metric_name] = int(value)
            except (ValueError, IndexError):
                continue  # Skip invalid matches
    
    return metrics


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
    ap.add_argument("--cmd", default="./lat_bench 1 256 28 1", help="Command to execute per run (use quotes). Include 'sudo ' if needed.")
    ap.add_argument("--iters", type=int, default=1000, help="Number of iterations")
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

    # Summary - dynamically show all available metrics
    print(f"Summary (mean ± stdev) over {args.iters} runs:")
    
    # Define display order and names for metrics
    METRIC_DISPLAY = {
        'l1i_misses': ('L1I cache misses', ''),
        'itlb_misses': ('iTLB misses', ''), 
        'instructions': ('Instructions', ''),
        'l1i_mpki': ('L1I MPKI', ''),
        'itlb_mpki': ('iTLB MPKI', ''),
        'time_monotonic_ns': ('Time (monotonic)', ' ns'),
        'tsc_cycles': ('TSC cycles', ''),
        'cycles_per_ns_raw': ('Cycles/ns (raw)', ''),
        'ns_per_task_raw': ('ns/task (raw)', ' ns'),
        'freq_mhz': ('CPU frequency', ' MHz'),
        'time_ns_fixed': ('Time (fixed freq)', ' ns'),
        'ns_per_task_fixed': ('ns/task (fixed freq)', ' ns'),
    }
    
    # Show metrics in preferred order, but only if available
    for metric_key, (display_name, unit) in METRIC_DISPLAY.items():
        if metric_key in stats:
            s = stats[metric_key]
            print(f"  {display_name}: {s['mean']:.2f} ± {s['stdev']:.2f}{unit}")
    
    # Show any additional metrics not in the display list
    shown_keys = set(METRIC_DISPLAY.keys())
    for metric_key in sorted(stats.keys()):
        if metric_key not in shown_keys:
            s = stats[metric_key]
            print(f"  {metric_key}: {s['mean']:.2f} ± {s['stdev']:.2f}")

if __name__ == "__main__":
    main()
