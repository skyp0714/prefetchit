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
NM_SIZE_LINE_RE = re.compile(
    r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([A-Za-z])\s+(.+)$"
)
SYM_OFF_RE = re.compile(r"^(.*)\+0x([0-9a-fA-F]+)$")
LOC_RE = re.compile(r"^(.*):([0-9]+)(?:\s+.*)?$")
TEXT_SYMBOL_TYPES = set("tTwW")
PREFETCH_MNEMONICS = (
    "prefetcht0",
    "prefetcht1",
    "prefetcht2",
    "prefetchnta",
    "prefetchit0",
    "prefetchit1",
)


def parse_byte_offsets(raw: str) -> list[int]:
    offsets: list[int] = []
    for item in raw.split(","):
        text = item.strip()
        if not text:
            continue
        try:
            value = int(text, 0)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid byte offset {text!r}") from exc
        if value < 0:
            raise argparse.ArgumentTypeError("prefetch byte offsets must be non-negative")
        offsets.append(value)
    if not offsets:
        raise argparse.ArgumentTypeError("at least one prefetch byte offset is required")
    # Preserve the user's order but remove duplicates. Order matters for the
    # emitted assembly because nearby cachelines should be prefetched first.
    deduped: list[int] = []
    seen: set[int] = set()
    for value in offsets:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def parse_branch_depth_policy(raw: str) -> dict[str, tuple[int, int]]:
    policy: dict[str, tuple[int, int]] = {}
    if not raw.strip():
        return policy
    for item in raw.split(","):
        text = item.strip()
        if not text:
            continue
        if ":" not in text:
            raise argparse.ArgumentTypeError(
                f"invalid branch-depth policy item {text!r}; expected BRANCH:min-max"
            )
        branch, window = text.split(":", 1)
        branch = branch.strip().upper()
        if not branch:
            raise argparse.ArgumentTypeError("branch-depth policy branch type is empty")
        if "-" in window:
            lo_text, hi_text = window.split("-", 1)
        else:
            lo_text = hi_text = window
        try:
            lo = int(lo_text, 0)
            hi = int(hi_text, 0)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"invalid branch-depth window {window!r}"
            ) from exc
        if lo <= 0 or hi <= 0 or lo > hi:
            raise argparse.ArgumentTypeError(
                f"invalid branch-depth window {window!r}; need 1 <= min <= max"
            )
        policy[branch] = (lo, hi)
    return policy


def parse_branch_type_filter(raw: str) -> set[str]:
    branch_types: set[str] = set()
    if not raw.strip():
        return branch_types
    for item in raw.split(","):
        text = item.strip().upper()
        if text:
            branch_types.add(text)
    return branch_types


def branch_depth_allowed(
    policy: dict[str, tuple[int, int]],
    branch_type: str,
    depth: int,
    default_min: int,
    default_max: int,
) -> bool:
    key = (branch_type or "UNKNOWN").upper()
    lo, hi = policy.get(key, policy.get("DEFAULT", (default_min, default_max)))
    return lo <= depth <= hi


def branch_type_allowed(branch_type_filter: set[str], branch_type: str) -> bool:
    if not branch_type_filter:
        return True
    key = (branch_type or "UNKNOWN").upper()
    return key in branch_type_filter


@dataclass(frozen=True)
class Symbol:
    addr: int
    size: int
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
class TraceInput:
    trace_dir: Path
    lbr_sym: Path
    lbr_raw: Path | None


