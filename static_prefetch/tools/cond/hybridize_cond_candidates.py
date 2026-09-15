#!/usr/bin/env python3
"""Build a two-stage static COND candidate order from two static rankings."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def target_key(row: dict[str, str]) -> tuple[str, str]:
    return row["target_function"], row["target_cacheline64"]


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix-csv", type=Path, required=True)
    parser.add_argument("--tail-csv", type=Path, required=True)
    parser.add_argument("--prefix-count", type=int, default=10000)
    parser.add_argument("--out-csv", type=Path, required=True)
    args = parser.parse_args()

    fields, prefix_rows = read_rows(args.prefix_csv)
    tail_fields, tail_rows = read_rows(args.tail_csv)
    if fields != tail_fields:
        raise SystemExit("CSV field mismatch")

    out = []
    seen: set[tuple[str, str]] = set()

    def add(row: dict[str, str]) -> None:
        key = target_key(row)
        if key in seen:
            return
        seen.add(key)
        out.append(dict(row))

    for row in prefix_rows[: args.prefix_count]:
        add(row)
    for row in tail_rows:
        add(row)
    for row in prefix_rows[args.prefix_count :]:
        add(row)

    total = len(out)
    for idx, row in enumerate(out, 1):
        row["rank"] = str(idx)
        row["mode"] = f"hybrid-prefix{args.prefix_count}"
        # Preserve monotonic ordering for downstream tools that sort by score.
        row["score"] = f"{float(total - idx):.9f}"

    write_rows(args.out_csv, fields, out)
    print(f"[ok] wrote {args.out_csv} rows={len(out)} prefix={args.prefix_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
