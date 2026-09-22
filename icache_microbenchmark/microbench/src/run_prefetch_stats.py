#!/usr/bin/env python3
"""
Build prefetch_test at -O1, run the CSV harness, and summarize p50 deltas.

Usage:
    python3 run_prefetch_stats.py [iterations] [evict_kib] [cpu] [output_csv]
"""

import csv
import io
import os
import subprocess
import sys


def compile_prefetch_test():
    arch = os.environ.get("ARCH", "graniterapids")
    cmd = [
        "clang",
        "-O1",
        f"-march={arch}",
        "-m64",
        "-no-pie",
        "-fno-plt",
        "-mprefetchi",
        "prefetch_test.c",
        "utils.c",
        "-o",
        "prefetch_test",
    ]
    subprocess.run(cmd, check=True)


def run_prefetch_test(iterations, evict_kib, cpu):
    result = subprocess.run(
        ["./prefetch_test", str(iterations), str(evict_kib), str(cpu)],
        capture_output=True,
        text=True,
        check=True,
    )
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result.stdout


def parse_rows(csv_text):
    rows = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        for field in ("mean", "min", "p05", "p25", "p50", "p75", "p95", "p99", "max"):
            row[field] = float(row[field])
        rows.append(row)
    return rows


def print_summary(rows):
    by_delay = {}
    for row in rows:
        by_delay.setdefault(row["delay"], {})[row["strategy"]] = row

    print("Best p50 improvements vs baseline")
    print("delay,strategy,baseline_p50,p50,gain,mean,p95,ideal_actual_p50")
    for delay, strategies in by_delay.items():
        baseline = strategies.get("baseline")
        actual = strategies.get("actual_exec_warm")
        if not baseline:
            continue

        candidates = [
            row for name, row in strategies.items()
            if name not in ("baseline", "actual_exec_warm")
        ]
        if not candidates:
            continue

        best = max(candidates, key=lambda row: baseline["p50"] - row["p50"])
        gain = baseline["p50"] - best["p50"]
        ideal = actual["p50"] if actual else 0.0
        print(
            f"{delay},{best['strategy']},{baseline['p50']:.0f},"
            f"{best['p50']:.0f},{gain:.0f},{best['mean']:.2f},"
            f"{best['p95']:.0f},{ideal:.0f}"
        )

    print()
    print("Best PREFETCHI vs PREFETCHT by delay")
    print("delay,baseline_p50,actual_p50,best_prefetchi,prefetchi_p50,best_prefetcht,prefetcht_p50,winner")
    for delay, strategies in by_delay.items():
        baseline = strategies.get("baseline")
        actual = strategies.get("actual_exec_warm")
        if not baseline:
            continue

        prefetchi = [
            row for name, row in strategies.items()
            if name.startswith("prefetchi_")
        ]
        prefetcht = [
            row for name, row in strategies.items()
            if name.startswith("prefetcht_")
        ]
        if not prefetchi or not prefetcht:
            continue

        best_i = min(prefetchi, key=lambda row: row["p50"])
        best_t = min(prefetcht, key=lambda row: row["p50"])
        if best_i["p50"] < best_t["p50"]:
            winner = "prefetchi"
        elif best_t["p50"] < best_i["p50"]:
            winner = "prefetcht"
        else:
            winner = "tie"

        print(
            f"{delay},{baseline['p50']:.0f},{actual['p50'] if actual else 0:.0f},"
            f"{best_i['strategy']},{best_i['p50']:.0f},"
            f"{best_t['strategy']},{best_t['p50']:.0f},{winner}"
        )


def main():
    iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    evict_kib = int(sys.argv[2]) if len(sys.argv) > 2 else 1024
    cpu = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    output_csv = sys.argv[4] if len(sys.argv) > 4 else None

    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    compile_prefetch_test()
    csv_text = run_prefetch_test(iterations, evict_kib, cpu)

    if output_csv:
        with open(output_csv, "w", encoding="utf-8") as out:
            out.write(csv_text)

    print_summary(parse_rows(csv_text))


if __name__ == "__main__":
    main()
