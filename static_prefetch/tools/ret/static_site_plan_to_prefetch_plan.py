#!/usr/bin/env python3
"""Convert static return-prefetch site CSVs to prefetchit.plan.v1 JSON."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TEXT_TYPES = set("tTwW")


@dataclass(frozen=True)
class Symbol:
    addr: int
    size: int
    typ: str
    raw: str
    demangled: str


@dataclass(frozen=True)
class Loc:
    function: str
    file: str
    line: int


class SymbolIndex:
    def __init__(self, symbols: list[Symbol]):
        self.symbols = sorted(symbols, key=lambda s: (s.addr, s.raw))
        self.addrs = [s.addr for s in self.symbols]

    def symbol_at(self, addr: int) -> Symbol | None:
        import bisect

        idx = bisect.bisect_right(self.addrs, addr) - 1
        if idx < 0:
            return None
        return self.symbols[idx]


def run_lines(cmd: list[str]) -> list[str]:
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.splitlines()


def parse_nm_line(line: str) -> tuple[int, int, str, str] | None:
    parts = line.split(None, 3)
    if len(parts) >= 4:
        try:
            addr = int(parts[0], 16)
            size = int(parts[1], 16)
        except ValueError:
            return None
        typ = parts[2]
        name = parts[3].strip()
        return addr, size, typ, name
    m = re.match(r"^([0-9a-fA-F]+)\s+([A-Za-z])\s+(.+)$", line)
    if not m:
        return None
    return int(m.group(1), 16), 0, m.group(2), m.group(3).strip()


def build_symbol_index(binary: Path, nm_bin: str) -> SymbolIndex:
    raw_lines = run_lines([nm_bin, "-S", "-n", "--defined-only", str(binary)])
    demangled_lines = run_lines([nm_bin, "-S", "-n", "--defined-only", "--demangle", str(binary)])
    demangled_by_key: dict[tuple[int, str], str] = {}
    for line in demangled_lines:
        parsed = parse_nm_line(line)
        if not parsed:
            continue
        addr, _size, typ, name = parsed
        demangled_by_key[(addr, typ)] = name

    symbols: list[Symbol] = []
    for line in raw_lines:
        parsed = parse_nm_line(line)
        if not parsed:
            continue
        addr, size, typ, raw = parsed
        if typ not in TEXT_TYPES:
            continue
        symbols.append(
            Symbol(
                addr=addr,
                size=size,
                typ=typ,
                raw=raw,
                demangled=demangled_by_key.get((addr, typ), raw),
            )
        )
    if not symbols:
        raise SystemExit(f"no text symbols parsed from {binary}")
    return SymbolIndex(symbols)


def parse_int(raw: Any) -> int:
    return int(str(raw), 0)


def parse_offsets(raw: str) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        value = int(item, 0)
        if value < 0 or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out or [0]


def resolve_addrs(binary: Path, addr2line_bin: str, addrs: list[int]) -> dict[int, Loc]:
    locs: dict[int, Loc] = {}
    for start in range(0, len(addrs), 512):
        chunk = addrs[start : start + 512]
        lines = run_lines([addr2line_bin, "-e", str(binary), "-f", "-C"] + [hex(a) for a in chunk])
        for idx, addr in enumerate(chunk):
            fn = lines[2 * idx].strip() if 2 * idx < len(lines) else "??"
            raw_loc = lines[2 * idx + 1].strip() if 2 * idx + 1 < len(lines) else "??:0"
            file_name = ""
            line_no = 0
            if ":" in raw_loc and not raw_loc.startswith("??"):
                file_name, line_text = raw_loc.rsplit(":", 1)
                try:
                    line_no = int(line_text.split()[0])
                except ValueError:
                    line_no = 0
            locs[addr] = Loc(function=fn, file=file_name, line=line_no)
    return locs


def read_targets(path: Path, limit: int) -> dict[tuple[str, int], dict[str, str]]:
    out: dict[tuple[str, int], dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["target_function"], parse_int(row["target_cacheline64"]))
            if key in out:
                continue
            out[key] = row
            if limit and len(out) >= limit:
                break
    return out


def branch_type_for_site_kind(site_kind: str) -> str:
    kind = site_kind.lower()
    if "ret" in kind:
        return "RET"
    if "call" in kind:
        return "CALL"
    return "UNKNOWN"


def source_obj(sym: Symbol, addr: int, loc: Loc) -> dict[str, Any]:
    return {
        "mangled": sym.raw,
        "demangled": sym.demangled,
        "function": loc.function or sym.demangled,
        "file": loc.file,
        "line": loc.line,
        "addr": hex(addr),
        "cacheline64": hex(addr & ~0x3F),
        "symbol_offset": hex(addr - sym.addr),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--targets", type=Path, required=True)
    ap.add_argument("--site-plan", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--top-k", type=int, default=0)
    ap.add_argument("--prefetch-mnemonic", default="prefetcht1")
    ap.add_argument("--prefetch-byte-offsets", default="0")
    ap.add_argument("--label", default="static")
    ap.add_argument("--skip-unresolved-site", action="store_true")
    ap.add_argument("--pretty", action="store_true", help="write indented JSON")
    ap.add_argument("--nm", default="llvm-nm-19")
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    args = ap.parse_args()

    symbols = build_symbol_index(args.binary, args.nm)
    targets = read_targets(args.targets, args.top_k)
    site_rows: list[dict[str, str]] = []
    missing_target_rows = 0
    with args.site_plan.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["target_function"], parse_int(row["target_cacheline64"]))
            target = targets.get(key)
            if target is None:
                missing_target_rows += 1
                continue
            row = dict(row)
            row["_target_addr"] = target["target_addr"]
            row["_target_rank"] = target.get("rank", "0")
            site_rows.append(row)

    addr_set = {
        parse_int(row["_target_addr"]) for row in site_rows
    } | {parse_int(row["site_addr"]) for row in site_rows}
    locs = resolve_addrs(args.binary, args.addr2line, sorted(addr_set))

    injections: list[dict[str, Any]] = []
    skipped_no_symbol = 0
    skipped_site_line = 0
    site_rank_by_target: dict[tuple[str, int], int] = {}
    for row in site_rows:
        target_addr = parse_int(row["_target_addr"])
        site_addr = parse_int(row["site_addr"])
        target_sym = symbols.symbol_at(target_addr)
        site_sym = symbols.symbol_at(site_addr)
        if target_sym is None or site_sym is None:
            skipped_no_symbol += 1
            continue
        target_loc = locs.get(target_addr, Loc("", "", 0))
        site_loc = locs.get(site_addr, Loc("", "", 0))
        if args.skip_unresolved_site and site_loc.line <= 0:
            skipped_site_line += 1
            continue

        target_key = (row["target_function"], parse_int(row["target_cacheline64"]))
        site_rank_by_target[target_key] = site_rank_by_target.get(target_key, 0) + 1
        site_kind = row.get("site_kind", "")
        site = source_obj(site_sym, site_addr, site_loc)
        site.update(
            {
                "branch_type": branch_type_for_site_kind(site_kind),
                "lbr_depth": 0,
                "site_kind": site_kind,
            }
        )
        inj = {
            "target_rank": int(row.get("_target_rank") or 0),
            "site_rank": site_rank_by_target[target_key],
            "samples": 0,
            "new_covered_samples": 0,
            "cumulative_coverage_pct": 0.0,
            "prefetch_mnemonic": args.prefetch_mnemonic,
            "target": source_obj(target_sym, target_addr, target_loc),
            "site": site,
        }
        injections.append(inj)

    byte_offsets = parse_offsets(args.prefetch_byte_offsets)
    plan = {
        "schema": "prefetchit.plan.v1",
        "prefetch_mnemonic": args.prefetch_mnemonic,
        "prefetch": {
            "mnemonic": args.prefetch_mnemonic,
            "operand": "pc-relative-symbol-offset",
            "byte_offsets": byte_offsets,
        },
        "options": {
            "source": "static_return_prefetch",
            "label": args.label,
            "top_k": args.top_k,
            "site_plan": str(args.site_plan),
            "target_csv": str(args.targets),
            "skip_unresolved_site": bool(args.skip_unresolved_site),
        },
        "stats": {
            "site_rows_read": len(site_rows) + missing_target_rows,
            "missing_target_rows": missing_target_rows,
            "skipped_no_symbol": skipped_no_symbol,
            "skipped_unresolved_site": skipped_site_line,
            "selected_injections": len(injections),
            "planned_prefetches": len(injections) * len(byte_offsets),
            "selected_targets": len({(inj["target"]["mangled"], inj["target"]["symbol_offset"]) for inj in injections}),
            "unique_sites": len({(inj["site"]["mangled"], inj["site"]["symbol_offset"]) for inj in injections}),
        },
        "injections": injections,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.pretty:
        text = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    else:
        text = json.dumps(plan, separators=(",", ":"), sort_keys=True) + "\n"
    args.output.write_text(text, encoding="utf-8")
    print(f"[ok] wrote {args.output}")
    for key, value in plan["stats"].items():
        print(f"[ok] {key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
