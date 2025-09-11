#!/usr/bin/env python3
"""
Sweep script to compare lat_bench_perf vs lat_bench_prefetch_perf
across different round counts, saving results to CSV files.
"""

import subprocess
import re
import csv
import os
import time
from statistics import mean, stdev
from collections import defaultdict
import pandas as pd

# Metric patterns for parsing output
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
        if result.returncode != 0:
            print(f"WARNING: Command failed with return code {result.returncode}")
            print(f"STDERR: {result.stderr}")
            return None
        # Combine stdout and stderr as the benchmark prints to both
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        print(f"WARNING: Command timed out: {cmd}")
        return None
    except Exception as e:
        print(f"WARNING: Command failed with exception: {e}")
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

def run_experiment(executable, rounds, qlen, iterations=10):
    """Run the experiment for given parameters"""
    cmd = f"sudo ./{executable} {rounds} {qlen}"
    results = []
    
    print(f"Running {iterations} iterations of: {cmd}")
    
    for i in range(iterations):
        if (i + 1) % 10 == 0:
            print(f"  Progress: {i + 1}/{iterations}")
            
        output = run_command(cmd)
        metrics = parse_metrics(output)
        
        if metrics:
            metrics['executable'] = executable
            metrics['rounds'] = rounds
            metrics['qlen'] = qlen
            metrics['iteration'] = i + 1
            results.append(metrics)
        else:
            print(f"  WARNING: Failed to parse metrics for iteration {i + 1}")
        
        # Sleep for 1 second between executions to let system settle
        time.sleep(1)
    
    return results

def compute_statistics(data, group_by):
    """Compute mean and std dev for grouped data"""
    grouped = defaultdict(list)
    
    # Group data
    for row in data:
        key = tuple(row[col] for col in group_by)
        grouped[key].append(row)
    
    stats = []
    for key, group in grouped.items():
        stat_row = {}
        for i, col in enumerate(group_by):
            stat_row[col] = key[i]
        
        # Compute statistics for numeric columns
        numeric_cols = ['l1i_misses', 'l1i_mpki', 'l1i_miss_rate', 
                       'itlb_misses', 'itlb_mpki', 'itlb_miss_rate',
                       'instructions', 'time_ns', 'tsc_cycles']
        
        for col in numeric_cols:
            values = [row[col] for row in group if col in row]
            if values:
                stat_row[f'{col}_mean'] = mean(values)
                stat_row[f'{col}_std'] = stdev(values) if len(values) > 1 else 0.0
                stat_row[f'{col}_count'] = len(values)
        
        stats.append(stat_row)
    
    return stats

def main():
    # Use existing result directory
    results_dir = "../result"
    os.makedirs(results_dir, exist_ok=True)
    
    # Configuration
    executables = ['lat_bench_perf', 'lat_bench_prefetch_perf']
    rounds_list = [10]#list(range(0, 16, 1))[1:]  # 1, 10, 20, 30, ..., 90, 100
    qlen = 4096
    iterations = 1
    
    print("Starting sweep experiment...")
    print(f"Executables: {executables}")
    print(f"Rounds: {rounds_list}")
    print(f"Queue length: {qlen}")
    print(f"Iterations per configuration: {iterations}")
    print()
    
    all_raw_data = []
    
    # Run experiments
    for executable in executables:
        for rounds in rounds_list:
            print(f"\n=== {executable} with {rounds} rounds ===")
            results = run_experiment(executable, rounds, qlen, iterations)
            all_raw_data.extend(results)
            print(f"Collected {len(results)} valid results")
    
    if not all_raw_data:
        print("ERROR: No data collected!")
        return
    
    print(f"\nCollected {len(all_raw_data)} total data points")
    
    # Convert to DataFrame for easier manipulation
    df_raw = pd.DataFrame(all_raw_data)
    
    # Compute statistics
    print("Computing statistics...")
    stats_data = compute_statistics(all_raw_data, ['executable', 'rounds', 'qlen'])
    df_stats = pd.DataFrame(stats_data)
    
    # Save raw data to CSV
    raw_csv_path = os.path.join(results_dir, 'raw_sweep_data.csv')
    df_raw.to_csv(raw_csv_path, index=False)
    print(f"Raw data saved to: {raw_csv_path}")
    
    # Save statistics to CSV
    stats_csv_path = os.path.join(results_dir, 'sweep_statistics.csv')
    df_stats.to_csv(stats_csv_path, index=False)
    print(f"Statistics saved to: {stats_csv_path}")
    
    # Create Excel file with two sheets
    excel_path = os.path.join(results_dir, 'sweep_comparison.xlsx')
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        df_raw.to_excel(writer, sheet_name='Raw Data', index=False)
        df_stats.to_excel(writer, sheet_name='Statistics', index=False)
    print(f"Excel file saved to: {excel_path}")
    
    # Print summary
    print("\n=== Summary ===")
    print("Key metrics comparison (mean values):")
    
    for rounds in sorted(df_stats['rounds'].unique()):
        print(f"\nRounds = {rounds}:")
        subset = df_stats[df_stats['rounds'] == rounds]
        
        for _, row in subset.iterrows():
            exec_name = row['executable']
            l1i_misses = row.get('l1i_misses_mean', 0)
            itlb_misses = row.get('itlb_misses_mean', 0)
            l1i_rate = row.get('l1i_miss_rate_mean', 0)
            itlb_rate = row.get('itlb_miss_rate_mean', 0)
            time_ns = row.get('time_ns_mean', 0)
            
            print(f"  {exec_name}:")
            print(f"    L1I misses: {l1i_misses:.0f} ({l1i_rate:.4f}%)")
            print(f"    iTLB misses: {itlb_misses:.0f} ({itlb_rate:.4f}%)")
            print(f"    Runtime: {time_ns/1e6:.1f} ms")

if __name__ == "__main__":
    main()