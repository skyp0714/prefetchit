#!/usr/bin/env python3
"""Generate profile-free COND branch-target candidates from an x86-64 binary.

The target unit is the 64-byte cacheline reached by a conditional branch.  By
default, each direct conditional branch emits only the explicit taken target;
fallthrough/next-line successors are excluded because they are usually already
near the current fetch stream.  Scoring uses only static binary structure;
PGO/LBR samples are intentionally not read here.
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


FUNC_RE = re.compile(r"^([0-9a-fA-F]+)\s+<(.+)>:$")
INSN_RE = re.compile(r"^\s*([0-9a-fA-F]+):\s*(.*?)(?:\s+#.*)?$")
TARGET_RE = re.compile(r"0x([0-9a-fA-F]+)(?:\s+<(.+)>)?")
COND_RE = re.compile(r"\b(j[a-z]+)\b\s+(.+)$")
CALL_RE = re.compile(r"\bcallq?\b\s+(.+)$")
TEXT_TYPES = set("tTwW")
CACHELINE = 64


@dataclass
class FunctionInfo:
    addr: int
    size: int
    typ: str
    name: str
    insns: list[int] = field(default_factory=list)
    conds: list["CondBranch"] = field(default_factory=list)
    calls: list[tuple[int, str]] = field(default_factory=list)
    branch_addrs: list[int] = field(default_factory=list)
    backedge_regions: list[tuple[int, int]] = field(default_factory=list)
    backedge_starts: list[int] = field(default_factory=list)
    backedge_ends: list[int] = field(default_factory=list)

    @property
    def end(self) -> int:
        return self.addr + max(self.size, 1)

    @property
    def cachelines(self) -> int:
        return max(1, math.ceil(max(self.size, 1) / CACHELINE))


@dataclass
class CondBranch:
    function: str
    op: str
    from_addr: int
    taken_addr: int
    fallthrough_addr: int
    from_offset: int
    taken_offset: int
    fallthrough_offset: int


class SymbolIndex:
    def __init__(self, funcs: list[FunctionInfo]):
        self.funcs = sorted(funcs, key=lambda f: f.addr)
        self.addrs = [f.addr for f in self.funcs]
        self.by_addr = {f.addr: f for f in self.funcs}
        self.by_name = {f.name: f for f in self.funcs}

    def at(self, addr: int) -> FunctionInfo | None:
        idx = bisect.bisect_right(self.addrs, addr) - 1
        if idx < 0:
            return None
        func = self.funcs[idx]
        return func if addr < func.end else None


def run_lines(cmd: list[str]) -> list[str]:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, encoding="utf-8", errors="replace").stdout.splitlines()


def parse_nm(binary: Path, nm: str) -> SymbolIndex:
    funcs: list[FunctionInfo] = []
    for line in run_lines([nm, "-S", "-n", "--defined-only", "--demangle", str(binary)]):
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
        if name and not name.startswith(".L"):
            funcs.append(FunctionInfo(addr=addr, size=size, typ=typ, name=name))
    if not funcs:
        raise SystemExit(f"no text symbols parsed from {binary}")
    return SymbolIndex(funcs)


def parse_target_operand(operand: str) -> tuple[int | None, str]:
    match = TARGET_RE.search(operand)
    if not match:
        return None, ""
    return int(match.group(1), 16), (match.group(2) or "").strip()


def parse_objdump(binary: Path, objdump: str, symbols: SymbolIndex) -> None:
    pending_conds: list[tuple[FunctionInfo, str, int, int]] = []
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
    for line in proc.stdout:
        fmatch = FUNC_RE.match(line.strip())
        if fmatch:
            current = symbols.by_addr.get(int(fmatch.group(1), 16))
            continue
        if current is None:
            continue
        imatch = INSN_RE.match(line)
        if not imatch:
            continue
        addr = int(imatch.group(1), 16)
        asm = imatch.group(2).strip()
        current.insns.append(addr)

        cmatch = CALL_RE.search(asm)
        if cmatch:
            target_addr, target_name = parse_target_operand(cmatch.group(1))
            callee = symbols.at(target_addr) if target_addr is not None else None
            current.calls.append((addr, callee.name if callee else (target_name or "UNKNOWN_CALL_TARGET")))

        bmatch = COND_RE.search(asm)
        if not bmatch:
            if asm.startswith("jmp") or asm.startswith("ret") or cmatch:
                current.branch_addrs.append(addr)
            continue
        op = bmatch.group(1)
        if op.startswith("jmp"):
            current.branch_addrs.append(addr)
            continue
        target_addr, _target_name = parse_target_operand(bmatch.group(2))
        if target_addr is None:
            continue
        current.branch_addrs.append(addr)
        pending_conds.append((current, op, addr, target_addr))
        if current.addr <= target_addr < addr:
            current.backedge_regions.append((target_addr, addr))

    stderr = proc.stderr.read() if proc.stderr is not None else ""
    rc = proc.wait()
    if rc != 0:
        raise SystemExit(f"objdump failed rc={rc}: {stderr[:1000]}")

    next_by_func: dict[str, dict[int, int]] = {}
    for func in symbols.funcs:
        func.insns.sort()
        func.branch_addrs.sort()
        func.backedge_starts = sorted(lo for lo, _hi in func.backedge_regions)
        func.backedge_ends = sorted(hi for _lo, hi in func.backedge_regions)
        next_by_func[func.name] = {a: func.insns[i + 1] for i, a in enumerate(func.insns[:-1])}
    for func, op, addr, target_addr in pending_conds:
        fallthrough = next_by_func.get(func.name, {}).get(addr, addr + 2)
        func.conds.append(
            CondBranch(
                function=func.name,
                op=op,
                from_addr=addr,
                taken_addr=target_addr,
                fallthrough_addr=fallthrough,
                from_offset=addr - func.addr,
                taken_offset=target_addr - func.addr,
                fallthrough_offset=fallthrough - func.addr,
            )
        )


def compute_loop_hot_reach(symbols: SymbolIndex, max_depth: int) -> dict[str, int]:
    """Profile-free steady-state hotness proxy.

    Prefer functions reachable from callsites inside static loops.  This avoids
    naming generated Verilator functions directly while still separating large
    one-shot setup code from loop-reachable simulation code.
    """
    graph = {f.name: [callee for _addr, callee in f.calls if callee in symbols.by_name] for f in symbols.funcs}
    roots: set[str] = set()
    for func in symbols.funcs:
        loop_regions = func.backedge_regions
        if not loop_regions:
            continue
        for call_addr, callee in func.calls:
            if callee not in symbols.by_name:
                continue
            if any(lo <= call_addr <= hi for lo, hi in loop_regions):
                roots.add(func.name)
                roots.add(callee)
    if not roots:
        roots = {f.name for f in symbols.funcs if f.backedge_regions}
    dist: dict[str, int] = {}
    q: deque[tuple[str, int]] = deque()
    for root in roots:
        dist[root] = 0
        q.append((root, 0))
    while q:
        name, d = q.popleft()
        if d >= max_depth:
            continue
        for callee in graph.get(name, []):
            if callee not in dist or d + 1 < dist[callee]:
                dist[callee] = d + 1
                q.append((callee, d + 1))
    return dist


def count_between(sorted_addrs: list[int], lo: int, hi: int) -> int:
    if hi <= lo:
        return 0
    return bisect.bisect_left(sorted_addrs, hi) - bisect.bisect_left(sorted_addrs, lo)


def interval_depth(func: FunctionInfo, addr: int) -> int:
    # Number of backedge intervals covering addr:
    # starts <= addr minus intervals whose end < addr.
    return bisect.bisect_right(func.backedge_starts, addr) - bisect.bisect_left(func.backedge_ends, addr)


def log2p(value: float) -> float:
    return math.log2(max(0.0, value) + 1.0)


def base_features(
    func: FunctionInfo,
    cond: CondBranch,
    target_addr: int,
    target_kind: str,
    incoming_by_cl: Counter[int],
    hot_dist: int,
) -> dict[str, float | int | str]:
    # For branch-source candidates the prefetch target is the branch's own
    # cacheline, but the reason it may miss is still the control-flow edge that
    # reached or leaves that branch. Score it using the explicit taken-edge
    # span/direction rather than a zero source-to-source distance.
    edge_addr = cond.taken_addr if target_kind == "source" else target_addr
    span = abs(edge_addr - cond.from_addr)
    target_offset = target_addr - func.addr
    direction = "forward" if edge_addr > cond.from_addr else "backward" if edge_addr < cond.from_addr else "zero"
    target_cl = target_addr & ~0x3F
    lo4 = max(func.addr, target_addr - 4096)
    hi4 = min(func.end, target_addr + 4096)
    lo16 = max(func.addr, target_addr - 16384)
    hi16 = min(func.end, target_addr + 16384)
    branch_before_4k = count_between(func.branch_addrs, lo4, target_addr)
    branch_after_4k = count_between(func.branch_addrs, target_addr, hi4)
    branch_before_16k = count_between(func.branch_addrs, lo16, target_addr)
    branch_after_16k = count_between(func.branch_addrs, target_addr, hi16)
    loop_depth = interval_depth(func, target_addr)
    incoming = incoming_by_cl[target_cl]
    cond_density = len(func.conds) / max(1.0, func.cachelines)
    branch_density = len(func.branch_addrs) / max(1.0, func.cachelines)
    hot_bonus = 96.0 / (1.0 + min(hot_dist, 24)) if hot_dist < 9999 else 0.0
    cold_penalty = -80.0 if hot_dist >= 9999 else 0.0
    return {
        "target_function": func.name,
        "target_addr": f"0x{target_addr:x}",
        "target_symbol_offset": f"0x{target_offset:x}",
        "target_cacheline64": f"0x{target_cl:x}",
        "branch_addr": f"0x{cond.from_addr:x}",
        "branch_symbol_offset": f"0x{cond.from_offset:x}",
        "branch_op": cond.op,
        "successor_kind": target_kind,
        "direction": direction,
        "span_bytes": span,
        "span_cachelines": max(1, math.ceil(span / CACHELINE)),
        "function_size_bytes": func.size,
        "function_cachelines": func.cachelines,
        "function_cond_branches": len(func.conds),
        "function_all_branches": len(func.branch_addrs),
        "cond_density": cond_density,
        "branch_density": branch_density,
        "target_position": target_offset / max(1, func.size),
        "target_incoming_cacheline_edges": incoming,
        "branch_before_4k": branch_before_4k,
        "branch_after_4k": branch_after_4k,
        "branch_before_16k": branch_before_16k,
        "branch_after_16k": branch_after_16k,
        "loop_depth_est": loop_depth,
        "loop_hot_distance": hot_dist,
        "hot_bonus": hot_bonus,
        "cold_penalty": cold_penalty,
    }


def bounded_inverse(value: float, scale: float) -> float:
    return 1.0 / (1.0 + max(0.0, value) / scale)


def score_row(row: dict[str, float | int | str], mode: str) -> float:
    span = float(row["span_bytes"])
    func_cl = float(row["function_cachelines"])
    conds = float(row["function_cond_branches"])
    branch_density = float(row["branch_density"])
    cond_density = float(row["cond_density"])
    incoming = float(row["target_incoming_cacheline_edges"])
    before4 = float(row["branch_before_4k"])
    after4 = float(row["branch_after_4k"])
    before16 = float(row["branch_before_16k"])
    after16 = float(row["branch_after_16k"])
    loop_depth = float(row["loop_depth_est"])
    target_pos = float(row["target_position"])
    hot = float(row["hot_bonus"])
    cold = float(row["cold_penalty"])
    forward = 1.0 if row["direction"] == "forward" else 0.0
    backward = 1.0 if row["direction"] == "backward" else 0.0
    taken = 1.0 if row["successor_kind"] == "taken" else 0.0

    common = hot + cold + 3.0 * log2p(func_cl) + 0.6 * log2p(conds)
    if mode == "span":
        return common + 8.0 * log2p(span / 64.0) + 4.0 * forward + 2.0 * taken
    if mode == "density":
        return common + 5.0 * log2p(span / 64.0) + 12.0 * log2p(branch_density) + 7.0 * log2p(cond_density)
    if mode == "frontier":
        return common + 6.0 * log2p(span / 64.0) + 3.0 * log2p(incoming) + 2.5 * log2p(after4 + after16)
    if mode == "ifelse":
        return common + 7.0 * forward + 7.0 * log2p(span / 64.0) + 3.0 * log2p(after4) + 1.0 * taken
    if mode == "loop":
        return common + 8.0 * backward + 7.0 * log2p(loop_depth) + 5.0 * log2p(incoming) + 2.0 * log2p(before4)
    if mode == "small-forward":
        # Common COND I-side miss shape: a guard branch enters a nearby block
        # that is not part of the dense fallthrough stream.  Long-distance jumps
        # are deliberately penalized here; those were over-ranked by span-only
        # formulas.
        return (
            common
            + 34.0 * forward
            + 10.0 * taken
            + 18.0 * bounded_inverse(span, 256.0)
            + 7.0 * log2p(before4)
            - 4.0 * log2p(after4)
            - 2.5 * log2p(span / 256.0)
        )
    if mode == "tail-sparse":
        # Prefer branch targets in later parts of large functions where the
        # target block has little branch activity immediately after entry.  This
        # models if/else side exits and generated-code tail regions without
        # naming Verilator functions or source lines.
        return (
            common
            + 30.0 * forward
            + 10.0 * taken
            + 28.0 * target_pos
            + 20.0 * bounded_inverse(after4, 8.0)
            + 7.0 * bounded_inverse(span, 512.0)
            + 2.5 * log2p(before4)
            - 3.5 * log2p(after4)
            - 1.2 * log2p(span / 1024.0)
        )
    if mode == "guard-exit":
        # Side-exit heuristic: source side is branch-dense, destination side is
        # sparse, and the jump is forward/taken.  This intentionally scores the
        # shape of the CFG edge rather than the absolute target address.
        contrast = math.log2((before4 + 4.0) / (after4 + 4.0))
        return (
            common
            + 32.0 * forward
            + 12.0 * taken
            + 18.0 * max(-4.0, min(4.0, contrast))
            + 18.0 * bounded_inverse(after4, 8.0)
            + 8.0 * bounded_inverse(span, 768.0)
            + 10.0 * target_pos
            - 1.0 * log2p(span / 2048.0)
        )
    if mode == "entry-window":
        # General rule: conditional misses often land shortly after an explicit
        # taken edge enters a code island. Prefer loop-reachable large functions,
        # sparse target-side control flow, and moderate source-target distance.
        # This avoids naming generated Verilator functions while modeling the
        # sample-IP observation that the miss can be inside the target block, not
        # only at the exact branch destination.
        contrast = math.log2((before4 + 6.0) / (after4 + 6.0))
        moderate_span = bounded_inverse(abs(span - 1024.0), 2048.0)
        return (
            common
            + 24.0 * forward
            + 9.0 * taken
            + 18.0 * target_pos
            + 14.0 * max(-3.0, min(3.0, contrast))
            + 12.0 * moderate_span
            + 8.0 * log2p(incoming)
            + 8.0 * bounded_inverse(after4, 10.0)
            - 1.4 * log2p(span / 4096.0)
        )
    if mode == "fetch-gap":
        # General rule: front-end prefetchers handle near fallthrough well; far
        # taken edges and isolated cachelines are riskier. Rank moderate-to-long
        # jumps in hot, large functions without pushing extreme spans too high.
        gap = min(log2p(span / 64.0), 8.0)
        too_far_penalty = log2p(max(0.0, span - 32768.0) / 4096.0)
        return (
            common
            + 16.0 * forward
            + 7.0 * taken
            + 11.0 * gap
            + 9.0 * log2p(incoming)
            + 6.0 * log2p(func_cl)
            + 5.0 * bounded_inverse(after4, 12.0)
            - 7.0 * too_far_penalty
        )
    if mode == "sparse-hot":
        # General rule: a target cacheline in a loop-reachable function with few
        # immediately-following branches is likely outside the current fetch
        # stream. This mode intentionally de-emphasizes exact branch span.
        return (
            common
            + 22.0 * forward
            + 10.0 * taken
            + 18.0 * bounded_inverse(after4, 6.0)
            + 11.0 * log2p(before4)
            + 10.0 * target_pos
            + 8.0 * log2p(incoming)
            + 4.0 * bounded_inverse(span, 4096.0)
            - 2.0 * log2p(after16)
        )
    if mode == "spread":
        # Reward targets that are separated from the source branch and sit in
        # branch-rich regions, but avoid relying on any one feature too heavily.
        return (
            common
            + 5.5 * log2p(span / 64.0)
            + 2.2 * log2p(incoming)
            + 1.8 * log2p(before4)
            + 2.4 * log2p(after4)
            + 1.2 * log2p(before16 + after16)
            + 2.0 * forward
            + 1.0 * backward
            + 0.8 * taken
        )
    # balanced default
    return (
        common
        + 6.5 * log2p(span / 64.0)
        + 3.0 * log2p(incoming)
        + 2.0 * log2p(before4 + after4)
        + 2.0 * forward
        + 1.5 * backward
        + 1.0 * taken
        + 2.0 * log2p(loop_depth)
    )


def generate_candidates(
    symbols: SymbolIndex,
    mode: str,
    max_depth: int,
    successors: str = "taken",
    candidate_targets: str = "taken",
    target_window_lines: int = 0,
) -> list[dict[str, str]]:
    hot_dist = compute_loop_hot_reach(symbols, max_depth)
    incoming_by_func_cl: dict[str, Counter[int]] = defaultdict(Counter)
    for func in symbols.funcs:
        for cond in func.conds:
            for addr in (cond.taken_addr, cond.fallthrough_addr):
                if func.addr <= addr < func.end:
                    incoming_by_func_cl[func.name][addr & ~0x3F] += 1

    best_by_target: dict[tuple[str, int], dict[str, str]] = {}
    for func in symbols.funcs:
        incoming = incoming_by_func_cl[func.name]
        for cond in func.conds:
            if candidate_targets == "source":
                successor_list = [("source", cond.from_addr)]
            elif candidate_targets == "both":
                successor_list = [("source", cond.from_addr), ("taken", cond.taken_addr)]
            elif successors == "both":
                successor_list = [("taken", cond.taken_addr), ("fallthrough", cond.fallthrough_addr)]
            elif successors == "fallthrough":
                successor_list = [("fallthrough", cond.fallthrough_addr)]
            else:
                successor_list = [("taken", cond.taken_addr)]
            for kind, target_addr in successor_list:
                for line_delta in range(target_window_lines + 1):
                    window_addr = (target_addr & ~0x3F) + line_delta * CACHELINE
                    if not (func.addr <= window_addr < func.end):
                        continue
                    features = base_features(func, cond, window_addr, kind, incoming, hot_dist.get(func.name, 9999))
                    score = score_row(features, mode) - 0.02 * line_delta
                    row = {key: str(value) for key, value in features.items()}
                    row["score"] = f"{score:.9f}"
                    row["mode"] = mode
                    key = (func.name, window_addr & ~0x3F)
                    prev = best_by_target.get(key)
                    if prev is None or float(row["score"]) > float(prev["score"]):
                        best_by_target[key] = row

    rows = sorted(best_by_target.values(), key=lambda r: float(r["score"]), reverse=True)
    for rank, row in enumerate(rows, 1):
        row["rank"] = str(rank)
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "rank",
        "score",
        "mode",
        "target_function",
        "target_addr",
        "target_symbol_offset",
        "target_cacheline64",
        "branch_addr",
        "branch_symbol_offset",
        "branch_op",
        "successor_kind",
        "direction",
        "span_bytes",
        "span_cachelines",
        "function_size_bytes",
        "function_cachelines",
        "function_cond_branches",
        "function_all_branches",
        "cond_density",
        "branch_density",
        "target_position",
        "target_incoming_cacheline_edges",
        "branch_before_4k",
        "branch_after_4k",
        "branch_before_16k",
        "branch_after_16k",
        "loop_depth_est",
        "loop_hot_distance",
        "hot_bonus",
        "cold_penalty",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out-csv", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=[
            "combined",
            "span",
            "density",
            "frontier",
            "ifelse",
            "loop",
            "spread",
            "small-forward",
            "tail-sparse",
            "guard-exit",
            "entry-window",
            "fetch-gap",
            "sparse-hot",
        ],
        default="combined",
    )
    parser.add_argument("--successors", choices=["taken", "fallthrough", "both"], default="taken")
    parser.add_argument(
        "--candidate-targets",
        choices=["taken", "source", "both"],
        default="taken",
        help=(
            "Static prefetch target candidates to emit. 'taken' preserves the "
            "old LBR[0].to model; 'source' emits the conditional branch "
            "instruction cacheline; 'both' covers actual sample-IP cases where "
            "the miss lands on either side of the branch edge."
        ),
    )
    parser.add_argument(
        "--target-window-lines",
        type=int,
        default=0,
        help=(
            "Also emit the next N cachelines after each selected source/taken "
            "address. This models PEBS sample IPs that land inside the branch "
            "target block rather than exactly at LBR[0].to."
        ),
    )
    parser.add_argument("--max-depth", type=int, default=96)
    parser.add_argument("--nm", default="llvm-nm-19")
    parser.add_argument("--objdump", default="llvm-objdump-19")
    args = parser.parse_args()

    symbols = parse_nm(args.binary, args.nm)
    parse_objdump(args.binary, args.objdump, symbols)
    if args.target_window_lines < 0:
        raise SystemExit("--target-window-lines must be non-negative")
    rows = generate_candidates(
        symbols,
        args.mode,
        args.max_depth,
        args.successors,
        args.candidate_targets,
        args.target_window_lines,
    )
    write_csv(args.out_csv, rows)
    print(f"[ok] wrote {args.out_csv} rows={len(rows)} mode={args.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
