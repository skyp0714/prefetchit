#!/usr/bin/env python3
"""Build external GOT-indirect prefetch plans from PEBS/LBR dumps.

This targets dynamic-library code misses that the normal main-binary symbol
index cannot represent. The generated plan uses the PrefetchIT pass operand
mode "got-symbol-offset", which emits:

  mov symbol@GOTPCREL(%rip), %r11
  prefetcht1 offset(%r11)

The newest branch, LBR[0].to, is always the prefetch target. Older
LBR[d].from entries are candidate injection sites in the main executable.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load_plan_helpers(script_dir: Path):
    helper = script_dir / "prefetchit_trace_to_plan.py"
    spec = importlib.util.spec_from_file_location("prefetchit_trace_to_plan_helpers", helper)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {helper}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace-dir", action="append", required=True)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--summary-dir", default="")
    ap.add_argument("--target-coverage-pct", type=float, default=100.0)
    ap.add_argument("--depth", type=int, default=24)
    ap.add_argument("--depth-min", type=int, default=4)
    ap.add_argument("--site-budget-per-target", type=int, default=8)
    ap.add_argument("--prefetch-mnemonic", default="prefetcht0")
    ap.add_argument("--prefetch-byte-offsets", default="0")
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    ap.add_argument("--nm", default="nm")
    ap.add_argument("--cxxfilt", default="c++filt")
    return ap.parse_args()


def parse_byte_offsets(raw: str) -> list[int]:
    out = []
    seen = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        value = int(item, 0)
        if value < 0:
            continue
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out or [0]


def strip_ver(sym: str) -> str:
    return sym.split("@@", 1)[0].split("@", 1)[0]


def split_sym_off(text: str) -> tuple[str, int]:
    if "+0x" not in text:
        return text, 0
    base, raw_off = text.rsplit("+0x", 1)
    match = re.match(r"([0-9a-fA-F]+)", raw_off)
    return base, int(match.group(1), 16) if match else 0


def strip_args(name: str) -> str:
    return name.split("(", 1)[0].strip()


def build_dynamic_symbol_map(
    nm_bin: str, cxxfilt_bin: str, binary: Path
) -> tuple[set[str], dict[str, str], list[Path]]:
    ldd = subprocess.run(
        ["ldd", str(binary)],
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    objects = [binary]
    for line in ldd.stdout.splitlines():
        fields = line.strip().split()
        candidates = []
        if "=>" in fields:
            index = fields.index("=>")
            if index + 1 < len(fields):
                candidates.append(fields[index + 1])
        elif fields and fields[0].startswith("/"):
            candidates.append(fields[0])
        for candidate in candidates:
            path = Path(candidate)
            if path.is_file() and path not in objects:
                objects.append(path)

    raw_symbols = []
    seen_raw = set()
    for obj in objects:
        modes = ["--undefined-only"] if obj == binary else ["--defined-only"]
        proc = subprocess.run(
            [nm_bin, "-D", *modes, str(obj)],
            check=True,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            versioned = parts[-1]
            if "@" in versioned and "@@" not in versioned:
                continue
            raw = strip_ver(versioned)
            if raw and raw not in seen_raw:
                seen_raw.add(raw)
                raw_symbols.append(raw)

    demangled = subprocess.run(
        [cxxfilt_bin],
        input="\n".join(raw_symbols) + "\n",
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.splitlines()
    by_name: dict[str, str] = {}
    for raw, dem in zip(raw_symbols, demangled):
        for key in (raw, dem, strip_args(dem)):
            by_name.setdefault(key, raw)
    return set(raw_symbols), by_name, objects


def dynamic_symbol_for_base(
    base: str, dynamic_raw: set[str], dynamic_by_name: dict[str, str]
) -> str | None:
    clean = strip_ver(base[:-4] if base.endswith("@plt") else base).strip()
    if clean.startswith("cfree") and "free" in dynamic_raw:
        return "free"
    direct = dynamic_by_name.get(clean) or dynamic_by_name.get(strip_args(clean))
    if direct:
        return direct

    aliases = []
    for prefix, public in (
        ("__memmove", "memmove"),
        ("__memset", "memset"),
        ("__memcpy", "memcpy"),
        ("__memcmp", "memcmp"),
    ):
        if clean.startswith(prefix):
            aliases.append(public)
    for alias in aliases:
        if alias in dynamic_raw:
            return alias
    return None


def choose_targets(counts: Counter, coverage_pct: float):
    ordered = counts.most_common()
    if coverage_pct >= 100.0:
        return ordered
    threshold = sum(counts.values()) * coverage_pct / 100.0
    selected = []
    cumulative = 0
    for target, count in ordered:
        selected.append((target, count))
        cumulative += count
        if cumulative >= threshold:
            break
    return selected


def main() -> None:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    p2p = load_plan_helpers(script_dir)

    trace_dirs = [Path(p).resolve() for p in args.trace_dir]
    binary = Path(args.binary).resolve()
    output = Path(args.output).resolve()
    summary_dir = Path(args.summary_dir).resolve() if args.summary_dir else output.parent
    byte_offsets = parse_byte_offsets(args.prefetch_byte_offsets)
    symbols = p2p.build_symbol_index(args.nm, binary)
    dynamic_raw, dynamic_by_name, dynamic_objects = build_dynamic_symbol_map(
        args.nm, args.cxxfilt, binary
    )

    target_counts = Counter()
    target_symbolic = defaultdict(Counter)
    unsupported_targets = Counter()
    external_branch_types = Counter()
    mapped_branch_types = Counter()
    usable_branch_types = Counter()
    samples_by_site = defaultdict(lambda: defaultdict(set))
    site_meta = defaultdict(lambda: defaultdict(lambda: {"branch_types": Counter(), "depths": Counter()}))
    scanned = 0
    parsed = 0
    external_samples = 0
    mapped_external_samples = 0
    mapped_without_main_site = 0

    for trace_dir in trace_dirs:
        sym_path = trace_dir / "lbr_symbolic_dump.txt"
        raw_path = trace_dir / "lbr_raw_dump.txt"
        with sym_path.open(encoding="utf-8", errors="replace") as sym_fh, raw_path.open(
            encoding="utf-8", errors="replace"
        ) as raw_fh:
            for sym_line, raw_line in zip(sym_fh, raw_fh):
                scanned += 1
                sym_entries = p2p.parse_entries(sym_line, raw=False)
                raw_entries = p2p.parse_entries(raw_line, raw=True)
                if not sym_entries or not raw_entries:
                    continue
                newest = sym_entries[0]
                newest_raw = raw_entries[0]
                if p2p.infer_binary_addr(
                    newest.to_raw, newest_raw.raw_to_addr, None, symbols
                ) is not None:
                    continue
                external_samples += 1
                branch_type = newest.branch_type or newest_raw.branch_type or "UNKNOWN"
                external_branch_types[branch_type] += 1
                target_base, target_offset = split_sym_off(newest.to_raw)
                public = dynamic_symbol_for_base(
                    target_base, dynamic_raw, dynamic_by_name
                )
                if not public:
                    unsupported_targets[newest.to_raw] += 1
                    continue
                mapped_external_samples += 1
                mapped_branch_types[branch_type] += 1
                target = (public, target_offset & ~0x3F)

                upto = min(args.depth, len(sym_entries), len(raw_entries))
                seen_sites = set()
                candidates = []
                for pos in range(max(args.depth_min, 1) - 1, upto):
                    sym_entry = sym_entries[pos]
                    raw_entry = raw_entries[pos]
                    site_addr = p2p.infer_binary_addr(
                        sym_entry.from_raw, raw_entry.raw_from_addr, None, symbols
                    )
                    if site_addr is None or symbols.symbol_at(site_addr) is None:
                        continue
                    if site_addr in seen_sites:
                        continue
                    seen_sites.add(site_addr)
                    branch_type = sym_entry.branch_type or raw_entry.branch_type or "UNKNOWN"
                    candidates.append((site_addr, branch_type, pos + 1))
                if not candidates:
                    mapped_without_main_site += 1
                    continue

                sample_idx = parsed
                parsed += 1
                usable_branch_types[branch_type] += 1
                target_counts[target] += 1
                target_symbolic[target][newest.to_raw] += 1
                for site_addr, branch_type, depth in candidates:
                    samples_by_site[target][site_addr].add(sample_idx)
                    site_meta[target][site_addr]["branch_types"][branch_type] += 1
                    site_meta[target][site_addr]["depths"][depth] += 1

    all_site_addrs = {addr for site_map in samples_by_site.values() for addr in site_map}
    site_locs = p2p.resolve_addrs(args.addr2line, binary, all_site_addrs)

    def loc_ok(addr: int) -> bool:
        empty = p2p.SourceLoc(function="", file="", line=0)
        return p2p.is_resolved_loc(site_locs.get(addr, empty))

    selected_targets = choose_targets(target_counts, args.target_coverage_pct)
    injections = []
    top_rows = []
    site_rows = []
    for target_rank, ((public, target_offset), target_count) in enumerate(selected_targets, 1):
        target_key = (public, target_offset)
        top_rows.append(
            {
                "rank": target_rank,
                "samples": target_count,
                "public_symbol": public,
                "symbol_offset": hex(target_offset),
                "cacheline64": hex(target_offset),
                "raw_lbr0_to": target_symbolic[target_key].most_common(1)[0][0],
            }
        )
        site_map = {
            addr: sample_set
            for addr, sample_set in samples_by_site[target_key].items()
            if loc_ok(addr)
        }
        pool = sorted(site_map.items(), key=lambda kv: (-len(kv[1]), kv[0]))[
            : args.site_budget_per_target
        ]
        covered = set()
        for site_rank, (site_addr, sample_set) in enumerate(pool, 1):
            meta = site_meta[target_key][site_addr]
            branch_type = (
                meta["branch_types"].most_common(1)[0][0]
                if meta["branch_types"]
                else "UNKNOWN"
            )
            depth = meta["depths"].most_common(1)[0][0] if meta["depths"] else 0
            new_cover = len(sample_set - covered)
            covered |= set(sample_set)
            site_loc = site_locs.get(site_addr, p2p.SourceLoc(function="", file="", line=0))
            site_sym = symbols.symbol_at(site_addr)
            coverage_pct = 100.0 * len(covered) / target_count if target_count else 0.0
            injection = {
                "target_rank": target_rank,
                "site_rank": site_rank,
                "prefetch_mnemonic": args.prefetch_mnemonic,
                "samples": len(sample_set),
                "new_covered_samples": new_cover,
                "cumulative_covered_samples": len(covered),
                "cumulative_coverage_pct": round(coverage_pct, 4),
                "target": {
                    "addr": hex(target_offset),
                    "cacheline64": hex(target_offset),
                    "cacheline_offset": target_offset & 0x3F,
                    "symbol_offset": hex(target_offset),
                    "mangled": public,
                    "demangled": public,
                    "function": public,
                    "file": "<external_got>",
                    "line": 0,
                    "operand": "got-symbol-offset",
                },
                "site": {
                    **p2p.loc_to_json(site_loc, site_sym, site_addr),
                    "branch_type": branch_type,
                    "lbr_depth": depth,
                    "observed_depths": ",".join(
                        str(d) for d, _ in meta["depths"].most_common()
                    ),
                },
            }
            injections.append(injection)
            site_rows.append(
                {
                    "target_rank": target_rank,
                    "site_rank": site_rank,
                    "target_symbol": public,
                    "target_offset": hex(target_offset),
                    "target_samples": target_count,
                    "site_function": site_loc.function,
                    "site_file": site_loc.file,
                    "site_line": site_loc.line,
                    "branch_type": branch_type,
                    "lbr_depth": depth,
                    "samples": len(sample_set),
                    "new_covered_samples": new_cover,
                    "site_mangled": site_sym.raw if site_sym else "",
                }
            )

    plan = {
        "schema": "prefetchit.plan.v1",
        "prefetch": {
            "mnemonic": args.prefetch_mnemonic,
            "operand": "got-symbol-offset",
            "byte_offsets": byte_offsets,
            "offset_mode": "got-target-symbol-offset",
        },
        "trace_dirs": [str(p) for p in trace_dirs],
        "binary": str(binary),
        "options": {
            "target_coverage_pct": args.target_coverage_pct,
            "depth": args.depth,
            "depth_min": args.depth_min,
            "site_budget_per_target": args.site_budget_per_target,
            "prefetch_mnemonic": args.prefetch_mnemonic,
            "prefetch_byte_offsets": byte_offsets,
        },
        "stats": {
            "input_traces": len(trace_dirs),
            "scanned_samples": scanned,
            "external_lbr0_samples": external_samples,
            "mapped_external_lbr0_samples": mapped_external_samples,
            "mapped_without_main_site_samples": mapped_without_main_site,
            "parsed_external_samples": parsed,
            "unsupported_external_samples": sum(unsupported_targets.values()),
            "dynamic_symbols": len(dynamic_raw),
            "dynamic_objects": len(dynamic_objects),
            "external_lbr0_branch_types": dict(sorted(external_branch_types.items())),
            "mapped_lbr0_branch_types": dict(sorted(mapped_branch_types.items())),
            "usable_lbr0_branch_types": dict(sorted(usable_branch_types.items())),
            "unique_external_targets": len(target_counts),
            "selected_targets": len(selected_targets),
            "selected_injections": len(injections),
            "planned_prefetches": len(injections) * len(byte_offsets),
        },
        "injections": injections,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with (summary_dir / "selected_top_targets.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "rank",
                "samples",
                "public_symbol",
                "symbol_offset",
                "cacheline64",
                "raw_lbr0_to",
            ],
        )
        writer.writeheader()
        writer.writerows(top_rows)
    with (summary_dir / "selected_injection_sites.csv").open(
        "w", newline="", encoding="utf-8"
    ) as fh:
        fieldnames = [
            "target_rank",
            "site_rank",
            "target_symbol",
            "target_offset",
            "target_samples",
            "site_function",
            "site_file",
            "site_line",
            "branch_type",
            "lbr_depth",
            "samples",
            "new_covered_samples",
            "site_mangled",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(site_rows)
    with (summary_dir / "unsupported_lbr0_targets.csv").open(
        "w", newline="", encoding="utf-8"
    ) as fh:
        writer = csv.writer(fh)
        writer.writerow(["rank", "samples", "raw_lbr0_to"])
        for rank, (raw_target, count) in enumerate(unsupported_targets.most_common(), 1):
            writer.writerow([rank, count, raw_target])

    print(f"[ok] wrote {output}")
    print(
        "[ok] "
        f"targets={len(selected_targets)} injections={len(injections)} "
        f"parsed_external={parsed}"
    )


if __name__ == "__main__":
    main()
