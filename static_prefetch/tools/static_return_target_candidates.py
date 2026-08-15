#!/usr/bin/env python3
"""Generate profile-free return target candidates from an x86-64 binary.

The core target unit is the cacheline containing the instruction immediately
after a direct call. That is the return target for the callee's RET.
"""

from __future__ import annotations

import argparse
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
CALL_RE = re.compile(r"\bcallq?\b\s+(.+)$")
BRANCH_RE = re.compile(r"\b(j[a-z]+|jmpq?|callq?)\b\s+(.+)$")
TARGET_RE = re.compile(r"0x([0-9a-fA-F]+)(?:\s+<(.+)>)?")
TEXT_TYPES = set("tTwW")


@dataclass
class FunctionInfo:
    addr: int
    size: int
    typ: str
    name: str
    calls: list["CallSite"] = field(default_factory=list)
    branch_count: int = 0
    backedge_count: int = 0
    loop_call_count: int = 0
    max_backedge_span: int = 0
    backedge_regions: list[tuple[int, int]] = field(default_factory=list)

    @property
    def end(self) -> int:
        return self.addr + max(self.size, 1)

    @property
    def cachelines(self) -> int:
        return max(1, math.ceil(max(self.size, 1) / 64))


@dataclass
class CallSite:
    caller: str
    callee: str
    call_addr: int
    return_addr: int
    call_offset: int
    return_offset: int
    target_addr: int
    in_loop: bool
    loop_depth_est: int
    callee_known: bool = True


class SymbolIndex:
    def __init__(self, funcs: list[FunctionInfo]):
        self.funcs = sorted(funcs, key=lambda f: f.addr)
        self.addrs = [f.addr for f in self.funcs]
        self.by_name = {f.name: f for f in self.funcs}
        self.by_addr = {f.addr: f for f in self.funcs}

    def at(self, addr: int) -> FunctionInfo | None:
        import bisect

        idx = bisect.bisect_right(self.addrs, addr) - 1
        if idx < 0:
            return None
        f = self.funcs[idx]
        if addr < f.end:
            return f
        return None

    def by_start(self, addr: int) -> FunctionInfo | None:
        return self.by_addr.get(addr)


def run_lines(cmd: list[str]) -> list[str]:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, encoding="utf-8", errors="replace").stdout.splitlines()


def parse_nm(binary: Path, nm: str) -> SymbolIndex:
    lines = run_lines([nm, "-S", "-n", "--defined-only", "--demangle", str(binary)])
    funcs: list[FunctionInfo] = []
    for line in lines:
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            addr = int(parts[0], 16)
            size = int(parts[1], 16)
        except ValueError:
            continue
        typ = parts[2]
        if typ not in TEXT_TYPES:
            continue
        name = parts[3].strip()
        if not name or name.startswith(".L"):
            continue
        funcs.append(FunctionInfo(addr=addr, size=size, typ=typ, name=name))
    if not funcs:
        raise SystemExit(f"no text symbols parsed from {binary}")
    return SymbolIndex(funcs)


def parse_target_operand(operand: str) -> tuple[int | None, str]:
    match = TARGET_RE.search(operand)
    if not match:
        return None, ""
    addr = int(match.group(1), 16)
    name = (match.group(2) or "").strip()
    return addr, name


