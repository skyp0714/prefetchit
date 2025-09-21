#!/usr/bin/env python3
"""
Script to compile and run prefetch_test multiple times and calculate statistics.
Usage: python3 run_prefetch_stats.py [iterations]
"""

import subprocess
import sys
import re
import statistics
import os

def compile_prefetch_test():
    """Compile the prefetch_test program."""
    try:
        cmd = [
            "gcc",
            "-march=graniterapids",
            "-m64",
            "-no-pie",
            "-fno-plt",
            "-mprefetchi",
            "prefetch_test.c",
            "utils.c",
            "-o",
            "prefetch_test"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Compilation failed:")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        return False

def run_prefetch_test():
    """Run prefetch_test once and extract metrics."""
    try:
        result = subprocess.run(["./prefetch_test"], capture_output=True, text=True, check=True)

        metrics = {}

        # Parse execution time
        for line in result.stdout.split('\n'):
            if "execution time:" in line and "cycles" in line:
                match = re.search(r'execution time:\s*(\d+)\s*cycles', line)
                if match:
                    metrics['cycles'] = int(match.group(1))

            # Parse L1I misses
            elif line.startswith("L1I-load-misses:") and "MPKI=" in line:
                match = re.search(r'L1I-load-misses:\s*(\d+)', line)
                if match:
                    metrics['l1i_misses'] = int(match.group(1))

            # Parse iTLB misses
            elif line.startswith("iTLB-load-misses:") and "MPKI=" in line:
                match = re.search(r'iTLB-load-misses:\s*(\d+)', line)
                if match:
                    metrics['itlb_misses'] = int(match.group(1))

            # Parse L2 misses
            elif line.startswith("L2-misses:") and "MPKI=" in line:
                match = re.search(r'L2-misses:\s*(\d+)', line)
                if match:
                    metrics['l2_misses'] = int(match.group(1))

        if 'cycles' not in metrics:
            print(f"Warning: Could not find execution time in output:")
            print(result.stdout)
            return None

        return metrics

    except subprocess.CalledProcessError as e:
        print(f"Error running prefetch_test:")
        print(f"Return code: {e.returncode}")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        return None

def main():
    # Parse command line arguments
    iterations = 100  # default
    if len(sys.argv) > 1:
        try:
            iterations = int(sys.argv[1])
        except ValueError:
            print(f"Error: Invalid number of iterations '{sys.argv[1]}'")
            sys.exit(1)

    print(f"Running prefetch_test statistics with {iterations} iterations")
    print("=" * 60)

    # Change to the script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    # Check if we need root privileges for optimal results
    if os.geteuid() != 0:
        print("⚠️  Warning: Running without root privileges.")
        print("   For best results, run with sudo for CPU frequency locking.")
        print()

    # Run the test multiple times (compile + run each iteration)
    print(f"Running {iterations} iterations (recompiling each time)...")
    metrics_list = []
    failed_runs = 0
    compilation_failures = 0

    for i in range(iterations):
        if (i + 1) % 10 == 0 or i == 0:
            print(f"  Progress: {i + 1}/{iterations}")

        # Recompile for each iteration
        if not compile_prefetch_test():
            compilation_failures += 1
            print(f"  Compilation failed on iteration {i + 1}")
            if compilation_failures > 3:  # Stop if too many compilation failures
                print(f"Too many compilation failures ({compilation_failures}). Stopping.")
                break
            continue

        metrics = run_prefetch_test()
        if metrics is not None:
            metrics_list.append(metrics)
        else:
            failed_runs += 1
            if failed_runs > 5:  # Stop if too many failures
                print(f"Too many failed runs ({failed_runs}). Stopping.")
                break

    if not metrics_list:
        print("No successful runs. Exiting.")
        sys.exit(1)

    # Calculate statistics
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    successful_runs = len(metrics_list)
    print(f"Successful runs:     {successful_runs}/{iterations}")
    if failed_runs > 0:
        print(f"Failed runs:         {failed_runs}")
    if compilation_failures > 0:
        print(f"Compilation failures: {compilation_failures}")
    print()

    # Extract metric arrays
    cycles_list = [m['cycles'] for m in metrics_list]
    l1i_list = [m.get('l1i_misses', 0) for m in metrics_list]
    itlb_list = [m.get('itlb_misses', 0) for m in metrics_list]
    l2_list = [m.get('l2_misses', 0) for m in metrics_list]

    def calc_stats(values):
        """Calculate mean, stdev, and 99th percentile for a metric."""
        if not values:
            return "      N/A ", "      N/A ", "      N/A "

        mean_val = statistics.mean(values)
        stdev_val = statistics.stdev(values) if len(values) > 1 else 0.0
        sorted_vals = sorted(values)
        p99_idx = int(len(sorted_vals) * 0.99)
        p99_val = sorted_vals[p99_idx] if p99_idx < len(sorted_vals) else sorted_vals[-1]

        return f"{mean_val:10.2f}", f"{stdev_val:10.2f}", f"{p99_val:10.2f}"

    # Calculate statistics for each metric
    cycles_mean, cycles_std, cycles_99p = calc_stats(cycles_list)
    l1i_mean, l1i_std, l1i_99p = calc_stats(l1i_list)
    itlb_mean, itlb_std, itlb_99p = calc_stats(itlb_list)
    l2_mean, l2_std, l2_99p = calc_stats(l2_list)

    # Print table header
    print("Metric                    Mean     StdDev        99p")
    print("-" * 52)

    # Print table rows
    print(f"Execution Time (cyc) {cycles_mean} {cycles_std} {cycles_99p}")
    print(f"L1I Misses           {l1i_mean} {l1i_std} {l1i_99p}")
    print(f"iTLB Misses          {itlb_mean} {itlb_std} {itlb_99p}")
    print(f"L2 Misses            {l2_mean} {l2_std} {l2_99p}")

    # Raw data for analysis (optional)
    if len(sys.argv) > 2 and sys.argv[2] == "--raw":
        print(f"\nRaw data ({successful_runs} runs):")
        for i, m in enumerate(metrics_list):
            print(f"  Run {i+1}: {m}")

if __name__ == "__main__":
    main()