#!/usr/bin/env python3
"""Snapshot Linux per-thread CPU accounting for a running process."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def status_fields(path: Path) -> dict[str, str]:
    fields = {}
    for line in path.read_text(errors="replace").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key] = value.strip()
    return fields


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pid", type=int)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    task_root = Path(f"/proc/{args.pid}/task")
    rows = []
    for task in sorted(task_root.iterdir(), key=lambda path: int(path.name)):
        try:
            raw_stat = (task / "stat").read_text()
            close = raw_stat.rfind(")")
            comm = raw_stat[raw_stat.find("(") + 1 : close]
            fields = raw_stat[close + 2 :].split()
            schedstat = [int(value) for value in (task / "schedstat").read_text().split()]
            status = status_fields(task / "status")
        except (FileNotFoundError, ProcessLookupError):
            continue
        rows.append(
            {
                "pid": args.pid,
                "tid": int(task.name),
                "comm": comm,
                "state": fields[0],
                "processor": int(fields[36]),
                "allowed_list": status.get("Cpus_allowed_list", ""),
                "utime_ticks": int(fields[11]),
                "stime_ticks": int(fields[12]),
                "total_ticks": int(fields[11]) + int(fields[12]),
                "runtime_ns": schedstat[0],
                "runqueue_wait_ns": schedstat[1],
                "timeslices": schedstat[2],
                "voluntary_context_switches": int(
                    status.get("voluntary_ctxt_switches", "0")
                ),
                "nonvoluntary_context_switches": int(
                    status.get("nonvoluntary_ctxt_switches", "0")
                ),
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "pid",
        "tid",
        "comm",
        "state",
        "processor",
        "allowed_list",
        "utime_ticks",
        "stime_ticks",
        "total_ticks",
        "runtime_ns",
        "runqueue_wait_ns",
        "timeslices",
        "voluntary_context_switches",
        "nonvoluntary_context_switches",
    ]
    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
