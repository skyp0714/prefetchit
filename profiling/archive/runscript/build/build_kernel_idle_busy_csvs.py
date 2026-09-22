#!/usr/bin/env python3
import argparse
import csv
from pathlib import Path


def parse_perf_raw(path: Path, event_names: set[str]) -> dict[int, dict[str, float]]:
    by_cpu: dict[int, dict[str, float]] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = raw.split(",")
        if len(parts) < 4:
            continue
        cpu_tok = parts[0].strip()
        value_tok = parts[1].strip().replace(" ", "")
        event_tok = parts[3].strip()
        if not cpu_tok.startswith("CPU"):
            continue
        if event_tok not in event_names:
            continue
        if value_tok.startswith("<") or value_tok in ("notcounted", "not-counted", "not", "notsupported"):
            continue
        try:
            cpu = int(cpu_tok[3:])
            value = float(value_tok)
        except ValueError:
            continue
        by_cpu.setdefault(cpu, {})
        by_cpu[cpu][event_tok] = value
    return by_cpu


def mpki(count: float, inst: float) -> float:
    if inst <= 0.0:
        return 0.0
    return (count * 1000.0) / inst


def build_scenario_rows(
    scenario: str,
    per_cpu: dict[int, dict[str, float]],
    e0: str,
    e1: str,
    e2: str,
    e3: str,
) -> tuple[list[dict[str, object]], dict[str, float]]:
    cpus = sorted(per_cpu.keys())
    rows: list[dict[str, object]] = []

    total_inst = 0.0
    total_e0 = 0.0
    total_e1 = 0.0
    total_e2 = 0.0
    total_e3 = 0.0
    for cpu in cpus:
        d = per_cpu[cpu]
        inst = float(d.get("instructions", 0.0))
        c0 = float(d.get(e0, 0.0))
        c1 = float(d.get(e1, 0.0))
        c2 = float(d.get(e2, 0.0))
        c3 = float(d.get(e3, 0.0))
        total_inst += inst
        total_e0 += c0
        total_e1 += c1
        total_e2 += c2
        total_e3 += c3

        rows.append(
            {
                "Scenario": scenario,
                "CPU": cpu,
                "Instructions": inst,
                "Event0": c0,
                "Event1": c1,
                "Event2": c2,
                "Event3": c3,
                "L1I_MPKI": mpki(c0, inst),
                "L2I_MPKI": mpki(c1, inst),
                "iTLB_MPKI": mpki(c2 + c3, inst),
                "sTLB_MPKI": mpki(c2, inst),
            }
        )

    summary = {
        "Instructions": total_inst,
        "Event0": total_e0,
        "Event1": total_e1,
        "Event2": total_e2,
        "Event3": total_e3,
        "L1I_MPKI": mpki(total_e0, total_inst),
        "L2I_MPKI": mpki(total_e1, total_inst),
        "iTLB_MPKI": mpki(total_e2 + total_e3, total_inst),
        "sTLB_MPKI": mpki(total_e2, total_inst),
    }
    return rows, summary


def write_main_csv(
    out_csv: Path,
    cores: str,
    idle_secs: int,
    busy_secs: int,
    idle_summary: dict[str, float],
    busy_summary: dict[str, float],
    idle_raw: Path,
    busy_raw: Path,
    busy_log: str,
) -> None:
    fields = [
        "Scenario",
        "Cores",
        "Scope",
        "MeasureSec",
        "Instructions",
        "Event0",
        "Event1",
        "Event2",
        "Event3",
        "L1I_MPKI",
        "L2I_MPKI",
        "iTLB_MPKI",
        "sTLB_MPKI",
        "PerfRaw",
        "WorkloadLog",
    ]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerow(
            {
                "Scenario": "kernel_idle",
                "Cores": cores,
                "Scope": "kernel_only",
                "MeasureSec": idle_secs,
                **idle_summary,
                "PerfRaw": str(idle_raw),
                "WorkloadLog": "",
            }
        )
        w.writerow(
            {
                "Scenario": "kernel_busy",
                "Cores": cores,
                "Scope": "kernel_only",
                "MeasureSec": busy_secs,
                **busy_summary,
                "PerfRaw": str(busy_raw),
                "WorkloadLog": busy_log,
            }
        )


def write_percore_csv(
    out_csv: Path,
    idle_rows: list[dict[str, object]],
    busy_rows: list[dict[str, object]],
    idle_summary: dict[str, float],
    busy_summary: dict[str, float],
) -> None:
    fields = [
        "Scenario",
        "CPU",
        "Instructions",
        "Event0",
        "Event1",
        "Event2",
        "Event3",
        "L1I_MPKI",
        "L2I_MPKI",
        "iTLB_MPKI",
        "sTLB_MPKI",
        "System_L1I_MPKI",
        "System_L2I_MPKI",
        "System_iTLB_MPKI",
        "System_sTLB_MPKI",
    ]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in idle_rows:
            w.writerow(
                {
                    **row,
                    "System_L1I_MPKI": idle_summary["L1I_MPKI"],
                    "System_L2I_MPKI": idle_summary["L2I_MPKI"],
                    "System_iTLB_MPKI": idle_summary["iTLB_MPKI"],
                    "System_sTLB_MPKI": idle_summary["sTLB_MPKI"],
                }
            )
        for row in busy_rows:
            w.writerow(
                {
                    **row,
                    "System_L1I_MPKI": busy_summary["L1I_MPKI"],
                    "System_L2I_MPKI": busy_summary["L2I_MPKI"],
                    "System_iTLB_MPKI": busy_summary["iTLB_MPKI"],
                    "System_sTLB_MPKI": busy_summary["sTLB_MPKI"],
                }
            )


def main() -> None:
    ap = argparse.ArgumentParser(description="Build kernel idle/busy system + per-core CSVs from perf -A raw files")
    ap.add_argument("--idle-raw", required=True)
    ap.add_argument("--busy-raw", required=True)
    ap.add_argument("--cores", required=True)
    ap.add_argument("--idle-secs", required=True, type=int)
    ap.add_argument("--busy-secs", required=True, type=int)
    ap.add_argument("--event0", required=True)
    ap.add_argument("--event1", required=True)
    ap.add_argument("--event2", required=True)
    ap.add_argument("--event3", required=True)
    ap.add_argument("--main-csv", required=True)
    ap.add_argument("--percore-csv", required=True)
    ap.add_argument("--busy-log", default="")
    args = ap.parse_args()

    event_names = {"instructions", args.event0, args.event1, args.event2, args.event3}
    idle_per_cpu = parse_perf_raw(Path(args.idle_raw), event_names)
    busy_per_cpu = parse_perf_raw(Path(args.busy_raw), event_names)

    idle_rows, idle_summary = build_scenario_rows(
        "kernel_idle", idle_per_cpu, args.event0, args.event1, args.event2, args.event3
    )
    busy_rows, busy_summary = build_scenario_rows(
        "kernel_busy", busy_per_cpu, args.event0, args.event1, args.event2, args.event3
    )

    write_main_csv(
        Path(args.main_csv),
        args.cores,
        args.idle_secs,
        args.busy_secs,
        idle_summary,
        busy_summary,
        Path(args.idle_raw),
        Path(args.busy_raw),
        args.busy_log,
    )
    write_percore_csv(Path(args.percore_csv), idle_rows, busy_rows, idle_summary, busy_summary)

    print(f"[ok] saved {args.main_csv}")
    print(f"[ok] saved {args.percore_csv}")


if __name__ == "__main__":
    main()