@dataclass(frozen=True)
class TargetKey:
    function: str
    file: str
    line: int
    cacheline64: int


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
        addr = sym.addr + off
        if not self.addr_in_symbol(addr, sym):
            return None
        return addr, sym

    def symbol_at(self, addr: int) -> Symbol | None:
        idx = bisect.bisect_right(self.addrs, addr) - 1
        if idx < 0:
            return None
        start = self.symbols[idx].addr
        while idx >= 0 and self.symbols[idx].addr == start:
            sym = self.symbols[idx]
            if self.addr_in_symbol(addr, sym):
                return sym
            idx -= 1
        return None

    def addr_in_symbol(self, addr: int, sym: Symbol) -> bool:
        if addr < sym.addr:
            return False
        if sym.size > 0:
            return addr < sym.addr + sym.size

        # A zero-sized assembler label is only safe at its exact address. Do
        # not infer an open-ended function range: that was the source of plans
        # which addressed .eh_frame/data as symbol+large_offset.
        return addr == sym.addr


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
    ap.add_argument(
        "--trace-dir",
        action="append",
        required=True,
        help=(
            "Directory containing lbr_symbolic_dump.txt. May be passed more "
            "than once; all samples are aggregated before target selection."
        ),
    )
    ap.add_argument("--binary", required=True, help="Profiled executable with symbols/debug info")
    ap.add_argument(
        "--validation-binary",
        default="",
        help=(
            "Optional uninjected binary produced by the exact compiler/link settings used for "
            "the planned rebuild. Targets whose mangled-symbol offset is outside this binary's "
            "function are discarded before coverage selection."
        ),
    )
    ap.add_argument("--output", required=True, help="Output JSON plan path")
    ap.add_argument("--lbr-sym", default="", help="Override symbolic LBR dump path")
    ap.add_argument("--lbr-raw", default="", help="Override raw LBR dump path")
    ap.add_argument("--top-k", type=int, default=10, help="Top miss targets to select")
    ap.add_argument(
        "--target-coverage-pct",
        type=float,
        default=0.0,
        help=(
            "Select enough hottest target cachelines to cover this percentage "
            "of aggregated samples. Overrides --top-k when > 0. Use 50, 75, or 100 "
            "for the new coverage-based experiments."
        ),
    )
    ap.add_argument("--depth", type=int, default=16, help="Maximum LBR depth to inspect")
    ap.add_argument(
        "--depth-min",
        type=int,
        default=1,
        help="Minimum LBR depth to use for injection-site candidates",
    )
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
    ap.add_argument(
        "--selection-mode",
        choices=("greedy", "top-sites", "per-depth", "all-paths"),
        default="greedy",
        help=(
            "Site selection policy. greedy preserves the old max-new-coverage "
            "behavior; top-sites keeps the hottest sites even if they cover the "
            "same samples; per-depth keeps hot sites independently at each LBR depth; "
            "all-paths emits every resolved LBR[d].from site for each selected target."
        ),
    )
    ap.add_argument(
        "--sites-per-depth",
        type=int,
        default=1,
        help="For --selection-mode per-depth, keep this many hot sites per depth/target",
    )
    ap.add_argument(
        "--branch-depth-policy",
        type=parse_branch_depth_policy,
        default=parse_branch_depth_policy(""),
        help=(
            "Optional branch-type-specific LBR depth windows, for example "
            "'CALL:2-8,IND_CALL:2-8,COND:4-16,UNCOND:4-16,RET:8-32,IND:4-24'. "
            "Types not listed use --depth-min/--depth."
        ),
    )
    ap.add_argument(
        "--branch-type-filter",
        type=parse_branch_type_filter,
        default=parse_branch_type_filter(""),
        help=(
            "Optional comma-separated branch-type allow-list for injection "
            "candidate sites, for example 'RET' or 'COND,CALL'. Empty means all "
            "branch types."
        ),
    )
    ap.add_argument(
        "--sample-branch-type-filter",
        type=parse_branch_type_filter,
        default=parse_branch_type_filter(""),
        help=(
            "Optional comma-separated branch-type allow-list for the sampled "
            "miss target branch, i.e. LBR[0]. Empty means all target branch "
            "types. This is distinct from --branch-type-filter, which filters "
            "injection candidate sites."
        ),
    )
    ap.add_argument(
        "--target-ip-source",
        choices=("lbr-to", "sample-ip"),
        default="lbr-to",
        help=(
            "Address used as the prefetch target for each selected sample. "
            "'lbr-to' preserves the historical LBR[0].to behavior; "
            "'sample-ip' uses the actual PEBS sample IP and keeps LBR[0] only "
            "for branch-type filtering and site history."
        ),
    )
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    ap.add_argument("--nm", default="nm")
    ap.add_argument("--summary-dir", default="", help="Directory for CSV summaries")
    ap.add_argument(
        "--prefetch-mnemonic",
        choices=PREFETCH_MNEMONICS,
        default="prefetcht1",
        help="Prefetch instruction mnemonic to request in the LLVM pass plan",
    )
    ap.add_argument(
        "--prefetch-byte-offsets",
        type=parse_byte_offsets,
        default=parse_byte_offsets("0"),
        help=(
            "Comma-separated byte offsets from the LLVM target block label. "
            "Use values such as 0,64,128,192 to prefetch multiple nearby "
            "I-cache lines when source-line debug info is coarser than the "
            "sampled miss PC."
        ),
    )
    ap.add_argument(
        "--allow-unresolved-targets",
        action="store_true",
        help="Allow top targets without a resolved source file and line",
    )
    ap.add_argument("--max-samples", type=int, default=0, help="Testing/debug limit")
    args = ap.parse_args()
    if args.top_k <= 0 or args.depth <= 0:
        raise SystemExit("--top-k and --depth must be positive")
    if args.selection_mode != "all-paths" and args.site_budget_per_target <= 0:
        raise SystemExit("--site-budget-per-target must be positive unless --selection-mode all-paths")
    if args.selection_mode == "all-paths" and args.site_budget_per_target < 0:
        raise SystemExit("--site-budget-per-target must be non-negative")
    if args.target_coverage_pct < 0.0 or args.target_coverage_pct > 100.0:
        raise SystemExit("--target-coverage-pct must be in [0, 100]")
    if args.depth_min <= 0 or args.depth_min > args.depth:
        raise SystemExit("--depth-min must be positive and <= --depth")
    if args.sites_per_depth <= 0:
        raise SystemExit("--sites-per-depth must be positive")
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


