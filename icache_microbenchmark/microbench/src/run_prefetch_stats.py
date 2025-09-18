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
    """Run prefetch_test once and extract the execution time cycles."""
    try:
        result = subprocess.run(["./prefetch_test"], capture_output=True, text=True, check=True)

        # Look for the execution time line in the output
        # Expected format: "bar(1) execution time: XXXXX cycles"
        for line in result.stdout.split('\n'):
            if "execution time:" in line and "cycles" in line:
                # Extract the number using regex
                match = re.search(r'execution time:\s*(\d+)\s*cycles', line)
                if match:
                    return int(match.group(1))

        print(f"Warning: Could not find execution time in output:")
        print(result.stdout)
        return None

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
    cycles_list = []
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

        cycles = run_prefetch_test()
        if cycles is not None:
            cycles_list.append(cycles)
        else:
            failed_runs += 1
            if failed_runs > 5:  # Stop if too many failures
                print(f"Too many failed runs ({failed_runs}). Stopping.")
                break

    if not cycles_list:
        print("No successful runs. Exiting.")
        sys.exit(1)

    # Calculate statistics
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    mean_cycles = statistics.mean(cycles_list)
    median_cycles = statistics.median(cycles_list)
    min_cycles = min(cycles_list)
    max_cycles = max(cycles_list)

    if len(cycles_list) > 1:
        stdev_cycles = statistics.stdev(cycles_list)
        variance_cycles = statistics.variance(cycles_list)
    else:
        stdev_cycles = 0
        variance_cycles = 0

    successful_runs = len(cycles_list)

    print(f"Successful runs:     {successful_runs}/{iterations}")
    if failed_runs > 0:
        print(f"Failed runs:         {failed_runs}")
    if compilation_failures > 0:
        print(f"Compilation failures: {compilation_failures}")
    print()
    print(f"Mean execution time: {mean_cycles:.2f} cycles")
    print(f"Median:              {median_cycles:.2f} cycles")
    print(f"Standard deviation:  {stdev_cycles:.2f} cycles")
    print(f"Variance:            {variance_cycles:.2f}")
    print(f"Min:                 {min_cycles} cycles")
    print(f"Max:                 {max_cycles} cycles")
    print(f"Range:               {max_cycles - min_cycles} cycles")

    if successful_runs > 1:
        cv = (stdev_cycles / mean_cycles) * 100  # Coefficient of variation
        print(f"Coefficient of var:  {cv:.2f}%")

    # Additional statistics
    if successful_runs >= 10:
        print("\nPercentiles:")
        for p in [10, 25, 75, 90, 95, 99]:
            if successful_runs > p:
                percentile_val = sorted(cycles_list)[int(successful_runs * p / 100)]
                print(f"  {p}th percentile:    {percentile_val} cycles")

    # Raw data for analysis (optional)
    if len(sys.argv) > 2 and sys.argv[2] == "--raw":
        print(f"\nRaw data ({successful_runs} values):")
        print(cycles_list)

if __name__ == "__main__":
    main()