def parse_objdump(binary: Path, objdump: str, symbols: SymbolIndex) -> None:
    proc = subprocess.Popen(
        [objdump, "-d", "--demangle", "--no-show-raw-insn", "--section=.text", str(binary)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    current: FunctionInfo | None = None
    prev_addr: int | None = None

    for line in proc.stdout:
        fmatch = FUNC_RE.match(line.strip())
        if fmatch:
            addr = int(fmatch.group(1), 16)
            current = symbols.by_start(addr)
            prev_addr = None
            continue
        if current is None:
            continue
        imatch = INSN_RE.match(line)
        if not imatch:
            continue
        addr = int(imatch.group(1), 16)
        asm = imatch.group(2).strip()
        if prev_addr is not None and addr <= prev_addr:
            prev_addr = addr
        bmatch = BRANCH_RE.search(asm)
        if bmatch:
            op = bmatch.group(1)
            operand = bmatch.group(2)
            target_addr, target_name = parse_target_operand(operand)
            if op.startswith("j"):
                current.branch_count += 1
                if target_addr is not None and current.addr <= target_addr < addr:
                    current.backedge_count += 1
                    current.max_backedge_span = max(current.max_backedge_span, addr - target_addr)
                    current.backedge_regions.append((target_addr, addr))
            elif op.startswith("call"):
                call_match = CALL_RE.search(asm)
                if call_match:
                    callee = symbols.at(target_addr) if target_addr is not None else None
                    if callee is not None:
                        callee_name = callee.name
                        callee_known = True
                        callee_addr = target_addr if target_addr is not None else 0
                    else:
                        operand = call_match.group(1).strip()
                        callee_name = target_name or operand or "UNKNOWN_CALL_TARGET"
                        callee_known = False
                        callee_addr = target_addr if target_addr is not None else 0
                    if callee_name:
                        ret_addr = addr
                        # We do not know instruction length from no-raw objdump.
                        # Infer it when the next instruction appears; temporarily
                        # store call_addr as return_addr and fix in a second pass
                        # using sorted instruction addresses collected below.
                        current.calls.append(
                            CallSite(
                                caller=current.name,
                                callee=callee_name,
                                call_addr=addr,
                                return_addr=addr,
                                call_offset=addr - current.addr,
                                return_offset=addr - current.addr,
                                target_addr=callee_addr,
                                in_loop=False,
                                loop_depth_est=0,
                                callee_known=callee_known,
                            )
                        )
        prev_addr = addr
    stderr = proc.stderr.read() if proc.stderr is not None else ""
    rc = proc.wait()
    if rc != 0:
        raise SystemExit(f"objdump failed rc={rc}: {stderr[:1000]}")

    # Fill return addresses from the next instruction address inside each function.
    fill_return_addresses(binary, objdump, symbols)
    mark_loop_calls(symbols)


def mark_loop_calls(symbols: SymbolIndex) -> None:
    for func in symbols.funcs:
        func.loop_call_count = 0
        for call in func.calls:
            loop_depth = sum(1 for lo, hi in func.backedge_regions if lo <= call.call_addr <= hi)
            call.loop_depth_est = loop_depth
            call.in_loop = loop_depth > 0
            if call.in_loop:
                func.loop_call_count += 1


def fill_return_addresses(binary: Path, objdump: str, symbols: SymbolIndex) -> None:
    proc = subprocess.Popen(
        [objdump, "-d", "--demangle", "--no-show-raw-insn", "--section=.text", str(binary)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    current: FunctionInfo | None = None
    addrs_by_func: dict[str, list[int]] = defaultdict(list)
    for line in proc.stdout:
        fmatch = FUNC_RE.match(line.strip())
        if fmatch:
            current = symbols.by_start(int(fmatch.group(1), 16))
            continue
        if current is None:
            continue
        imatch = INSN_RE.match(line)
        if imatch:
            addrs_by_func[current.name].append(int(imatch.group(1), 16))
    stderr = proc.stderr.read() if proc.stderr is not None else ""
    rc = proc.wait()
    if rc != 0:
        raise SystemExit(f"objdump failed rc={rc}: {stderr[:1000]}")

    for func in symbols.funcs:
        addrs = addrs_by_func.get(func.name, [])
        next_by_addr = {a: addrs[i + 1] for i, a in enumerate(addrs[:-1])}
        for call in func.calls:
            ret = next_by_addr.get(call.call_addr, call.call_addr + 5)
            call.return_addr = ret
            call.return_offset = ret - func.addr


def compute_reachable_depths(symbols: SymbolIndex, max_depth: int) -> dict[str, int]:
    graph = {f.name: [c.callee for c in f.calls if c.callee in symbols.by_name] for f in symbols.funcs}
    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def dfs(name: str, depth_left: int) -> int:
        if depth_left <= 0:
            return 0
        key = (name, depth_left)
        if name in visiting:
            return 0
        if depth_left == max_depth and name in memo:
            return memo[name]
        visiting.add(name)
        best = 0
        for callee in graph.get(name, []):
            best = max(best, 1 + dfs(callee, depth_left - 1))
        visiting.remove(name)
        if depth_left == max_depth:
            memo[name] = best
        return best

    return {f.name: dfs(f.name, max_depth) for f in symbols.funcs}


def compute_reverse_reach(symbols: SymbolIndex, roots: list[str], max_depth: int) -> dict[str, int]:
    reverse: dict[str, list[str]] = defaultdict(list)
    for f in symbols.funcs:
        for c in f.calls:
            reverse[c.callee].append(f.name)
    dist: dict[str, int] = {}
    q: deque[tuple[str, int]] = deque()
    for r in roots:
        if r in symbols.by_name:
            dist[r] = 0
            q.append((r, 0))
    while q:
        name, d = q.popleft()
        if d >= max_depth:
            continue
        for parent in reverse.get(name, []):
            if parent not in dist or d + 1 < dist[parent]:
                dist[parent] = d + 1
                q.append((parent, d + 1))
    return dist


def is_verilator_one_shot(name: str) -> bool:
    lowered = name.lower()
    return (
        "eval_initial" in lowered
        or "eval_static" in lowered
        or "eval_final" in lowered
        or lowered.endswith("::final()")
    )


def compute_loop_hot_reach(symbols: SymbolIndex, max_depth: int) -> dict[str, int]:
    """Functions reachable from the main simulation loop callsites.

    This is the main profile-free proxy for dynamic hotness. It separates
    steady-state simulation paths from one-shot initialization chains.
    """
    graph = {f.name: [c.callee for c in f.calls if c.callee in symbols.by_name] for f in symbols.funcs}
    roots: set[str] = set()
    for f in symbols.funcs:
        for call in f.calls:
            if call.in_loop and f.name == "main":
                roots.add(call.callee)
                roots.add(f.name)
    if not roots:
        # Conservative fallback for non-Verilator binaries.
        for f in symbols.funcs:
            for call in f.calls:
                if call.in_loop:
                    roots.add(call.callee)
                    roots.add(f.name)
    dist: dict[str, int] = {}
    q: deque[tuple[str, int]] = deque()
    for r in roots:
        dist[r] = 0
        q.append((r, 0))
    while q:
        name, d = q.popleft()
        if d >= max_depth:
            continue
        for callee in graph.get(name, []):
            if callee not in dist or d + 1 < dist[callee]:
                dist[callee] = d + 1
                q.append((callee, d + 1))
    return dist


def score_callsite(
    call: CallSite,
    symbols: SymbolIndex,
    depths: dict[str, int],
    root_dist: dict[str, int],
    loop_hot_dist: dict[str, int],
    ras_size: int,
    mode: str,
    synthetic_external_size: int,
    external_penalty_value: float,
    one_shot_penalty_value: float,
) -> tuple[float, dict[str, float]]:
    caller = symbols.by_name[call.caller]
    callee = symbols.by_name.get(call.callee)
    caller_kb = caller.size / 1024.0
    # Unknown external/PLT/indirect calls still have a statically known return
    # continuation and can evict the caller's I-side footprint. Give them a
    # conservative synthetic footprint instead of dropping them.
    callee_size = callee.size if callee is not None else synthetic_external_size
    callee_kb = callee_size / 1024.0
    caller_cls = caller.cachelines
    callee_cls = callee.cachelines if callee is not None else max(1, synthetic_external_size // 64)
    fanout = max(1, len(caller.calls))
    backedges = caller.backedge_count + (callee.backedge_count if callee is not None else 0)
    loop_bonus = (
        (1.0 if call.in_loop else 0.0)
        + 0.75 * math.log2(call.loop_depth_est + 1)
        + 0.5 * math.log2(backedges + 1)
    )
    depth_down = depths.get(call.callee, 0)
    depth_from_root = root_dist.get(call.caller, 0)
    possible_chain_depth = depth_from_root + 1 + depth_down
    ras_overflow = max(0, possible_chain_depth - ras_size)
    hot_dist = loop_hot_dist.get(call.caller, 9999)
    callee_hot_dist = loop_hot_dist.get(call.callee, 9999)
    hot_reachable = 1 if hot_dist < 9999 or callee_hot_dist < 9999 else 0
    hot_bonus = 90.0 / (1.0 + min(hot_dist, callee_hot_dist, 16)) if hot_reachable else -140.0
    one_shot_penalty = one_shot_penalty_value if (is_verilator_one_shot(call.caller) or is_verilator_one_shot(call.callee)) else 0.0
    external_penalty = external_penalty_value if not call.callee_known else 0.0
    continuation_pos = call.return_offset / max(caller.size, 1)
    # Static code layout distance from callee back into caller is a proxy for how
    # unlikely both regions stay resident after the callee executes.
    layout_distance_kb = abs(call.target_addr - call.return_addr) / 1024.0

    if mode == "depth":
        score = 100.0 * ras_overflow + 5.0 * math.log2(depth_down + 1) + math.log2(callee_cls + 1) - one_shot_penalty - external_penalty
    elif mode == "footprint":
        score = 3.0 * math.log2(caller_cls + 1) + 4.0 * math.log2(callee_cls + 1) + 0.8 * math.log2(fanout + 1) - one_shot_penalty - external_penalty
    elif mode == "loop":
        score = hot_bonus + 4.0 * loop_bonus + 2.5 * math.log2(callee_cls + 1) + 1.5 * math.log2(caller_cls + 1) - one_shot_penalty - external_penalty
    else:
        score = (
            hot_bonus
            +
            4.5 * math.log2(caller_cls + 1)
            + 5.5 * math.log2(callee_cls + 1)
            + 1.2 * math.log2(fanout + 1)
            + 1.5 * loop_bonus
            + 2.5 * math.log2(layout_distance_kb + 1)
            + 35.0 * min(ras_overflow, 8)
            + 0.7 * math.log2(depth_down + 1)
            + 0.1 * continuation_pos
            - one_shot_penalty
            - external_penalty
        )
    features = {
        "caller_size_bytes": caller.size,
        "callee_size_bytes": callee_size,
        "caller_cachelines": caller_cls,
        "callee_cachelines": callee_cls,
        "caller_call_count": fanout,
        "caller_backedges": caller.backedge_count,
        "callee_backedges": callee.backedge_count if callee is not None else 0,
        "call_in_loop": 1 if call.in_loop else 0,
        "loop_depth_est": call.loop_depth_est,
        "depth_from_root": depth_from_root,
        "depth_down": depth_down,
        "possible_chain_depth": possible_chain_depth,
        "ras_overflow": ras_overflow,
        "loop_hot_reachable": hot_reachable,
        "loop_hot_distance": min(hot_dist, callee_hot_dist),
        "one_shot_penalty": one_shot_penalty,
        "external_penalty": external_penalty,
        "callee_known": 1 if call.callee_known else 0,
        "layout_distance_kb": layout_distance_kb,
        "continuation_pos": continuation_pos,
    }
    return score, features


def write_candidates(
    symbols: SymbolIndex,
    out_csv: Path,
    ras_size: int,
    max_depth: int,
    roots: list[str],
    mode: str,
    min_caller_size: int,
    min_callee_size: int,
    synthetic_external_size: int,
    external_penalty: float,
    one_shot_penalty: float,
    nested_base_count: int,
    nested_per_callee: int,
    nested_helper_only: bool,
    nested_round_robin: bool,
) -> None:
    depths = compute_reachable_depths(symbols, max_depth)
    root_dist = compute_reverse_reach(symbols, roots, max_depth)
    loop_hot_dist = compute_loop_hot_reach(symbols, max_depth)
    rows = []
    seen_cacheline: dict[tuple[str, int], dict] = {}
    score_mode = "footprint" if mode in ("nested", "nested_rr") else mode
    for func in symbols.funcs:
        if func.size < min_caller_size:
            continue
        for call in func.calls:
            callee = symbols.by_name.get(call.callee)
            callee_size = callee.size if callee is not None else synthetic_external_size
            if callee_size < min_callee_size:
                continue
            score, features = score_callsite(
                call,
                symbols,
                depths,
                root_dist,
                loop_hot_dist,
                ras_size,
                score_mode,
                synthetic_external_size,
                external_penalty,
                one_shot_penalty,
            )
            cacheline = call.return_addr & ~0x3F
            key = (call.caller, cacheline)
            row = {
                "score": score,
                "target_function": call.caller,
                "target_addr": f"0x{call.return_addr:x}",
                "target_symbol_offset": f"0x{call.return_offset:x}",
                "target_cacheline64": f"0x{cacheline:x}",
                "call_addr": f"0x{call.call_addr:x}",
                "call_symbol_offset": f"0x{call.call_offset:x}",
                "callee_function": call.callee,
                "callee_addr": f"0x{call.target_addr:x}",
                "mode": mode,
                "base_score": score,
                **features,
            }
            prev = seen_cacheline.get(key)
            if prev is None or score > float(prev["score"]):
                seen_cacheline[key] = row
    rows = sorted(seen_cacheline.values(), key=lambda r: float(r["score"]), reverse=True)
    if mode in ("nested", "nested_rr"):
        rows = apply_nested_order(rows, nested_base_count, nested_per_callee, nested_helper_only, nested_round_robin or mode == "nested_rr")
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "rank",
        "score",
        "base_score",
        "target_function",
        "target_addr",
        "target_symbol_offset",
        "target_cacheline64",
        "call_addr",
        "call_symbol_offset",
        "callee_function",
        "callee_addr",
        "callee_known",
        "mode",
        "caller_size_bytes",
        "callee_size_bytes",
        "caller_cachelines",
        "callee_cachelines",
        "caller_call_count",
        "caller_backedges",
        "callee_backedges",
        "call_in_loop",
        "loop_depth_est",
        "depth_from_root",
        "depth_down",
        "possible_chain_depth",
        "ras_overflow",
        "loop_hot_reachable",
        "loop_hot_distance",
        "one_shot_penalty",
        "external_penalty",
        "layout_distance_kb",
        "continuation_pos",
    ]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for idx, row in enumerate(rows, 1):
            row = dict(row)
            row["rank"] = idx
            w.writerow(row)
    print(f"[ok] wrote {out_csv} candidates={len(rows)} mode={mode}")


def is_helper_or_external(row: dict) -> bool:
    try:
        callee_known = int(row.get("callee_known", 1))
        callee_cachelines = float(row.get("callee_cachelines", 0))
    except (TypeError, ValueError):
        return False
    return callee_known == 0 or callee_cachelines <= 12


def nested_local_score(row: dict, hot_score: float) -> float:
    """Rank continuation targets inside callees of high-risk callsites.

    This is profile-free. The intent is to model the common RET-miss pattern:
    a hot dispatcher calls a generated helper, and the helper's own call to a
    small runtime/library routine evicts the helper continuation. The caller
    context gives the helper function hotness; local helper/external calls give
    the return target risk.
    """
    try:
        base = float(row.get("base_score", row.get("score", 0.0)))
        callee_known = int(row.get("callee_known", 1))
        callee_cachelines = float(row.get("callee_cachelines", 0))
        layout_distance_kb = float(row.get("layout_distance_kb", 0.0))
    except (TypeError, ValueError):
        return hot_score
    external_bonus = 100.0 if callee_known == 0 else 0.0
    helper_bonus = 50.0 if callee_cachelines <= 12 else 0.0
    distance_bonus = 2.0 * math.log2(max(0.0, layout_distance_kb) + 1.0)
    return hot_score + external_bonus + helper_bonus + base + distance_bonus


def apply_nested_order(
    rows: list[dict],
    nested_base_count: int,
    nested_per_callee: int,
    nested_helper_only: bool,
    nested_round_robin: bool,
) -> list[dict]:
    if nested_base_count <= 0 or nested_per_callee <= 0:
        return rows

    by_target_func: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_target_func[row["target_function"]].append(row)

    selected: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    hot_callees: dict[str, float] = {}

    def add_row(row: dict) -> None:
        key = (row["target_function"], row["target_cacheline64"])
        if key in seen_keys:
            return
        seen_keys.add(key)
        selected.append(row)

    for row in rows[:nested_base_count]:
        add_row(row)
        hot_callees[row["callee_function"]] = max(
            hot_callees.get(row["callee_function"], float("-inf")),
            float(row.get("base_score", row.get("score", 0.0))),
        )

    nested_by_hot_callee: list[tuple[str, float, list[dict]]] = []
    for callee, hot_score in sorted(hot_callees.items(), key=lambda item: item[1], reverse=True):
        nested_rows = by_target_func.get(callee, [])
        if nested_helper_only:
            nested_rows = [row for row in nested_rows if is_helper_or_external(row)]
        nested_rows = sorted(
            nested_rows,
            key=lambda row: nested_local_score(row, hot_score),
            reverse=True,
        )
        nested_by_hot_callee.append((callee, hot_score, nested_rows[:nested_per_callee]))

    if nested_round_robin:
        # Breadth-first over hot callees.  This avoids overfitting the first few
        # generated helper functions and improves top-K coverage when many
        # similarly-shaped Verilator nba_sequent functions contain hot helper
        # calls.
        for depth in range(nested_per_callee):
            for _callee, _hot_score, nested_rows in nested_by_hot_callee:
                if depth < len(nested_rows):
                    add_row(nested_rows[depth])
    else:
        for _callee, _hot_score, nested_rows in nested_by_hot_callee:
            for row in nested_rows:
                add_row(row)

    for row in rows:
        add_row(row)

    # Rewrite the score to preserve the final priority order for downstream
    # tools that sort or report by score.
    total = len(selected)
    for idx, row in enumerate(selected):
        row["score"] = float(total - idx)
    return selected


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--out-csv", type=Path, required=True)
    ap.add_argument("--nm", default="llvm-nm-19")
    ap.add_argument("--objdump", default="llvm-objdump-19")
    ap.add_argument("--ras-size", type=int, default=32)
    ap.add_argument("--max-depth", type=int, default=96)
    ap.add_argument("--root", action="append", default=[])
    ap.add_argument("--mode", choices=["combined", "depth", "footprint", "loop", "nested", "nested_rr"], default="combined")
    ap.add_argument("--min-caller-size", type=int, default=0)
    ap.add_argument("--min-callee-size", type=int, default=0)
    ap.add_argument("--synthetic-external-size", type=int, default=512)
    ap.add_argument("--external-penalty", type=float, default=45.0)
    ap.add_argument("--one-shot-penalty", type=float, default=500.0)
    ap.add_argument("--nested-base-count", type=int, default=1500)
    ap.add_argument("--nested-per-callee", type=int, default=32)
    ap.add_argument("--nested-include-all-calls", action="store_true")
    ap.add_argument("--nested-round-robin", action="store_true")
    args = ap.parse_args()

    roots = args.root or [
        "VTestDriver___024root___eval(VTestDriver___024root*)",
        "VTestDriver___024root___eval_nba(VTestDriver___024root*)",
        "VTestDriver___024root___eval_nba__0(VTestDriver___024root*)",
    ]
    symbols = parse_nm(args.binary, args.nm)
    parse_objdump(args.binary, args.objdump, symbols)
    write_candidates(
        symbols,
        args.out_csv,
        args.ras_size,
        args.max_depth,
        roots,
        args.mode,
        args.min_caller_size,
        args.min_callee_size,
        args.synthetic_external_size,
        args.external_penalty,
        args.one_shot_penalty,
        args.nested_base_count,
        args.nested_per_callee,
        not args.nested_include_all_calls,
        args.nested_round_robin,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
