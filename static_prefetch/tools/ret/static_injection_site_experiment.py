#!/usr/bin/env python3
"""Evaluate static injection-site policies for static return targets.

Selection remains profile-free. PEBS/LBR traces are used only to measure whether
selected target/site pairs would have appeared on profiled RET-miss paths.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import re
import subprocess
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

FUNC_RE = re.compile(r"^([0-9a-fA-F]+)\s+<(.+)>:$")
INSN_RE = re.compile(r"^\s*([0-9a-fA-F]+):\s*(.*?)(?:\s+#.*)?$")
BRANCH_RE = re.compile(r"\b(j[a-z]+|jmpq?|callq?|retq?)\b\s*(.*)$")
TARGET_RE = re.compile(r"0x([0-9a-fA-F]+)(?:\s+<(.+)>)?")
SYM_OFF_RE = re.compile(r"^(.*)\+0x([0-9a-fA-F]+)$")
NM_RE = re.compile(r"^([0-9a-fA-F]+)\s+(?:[0-9a-fA-F]+\s+)?([A-Za-z])\s+(.+)$")
TEXT_TYPES = set("tTwW")
ENTRY_MIN_SLASHES = 7
CACHELINE = 64


@dataclass(frozen=True)
class Symbol:
    addr: int
    typ: str
    name: str
    size: int = 0


class SymbolIndex:
    def __init__(self, symbols: list[Symbol]):
        self.symbols = sorted(symbols, key=lambda s: (s.addr, s.name))
        self.addrs = [s.addr for s in self.symbols]
        self.by_name: dict[str, Symbol] = {}
        self.by_no_args: dict[str, Symbol] = {}
        self.by_addr: dict[int, Symbol] = {}
        for sym in self.symbols:
            self.by_name.setdefault(sym.name, sym)
            self.by_no_args.setdefault(strip_args(sym.name), sym)
            self.by_addr.setdefault(sym.addr, sym)

    def lookup_name(self, name: str) -> Symbol | None:
        base = normalize_symbol_name(name)
        return self.by_name.get(base) or self.by_no_args.get(strip_args(base))

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


def run_lines(cmd: list[str]) -> list[str]:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, encoding="utf-8", errors="replace").stdout.splitlines()


def build_symbol_index(binary: Path, nm: str) -> SymbolIndex:
    lines = run_lines([nm, "-S", "-n", "--defined-only", "--demangle", str(binary)])
    symbols: list[Symbol] = []
    for line in lines:
        parts = line.split(None, 3)
        if len(parts) >= 4:
            try:
                addr = int(parts[0], 16)
                size = int(parts[1], 16)
            except ValueError:
                continue
            typ = parts[2]
            name = parts[3].strip()
        else:
            m = NM_RE.match(line)
            if not m:
                continue
            addr_s, typ, name = m.groups()
            addr = int(addr_s, 16)
            size = 0
            name = name.strip()
        if typ not in TEXT_TYPES:
            continue
        symbols.append(Symbol(addr=addr, typ=typ, name=name, size=size))
    if not symbols:
        raise SystemExit(f"no text symbols parsed from {binary}")
    return SymbolIndex(symbols)


@dataclass
class FunctionSites:
    name: str
    addr: int
    size: int
    branch_addrs: list[int] = field(default_factory=list)
    call_addrs: list[int] = field(default_factory=list)
    ret_addrs: list[int] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class RetSample:
    target_key: tuple[str, int]
    lbr_sites: frozenset[tuple[str, int]]


def parse_target_operand(operand: str) -> tuple[int | None, str]:
    match = TARGET_RE.search(operand)
    if not match:
        return None, ""
    return int(match.group(1), 16), (match.group(2) or "").strip()


def build_static_sites(binary: Path, objdump: str, symbols: SymbolIndex) -> dict[str, FunctionSites]:
    funcs: dict[str, FunctionSites] = {
        s.name: FunctionSites(name=s.name, addr=s.addr, size=s.size) for s in symbols.symbols
    }
    proc = subprocess.Popen(
        [objdump, "-d", "--demangle", "--no-show-raw-insn", "--section=.text", str(binary)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    current: FunctionSites | None = None
    insns_by_func: dict[str, list[int]] = defaultdict(list)
    pending_calls: list[tuple[FunctionSites, int, int, str, bool]] = []
    for line in proc.stdout:
        fmatch = FUNC_RE.match(line.strip())
        if fmatch:
            sym = symbols.by_addr.get(int(fmatch.group(1), 16))
            current = funcs.get(sym.name) if sym else None
            continue
        if current is None:
            continue
        imatch = INSN_RE.match(line)
        if not imatch:
            continue
        addr = int(imatch.group(1), 16)
        asm = imatch.group(2).strip()
        insns_by_func[current.name].append(addr)
        bmatch = BRANCH_RE.search(asm)
        if not bmatch:
            continue
        op = bmatch.group(1)
        operand = bmatch.group(2)
        current.branch_addrs.append(addr)
        if op.startswith("ret"):
            current.ret_addrs.append(addr)
        elif op.startswith("call"):
            current.call_addrs.append(addr)
            target_addr, target_name = parse_target_operand(operand)
            callee_sym = symbols.symbol_at(target_addr) if target_addr is not None else None
            if callee_sym is not None:
                callee_name = callee_sym.name
                known = True
            else:
                callee_name = target_name or operand.strip() or "UNKNOWN_CALL_TARGET"
                known = False
            pending_calls.append((current, addr, target_addr or 0, callee_name, known))
    stderr = proc.stderr.read() if proc.stderr is not None else ""
    rc = proc.wait()
    if rc != 0:
        raise SystemExit(f"objdump failed rc={rc}: {stderr[:1000]}")

    next_by_func: dict[str, dict[int, int]] = {}
    for name, addrs in insns_by_func.items():
        next_by_func[name] = {a: addrs[i + 1] for i, a in enumerate(addrs[:-1])}
    for func, call_addr, callee_addr, callee_name, known in pending_calls:
        func.calls.append(
            {
                "call_addr": call_addr,
                "return_addr": next_by_func.get(func.name, {}).get(call_addr, call_addr + 5),
                "callee_addr": callee_addr,
                "callee_function": callee_name,
                "callee_known": 1 if known else 0,
                "callee_size": symbols.lookup_name(callee_name).size if symbols.lookup_name(callee_name) else 512,
            }
        )
    for func in funcs.values():
        func.branch_addrs.sort()
        func.call_addrs.sort()
        func.ret_addrs.sort()
    return funcs


def read_targets(path: Path, top_k: int) -> list[dict[str, str]]:
    rows = []
    seen: set[tuple[str, str]] = set()
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["target_function"], row["target_cacheline64"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            if top_k and len(rows) >= top_k:
                break
    return rows


@dataclass(frozen=True)
class Site:
    site_function: str
    site_addr: int
    site_cacheline64: int
    site_kind: str


def branch_sites_before(func: FunctionSites | None, target_addr: int, distance: int, budget: int) -> list[Site]:
    if func is None:
        return []
    lo = max(func.addr, target_addr - distance)
    # branch_addrs follows objdump order, so use binary search instead of
    # rescanning huge Verilator functions for every target.
    left = bisect.bisect_left(func.branch_addrs, lo)
    right = bisect.bisect_left(func.branch_addrs, target_addr)
    addrs = list(reversed(func.branch_addrs[left:right]))
    return [Site(func.name, a, a & ~0x3F, f"distance-{distance}") for a in addrs[:budget]]


def spread_branch_sites_before(func: FunctionSites | None, target_addr: int, distance: int, budget: int) -> list[Site]:
    if func is None or budget <= 0:
        return []
    lo = max(func.addr, target_addr - distance)
    left = bisect.bisect_left(func.branch_addrs, lo)
    right = bisect.bisect_left(func.branch_addrs, target_addr)
    addrs = func.branch_addrs[left:right]
    if not addrs:
        return []
    if len(addrs) <= budget:
        selected = list(reversed(addrs))
    else:
        # Keep the nearest branch, but spread the rest across the whole window.
        # This avoids spending every slot in a tiny branch-dense region just
        # before the return target.
        newest_first = list(reversed(addrs))
        idxs = {0}
        span = len(newest_first) - 1
        for i in range(1, budget):
            idxs.add(round(i * span / (budget - 1)))
        selected = [newest_first[i] for i in sorted(idxs)]
    return [Site(func.name, a, a & ~0x3F, f"distance-spread-{distance}") for a in selected[:budget]]


def call_sites_before(func: FunctionSites | None, target_addr: int, distance: int, budget: int) -> list[Site]:
    if func is None:
        return []
    lo = max(func.addr, target_addr - distance)
    left = bisect.bisect_left(func.call_addrs, lo)
    right = bisect.bisect_left(func.call_addrs, target_addr)
    addrs = list(reversed(func.call_addrs[left:right]))
    return [Site(func.name, a, a & ~0x3F, f"same-func-calls-{distance}") for a in addrs[:budget]]


def callee_calls(funcs: dict[str, FunctionSites], callee: str, depth: int, budget: int) -> list[Site]:
    out: list[tuple[int, Site]] = []
    q = deque([(callee, 1)])
    seen = set()
    while q:
        name, d = q.popleft()
        if (name, d) in seen:
            continue
        seen.add((name, d))
        f = funcs.get(name)
        if f is None:
            continue
        for c in f.calls:
            site = Site(f.name, int(c["call_addr"]), int(c["call_addr"]) & ~0x3F, f"callee-calls-d{depth}")
            out.append((int(c.get("callee_size", 0)), site))
            if d < depth and c.get("callee_known"):
                q.append((str(c["callee_function"]), d + 1))
    out.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in out[:budget]]


def build_reverse_callers(funcs: dict[str, FunctionSites]) -> dict[str, list[tuple[int, Site]]]:
    callers: dict[str, list[tuple[int, Site]]] = defaultdict(list)
    for func in funcs.values():
        for call in func.calls:
            callee = str(call["callee_function"])
            site = Site(func.name, int(call["call_addr"]), int(call["call_addr"]) & ~0x3F, "caller-chain")
            callers[callee].append((func.size, site))
    for edges in callers.values():
        edges.sort(key=lambda x: (x[0], x[1].site_addr), reverse=True)
    return callers


def caller_chain_sites(
    reverse_callers: dict[str, list[tuple[int, Site]]],
    target_func: str,
    depth: int,
    budget: int,
) -> list[Site]:
    out: list[tuple[int, Site]] = []
    q = deque([(target_func, 1)])
    seen_nodes: set[tuple[str, int]] = set()
    while q:
        func_name, d = q.popleft()
        if (func_name, d) in seen_nodes:
            continue
        seen_nodes.add((func_name, d))
        for weight, site in reverse_callers.get(func_name, []):
            out.append((weight, Site(site.site_function, site.site_addr, site.site_cacheline64, f"caller-chain-d{depth}")))
            if d < depth:
                q.append((site.site_function, d + 1))
    out.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in out[:budget]]


def sites_for_target(
    row: dict[str, str],
    funcs: dict[str, FunctionSites],
    reverse_callers: dict[str, list[tuple[int, Site]]],
    strategy: str,
    budget: int,
    callee_cache: dict[tuple[str, int, int], list[Site]],
) -> list[Site]:
    target_func = row["target_function"]
    callee = row["callee_function"]
    target_addr = int(row["target_addr"], 16)
    call_addr = int(row["call_addr"], 16)
    target_f = funcs.get(target_func)
    callee_f = funcs.get(callee)
    sites: list[Site] = []
    if strategy == "callsite":
        sites = [Site(target_func, call_addr, call_addr & ~0x3F, "callsite")]
    elif strategy == "callee-ret":
        if callee_f is not None:
            sites = [Site(callee_f.name, a, a & ~0x3F, "callee-ret") for a in callee_f.ret_addrs[:budget]]
    elif strategy.startswith("distance-"):
        distance = int(strategy.split("-", 1)[1].replace("k", "")) * 1024
        sites = branch_sites_before(target_f, target_addr, distance, budget)
    elif strategy.startswith("spread-distance-"):
        distance = int(strategy.rsplit("-", 1)[1].replace("k", "")) * 1024
        sites = spread_branch_sites_before(target_f, target_addr, distance, budget)
    elif strategy.startswith("same-func-calls-"):
        distance = int(strategy.rsplit("-", 1)[1].replace("k", "")) * 1024
        sites = call_sites_before(target_f, target_addr, distance, budget)
    elif strategy.startswith("callee-calls-d"):
        depth = int(strategy.rsplit("d", 1)[1])
        cache_key = (callee, depth, budget)
        sites = callee_cache.get(cache_key)
        if sites is None:
            sites = callee_calls(funcs, callee, depth, budget)
            callee_cache[cache_key] = sites
    elif strategy.startswith("caller-chain-d"):
        depth = int(strategy.rsplit("d", 1)[1])
        sites = caller_chain_sites(reverse_callers, target_func, depth, budget)
    elif strategy == "mixed-call-ret-d1":
        sites.extend(sites_for_target(row, funcs, reverse_callers, "callsite", 1, callee_cache))
        sites.extend(sites_for_target(row, funcs, reverse_callers, "callee-ret", max(1, budget // 3), callee_cache))
        sites.extend(sites_for_target(row, funcs, reverse_callers, "callee-calls-d1", max(1, budget - len(sites)), callee_cache))
    else:
        raise SystemExit(f"unknown strategy: {strategy}")
    # Deduplicate site cachelines per target while preserving order.
    deduped = []
    seen = set()
    for s in sites:
        key = (s.site_function, s.site_cacheline64, s.site_kind)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s)
        if len(deduped) >= budget:
            break
    return deduped


def build_site_plan(
    targets: list[dict[str, str]],
    funcs: dict[str, FunctionSites],
    reverse_callers: dict[str, list[tuple[int, Site]]],
    strategy: str,
    budget: int,
):
    plan: dict[tuple[str, int], list[Site]] = {}
    callee_cache: dict[tuple[str, int, int], list[Site]] = {}
    for row in targets:
        key = (row["target_function"], int(row["target_cacheline64"], 16))
        plan[key] = sites_for_target(row, funcs, reverse_callers, strategy, budget, callee_cache)
    return plan


@dataclass(frozen=True)
class BranchEntry:
    from_raw: str
    to_raw: str
    branch_type: str


def parse_symbolic_entry(tok: str) -> BranchEntry | None:
    if tok.count("/") < ENTRY_MIN_SLASHES:
        return None
    parts = tok.split("/")
    if len(parts) < 7:
        return None
    return BranchEntry(from_raw=parts[0], to_raw=parts[1], branch_type=parts[6].upper())


def parse_entries(line: str) -> list[BranchEntry]:
    out = []
    for tok in line.strip().split():
        e = parse_symbolic_entry(tok)
        if e is not None:
            out.append(e)
    return out


def iter_ret_samples(trace_dirs: list[Path], symbols: SymbolIndex):
    for trace_dir in trace_dirs:
        lbr = trace_dir / "lbr_symbolic_dump.txt"
        if not lbr.exists():
            raise SystemExit(f"missing {lbr}")
        with lbr.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                entries = parse_entries(line)
                if not entries or entries[0].branch_type != "RET":
                    continue
                resolved = symbols.lookup_addr(entries[0].to_raw)
                if resolved is None or resolved[1] is None:
                    continue
                target_addr, target_sym = resolved
                lbr_sites = set()
                for e in entries:
                    from_res = symbols.lookup_addr(e.from_raw)
                    if from_res is None or from_res[1] is None:
                        continue
                    from_addr, from_sym = from_res
                    lbr_sites.add((from_sym.name, from_addr & ~0x3F))
                yield (target_sym.name, target_addr & ~0x3F), lbr_sites


def load_ret_samples(trace_dirs: list[Path], symbols: SymbolIndex) -> list[RetSample]:
    return [RetSample(target_key=k, lbr_sites=frozenset(s)) for k, s in iter_ret_samples(trace_dirs, symbols)]


def evaluate_plan(plan: dict[tuple[str, int], list[Site]], samples: list[RetSample]) -> dict[str, float | int]:
    truth_samples = 0
    target_hit = 0
    site_hit = 0
    selected_target_set = set(plan)
    site_pairs = sum(len(v) for v in plan.values())
    unique_site_cachelines = len({(s.site_function, s.site_cacheline64) for sites in plan.values() for s in sites})
    targets_with_site = sum(1 for sites in plan.values() if sites)
    for sample in samples:
        target_key = sample.target_key
        lbr_sites = sample.lbr_sites
        truth_samples += 1
        sites = plan.get(target_key)
        if sites is None:
            continue
        target_hit += 1
        selected_sites = {(s.site_function, s.site_cacheline64) for s in sites}
        if selected_sites & lbr_sites:
            site_hit += 1
    return {
        "truth_samples": truth_samples,
        "selected_targets": len(selected_target_set),
        "targets_with_site": targets_with_site,
        "site_pairs": site_pairs,
        "unique_site_cachelines": unique_site_cachelines,
        "target_hit_samples": target_hit,
        "target_weighted_recall": target_hit / truth_samples if truth_samples else 0.0,
        "site_hit_samples": site_hit,
        "site_weighted_coverage": site_hit / truth_samples if truth_samples else 0.0,
        "site_conditional_coverage": site_hit / target_hit if target_hit else 0.0,
    }


def write_site_csv(path: Path, plan: dict[tuple[str, int], list[Site]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        fields = ["target_function", "target_cacheline64", "site_function", "site_addr", "site_cacheline64", "site_kind"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for (tf, tc), sites in plan.items():
            for s in sites:
                w.writerow(
                    {
                        "target_function": tf,
                        "target_cacheline64": f"0x{tc:x}",
                        "site_function": s.site_function,
                        "site_addr": f"0x{s.site_addr:x}",
                        "site_cacheline64": f"0x{s.site_cacheline64:x}",
                        "site_kind": s.site_kind,
                    }
                )


def parse_int_list(raw: str) -> list[int]:
    return [int(x) for x in raw.split(",") if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--targets", type=Path, required=True)
    ap.add_argument("--trace-dir", type=Path, action="append", default=[],
                    help="PEBS/LBR trace dirs; optional — without them site plans are still written but recall/coverage metrics are 0")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--top-k", default="1000,10000,50000,100000")
    ap.add_argument("--strategy", action="append", default=[])
    ap.add_argument("--site-budget", type=int, default=8)
    ap.add_argument("--site-budget-list", default="", help="comma-separated budgets; overrides --site-budget")
    ap.add_argument("--skip-site-csv", action="store_true", help="write metrics/report only")
    ap.add_argument("--nm", default="llvm-nm-19")
    ap.add_argument("--objdump", default="llvm-objdump-19")
    args = ap.parse_args()

    strategies = args.strategy or [
        "callsite",
        "callee-ret",
        "distance-4k",
        "distance-16k",
        "distance-64k",
        "spread-distance-64k",
        "same-func-calls-4k",
        "same-func-calls-16k",
        "caller-chain-d1",
        "caller-chain-d2",
        "callee-calls-d1",
        "callee-calls-d2",
        "mixed-call-ret-d1",
    ]
    symbols = build_symbol_index(args.binary, args.nm)
    funcs = build_static_sites(args.binary, args.objdump, symbols)
    reverse_callers = build_reverse_callers(funcs)
    samples = load_ret_samples(args.trace_dir, symbols) if args.trace_dir else []
    print(f"[ok] loaded {len(samples)} immediate RET miss samples" + ("" if args.trace_dir else " (no traces: selection is profile-free, metrics are placeholders)"))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    metrics = []
    site_budgets = parse_int_list(args.site_budget_list) if args.site_budget_list else [args.site_budget]
    for top_k in parse_int_list(args.top_k):
        targets = read_targets(args.targets, top_k)
        for site_budget in site_budgets:
            for strategy in strategies:
                plan = build_site_plan(targets, funcs, reverse_callers, strategy, site_budget)
                m = evaluate_plan(plan, samples)
                row = {"top_k": top_k, "strategy": strategy, "site_budget": site_budget, **m}
                metrics.append(row)
                if not args.skip_site_csv:
                    site_csv = args.out_dir / "site_plans" / f"top{top_k}_budget{site_budget}_{strategy}.csv"
                    write_site_csv(site_csv, plan)
                print(f"[ok] top_k={top_k} budget={site_budget} strategy={strategy} target_recall={m['target_weighted_recall']:.4f} site_cov={m['site_weighted_coverage']:.4f} pairs={m['site_pairs']}")

    fields = [
        "top_k",
        "strategy",
        "site_budget",
        "truth_samples",
        "selected_targets",
        "targets_with_site",
        "site_pairs",
        "unique_site_cachelines",
        "target_hit_samples",
        "target_weighted_recall",
        "site_hit_samples",
        "site_weighted_coverage",
        "site_conditional_coverage",
    ]
    with (args.out_dir / "site_policy_metrics.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(metrics)
    with (args.out_dir / "site_policy_report.md").open("w", encoding="utf-8") as f:
        f.write("# Static Injection-Site Policy Evaluation\n\n")
        f.write("| Top K | Strategy | Targets With Site | Site Pairs | Unique Site CL | Target Recall | Site Coverage | Conditional Site Coverage |\n")
        f.write("|---:|---|---:|---:|---:|---:|---:|---:|\n")
        for r in metrics:
            f.write(
                f"| {r['top_k']} | {r['strategy']} | {r['targets_with_site']} | {r['site_pairs']} | {r['unique_site_cachelines']} | "
                f"{r['target_weighted_recall']:.4f} | {r['site_weighted_coverage']:.4f} | {r['site_conditional_coverage']:.4f} |\n"
            )
    print(f"[ok] wrote {args.out_dir / 'site_policy_metrics.csv'}")
    print(f"[ok] wrote {args.out_dir / 'site_policy_report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
