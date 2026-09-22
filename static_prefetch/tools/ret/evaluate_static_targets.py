#!/usr/bin/env python3
"""Evaluate static return target candidates against PEBS/LBR RET-related targets."""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ENTRY_MIN_SLASHES = 7
SYM_OFF_RE = re.compile(r"^(.*)\+0x([0-9a-fA-F]+)$")
NM_RE = re.compile(r"^([0-9a-fA-F]+)\s+(?:[0-9a-fA-F]+\s+)?([A-Za-z])\s+(.+)$")
TEXT_TYPES = set("tTwW")


def strip_args(name: str) -> str:
    return name.split("(", 1)[0].strip()


def normalize_symbol_name(name: str) -> str:
    out = name.strip()
    if "@" in out:
        out = out.split("@", 1)[0]
    return out


@dataclass(frozen=True)
class Symbol:
    addr: int
    typ: str
    name: str


class SymbolIndex:
    def __init__(self, symbols: list[Symbol]):
        self.symbols = sorted(symbols, key=lambda s: (s.addr, s.name))
        self.addrs = [s.addr for s in self.symbols]
        self.by_name: dict[str, Symbol] = {}
        self.by_no_args: dict[str, Symbol] = {}
        for sym in self.symbols:
            self.by_name.setdefault(sym.name, sym)
            self.by_no_args.setdefault(strip_args(sym.name), sym)

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


def run_lines(cmd: list[str]) -> list[str]:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, encoding="utf-8", errors="replace").stdout.splitlines()


def build_symbol_index(binary: Path, nm: str) -> SymbolIndex:
    lines = run_lines([nm, "-S", "-n", "--defined-only", "--demangle", str(binary)])
    symbols: list[Symbol] = []
    for line in lines:
        m = NM_RE.match(line)
        if not m:
            continue
        addr_s, typ, name = m.groups()
        if typ not in TEXT_TYPES:
            continue
        symbols.append(Symbol(addr=int(addr_s, 16), typ=typ, name=name.strip()))
    if not symbols:
        raise SystemExit(f"no text symbols parsed from {binary}")
    return SymbolIndex(symbols)


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


def trace_dirs_from_args(paths: list[Path]) -> list[Path]:
    out = []
    for p in paths:
        if p.is_file():
            out.append(p.parent)
        else:
            out.append(p)
    return out


def collect_ground_truth(trace_dirs: list[Path], symbols: SymbolIndex, ret_mode: str, max_samples: int) -> Counter[tuple[str, int]]:
    counts: Counter[tuple[str, int]] = Counter()
    parsed = 0
    kept = 0
    for trace_dir in trace_dirs:
        lbr = trace_dir / "lbr_symbolic_dump.txt"
        if not lbr.exists():
            raise SystemExit(f"missing {lbr}")
        with lbr.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if max_samples and parsed >= max_samples:
                    break
                parsed += 1
                entries = parse_entries(line)
                if not entries:
                    continue
                if ret_mode == "immediate":
                    use = entries[0].branch_type == "RET"
                elif ret_mode == "any":
                    use = any(e.branch_type == "RET" for e in entries)
                else:
                    raise SystemExit(f"unsupported ret mode {ret_mode}")
                if not use:
                    continue
                resolved = symbols.lookup_addr(entries[0].to_raw)
                if resolved is None:
                    continue
                addr, sym = resolved
                if sym is None:
                    continue
                counts[(sym.name, addr & ~0x3F)] += 1
                kept += 1
    print(f"[ok] parsed_samples={parsed} ret_mode={ret_mode} kept={kept} unique_targets={len(counts)}")
    return counts


def read_candidates(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def candidate_key(row: dict[str, str]) -> tuple[str, int]:
    return row["target_function"], int(row["target_cacheline64"], 16)


def evaluate(candidates: list[dict[str, str]], truth: Counter[tuple[str, int]], ks: list[int], out_dir: Path) -> None:
    total_weight = sum(truth.values())
    truth_set = set(truth)
    out_dir.mkdir(parents=True, exist_ok=True)
    metrics = []
    seen: set[tuple[str, int]] = set()
    ordered_keys = []
    for row in candidates:
        key = candidate_key(row)
        if key in seen:
            continue
        seen.add(key)
        ordered_keys.append(key)

    for k in ks:
        pred = set(ordered_keys[:k])
        hit_weight = sum(count for key, count in truth.items() if key in pred)
        hit_unique = len(truth_set & pred)
        precision = hit_unique / max(1, min(k, len(pred)))
        recall = hit_unique / max(1, len(truth_set))
        weighted_recall = hit_weight / max(1, total_weight)
        metrics.append(
            {
                "k": k,
                "pred_unique": min(k, len(pred)),
                "truth_unique": len(truth_set),
                "hit_unique": hit_unique,
                "precision": precision,
                "recall": recall,
                "weighted_recall": weighted_recall,
                "hit_samples": hit_weight,
                "truth_samples": total_weight,
            }
        )

    with (out_dir / "overlap_metrics.csv").open("w", newline="", encoding="utf-8") as f:
        fields = list(metrics[0].keys()) if metrics else []
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(metrics)

    rank_by_key = {key: idx + 1 for idx, key in enumerate(ordered_keys)}
    with (out_dir / "profile_ret_targets_with_static_rank.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["profile_rank", "samples", "target_function", "target_cacheline64", "static_rank", "static_hit"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for idx, (key, count) in enumerate(truth.most_common(), 1):
            rank = rank_by_key.get(key, 0)
            w.writerow(
                {
                    "profile_rank": idx,
                    "samples": count,
                    "target_function": key[0],
                    "target_cacheline64": f"0x{key[1]:x}",
                    "static_rank": rank,
                    "static_hit": 1 if rank else 0,
                }
            )

    with (out_dir / "overlap_report.md").open("w", encoding="utf-8") as f:
        f.write("# Static Return Target Overlap\n\n")
        f.write("| K | Precision | Recall | Weighted Recall | Hit Samples | Truth Samples |\n")
        f.write("|---:|---:|---:|---:|---:|---:|\n")
        for m in metrics:
            f.write(
                f"| {m['k']} | {m['precision']:.4f} | {m['recall']:.4f} | {m['weighted_recall']:.4f} | {m['hit_samples']} | {m['truth_samples']} |\n"
            )
    print(f"[ok] wrote {out_dir / 'overlap_metrics.csv'}")
    print(f"[ok] wrote {out_dir / 'profile_ret_targets_with_static_rank.csv'}")
    print(f"[ok] wrote {out_dir / 'overlap_report.md'}")


def parse_ks(raw: str) -> list[int]:
    return [int(x) for x in raw.split(",") if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--trace-dir", type=Path, action="append", required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--ret-mode", choices=["immediate", "any"], default="immediate")
    ap.add_argument("--k", default="100,500,1000,5000,10000,20000,50000")
    ap.add_argument("--max-samples", type=int, default=0)
    ap.add_argument("--nm", default="llvm-nm-19")
    args = ap.parse_args()

    symbols = build_symbol_index(args.binary, args.nm)
    truth = collect_ground_truth(trace_dirs_from_args(args.trace_dir), symbols, args.ret_mode, args.max_samples)
    candidates = read_candidates(args.candidates)
    evaluate(candidates, truth, parse_ks(args.k), args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
