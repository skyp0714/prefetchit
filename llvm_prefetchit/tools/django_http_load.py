#!/usr/bin/env python3
"""Deterministic single-connection load generator for DCPerf Django."""

from __future__ import annotations

import argparse
import http.client
import json
import random
import statistics
import time
from collections import Counter
from pathlib import Path


WEIGHTED_ROUTES = (
    ["feed_timeline"] * 30
    + ["timeline"] * 30
    + ["bundle_tray"] * 15
    + ["inbox"] * 20
    + ["seen"] * 5
)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--seen-body", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    seen_body = args.seen_body.read_bytes()
    rng = random.Random(args.seed)
    routes = list(WEIGHTED_ROUTES)
    rng.shuffle(routes)
    route_index = 0
    route_completed: Counter[str] = Counter()
    status_counts: Counter[int] = Counter()
    latencies: list[float] = []
    attempts = completed = failed = 0
    connection = http.client.HTTPConnection(args.host, args.port, timeout=10)
    started = time.monotonic()
    deadline = started + args.duration

    while time.monotonic() < deadline:
        route = routes[route_index]
        route_index += 1
        if route_index == len(routes):
            route_index = 0
            rng.shuffle(routes)
        attempts += 1
        request_started = time.monotonic()
        request_finished = False
        for _retry in range(2):
            try:
                if route == "seen":
                    connection.request(
                        "POST",
                        "/seen",
                        body=seen_body,
                        headers={"Content-Type": "application/json"},
                    )
                else:
                    connection.request("GET", f"/{route}")
                response = connection.getresponse()
                response.read()
                status_counts[response.status] += 1
                if response.status == 200:
                    completed += 1
                    route_completed[route] += 1
                    latencies.append(time.monotonic() - request_started)
                else:
                    failed += 1
                request_finished = True
                break
            except (OSError, http.client.HTTPException):
                connection.close()
                connection = http.client.HTTPConnection(
                    args.host, args.port, timeout=10
                )
        if not request_finished:
            failed += 1

    elapsed = time.monotonic() - started
    connection.close()
    result = {
        "attempts": attempts,
        "completed": completed,
        "failed": failed,
        "elapsed_time_s": elapsed,
        "completed_qps": completed / elapsed if elapsed else 0.0,
        "availability_pct": completed / attempts * 100.0 if attempts else 0.0,
        "mean_response_time_s": statistics.fmean(latencies) if latencies else 0.0,
        "p50_response_time_s": percentile(latencies, 0.50),
        "p95_response_time_s": percentile(latencies, 0.95),
        "p99_response_time_s": percentile(latencies, 0.99),
        "route_completed": dict(sorted(route_completed.items())),
        "status_counts": {str(key): value for key, value in sorted(status_counts.items())},
        "seed": args.seed,
        "thread_count": 1,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if completed > 0 and failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
