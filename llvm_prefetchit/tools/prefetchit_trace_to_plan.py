#!/usr/bin/env python3
"""Convert PEBS/LBR traces into a PrefetchIT LLVM-pass plan."""

from __future__ import annotations

import argparse
import bisect
import csv
import itertools
import json
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ENTRY_MIN_SLASHES = 7
NM_LINE_RE = re.compile(r"^([0-9a-fA-F]+)\s+([A-Za-z])\s+(.+)$")
SYM_OFF_RE = re.compile(r"^(.*)\+0x([0-9a-fA-F]+)$")
LOC_RE = re.compile(r"^(.*):([0-9]+)(?:\s+.*)?$")
TEXT_SYMBOL_TYPES = set("tTwW")


@dataclass(frozen=True)
class Symbol:
    addr: int
    typ: str
    raw: str
    demangled: str


@dataclass(frozen=True)
class BranchEntry:
    from_raw: str
    to_raw: str
    branch_type: str
    raw_from_addr: int | None = None
    raw_to_addr: int | None = None


@dataclass(frozen=True)
class SourceLoc:
    function: str
    file: str
    line: int


@dataclass(frozen=True)
class TargetKey:
    function: str
    file: str
    line: int


@dataclass
class SiteMeta:
    branch_types: Counter
    depths: Counter


class SymbolIndex:
    def __init__(self, symbols: list[Symbol]):
        self.symbols = sorted(symbols, key=lambda s: (s.addr, s.raw))
        self.addrs = [s.addr for s in self.symbols]
        self.by_raw: dict[str, Symbol] = {}
        self.by_demangled: dict[str, Symbol] = {}
        self.by_demangled_no_args: dict[str, Symbol] = {}

        for sym in self.symbols:
            self.by_raw.setdefault(sym.raw, sym)
            self.by_demangled.setdefault(sym.demangled, sym)
            self.by_demangled_no_args.setdefault(strip_args(sym.demangled), sym)

    def lookup_name(self, name: str) -> Symbol | None:
        base = normalize_symbol_name(name)
        return (
            self.by_raw.get(base)
            or self.by_demangled.get(base)
            or self.by_demangled_no_args.get(strip_args(base))
        )

    def lookup_addr(self, symoff: str) -> tuple[int, Symbol | None] | None:
        raw = symoff.strip()
        if not raw or raw == "-":
            return None
        if raw.startswith("0x"):
            try:
                addr = int(raw, 16)
            except ValueError:
                return None
            return addr, self.symbol_at(addr)

        match = SYM_OFF_RE.match(raw)
        if match:
            name = match.group(1).strip()
            off = int(match.group(2), 16)
        else:
            name = raw
            off = 0

        sym = self.lookup_name(name)
        if sym is None:
            return None
        return sym.addr + off, sym

    def symbol_at(self, addr: int) -> Symbol | None:
        idx = bisect.bisect_right(self.addrs, addr) - 1
        if idx < 0:
            return None
        return self.symbols[idx]


def strip_args(name: str) -> str:
    return name.split("(", 1)[0].strip()


def normalize_symbol_name(name: str) -> str:
    out = name.strip()
    if "@" in out:
        out = out.split("@", 1)[0]
    return out


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Build a prefetchit.plan.v1 JSON file from current PEBS/LBR traces."
    )
    ap.add_argument("--trace-dir", required=True, help="Directory containing lbr_symbolic_dump.txt")
    ap.add_argument("--binary", required=True, help="Profiled executable with symbols/debug info")
    ap.add_argument("--output", required=True, help="Output JSON plan path")
    ap.add_argument("--lbr-sym", default="", help="Override symbolic LBR dump path")
    ap.add_argument("--lbr-raw", default="", help="Override raw LBR dump path")
    ap.add_argument("--top-k", type=int, default=10, help="Top miss targets to select")
    ap.add_argument("--depth", type=int, default=16, help="Maximum LBR depth to inspect")
    ap.add_argument(
        "--site-budget-per-target",
        type=int,
        default=10,
        help="Maximum selected injection sites per target",
    )
    ap.add_argument(
        "--candidate-pool",
        type=int,
        default=1000,
        help="Top-count candidate pool used by greedy coverage selection; <=0 means all candidates",
    )
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    ap.add_argument("--nm", default="nm")
    ap.add_argument("--summary-dir", default="", help="Directory for CSV summaries")
    ap.add_argument(
        "--allow-unresolved-targets",
        action="store_true",
        help="Allow top targets without a resolved source file and line",
    )
    ap.add_argument("--max-samples", type=int, default=0, help="Testing/debug limit")
    args = ap.parse_args()
    if args.top_k <= 0 or args.depth <= 0 or args.site_budget_per_target <= 0:
        raise SystemExit("--top-k, --depth, and --site-budget-per-target must be positive")
    return args


