#!/usr/bin/env python3
"""Debug script to see what the Python subprocess captures vs manual run"""

import subprocess
import re

METRIC_PATTERNS = {
    'l1i_misses': re.compile(r"L1I-load-misses:\s*(\d+)"),
    'l1i_mpki': re.compile(r"L1I-load-misses:.*MPKI=([0-9]*\.?[0-9]+)"),
    'l1i_miss_rate': re.compile(r"L1I-load-misses:.*Miss-Rate=([0-9]*\.?[0-9]+)%"),
    'itlb_misses': re.compile(r"iTLB-load-misses:\s*(\d+)"),
    'itlb_mpki': re.compile(r"iTLB-load-misses:.*MPKI=([0-9]*\.?[0-9]+)"),
    'itlb_miss_rate': re.compile(r"iTLB-load-misses:.*Miss-Rate=([0-9]*\.?[0-9]+)%"),
    'instructions': re.compile(r"Instructions:\s*(\d+)"),
    'time_ns': re.compile(r"Time\(roi\):\s*(\d+)\s*ns"),
    'tsc_cycles': re.compile(r"TSC:\s*(\d+)\s*cycles"),
}

def run_command(cmd):
    """Run a command and capture its output"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        print(f"Return code: {result.returncode}")
        print(f"STDOUT:\n{result.stdout}")
        print(f"STDERR:\n{result.stderr}")
        return result.stdout + result.stderr
    except Exception as e:
        print(f"Exception: {e}")
        return None

def parse_metrics(output):
    """Parse metrics from benchmark output"""
    metrics = {}
    if not output:
        return metrics
        
    for metric_name, pattern in METRIC_PATTERNS.items():
        match = pattern.search(output)
        if match:
            try:
                value = match.group(1)
                if 'rate' in metric_name or 'mpki' in metric_name:
                    metrics[metric_name] = float(value)
                else:
                    metrics[metric_name] = int(value) if '.' not in value else float(value)
            except (ValueError, IndexError):
                continue
    
    return metrics

def main():
    # First, test if we can run the commands at all
    print("=== Testing current directory and files ===")
    test_cmd = "ls -la lat_bench*perf"
    print(f"Running: {test_cmd}")
    output = run_command(test_cmd)
    
    print("=== Testing lat_bench_perf (manual reproduction) ===")
    print("Please run manually in another terminal and compare:")
    print("sudo ./lat_bench_perf 10 4096")
    print("sudo ./lat_bench_prefetch_perf 10 4096")
    print()
    
    # Try to run a single iteration to see what happens
    import time
    print("Waiting 3 seconds for you to set up sudo credentials...")
    time.sleep(3)
    
    cmd = "sudo ./lat_bench_perf 10 4096"
    print(f"Attempting: {cmd}")
    output = run_command(cmd)
    
    if output:
        print(f"\nCombined output:\n{output}")
        metrics = parse_metrics(output)
        print(f"\nParsed metrics:")
        for k, v in metrics.items():
            print(f"  {k}: {v}")

if __name__ == "__main__":
    main()