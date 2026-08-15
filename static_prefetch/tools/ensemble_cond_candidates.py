#!/usr/bin/env python3
"""Compose multiple profile-free COND candidate rankings into one order.

This tool does not read PGO/LBR data. It combines already-generated static
candidate CSVs using either staged prefixes or round-robin prefixes, then
appends tail rankings for broad coverage.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def key(row: dict[str, str]) -> tuple[str, str]:
    return row["target_function"], row["target_cacheline64"]


def parse_mode_count(raw: str) -> tuple[str, int]:
    if ":" not in raw:
        raise argparse.ArgumentTypeError(f"expected MODE:COUNT, got {raw!r}")
    mode, count = raw.split(":", 1)
    try:
        n = int(count, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid count in {raw!r}") from exc
    if not mode or n < 0:
        raise argparse.ArgumentTypeError(f"invalid MODE:COUNT {raw!r}")
    return mode, n


def load_mode_rows(candidate_dir: Path, modes: set[str]) -> tuple[list[str], dict[str, list[dict[str, str]]]]:
    fields: list[str] | None = None
    rows_by_mode: dict[str, list[dict[str, str]]] = {}
    for mode in sorted(modes):
        path = candidate_dir / f"static_cond_{mode}.csv"
        mode_fields, rows = read_rows(path)
        if fields is None:
            fields = mode_fields
        elif fields != mode_fields:
            raise SystemExit(f"field mismatch for {path}")
        rows_by_mode[mode] = rows
    if fields is None:
        raise SystemExit("no modes requested")
    return fields, rows_by_mode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate-dir", type=Path, required=True)
    ap.add_argument("--out-csv", type=Path, required=True)
    ap.add_argument(
        "--stage",
        type=parse_mode_count,
        action="append",
        default=[],
        help="Append top COUNT rows from MODE before the tail, e.g. tail-sparse:5000",
    )
    ap.add_argument(
        "--round-robin",
        default="",
        help="Comma-separated modes to interleave before the tail, e.g. tail-sparse,guard-exit,loop",
    )
    ap.add_argument("--round-robin-limit", type=int, default=0)
    ap.add_argument("--round-robin-chunk", type=int, default=1)
    ap.add_argument(
        "--tail-mode",
        action="append",
        default=[],
        help="Tail mode appended after prefix. May be repeated. Default: span,tail-sparse,guard-exit,small-forward,loop,combined,frontier",
    )
    ap.add_argument("--label", default="ensemble")
    args = ap.parse_args()

    tail_modes = args.tail_mode or [
        "span",
        "tail-sparse",
        "guard-exit",
        "small-forward",
        "loop",
        "combined",
        "frontier",
    ]
    rr_modes = [m.strip() for m in args.round_robin.split(",") if m.strip()]
    if args.round_robin_limit < 0 or args.round_robin_chunk <= 0:
        raise SystemExit("invalid round-robin limit/chunk")

    modes = {m for m, _ in args.stage} | set(rr_modes) | set(tail_modes)
    fields, rows_by_mode = load_mode_rows(args.candidate_dir, modes)

    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(row: dict[str, str]) -> None:
        k = key(row)
        if k in seen:
            return
        seen.add(k)
        out.append(dict(row))

    for mode, count in args.stage:
        for row in rows_by_mode[mode][:count]:
            add(row)

    if rr_modes and args.round_robin_limit > 0:
        pos = {mode: 0 for mode in rr_modes}
        produced = 0
        while produced < args.round_robin_limit:
            progressed = False
            for mode in rr_modes:
                added = 0
                rows = rows_by_mode[mode]
                while pos[mode] < len(rows) and added < args.round_robin_chunk and produced < args.round_robin_limit:
                    row = rows[pos[mode]]
                    pos[mode] += 1
                    before = len(out)
                    add(row)
                    if len(out) != before:
                        added += 1
                        produced += 1
                        progressed = True
            if not progressed:
                break

    for mode in tail_modes:
        for row in rows_by_mode[mode]:
            add(row)

    total = len(out)
    for idx, row in enumerate(out, 1):
        row["rank"] = str(idx)
        row["mode"] = args.label
        row["score"] = f"{float(total - idx):.9f}"

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out)
    print(f"[ok] wrote {args.out_csv} rows={len(out)} label={args.label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