def run_text(args: list[str]) -> list[str]:
    proc = subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.stdout.splitlines()


def parse_nm_lines(lines: Iterable[str]) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for line in lines:
        match = NM_LINE_RE.match(line)
        if not match:
            continue
        addr, typ, name = match.groups()
        if typ not in TEXT_SYMBOL_TYPES:
            continue
        out[(addr, typ)] = name.strip()
    return out


def build_symbol_index(nm_bin: str, binary: Path) -> SymbolIndex:
    raw_by_key = parse_nm_lines(run_text([nm_bin, "-n", str(binary)]))
    dem_by_key = parse_nm_lines(run_text([nm_bin, "-n", "-C", str(binary)]))

    symbols: list[Symbol] = []
    for key, raw_name in raw_by_key.items():
        dem_name = dem_by_key.get(key)
        if not dem_name:
            continue
        addr = int(key[0], 16)
        symbols.append(Symbol(addr=addr, typ=key[1], raw=raw_name, demangled=dem_name))
    if not symbols:
        raise RuntimeError(f"no text symbols found in {binary}")
    return SymbolIndex(symbols)


def parse_raw_entry(tok: str) -> BranchEntry | None:
    if tok.count("/") < ENTRY_MIN_SLASHES or not tok.startswith("0x"):
        return None
    parts = tok.split("/")
    if len(parts) < 7:
        return None
    try:
        raw_from = int(parts[0], 16)
        raw_to = int(parts[1], 16)
    except ValueError:
        return None
    return BranchEntry(
        from_raw=parts[0],
        to_raw=parts[1],
        branch_type=parts[6],
        raw_from_addr=raw_from,
        raw_to_addr=raw_to,
    )


def parse_symbolic_entry(tok: str) -> BranchEntry | None:
    if tok.count("/") < ENTRY_MIN_SLASHES:
        return None
    parts = tok.split("/")
    if len(parts) < 7:
        return None
    return BranchEntry(from_raw=parts[0], to_raw=parts[1], branch_type=parts[6])


def parse_entries(line: str, raw: bool) -> list[BranchEntry]:
    parser = parse_raw_entry if raw else parse_symbolic_entry
    out = []
    for tok in line.strip().split():
        entry = parser(tok)
        if entry is not None:
            out.append(entry)
    return out


def infer_binary_addr(
    sym_text: str,
    raw_addr: int | None,
    load_bias: int | None,
    symbols: SymbolIndex,
) -> int | None:
    resolved = symbols.lookup_addr(sym_text)
    if resolved is not None:
        return resolved[0]
    if raw_addr is not None and load_bias is not None:
        addr = raw_addr - load_bias
        if addr >= 0:
            return addr
    return None


def iter_trace_samples(
    lbr_sym: Path,
    lbr_raw: Path | None,
    symbols: SymbolIndex,
    depth: int,
    max_samples: int = 0,
):
    raw_fh = lbr_raw.open("r", encoding="utf-8", errors="replace") if lbr_raw else None
    try:
        with lbr_sym.open("r", encoding="utf-8", errors="replace") as sym_fh:
            raw_iter = raw_fh if raw_fh is not None else itertools.repeat("")
            for idx, (sym_line, raw_line) in enumerate(zip(sym_fh, raw_iter)):
                if max_samples and idx >= max_samples:
                    break
                sym_entries = parse_entries(sym_line, raw=False)
                if not sym_entries:
                    continue
                raw_entries = parse_entries(raw_line, raw=True) if raw_line else []

                target_entry = sym_entries[0]
                target_resolved = symbols.lookup_addr(target_entry.to_raw)
                if target_resolved is None:
                    continue
                target_addr = target_resolved[0]

                load_bias = None
                if raw_entries and raw_entries[0].raw_to_addr is not None:
                    load_bias = raw_entries[0].raw_to_addr - target_addr

                candidates: list[tuple[int, str, int]] = []
                upto = min(depth, len(sym_entries))
                for pos in range(upto):
                    sym_entry = sym_entries[pos]
                    raw_entry = raw_entries[pos] if pos < len(raw_entries) else None
                    raw_from = raw_entry.raw_from_addr if raw_entry is not None else None
                    site_addr = infer_binary_addr(sym_entry.from_raw, raw_from, load_bias, symbols)
                    if site_addr is None:
                        continue
                    branch_type = sym_entry.branch_type or (raw_entry.branch_type if raw_entry else "UNKNOWN")
                    candidates.append((site_addr, branch_type, pos + 1))

                yield idx, target_addr, candidates
    finally:
        if raw_fh is not None:
            raw_fh.close()


