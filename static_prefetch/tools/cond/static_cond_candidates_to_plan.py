#!/usr/bin/env python3
"""Convert static COND target candidates into a PrefetchIT LLVM-pass plan.

The plan uses symbol+offset PC-relative operands for targets. Injection sites are
selected from the conditional branch that reaches the target, or from preceding
branch sites in the same containing function for more prefetch lead time.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


FUNC_RE = re.compile(r"^([0-9a-fA-F]+)\s+<(.+)>:$")
INSN_RE = re.compile(r"^\s*([0-9a-fA-F]+):\s*(.*?)(?:\s+#.*)?$")
COND_RE = re.compile(r"\b(j[a-z]+)\b\s+(.+)$")
CALL_RE = re.compile(r"\bcallq?\b\s+(.+)$")
RET_RE = re.compile(r"\bretq?\b")
JMP_RE = re.compile(r"\bjmpq?\b\s+(.+)$")
TEXT_TYPES = set("tTwW")


@dataclass(frozen=True)
class Symbol:
    addr: int
    size: int
    typ: str
    raw: str
    demangled: str

    @property
    def end(self) -> int:
        return self.addr + max(1, self.size)


@dataclass(frozen=True)
class BranchSite:
    addr: int
    branch_type: str
    op: str


@dataclass(frozen=True)
class SourceLoc:
    function: str
    file: str
    line: int


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

    def lookup_demangled(self, name: str) -> Symbol | None:
        name = name.strip()
        return self.by_demangled.get(name) or self.by_demangled_no_args.get(strip_args(name))

    def symbol_at(self, addr: int) -> Symbol | None:
        idx = bisect.bisect_right(self.addrs, addr) - 1
        if idx < 0:
            return None
        sym = self.symbols[idx]
        return sym if addr < sym.end else None


class BranchIndex:
    def __init__(self) -> None:
        self.by_func: dict[str, list[BranchSite]] = {}
        self.addrs_by_func: dict[str, list[int]] = {}
        self.by_addr: dict[int, BranchSite] = {}

    def add(self, func_raw: str, site: BranchSite) -> None:
        self.by_func.setdefault(func_raw, []).append(site)
        self.by_addr[site.addr] = site

    def finalize(self) -> None:
        for func, sites in self.by_func.items():
            sites.sort(key=lambda s: s.addr)
            self.addrs_by_func[func] = [s.addr for s in sites]

    def current_or_previous(self, func_raw: str, branch_addr: int, policy: str, prev_count: int) -> list[BranchSite]:
        sites = self.by_func.get(func_raw, [])
        if not sites:
            return []
        addrs = self.addrs_by_func.get(func_raw, [])
        idx = bisect.bisect_left(addrs, branch_addr)
        current = self.by_addr.get(branch_addr)
        selected: list[BranchSite] = []
        if policy in {"current", "current-prev"} and current is not None:
            selected.append(current)
        if policy in {"prev", "current-prev"} and prev_count > 0:
            prev = sites[max(0, idx - prev_count) : idx]
            selected.extend(reversed(prev))
        if policy == "prev" and not selected and current is not None:
            selected.append(current)
        return selected


def strip_args(name: str) -> str:
    return name.split("(", 1)[0].strip()


def run_lines(cmd: list[str]) -> list[str]:
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.splitlines()


def parse_nm(binary: Path, nm: str) -> SymbolIndex:
    raw_rows = []
    dem_rows = []
    for demangle, rows in [(False, raw_rows), (True, dem_rows)]:
        cmd = [nm, "-S", "-n", "--defined-only"]
        if demangle:
            cmd.append("--demangle")
        cmd.append(str(binary))
        for line in run_lines(cmd):
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            try:
                addr = int(parts[0], 16)
                size = int(parts[1], 16)
            except ValueError:
                continue
            if parts[2] not in TEXT_TYPES:
                continue
            rows.append((addr, size, parts[2], parts[3].strip()))
    dem_by_key = {(addr, size, typ): name for addr, size, typ, name in dem_rows}
    symbols = []
    for addr, size, typ, raw in raw_rows:
        demangled = dem_by_key.get((addr, size, typ), raw)
        symbols.append(Symbol(addr=addr, size=size, typ=typ, raw=raw, demangled=demangled))
    if not symbols:
        raise SystemExit(f"no text symbols parsed from {binary}")
    return SymbolIndex(symbols)


def classify_branch(asm: str) -> tuple[str, str] | None:
    if CALL_RE.search(asm):
        return "CALL", "call"
    if RET_RE.search(asm):
        return "RET", "ret"
    cm = COND_RE.search(asm)
    if cm and not cm.group(1).startswith("jmp"):
        return "COND", cm.group(1)
    jm = JMP_RE.search(asm)
    if jm:
        operand = jm.group(1).strip()
        if "*" in operand or "(" in operand:
            return "IND", "jmp"
        return "UNCOND", "jmp"
    return None


def parse_branch_index(binary: Path, objdump: str, symbols: SymbolIndex) -> BranchIndex:
    index = BranchIndex()
    current: Symbol | None = None
    proc = subprocess.Popen(
        [objdump, "-d", "--demangle", "--no-show-raw-insn", "--section=.text", str(binary)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        fm = FUNC_RE.match(line.strip())
        if fm:
            current = symbols.symbol_at(int(fm.group(1), 16))
            continue
        if current is None:
            continue
        im = INSN_RE.match(line)
        if not im:
            continue
        addr = int(im.group(1), 16)
        asm = im.group(2).strip()
        branch = classify_branch(asm)
        if branch is None:
            continue
        branch_type, op = branch
        index.add(current.raw, BranchSite(addr=addr, branch_type=branch_type, op=op))
    stderr = proc.stderr.read() if proc.stderr is not None else ""
    rc = proc.wait()
    if rc != 0:
        raise SystemExit(f"objdump failed rc={rc}: {stderr[:1000]}")
    index.finalize()
    return index


def parse_loc(raw: str) -> tuple[str, int]:
    text = raw.strip()
    if not text or text.startswith("??") or ":" not in text:
        return "", 0
    file_name, line_text = text.rsplit(":", 1)
    try:
        line = int(line_text.split()[0])
    except ValueError:
        line = 0
    return file_name, line


def resolve_addrs(addr2line: str, binary: Path, addrs: Iterable[int]) -> dict[int, SourceLoc]:
    ordered = sorted(set(addrs))
    out: dict[int, SourceLoc] = {}
    chunk = 1000
    for start in range(0, len(ordered), chunk):
        part = ordered[start : start + chunk]
        lines = run_lines([addr2line, "-e", str(binary), "-f", "-C"] + [hex(a) for a in part])
        for idx, addr in enumerate(part):
            fn = lines[2 * idx].strip() if 2 * idx < len(lines) else ""
            file_name, line = parse_loc(lines[2 * idx + 1] if 2 * idx + 1 < len(lines) else "")
            out[addr] = SourceLoc(function=fn, file=file_name, line=line)
    return out


def parse_offsets(raw: str) -> list[int]:
    out = []
    seen = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        value = int(item, 0)
        if value < 0:
            raise argparse.ArgumentTypeError("offsets must be non-negative")
        if value not in seen:
            seen.add(value)
            out.append(value)
    if not out:
        raise argparse.ArgumentTypeError("at least one offset required")
    return out


def parse_branch_types(raw: str) -> set[str]:
    out = {item.strip().upper() for item in raw.split(",") if item.strip()}
    valid = {"CALL", "COND", "IND", "RET", "UNCOND"}
    invalid = out - valid
    if invalid:
        raise argparse.ArgumentTypeError(f"invalid branch type(s): {','.join(sorted(invalid))}")
    return out


def loc_to_json(loc: SourceLoc, sym: Symbol | None, addr: int) -> dict[str, object]:
    sym_addr = sym.addr if sym else 0
    return {
        "addr": hex(addr),
        "cacheline64": hex(addr & ~0x3F),
        "cacheline_offset": addr & 0x3F,
        "symbol_offset": hex(addr - sym_addr) if sym else "",
        "mangled": sym.raw if sym else "",
        "demangled": sym.demangled if sym else loc.function,
        "function": loc.function or (sym.demangled if sym else ""),
        "file": loc.file,
        "line": loc.line,
    }


def read_candidates(path: Path, limit: int) -> list[dict[str, str]]:
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--top-k", type=int, default=10000)
    ap.add_argument("--site-policy", choices=["current", "prev", "current-prev"], default="current")
    ap.add_argument("--prev-branches", type=int, default=4)
    ap.add_argument("--site-budget-per-target", type=int, default=4)
    ap.add_argument("--prefetch-mnemonic", default="prefetcht1")
    ap.add_argument("--prefetch-byte-offsets", type=parse_offsets, default=parse_offsets("0,64"))
    ap.add_argument(
        "--site-branch-types",
        type=parse_branch_types,
        default=parse_branch_types(""),
        help="Optional comma-separated allowed site branch types, e.g. COND or COND,UNCOND. Empty means all.",
    )
    ap.add_argument(
        "--skip-same-cacheline-site-target",
        action="store_true",
        help="Drop injections whose site and target are already in the same 64B cacheline.",
    )
    ap.add_argument("--label", default="static-cond")
    ap.add_argument("--nm", default="llvm-nm-19")
    ap.add_argument("--objdump", default="llvm-objdump-19")
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    args = ap.parse_args()

    if args.top_k <= 0 or args.prev_branches < 0 or args.site_budget_per_target <= 0:
        raise SystemExit("invalid non-positive argument")
    binary = args.binary.resolve()
    symbols = parse_nm(binary, args.nm)
    branches = parse_branch_index(binary, args.objdump, symbols)
    candidates = read_candidates(args.candidates, args.top_k)

    all_target_addrs = []
    all_site_addrs = []
    selected: list[tuple[int, dict[str, str], Symbol, int, BranchSite]] = []
    missing_target = 0
    missing_site = 0
    filtered_site_type = 0
    skipped_same_cacheline = 0
    for target_rank, row in enumerate(candidates, 1):
        target_sym = symbols.lookup_demangled(row["target_function"])
        if target_sym is None:
            missing_target += 1
            continue
        target_addr = target_sym.addr + int(row["target_symbol_offset"], 16)
        branch_addr = int(row["branch_addr"], 16)
        sites = branches.current_or_previous(
            target_sym.raw,
            branch_addr,
            args.site_policy,
            args.prev_branches,
        )
        if args.site_branch_types:
            before_filter = len(sites)
            sites = [site for site in sites if site.branch_type in args.site_branch_types]
            filtered_site_type += before_filter - len(sites)
        if args.skip_same_cacheline_site_target:
            before_filter = len(sites)
            sites = [site for site in sites if (site.addr & ~0x3F) != (target_addr & ~0x3F)]
            skipped_same_cacheline += before_filter - len(sites)
        sites = sites[: args.site_budget_per_target]
        if not sites:
            missing_site += 1
            continue
        all_target_addrs.append(target_addr)
        for site in sites:
            all_site_addrs.append(site.addr)
            selected.append((target_rank, row, target_sym, target_addr, site))

    site_locs = resolve_addrs(args.addr2line, binary, all_site_addrs)
    target_locs = resolve_addrs(args.addr2line, binary, all_target_addrs)

    injections = []
    seen: set[tuple[str, int, str, int, str]] = set()
    site_type_counts: Counter[str] = Counter()
    unresolved_sites = 0
    for target_rank, row, target_sym, target_addr, site in selected:
        site_sym = symbols.symbol_at(site.addr)
        site_loc = site_locs.get(site.addr, SourceLoc("", "", 0))
        if site_sym is None or site_loc.line <= 0:
            unresolved_sites += 1
            continue
        target_loc = target_locs.get(target_addr, SourceLoc("", "", 0))
        dedupe = (site_sym.raw, site.addr, target_sym.raw, target_addr & ~0x3F, args.prefetch_mnemonic)
        if dedupe in seen:
            continue
        seen.add(dedupe)
        site_type_counts[site.branch_type] += 1
        injections.append(
            {
                "target_rank": target_rank,
                "site_rank": 1,
                "prefetch_mnemonic": args.prefetch_mnemonic,
                "samples": 0,
                "new_covered_samples": 0,
                "cumulative_covered_samples": 0,
                "cumulative_coverage_pct": 0.0,
                "target": loc_to_json(target_loc, target_sym, target_addr),
                "site": {
                    **loc_to_json(site_loc, site_sym, site.addr),
                    "branch_type": site.branch_type,
                    "branch_op": site.op,
                    "lbr_depth": 0,
                    "observed_depths": "static",
                },
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
        "binary": str(binary),
        "candidate_csv": str(args.candidates.resolve()),
        "options": {
            "label": args.label,
            "top_k": args.top_k,
            "site_policy": args.site_policy,
            "prev_branches": args.prev_branches,
            "site_budget_per_target": args.site_budget_per_target,
            "site_branch_types": sorted(args.site_branch_types),
            "skip_same_cacheline_site_target": args.skip_same_cacheline_site_target,
            "prefetch_mnemonic": args.prefetch_mnemonic,
            "prefetch_byte_offsets": args.prefetch_byte_offsets,
        },
        "stats": {
            "candidate_rows_read": len(candidates),
            "missing_target_symbols": missing_target,
            "missing_site_candidates": missing_site,
            "filtered_site_type_candidates": filtered_site_type,
            "skipped_same_cacheline_candidates": skipped_same_cacheline,
            "unresolved_site_locations": unresolved_sites,
            "selected_injections": len(injections),
            "planned_prefetches": len(injections) * len(args.prefetch_byte_offsets),
            "site_branch_type_counts": dict(sorted(site_type_counts.items())),
        },
        "injections": injections,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[ok] wrote {args.output}")
    print(json.dumps(plan["stats"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
