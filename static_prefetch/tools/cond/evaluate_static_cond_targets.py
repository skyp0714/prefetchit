#!/usr/bin/env python3
"""Evaluate static COND target candidates against PGO/LBR COND samples.

The PGO trace is used only as ground truth. Candidate CSVs must be generated
without reading these traces.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import itertools
import math
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


ENTRY_MIN_SLASHES = 7
SYM_OFF_RE = re.compile(r"^(.*)\+0x([0-9a-fA-F]+)$")
TEXT_TYPES = set("tTwW")


@dataclass(frozen=True)
class Symbol:
    addr: int
    size: int
    typ: str
    name: str

    @property
    def end(self) -> int:
        return self.addr + max(1, self.size)


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
        sym = self.symbols[idx]
        return sym if addr < sym.end else None


@dataclass(frozen=True)
class BranchEntry:
    from_raw: str
    to_raw: str
    branch_type: str
    raw_from_addr: int | None = None
    raw_to_addr: int | None = None


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
    symbols: list[Symbol] = []
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
        if typ in TEXT_TYPES:
            symbols.append(Symbol(addr=addr, size=size, typ=typ, name=parts[3].strip()))
    if not symbols:
        raise SystemExit(f"no text symbols parsed from {binary}")
    return SymbolIndex(symbols)


def parse_symbolic_entry(tok: str) -> BranchEntry | None:
    if tok.count("/") < ENTRY_MIN_SLASHES:
        return None
    parts = tok.split("/")
    if len(parts) < 7:
        return None
    return BranchEntry(from_raw=parts[0], to_raw=parts[1], branch_type=parts[6].upper())


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
        branch_type=parts[6].upper(),
        raw_from_addr=raw_from,
        raw_to_addr=raw_to,
    )


def parse_entries(line: str) -> list[BranchEntry]:
    out = []
    for tok in line.strip().split():
        entry = parse_symbolic_entry(tok)
        if entry is not None:
            out.append(entry)
    return out


def parse_raw_entries(line: str) -> list[BranchEntry]:
    out = []
    for tok in line.strip().split():
        entry = parse_raw_entry(tok)
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


def trace_dirs_from_args(paths: list[Path]) -> list[Path]:
    out = []
    for p in paths:
        out.append(p.parent if p.is_file() else p)
    return out


def collect_cond_truth(
    trace_dirs: list[Path],
    symbols: SymbolIndex,
    max_samples: int,
    target_ip_source: str = "lbr-to",
) -> tuple[Counter[tuple[str, int]], dict[str, Counter[tuple[str, int]]], dict[str, int]]:
    total: Counter[tuple[str, int]] = Counter()
    by_trace: dict[str, Counter[tuple[str, int]]] = {}
    stats = {"parsed": 0, "kept_cond": 0, "resolved": 0, "unresolved": 0, "sample_ip_fallback_lbr_to": 0}
    for trace_dir in trace_dirs:
        lbr = trace_dir / "lbr_symbolic_dump.txt"
        if not lbr.exists():
            raise SystemExit(f"missing {lbr}")
        raw_path = trace_dir / "lbr_raw_dump.txt"
        raw_fh = raw_path.open(encoding="utf-8", errors="replace") if raw_path.exists() else None
        local: Counter[tuple[str, int]] = Counter()
        try:
            with lbr.open(encoding="utf-8", errors="replace") as f:
                raw_iter = raw_fh if raw_fh is not None else itertools.repeat("")
                for line, raw_line in zip(f, raw_iter):
                    if max_samples and stats["parsed"] >= max_samples:
                        break
                    stats["parsed"] += 1
                    entries = parse_entries(line)
                    if not entries:
                        continue
                    first = entries[0]
                    if first.branch_type != "COND":
                        continue
                    stats["kept_cond"] += 1
                    resolved = symbols.lookup_addr(first.to_raw)
                    if resolved is None or resolved[1] is None:
                        stats["unresolved"] += 1
                        continue
                    addr, sym = resolved
                    if target_ip_source == "sample-ip":
                        raw_entries = parse_raw_entries(raw_line) if raw_line else []
                        sample_ip = parse_sample_ip(raw_line or line)
                        if raw_entries and raw_entries[0].raw_to_addr is not None and sample_ip is not None:
                            load_bias = raw_entries[0].raw_to_addr - addr
                            sample_addr = sample_ip - load_bias
                            sample_sym = symbols.symbol_at(sample_addr)
                            if sample_addr >= 0 and sample_sym is not None:
                                addr, sym = sample_addr, sample_sym
                            else:
                                stats["sample_ip_fallback_lbr_to"] += 1
                        else:
                            stats["sample_ip_fallback_lbr_to"] += 1
                    key = (sym.name, addr & ~0x3F)
                    local[key] += 1
                    total[key] += 1
                    stats["resolved"] += 1
        finally:
            if raw_fh is not None:
                raw_fh.close()
        by_trace[str(trace_dir)] = local
    return total, by_trace, stats


def read_candidates(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def candidate_key(row: dict[str, str]) -> tuple[str, int]:
    return row["target_function"], int(row["target_cacheline64"], 16)


def ordered_keys(rows: list[dict[str, str]]) -> list[tuple[str, int]]:
    seen: set[tuple[str, int]] = set()
    out: list[tuple[str, int]] = []
    for row in rows:
        key = candidate_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def eval_one(keys: list[tuple[str, int]], truth: Counter[tuple[str, int]], ks: list[int]) -> list[dict[str, str]]:
    total_weight = sum(truth.values())
    truth_set = set(truth)
    rows = []
    for k in ks:
        pred = set(keys[:k])
        hit_weight = sum(count for key, count in truth.items() if key in pred)
        hit_unique = len(truth_set & pred)
        pred_n = min(k, len(keys))
        rows.append(
            {
                "k": str(k),
                "pred_unique": str(pred_n),
                "truth_unique": str(len(truth_set)),
                "hit_unique": str(hit_unique),
                "precision": f"{hit_unique / max(1, pred_n):.9f}",
                "unique_recall": f"{hit_unique / max(1, len(truth_set)):.9f}",
                "weighted_recall": f"{hit_weight / max(1, total_weight):.9f}",
                "hit_samples": str(hit_weight),
                "truth_samples": str(total_weight),
            }
        )
    return rows


def rank_truth_rows(keys: list[tuple[str, int]], truth: Counter[tuple[str, int]]) -> list[dict[str, str]]:
    rank_by_key = {key: idx + 1 for idx, key in enumerate(keys)}
    out = []
    for key, count in truth.most_common():
        rank = rank_by_key.get(key)
        out.append(
            {
                "target_function": key[0],
                "target_cacheline64": f"0x{key[1]:x}",
                "samples": str(count),
                "rank": "" if rank is None else str(rank),
            }
        )
    return out


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, candidate_path: Path, stats: dict[str, int], total_rows: list[dict[str, str]], by_trace_rows: dict[str, list[dict[str, str]]]) -> None:
    lines = [
        "# Static COND Target Evaluation",
        "",
        f"- Candidate file: `{candidate_path}`",
        f"- Parsed samples: {stats['parsed']}",
        f"- LBR[0] COND samples: {stats['kept_cond']}",
        f"- Resolved COND targets: {stats['resolved']}",
        f"- Unresolved COND targets: {stats['unresolved']}",
        "",
        "## Aggregate",
        "",
        "| K | Pred unique | Truth unique | Hit unique | Unique recall | Weighted recall | Hit samples | Truth samples |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in total_rows:
        lines.append(
            f"| {row['k']} | {row['pred_unique']} | {row['truth_unique']} | {row['hit_unique']} | "
            f"{float(row['unique_recall']) * 100.0:.2f}% | {float(row['weighted_recall']) * 100.0:.2f}% | "
            f"{row['hit_samples']} | {row['truth_samples']} |"
        )
    lines.extend(["", "## Per Trace", ""])
    for trace, rows in by_trace_rows.items():
        lines.extend(
            [
                f"### {trace}",
                "",
                "| K | Weighted recall | Hit samples | Truth samples |",
                "|---:|---:|---:|---:|",
            ]
        )
        for row in rows:
            lines.append(f"| {row['k']} | {float(row['weighted_recall']) * 100.0:.2f}% | {row['hit_samples']} | {row['truth_samples']} |")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_ks(raw: str) -> list[int]:
    return [int(x) for x in raw.split(",") if x.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--trace-dir", type=Path, action="append", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--ks", default="100,500,1000,2500,5000,10000,25000,50000,100000")
    parser.add_argument("--max-samples", type=int, default=0)
    parser.add_argument(
        "--target-ip-source",
        choices=["lbr-to", "sample-ip"],
        default="lbr-to",
        help="Use LBR[0].to or the actual PEBS sample IP as the target cacheline truth.",
    )
    parser.add_argument("--nm", default="llvm-nm-19")
    args = parser.parse_args()

    symbols = build_symbol_index(args.binary, args.nm)
    trace_dirs = trace_dirs_from_args(args.trace_dir)
    truth, by_trace_truth, stats = collect_cond_truth(trace_dirs, symbols, args.max_samples, args.target_ip_source)
    keys = ordered_keys(read_candidates(args.candidates))
    ks = parse_ks(args.ks)
    total_rows = eval_one(keys, truth, ks)
    by_trace_rows = {trace: eval_one(keys, local, ks) for trace, local in by_trace_truth.items()}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "overlap_metrics.csv", total_rows)
    write_csv(args.out_dir / "profile_cond_targets_with_static_rank.csv", rank_truth_rows(keys, truth))
    for idx, (trace, rows) in enumerate(by_trace_rows.items(), 1):
        safe = f"trace{idx:02d}"
        write_csv(args.out_dir / f"{safe}_overlap_metrics.csv", rows)
    write_report(args.out_dir / "overlap_report.md", args.candidates, stats, total_rows, by_trace_rows)
    best = max(total_rows, key=lambda r: float(r["weighted_recall"])) if total_rows else {}
    print(
        f"[ok] cond_samples={stats['resolved']} unique_truth={len(truth)} "
        f"best_k={best.get('k')} best_weighted_recall={best.get('weighted_recall')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