def parse_loc(raw: str) -> tuple[str, int]:
    text = raw.strip()
    if not text or text.startswith("??"):
        return "", 0
    match = LOC_RE.match(text)
    if not match:
        return "", 0
    return match.group(1), int(match.group(2))


def resolve_addrs(addr2line_bin: str, binary: Path, addrs: Iterable[int]) -> dict[int, SourceLoc]:
    ordered = sorted(set(addrs))
    out: dict[int, SourceLoc] = {}
    chunk_size = 1500
    for start in range(0, len(ordered), chunk_size):
        chunk = ordered[start : start + chunk_size]
        lines = run_text([addr2line_bin, "-e", str(binary), "-f", "-C"] + [hex(a) for a in chunk])
        for idx, addr in enumerate(chunk):
            j = idx * 2
            if j + 1 >= len(lines):
                out[addr] = SourceLoc(function="", file="", line=0)
                continue
            file_name, line_no = parse_loc(lines[j + 1])
            out[addr] = SourceLoc(function=lines[j].strip(), file=file_name, line=line_no)
    return out


def target_key_for_addr(addr: int, locs: dict[int, SourceLoc], symbols: SymbolIndex) -> TargetKey:
    loc = locs.get(addr, SourceLoc(function="", file="", line=0))
    sym = symbols.symbol_at(addr)
    function = loc.function if loc.function and loc.function != "??" else (sym.demangled if sym else "")
    return TargetKey(function=function, file=loc.file, line=loc.line)


def is_resolved_target(key: TargetKey) -> bool:
    return bool(key.function and key.file and key.line > 0 and not key.file.startswith("<"))


def is_resolved_loc(loc: SourceLoc) -> bool:
    return bool(loc.file and loc.line > 0 and not loc.file.startswith("<"))


def choose_top_targets(
    target_addr_counts: Counter,
    target_locs: dict[int, SourceLoc],
    symbols: SymbolIndex,
    top_k: int,
    allow_unresolved: bool,
):
    counts_by_key: Counter = Counter()
    addr_counts_by_key: dict[TargetKey, Counter] = defaultdict(Counter)
    for addr, count in target_addr_counts.items():
        key = target_key_for_addr(addr, target_locs, symbols)
        if not allow_unresolved and not is_resolved_target(key):
            continue
        counts_by_key[key] += count
        addr_counts_by_key[key][addr] += count

    if not counts_by_key and not allow_unresolved:
        for addr, count in target_addr_counts.items():
            key = target_key_for_addr(addr, target_locs, symbols)
            counts_by_key[key] += count
            addr_counts_by_key[key][addr] += count

    top = counts_by_key.most_common(top_k)
    return top, addr_counts_by_key


def greedy_select_sites(
    samples_by_site: dict[int, set[int]],
    target_samples: set[int],
    budget: int,
    candidate_pool: int,
):
    if candidate_pool > 0:
        pool_items = sorted(samples_by_site.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:candidate_pool]
    else:
        pool_items = list(samples_by_site.items())

    remaining = set(target_samples)
    selected = []
    used: set[int] = set()

    for _ in range(budget):
        best_site = None
        best_new = 0
        best_total = 0
        for site_addr, sample_set in pool_items:
            if site_addr in used:
                continue
            new_cover = len(sample_set & remaining)
            total = len(sample_set)
            if (new_cover, total, -site_addr) > (best_new, best_total, -(best_site or 0)):
                best_site = site_addr
                best_new = new_cover
                best_total = total
        if best_site is None or best_new <= 0:
            break
        used.add(best_site)
        remaining -= samples_by_site[best_site]
        selected.append(
            {
                "site_addr": best_site,
                "site_samples": len(samples_by_site[best_site]),
                "new_covered_samples": best_new,
                "cumulative_covered_samples": len(target_samples) - len(remaining),
            }
        )
    return selected