def parse_nm_lines(lines: Iterable[str]) -> dict[tuple[str, str, str], str]:
    out: dict[tuple[str, str, str], str] = {}
    for line in lines:
        match = NM_SIZE_LINE_RE.match(line)
        if not match:
            continue
        addr, size, typ, name = match.groups()
        if typ not in TEXT_SYMBOL_TYPES:
            continue
        out[(addr, size, typ)] = name.strip()
    return out


def build_symbol_index(nm_bin: str, binary: Path) -> SymbolIndex:
    nm_args = [nm_bin, "-n", "-S", "--defined-only"]
    raw_by_key = parse_nm_lines(run_text(nm_args + [str(binary)]))
    dem_by_key = parse_nm_lines(run_text(nm_args + ["-C", str(binary)]))

    symbols: list[Symbol] = []
    for key, raw_name in raw_by_key.items():
        dem_name = dem_by_key.get(key)
        if not dem_name:
            continue
        addr = int(key[0], 16)
        size = int(key[1], 16)
        symbols.append(
            Symbol(addr=addr, size=size, typ=key[2], raw=raw_name, demangled=dem_name)
        )
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


def parse_sample_ip(line: str) -> int | None:
    first = line.strip().split(None, 1)[0] if line.strip() else ""
    if not first:
        return None
    try:
        return int(first, 16)
    except ValueError:
        return None


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
    target_ip_source: str,
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
                target_branch_type = target_entry.branch_type or (
                    raw_entries[0].branch_type if raw_entries else "UNKNOWN"
                )

                load_bias = None
                if raw_entries and raw_entries[0].raw_to_addr is not None:
                    load_bias = raw_entries[0].raw_to_addr - target_addr
                if target_ip_source == "sample-ip":
                    sample_ip = parse_sample_ip(raw_line or sym_line)
                    if sample_ip is not None and load_bias is not None:
                        sample_addr = sample_ip - load_bias
                        if sample_addr >= 0 and symbols.symbol_at(sample_addr) is not None:
                            target_addr = sample_addr

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

                yield idx, target_addr, target_branch_type, candidates
    finally:
        if raw_fh is not None:
            raw_fh.close()


def make_trace_inputs(args: argparse.Namespace) -> list[TraceInput]:
    if (args.lbr_sym or args.lbr_raw) and len(args.trace_dir) != 1:
        raise RuntimeError("--lbr-sym/--lbr-raw overrides are only supported with one --trace-dir")

    traces: list[TraceInput] = []
    for raw_dir in args.trace_dir:
        trace_dir = Path(raw_dir).resolve()
        lbr_sym = Path(args.lbr_sym).resolve() if args.lbr_sym else trace_dir / "lbr_symbolic_dump.txt"
        lbr_raw = Path(args.lbr_raw).resolve() if args.lbr_raw else trace_dir / "lbr_raw_dump.txt"
        if not lbr_sym.exists():
            raise RuntimeError(f"missing symbolic LBR dump: {lbr_sym}")
        if not lbr_raw.exists():
            lbr_raw = None
        traces.append(TraceInput(trace_dir=trace_dir, lbr_sym=lbr_sym, lbr_raw=lbr_raw))
    return traces


