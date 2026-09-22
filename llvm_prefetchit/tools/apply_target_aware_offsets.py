#!/usr/bin/env python3
"""Apply per-target prefetch offsets without crossing a function boundary."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


LDD_MAPPED_RE = re.compile(r"=>\s+(/\S+)\s+\(")
LDD_DIRECT_RE = re.compile(r"^\s*(/\S+)\s+\(")


def parse_offsets(raw: str) -> list[int]:
    values: list[int] = []
    seen: set[int] = set()
    for item in raw.split(","):
        try:
            value = int(item.strip(), 0)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid byte offset: {item}") from exc
        if value < 0:
            raise argparse.ArgumentTypeError("byte offsets must be non-negative")
        if value not in seen:
            values.append(value)
            seen.add(value)
    if not values:
        raise argparse.ArgumentTypeError("at least one byte offset is required")
    return values


def parse_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value), 0)
    except ValueError:
        return None


def dependency_paths(binary: Path) -> list[Path]:
    cp = subprocess.run(
        ["ldd", str(binary)],
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    paths: list[Path] = []
    for line in cp.stdout.splitlines():
        match = LDD_MAPPED_RE.search(line) or LDD_DIRECT_RE.search(line)
        if match:
            path = Path(match.group(1)).resolve()
            if path.is_file() and path not in paths:
                paths.append(path)
    return paths


def read_symbol_sizes(path: Path, nm: str, dynamic: bool) -> dict[str, int]:
    command = [nm]
    if dynamic:
        command.append("--dynamic")
    command.extend(["--defined-only", "--print-size", "--format=posix", str(path)])
    cp = subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    sizes: dict[str, int] = {}
    if cp.returncode != 0:
        return sizes
    for line in cp.stdout.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        name, symbol_type, _, raw_size = fields[:4]
        if symbol_type.lower() not in {"t", "w"}:
            continue
        try:
            size = int(raw_size, 16)
        except ValueError:
            continue
        if size <= 0:
            continue
        unversioned = name.split("@", 1)[0]
        sizes[unversioned] = max(size, sizes.get(unversioned, 0))
    return sizes


def collect_symbol_sizes(binary: Path, nm: str) -> tuple[dict[str, int], list[str]]:
    sizes = read_symbol_sizes(binary, nm, dynamic=False)
    objects = [binary]
    for dependency in dependency_paths(binary):
        objects.append(dependency)
        for name, size in read_symbol_sizes(dependency, nm, dynamic=True).items():
            sizes[name] = max(size, sizes.get(name, 0))
    return sizes, [str(path) for path in objects]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--requested-byte-offsets", type=parse_offsets, default=parse_offsets("0,64")
    )
    parser.add_argument(
        "--unknown-size-policy",
        choices=("target-only", "requested"),
        default="target-only",
    )
    parser.add_argument("--nm", default="llvm-nm-19")
    args = parser.parse_args()

    plan_path = Path(args.plan).resolve()
    binary = Path(args.binary).resolve()
    output = Path(args.output).resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema") != "prefetchit.plan.v1":
        raise SystemExit("unsupported or missing plan schema")

    symbol_sizes, scanned_objects = collect_symbol_sizes(binary, args.nm)
    requested = args.requested_byte_offsets
    resolved = 0
    unresolved = 0
    trimmed = 0
    effective_prefetches = 0
    for injection in plan.get("injections", []):
        target = injection.get("target", {})
        symbol = str(target.get("mangled") or "").split("@", 1)[0]
        miss_offset = parse_int(target.get("symbol_offset"))
        size = symbol_sizes.get(symbol)
        if size is not None and miss_offset is not None:
            offsets = [offset for offset in requested if miss_offset + offset < size]
            if not offsets:
                offsets = [0]
            resolved += 1
        else:
            offsets = requested if args.unknown_size_policy == "requested" else [0]
            unresolved += 1
        if offsets != requested:
            trimmed += 1
        injection["prefetch"] = {
            "byte_offsets": offsets,
            "target_symbol_size": size,
            "target_symbol_size_resolved": size is not None,
        }
        effective_prefetches += len(offsets)

    plan.setdefault("prefetch", {})["byte_offsets"] = requested
    options = plan.setdefault("options", {})
    options["target_aware_byte_offsets"] = True
    options["target_aware_unknown_size_policy"] = args.unknown_size_policy
    options["target_aware_requested_byte_offsets"] = requested
    options["target_aware_source_plan"] = str(plan_path)
    stats = plan.setdefault("stats", {})
    stats["target_aware_resolved_injections"] = resolved
    stats["target_aware_unresolved_injections"] = unresolved
    stats["target_aware_trimmed_injections"] = trimmed
    stats["planned_prefetches"] = effective_prefetches
    stats["target_aware_symbol_objects_scanned"] = len(scanned_objects)
    plan["target_aware_symbol_objects"] = scanned_objects

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"[ok] injections={len(plan.get('injections', []))} "
        f"resolved={resolved} unresolved={unresolved} trimmed={trimmed} "
        f"planned_prefetches={effective_prefetches} output={output}"
    )


if __name__ == "__main__":
    main()