def loc_to_json(loc: SourceLoc, sym: Symbol | None, addr: int) -> dict:
    return {
        "addr": hex(addr),
        "mangled": sym.raw if sym else "",
        "demangled": sym.demangled if sym else loc.function,
        "function": loc.function,
        "file": loc.file,
        "line": loc.line,
    }


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    args = parse_args()
    trace_dir = Path(args.trace_dir).resolve()
    binary = Path(args.binary).resolve()
    output = Path(args.output).resolve()
    lbr_sym = Path(args.lbr_sym).resolve() if args.lbr_sym else trace_dir / "lbr_symbolic_dump.txt"
    lbr_raw = Path(args.lbr_raw).resolve() if args.lbr_raw else trace_dir / "lbr_raw_dump.txt"
    if not lbr_raw.exists():
        lbr_raw = None

    if not lbr_sym.exists():
        raise RuntimeError(f"missing symbolic LBR dump: {lbr_sym}")
    if not binary.exists():
        raise RuntimeError(f"missing binary: {binary}")

    symbols = build_symbol_index(args.nm, binary)

    total_lines = 0
    parsed_samples = 0
    target_addr_counts: Counter = Counter()
    for sample_idx, target_addr, _ in iter_trace_samples(
        lbr_sym, lbr_raw, symbols, args.depth, args.max_samples
    ):
        total_lines = max(total_lines, sample_idx + 1)
        parsed_samples += 1
        target_addr_counts[target_addr] += 1

    target_locs = resolve_addrs(args.addr2line, binary, target_addr_counts.keys())
    top_targets, addr_counts_by_key = choose_top_targets(
        target_addr_counts,
        target_locs,
        symbols,
        args.top_k,
        args.allow_unresolved_targets,
    )
    selected_target_keys = {key for key, _ in top_targets}
    addr_to_key = {
        addr: key
        for key in selected_target_keys
        for addr in addr_counts_by_key.get(key, {})
    }

    target_samples: dict[TargetKey, set[int]] = defaultdict(set)
    samples_by_site: dict[TargetKey, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    site_meta: dict[TargetKey, dict[int, SiteMeta]] = defaultdict(
        lambda: defaultdict(lambda: SiteMeta(branch_types=Counter(), depths=Counter()))
    )

    for sample_idx, target_addr, candidates in iter_trace_samples(
        lbr_sym, lbr_raw, symbols, args.depth, args.max_samples
    ):
        target_key = addr_to_key.get(target_addr)
        if target_key not in selected_target_keys:
            continue
        target_samples[target_key].add(sample_idx)
        seen_sites: set[int] = set()
        for site_addr, branch_type, depth in candidates:
            if site_addr in seen_sites:
                continue
            seen_sites.add(site_addr)
            samples_by_site[target_key][site_addr].add(sample_idx)
            site_meta[target_key][site_addr].branch_types[branch_type] += 1
            site_meta[target_key][site_addr].depths[depth] += 1

    all_site_addrs = {
        site_addr
        for site_map in samples_by_site.values()
        for site_addr in site_map.keys()
    }
    site_locs = resolve_addrs(args.addr2line, binary, all_site_addrs)
    for target_key, site_map in list(samples_by_site.items()):
        for site_addr in list(site_map.keys()):
            if not is_resolved_loc(site_locs.get(site_addr, SourceLoc(function="", file="", line=0))):
                del site_map[site_addr]

    selected_rows = []
    for target_rank, (target_key, target_count) in enumerate(top_targets, start=1):
        selected = greedy_select_sites(
            samples_by_site.get(target_key, {}),
            target_samples.get(target_key, set()),
            args.site_budget_per_target,
            args.candidate_pool,
        )
        for site_rank, row in enumerate(selected, start=1):
            row["target_key"] = target_key
            row["target_rank"] = target_rank
            row["target_samples"] = target_count
            row["site_rank"] = site_rank
            selected_rows.append(row)

    injections = []
    injection_csv = []
    top_csv = []
    for target_rank, (target_key, target_count) in enumerate(top_targets, start=1):
        rep_addr = addr_counts_by_key[target_key].most_common(1)[0][0]
        target_sym = symbols.symbol_at(rep_addr)
        target_loc = SourceLoc(target_key.function, target_key.file, target_key.line)
        top_csv.append(
            {
                "rank": target_rank,
                "samples": target_count,
                "function": target_key.function,
                "file": target_key.file,
                "line": target_key.line,
                "addr": hex(rep_addr),
                "mangled": target_sym.raw if target_sym else "",
            }
        )

        for selected in [r for r in selected_rows if r["target_key"] == target_key]:
            site_addr = selected["site_addr"]
            meta = site_meta[target_key][site_addr]
            branch_type = meta.branch_types.most_common(1)[0][0] if meta.branch_types else "UNKNOWN"
            depth = meta.depths.most_common(1)[0][0] if meta.depths else 0
            site_loc = site_locs.get(site_addr, SourceLoc(function="", file="", line=0))
            site_sym = symbols.symbol_at(site_addr)
            coverage_pct = (
                100.0 * selected["cumulative_covered_samples"] / target_count
                if target_count
                else 0.0
            )
            injection = {
                "target_rank": selected["target_rank"],
                "site_rank": selected["site_rank"],
                "samples": selected["site_samples"],
                "new_covered_samples": selected["new_covered_samples"],
                "cumulative_covered_samples": selected["cumulative_covered_samples"],
                "cumulative_coverage_pct": round(coverage_pct, 4),
                "target": loc_to_json(target_loc, target_sym, rep_addr),
                "site": {
                    **loc_to_json(site_loc, site_sym, site_addr),
                    "branch_type": branch_type,
                    "lbr_depth": depth,
                    "observed_depths": ",".join(str(d) for d, _ in meta.depths.most_common()),
                },
            }
            injections.append(injection)
            injection_csv.append(
                {
                    "target_rank": injection["target_rank"],
                    "site_rank": injection["site_rank"],
                    "target_function": target_key.function,
                    "target_file": target_key.file,
                    "target_line": target_key.line,
                    "site_function": site_loc.function,
                    "site_file": site_loc.file,
                    "site_line": site_loc.line,
                    "branch_type": branch_type,
                    "lbr_depth": depth,
                    "samples": selected["site_samples"],
                    "new_covered_samples": selected["new_covered_samples"],
                    "cumulative_coverage_pct": f"{coverage_pct:.4f}",
                    "target_mangled": target_sym.raw if target_sym else "",
                    "site_mangled": site_sym.raw if site_sym else "",
                }
            )

    plan = {
        "schema": "prefetchit.plan.v1",
        "trace_dir": str(trace_dir),
        "binary": str(binary),
        "options": {
            "top_k": args.top_k,
            "depth": args.depth,
            "site_budget_per_target": args.site_budget_per_target,
            "candidate_pool": args.candidate_pool,
            "allow_unresolved_targets": args.allow_unresolved_targets,
        },
        "stats": {
            "input_lines_seen": total_lines,
            "parsed_samples": parsed_samples,
            "unique_target_addresses": len(target_addr_counts),
            "selected_targets": len(top_targets),
            "selected_injections": len(injections),
        },
        "injections": injections,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary_dir = Path(args.summary_dir).resolve() if args.summary_dir else output.parent
    write_csv(
        summary_dir / "selected_top_targets.csv",
        top_csv,
        ["rank", "samples", "function", "file", "line", "addr", "mangled"],
    )
    write_csv(
        summary_dir / "selected_injection_sites.csv",
        injection_csv,
        [
            "target_rank",
            "site_rank",
            "target_function",
            "target_file",
            "target_line",
            "site_function",
            "site_file",
            "site_line",
            "branch_type",
            "lbr_depth",
            "samples",
            "new_covered_samples",
            "cumulative_coverage_pct",
            "target_mangled",
            "site_mangled",
        ],
    )

    print(f"[ok] wrote {output}")
    print(
        "[ok] "
        f"targets={len(top_targets)} injections={len(injections)} parsed_samples={parsed_samples}"
    )


if __name__ == "__main__":
    main()