def iter_all_trace_samples(
    traces: list[TraceInput],
    symbols: SymbolIndex,
    depth: int,
    target_ip_source: str,
    max_samples: int = 0,
):
    global_idx = 0
    for trace_idx, trace in enumerate(traces):
        for _, target_addr, target_branch_type, candidates in iter_trace_samples(
            trace.lbr_sym, trace.lbr_raw, symbols, depth, target_ip_source, max_samples
        ):
            yield global_idx, trace_idx, target_addr, target_branch_type, candidates
            global_idx += 1


def audit_lbr0_targets(
    traces: list[TraceInput],
    symbols: SymbolIndex,
    max_samples: int = 0,
):
    """Count the newest LBR branch targets before any planner filtering."""
    target_counts: Counter = Counter()
    target_branch_types: dict[str, Counter] = defaultdict(Counter)
    target_resolutions: dict[str, tuple[int, Symbol] | None] = {}
    trace_lines = 0
    samples_with_lbr = 0

    for trace in traces:
        with trace.lbr_sym.open("r", encoding="utf-8", errors="replace") as handle:
            for idx, line in enumerate(handle):
                if max_samples and idx >= max_samples:
                    break
                trace_lines += 1
                entries = parse_entries(line, raw=False)
                if not entries:
                    continue
                samples_with_lbr += 1
                newest = entries[0]
                raw_target = newest.to_raw
                target_counts[raw_target] += 1
                target_branch_types[raw_target][newest.branch_type or "UNKNOWN"] += 1
                if raw_target not in target_resolutions:
                    target_resolutions[raw_target] = symbols.lookup_addr(raw_target)

    rows = []
    cumulative = 0
    total = sum(target_counts.values())
    for rank, (raw_target, count) in enumerate(target_counts.most_common(), start=1):
        cumulative += count
        resolved = target_resolutions[raw_target]
        if resolved is None:
            addr = None
            symbol = None
        else:
            addr, symbol = resolved
        rows.append(
            {
                "rank": rank,
                "samples": count,
                "cumulative_samples": cumulative,
                "cumulative_coverage_pct": 100.0 * cumulative / total if total else 0.0,
                "raw_lbr0_to": raw_target,
                "branch_type": target_branch_types[raw_target].most_common(1)[0][0],
                "binary_resolved": int(resolved is not None),
                "addr": hex(addr) if addr is not None else "",
                "cacheline64": hex(addr & ~0x3F) if addr is not None else "",
                "mangled": symbol.raw if symbol is not None else "",
                "demangled": symbol.demangled if symbol is not None else "",
            }
        )

    resolved_rows = [row for row in rows if row["binary_resolved"]]
    resolved_samples = sum(int(row["samples"]) for row in resolved_rows)
    return {
        "trace_lines": trace_lines,
        "samples_with_lbr": samples_with_lbr,
        "unique_symbolic_targets": len(target_counts),
        "binary_resolved_samples": resolved_samples,
        "binary_unresolved_samples": total - resolved_samples,
        "unique_binary_resolved_addresses": len({row["addr"] for row in resolved_rows}),
        "unique_binary_resolved_cachelines": len(
            {row["cacheline64"] for row in resolved_rows}
        ),
    }, rows


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
    # Use the containing text symbol as the target identity. addr2line often
    # reports inlined helper functions such as VL_NOT_W at the same header line
    # for many different generated Verilator functions. If we group only by
    # inline function:file:line, one "target" can actually represent hundreds
    # of distinct PCs, and the pass can only prefetch one representative block.
    #
    # The LLVM pass already carries the inlined file/line for debug-location
    # matching, but it finds the containing IR Function through the mangled
    # symbol. Keeping that symbol in the key makes the plan's target coverage
    # match the actual prefetchable PC locations much more closely.
    function = sym.demangled if sym else ""
    if not function:
        function = loc.function if loc.function and loc.function != "??" else ""
    return TargetKey(function=function, file=loc.file, line=loc.line, cacheline64=addr & ~0x3F)


def is_resolved_target(key: TargetKey) -> bool:
    return bool(key.function and key.file and key.line > 0 and not key.file.startswith("<"))


def is_resolved_loc(loc: SourceLoc) -> bool:
    return bool(loc.file and loc.line > 0 and not loc.file.startswith("<"))


def choose_top_targets(
    target_addr_counts: Counter,
    target_locs: dict[int, SourceLoc],
    symbols: SymbolIndex,
    top_k: int,
    target_coverage_pct: float,
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

    ordered = counts_by_key.most_common()
    if target_coverage_pct > 0.0:
        total = sum(counts_by_key.values())
        threshold = total * target_coverage_pct / 100.0
        cumulative = 0
        top = []
        for key, count in ordered:
            top.append((key, count))
            cumulative += count
            if target_coverage_pct < 100.0 and cumulative >= threshold:
                break
    else:
        top = ordered[:top_k]
    return top, addr_counts_by_key


def target_valid_in_binary(
    addr: int,
    profiled_symbols: SymbolIndex,
    validation_symbols: SymbolIndex,
) -> bool:
    profiled_sym = profiled_symbols.symbol_at(addr)
    if profiled_sym is None:
        return False
    validation_sym = validation_symbols.lookup_name(profiled_sym.raw)
    if validation_sym is None:
        return False
    offset = addr - profiled_sym.addr
    return validation_symbols.addr_in_symbol(validation_sym.addr + offset, validation_sym)


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


def append_selected_site(
    selected: list[dict],
    selected_sites: set[int],
    remaining: set[int],
    target_sample_count: int,
    site_addr: int,
    sample_set: set[int],
) -> None:
    if site_addr in selected_sites:
        return
    selected_sites.add(site_addr)
    new_cover = len(sample_set & remaining)
    remaining -= sample_set
    selected.append(
        {
            "site_addr": site_addr,
            "site_samples": len(sample_set),
            "new_covered_samples": new_cover,
            "cumulative_covered_samples": target_sample_count - len(remaining),
        }
    )


def top_sites_select_sites(
    samples_by_site: dict[int, set[int]],
    target_samples: set[int],
    budget: int,
    candidate_pool: int,
):
    pool_items = sorted(samples_by_site.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    if candidate_pool > 0:
        pool_items = pool_items[:candidate_pool]

    remaining = set(target_samples)
    selected: list[dict] = []
    selected_sites: set[int] = set()
    for site_addr, sample_set in pool_items:
        if len(selected) >= budget:
            break
        append_selected_site(
            selected, selected_sites, remaining, len(target_samples), site_addr, sample_set
        )
    return selected


def per_depth_select_sites(
    samples_by_site: dict[int, set[int]],
    target_samples: set[int],
    site_meta: dict[int, SiteMeta],
    budget: int,
    depth_min: int,
    depth_max: int,
    sites_per_depth: int,
):
    remaining = set(target_samples)
    selected: list[dict] = []
    selected_sites: set[int] = set()

    for depth in range(depth_min, depth_max + 1):
        candidates = []
        for site_addr, sample_set in samples_by_site.items():
            depth_hits = site_meta[site_addr].depths.get(depth, 0)
            if depth_hits <= 0:
                continue
            candidates.append((site_addr, sample_set, depth_hits))
        candidates.sort(key=lambda row: (-row[2], -len(row[1]), row[0]))

        kept_at_depth = 0
        for site_addr, sample_set, _ in candidates:
            if len(selected) >= budget:
                return selected
            if site_addr in selected_sites:
                continue
            append_selected_site(
                selected, selected_sites, remaining, len(target_samples), site_addr, sample_set
            )
            kept_at_depth += 1
            if kept_at_depth >= sites_per_depth:
                break
    return selected


def all_paths_select_sites(
    samples_by_site: dict[int, set[int]],
    target_samples: set[int],
):
    remaining = set(target_samples)
    selected: list[dict] = []
    selected_sites: set[int] = set()
    for site_addr, sample_set in sorted(samples_by_site.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        append_selected_site(
            selected, selected_sites, remaining, len(target_samples), site_addr, sample_set
        )
    return selected


def loc_to_json(loc: SourceLoc, sym: Symbol | None, addr: int) -> dict:
    sym_addr = sym.addr if sym else 0
    return {
        "addr": hex(addr),
        "cacheline64": hex(addr & ~0x3F),
        "cacheline_offset": addr & 0x3F,
        "symbol_offset": hex(addr - sym_addr) if sym else "",
        "symbol_size": hex(sym.size) if sym else "",
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
    binary = Path(args.binary).resolve()
    output = Path(args.output).resolve()
    if not binary.exists():
        raise RuntimeError(f"missing binary: {binary}")

    traces = make_trace_inputs(args)
    symbols = build_symbol_index(args.nm, binary)
    validation_binary = Path(args.validation_binary).resolve() if args.validation_binary else None
    if validation_binary is not None and not validation_binary.exists():
        raise RuntimeError(f"missing validation binary: {validation_binary}")
    validation_symbols = (
        build_symbol_index(args.nm, validation_binary) if validation_binary is not None else None
    )

    lbr0_audit, lbr0_rows = audit_lbr0_targets(traces, symbols, args.max_samples)

    scanned_samples = 0
    parsed_samples = 0
    target_addr_counts: Counter = Counter()
    for _, _, target_addr, target_branch_type, _ in iter_all_trace_samples(
        traces, symbols, args.depth, args.target_ip_source, args.max_samples
    ):
        scanned_samples += 1
        if not branch_type_allowed(args.sample_branch_type_filter, target_branch_type):
            continue
        parsed_samples += 1
        target_addr_counts[target_addr] += 1

    prevalidation_target_addr_counts = target_addr_counts.copy()
    validation_rejected_addresses = 0
    validation_rejected_samples = 0
    if validation_symbols is not None:
        validated_counts: Counter = Counter()
        for target_addr, count in target_addr_counts.items():
            if target_valid_in_binary(target_addr, symbols, validation_symbols):
                validated_counts[target_addr] = count
            else:
                validation_rejected_addresses += 1
                validation_rejected_samples += count
        target_addr_counts = validated_counts

    target_locs = resolve_addrs(args.addr2line, binary, target_addr_counts.keys())
    all_target_key_counts: Counter = Counter()
    all_target_key_addrs: dict[TargetKey, Counter] = defaultdict(Counter)
    for addr, count in target_addr_counts.items():
        key = target_key_for_addr(addr, target_locs, symbols)
        all_target_key_counts[key] += count
        all_target_key_addrs[key][addr] += count
    top_targets, addr_counts_by_key = choose_top_targets(
        target_addr_counts,
        target_locs,
        symbols,
        args.top_k,
        args.target_coverage_pct,
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

    for sample_idx, _, target_addr, target_branch_type, candidates in iter_all_trace_samples(
        traces, symbols, args.depth, args.target_ip_source, args.max_samples
    ):
        if not branch_type_allowed(args.sample_branch_type_filter, target_branch_type):
            continue
        target_key = addr_to_key.get(target_addr)
        if target_key not in selected_target_keys:
            continue
        target_samples[target_key].add(sample_idx)
        seen_sites: set[int] = set()
        for site_addr, branch_type, depth in candidates:
            if not branch_type_allowed(args.branch_type_filter, branch_type):
                continue
            if not branch_depth_allowed(
                args.branch_depth_policy,
                branch_type,
                depth,
                args.depth_min,
                args.depth,
            ):
                continue
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
    candidate_targets_before_source_resolution = sum(
        bool(site_map) for site_map in samples_by_site.values()
    )
    candidate_sites_before_source_resolution = len(all_site_addrs)
    site_locs = resolve_addrs(args.addr2line, binary, all_site_addrs)
    for target_key, site_map in list(samples_by_site.items()):
        for site_addr in list(site_map.keys()):
            if not is_resolved_loc(site_locs.get(site_addr, SourceLoc(function="", file="", line=0))):
                del site_map[site_addr]
    candidate_targets_after_source_resolution = sum(
        bool(site_map) for site_map in samples_by_site.values()
    )
    candidate_sites_after_source_resolution = len(
        {
            site_addr
            for site_map in samples_by_site.values()
            for site_addr in site_map
        }
    )

    selected_rows_by_target: dict[TargetKey, list[dict]] = defaultdict(list)
    for target_rank, (target_key, target_count) in enumerate(top_targets, start=1):
        target_site_samples = samples_by_site.get(target_key, {})
        target_sample_set = target_samples.get(target_key, set())
        if args.selection_mode == "greedy":
            selected = greedy_select_sites(
                target_site_samples,
                target_sample_set,
                args.site_budget_per_target,
                args.candidate_pool,
            )
        elif args.selection_mode == "top-sites":
            selected = top_sites_select_sites(
                target_site_samples,
                target_sample_set,
                args.site_budget_per_target,
                args.candidate_pool,
            )
        elif args.selection_mode == "per-depth":
            selected = per_depth_select_sites(
                target_site_samples,
                target_sample_set,
                site_meta.get(target_key, {}),
                args.site_budget_per_target,
                args.depth_min,
                args.depth,
                args.sites_per_depth,
            )
        else:
            selected = all_paths_select_sites(
                target_site_samples,
                target_sample_set,
            )
        for site_rank, row in enumerate(selected, start=1):
            row["target_key"] = target_key
            row["target_rank"] = target_rank
            row["target_samples"] = target_count
            row["site_rank"] = site_rank
            selected_rows_by_target[target_key].append(row)

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
                "cacheline64": hex(target_key.cacheline64),
                "mangled": target_sym.raw if target_sym else "",
                "symbol_size": hex(target_sym.size) if target_sym else "",
            }
        )

        for selected in selected_rows_by_target.get(target_key, []):
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
                "prefetch_mnemonic": args.prefetch_mnemonic,
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
                    "target_cacheline64": hex(target_key.cacheline64),
                    "site_function": site_loc.function,
                    "site_file": site_loc.file,
                    "site_line": site_loc.line,
                    "site_cacheline64": hex(site_addr & ~0x3F),
                    "branch_type": branch_type,
                    "lbr_depth": depth,
                    "samples": selected["site_samples"],
                    "new_covered_samples": selected["new_covered_samples"],
                    "cumulative_coverage_pct": f"{coverage_pct:.4f}",
                    "target_mangled": target_sym.raw if target_sym else "",
                    "site_mangled": site_sym.raw if site_sym else "",
                }
            )

    validated_target_samples = sum(target_addr_counts.values())
    selected_target_samples = sum(count for _, count in top_targets)
    selected_targets_with_injections = sum(
        bool(selected_rows_by_target.get(target_key)) for target_key, _ in top_targets
    )
    covered_selected_target_samples = sum(
        max(
            (
                int(row["cumulative_covered_samples"])
                for row in selected_rows_by_target.get(target_key, [])
            ),
            default=0,
        )
        for target_key, _ in top_targets
    )

    selected_target_keys = {key for key, _ in top_targets}
    all_target_rows = []
    cumulative_target_samples = 0
    for rank, (key, count) in enumerate(all_target_key_counts.most_common(), start=1):
        cumulative_target_samples += count
        rep_addr = all_target_key_addrs[key].most_common(1)[0][0]
        sym = symbols.symbol_at(rep_addr)
        all_target_rows.append(
            {
                "rank": rank,
                "samples": count,
                "cumulative_samples": cumulative_target_samples,
                "cumulative_coverage_pct": (
                    100.0 * cumulative_target_samples / validated_target_samples
                    if validated_target_samples
                    else 0.0
                ),
                "selected": int(key in selected_target_keys),
                "source_resolved": int(is_resolved_target(key)),
                "function": key.function,
                "file": key.file,
                "line": key.line,
                "addr": hex(rep_addr),
                "cacheline64": hex(key.cacheline64),
                "mangled": sym.raw if sym else "",
                "address_count": len(all_target_key_addrs[key]),
            }
        )

    plan = {
        "schema": "prefetchit.plan.v1",
        "prefetch": {
            "mnemonic": args.prefetch_mnemonic,
            "operand": "pc-relative-symbol-offset",
            "byte_offsets": args.prefetch_byte_offsets,
            "offset_mode": "target-symbol-offset",
        },
        "trace_dir": str(traces[0].trace_dir),
        "trace_dirs": [str(t.trace_dir) for t in traces],
        "binary": str(binary),
        "validation_binary": str(validation_binary) if validation_binary is not None else "",
        "options": {
            "top_k": args.top_k,
            "target_coverage_pct": args.target_coverage_pct,
            "depth": args.depth,
            "depth_min": args.depth_min,
            "site_budget_per_target": args.site_budget_per_target,
            "candidate_pool": args.candidate_pool,
            "selection_mode": args.selection_mode,
            "sites_per_depth": args.sites_per_depth,
            "allow_unresolved_targets": args.allow_unresolved_targets,
            "prefetch_mnemonic": args.prefetch_mnemonic,
            "prefetch_byte_offsets": args.prefetch_byte_offsets,
            "branch_depth_policy": {
                key: [lo, hi] for key, (lo, hi) in sorted(args.branch_depth_policy.items())
            },
            "branch_type_filter": sorted(args.branch_type_filter),
            "sample_branch_type_filter": sorted(args.sample_branch_type_filter),
            "target_ip_source": args.target_ip_source,
            "validation_binary": str(validation_binary) if validation_binary is not None else "",
        },
        "stats": {
            "input_traces": len(traces),
            "lbr0_trace_lines": lbr0_audit["trace_lines"],
            "lbr0_samples_with_branch_stack": lbr0_audit["samples_with_lbr"],
            "lbr0_unique_symbolic_targets": lbr0_audit["unique_symbolic_targets"],
            "lbr0_binary_resolved_samples": lbr0_audit["binary_resolved_samples"],
            "lbr0_binary_unresolved_samples": lbr0_audit["binary_unresolved_samples"],
            "lbr0_unique_binary_resolved_addresses": lbr0_audit[
                "unique_binary_resolved_addresses"
            ],
            "lbr0_unique_binary_resolved_cachelines": lbr0_audit[
                "unique_binary_resolved_cachelines"
            ],
            "scanned_samples": scanned_samples,
            "parsed_samples": parsed_samples,
            "prevalidation_target_samples": sum(prevalidation_target_addr_counts.values()),
            "prevalidation_unique_target_addresses": len(prevalidation_target_addr_counts),
            "prevalidation_unique_target_cachelines": len(
                {addr & ~0x3F for addr in prevalidation_target_addr_counts}
            ),
            "validated_target_samples": validated_target_samples,
            "unique_target_addresses": len(target_addr_counts),
            "unique_target_cachelines": len({addr & ~0x3F for addr in target_addr_counts}),
            "unique_target_keys": len(all_target_key_counts),
            "source_resolved_target_keys": sum(
                is_resolved_target(key) for key in all_target_key_counts
            ),
            "validation_rejected_target_addresses": validation_rejected_addresses,
            "validation_rejected_target_samples": validation_rejected_samples,
            "selected_targets": len(top_targets),
            "selected_target_samples": selected_target_samples,
            "selected_target_coverage_pct": (
                100.0 * selected_target_samples / validated_target_samples
                if validated_target_samples
                else 0.0
            ),
            "candidate_targets_before_source_resolution": (
                candidate_targets_before_source_resolution
            ),
            "candidate_sites_before_source_resolution": (
                candidate_sites_before_source_resolution
            ),
            "candidate_targets_after_source_resolution": (
                candidate_targets_after_source_resolution
            ),
            "candidate_sites_after_source_resolution": (
                candidate_sites_after_source_resolution
            ),
            "selected_targets_with_injections": selected_targets_with_injections,
            "selected_injections": len(injections),
            "covered_selected_target_samples": covered_selected_target_samples,
            "selected_site_dynamic_coverage_pct": (
                100.0 * covered_selected_target_samples / selected_target_samples
                if selected_target_samples
                else 0.0
            ),
            "planned_prefetches": len(injections) * len(args.prefetch_byte_offsets),
        },
        "injections": injections,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary_dir = Path(args.summary_dir).resolve() if args.summary_dir else output.parent
    write_csv(
        summary_dir / "all_lbr0_targets.csv",
        lbr0_rows,
        [
            "rank",
            "samples",
            "cumulative_samples",
            "cumulative_coverage_pct",
            "raw_lbr0_to",
            "branch_type",
            "binary_resolved",
            "addr",
            "cacheline64",
            "mangled",
            "demangled",
        ],
    )
    write_csv(
        summary_dir / "all_target_cachelines.csv",
        all_target_rows,
        [
            "rank",
            "samples",
            "cumulative_samples",
            "cumulative_coverage_pct",
            "selected",
            "source_resolved",
            "function",
            "file",
            "line",
            "addr",
            "cacheline64",
            "mangled",
            "address_count",
        ],
    )
    write_csv(
        summary_dir / "selected_top_targets.csv",
        top_csv,
        [
            "rank",
            "samples",
            "function",
            "file",
            "line",
            "addr",
            "cacheline64",
            "mangled",
            "symbol_size",
        ],
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
            "target_cacheline64",
            "site_function",
            "site_file",
            "site_line",
            "site_cacheline64",
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
