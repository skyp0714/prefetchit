#!/usr/bin/env python3
import argparse
import csv
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

BR_TYPE_RE = re.compile(r"^[A-Z_]+$")
SYM_OFF_RE = re.compile(r"^(.*)\+0x([0-9a-fA-F]+)$")
NM_LINE_RE = re.compile(r"^([0-9a-fA-F]+)\s+([A-Za-z])\s+(.+)$")
ENTRY_MIN_SLASHES = 7

PARSER_ARTIFACT_SYMBOLS = {"P", "M", "N", "-", "UNKNOWN"}
EXTERNAL_SYMBOL_PREFIXES = (
    "__mem",
    "__str",
    "__GI_",
    "__libc_",
    "_dl_",
    "_int_",
    "pthread_",
    "malloc",
    "free",
    "read",
    "write",
    "strcmp",
    "memcpy",
    "memset",
    "memmove",
)
EXTERNAL_SYMBOL_MARKERS = ("@plt", "@GLIBC")


def is_branch_entry_token(tok: str) -> bool:
    return tok.count("/") >= ENTRY_MIN_SLASHES


def classify_unresolved_symbol(sym: str) -> str:
    s = sym.strip()
    if not s:
        return "<unmapped_symbol>:0"
    if s.startswith("0x"):
        return "<hex_target>:0"
    if s in PARSER_ARTIFACT_SYMBOLS or len(s) <= 1:
        return "<parser_artifact>:0"
    for marker in EXTERNAL_SYMBOL_MARKERS:
        if marker in s:
            return "<external_symbol>:0"
    for pref in EXTERNAL_SYMBOL_PREFIXES:
        if s.startswith(pref):
            return "<external_symbol>:0"
    return "<unmapped_symbol>:0"


def extract_branch_type(br_entry: str) -> str:
    parts = br_entry.strip().split("/")
    for part in reversed(parts):
        token = part.strip()
        if not token or token == "-":
            continue
        if BR_TYPE_RE.match(token):
            return token
    return "UNKNOWN"


def normalize_symbol(sym: str) -> str:
    s = sym.strip()
    if not s:
        return "UNKNOWN"
    if s.startswith("0x"):
        return s
    if "+0x" in s:
        s = s.split("+0x", 1)[0]
    return s if s else "UNKNOWN"


def parse_lbr_types(path: Path) -> tuple[Counter, int]:
    counts: Counter = Counter()
    samples = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            tokens = line.split()
            br_entries = [t for t in tokens if t.startswith("0x") and is_branch_entry_token(t)]
            if not br_entries:
                continue
            samples += 1
            counts[extract_branch_type(br_entries[0])] += 1
    return counts, samples


def parse_first_lbr_records(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            tokens = line.split()
            if len(tokens) < 3:
                continue

            first_entry = None
            for tok in tokens[2:]:
                if is_branch_entry_token(tok):
                    first_entry = tok
                    break
            if first_entry is None:
                continue

            parts = first_entry.split("/")
            if len(parts) < 2:
                continue

            to_raw = parts[1].strip()
            symbol = normalize_symbol(to_raw)
            branch_type = extract_branch_type(first_entry)
            records.append(
                {
                    "symbol": symbol,
                    "to_raw": to_raw,
                    "branch_type": branch_type,
                    "srcline": "??:0",
                }
            )
    return records


def select_addr2line_bin(user_path: str | None) -> str | None:
    if user_path:
        p = Path(user_path)
        if p.exists() and p.is_file():
            return str(p)
        raise RuntimeError(f"addr2line binary not found: {user_path}")

    candidates = [
        "llvm-addr2line-19",
        "llvm-addr2line-18",
        "llvm-addr2line-17",
        "llvm-addr2line-16",
        "llvm-addr2line-15",
        "llvm-addr2line-14",
        "llvm-addr2line-13",
        "llvm-addr2line-12",
        "llvm-addr2line-11",
        "llvm-addr2line",
        "eu-addr2line",
        "addr2line",
    ]
    for c in candidates:
        found = shutil.which(c)
        if found:
            return found
    return None


def build_symbol_base_map(sim_binary: Path, needed_symbols: set[str]) -> dict[str, int]:
    if not needed_symbols:
        return {}

    cp = subprocess.run(
        ["nm", "-n", "-C", str(sim_binary)],
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )

    out: dict[str, int] = {}
    for raw in cp.stdout.splitlines():
        m = NM_LINE_RE.match(raw)
        if not m:
            continue
        name = m.group(3).strip()
        if name not in needed_symbols:
            continue
        if name in out:
            continue
        out[name] = int(m.group(1), 16)
    return out


def compute_target_addr(to_raw: str, sym_base_map: dict[str, int]) -> int | None:
    m = SYM_OFF_RE.match(to_raw)
    if not m:
        return None
    base_sym = m.group(1).strip()
    off = int(m.group(2), 16)
    base = sym_base_map.get(base_sym)
    if base is None:
        return None
    return base + off


def resolve_srclines(
    records: list[dict],
    sim_binary: Path | None,
    addr2line_bin: str | None,
) -> dict[str, int]:
    stats = {
        "samples_total": len(records),
        "samples_line_resolved": 0,
        "samples_line_unresolved": len(records),
        "samples_symbolic": 0,
        "samples_hex_target": 0,
    }

    if not records:
        return stats

    needed_symbols: set[str] = set()
    for rec in records:
        to_raw = rec["to_raw"]
        if to_raw.startswith("0x"):
            stats["samples_hex_target"] += 1
            rec["srcline"] = "<hex_target>:0"
            continue
        stats["samples_symbolic"] += 1
        m = SYM_OFF_RE.match(to_raw)
        if m:
            needed_symbols.add(m.group(1).strip())
        else:
            needed_symbols.add(to_raw.strip())

    sym_base_map: dict[str, int] = {}
    if sim_binary is not None:
        try:
            sym_base_map = build_symbol_base_map(sim_binary, needed_symbols)
        except Exception:
            sym_base_map = {}

    addr_to_records: dict[int, list[int]] = {}
    unresolved_by_map: list[int] = []
    for idx, rec in enumerate(records):
        to_raw = rec["to_raw"]
        if to_raw.startswith("0x"):
            continue

        m = SYM_OFF_RE.match(to_raw)
        if m:
            base_sym = m.group(1).strip()
            off = int(m.group(2), 16)
        else:
            base_sym = to_raw.strip()
            off = 0

        rec["_base_sym"] = base_sym
        base = sym_base_map.get(base_sym)
        if base is None:
            unresolved_by_map.append(idx)
            continue
        addr_to_records.setdefault(base + off, []).append(idx)

    if sim_binary is None or addr2line_bin is None or not addr_to_records:
        for idx in unresolved_by_map:
            records[idx]["srcline"] = classify_unresolved_symbol(records[idx].get("_base_sym", records[idx]["to_raw"]))
        stats["samples_line_resolved"] = 0
        stats["samples_line_unresolved"] = len(records)
        return stats

    addrs = sorted(addr_to_records.keys())
    resolved_map: dict[int, str] = {}
    chunk = 2000

    for i in range(0, len(addrs), chunk):
        sub = addrs[i : i + chunk]
        cmd = [addr2line_bin, "-e", str(sim_binary), "-f", "-C"] + [f"0x{x:x}" for x in sub]
        try:
            cp = subprocess.run(
                cmd,
                check=True,
                text=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            continue

        lines = cp.stdout.splitlines()
        pos = 0
        for a in sub:
            loc = "??:0"
            if pos + 1 < len(lines):
                loc_raw = lines[pos + 1].strip()
                if loc_raw and loc_raw not in ("??:?", "??:", "??:0"):
                    loc = loc_raw
            resolved_map[a] = loc
            pos += 2

    resolved_samples = 0
    for addr, idxs in addr_to_records.items():
        loc = resolved_map.get(addr, "??:0")
        for idx in idxs:
            if loc != "??:0":
                records[idx]["srcline"] = loc
                resolved_samples += 1
            else:
                records[idx]["srcline"] = "<no_lineinfo>:0"

    for idx in unresolved_by_map:
        records[idx]["srcline"] = classify_unresolved_symbol(records[idx].get("_base_sym", records[idx]["to_raw"]))

    stats["samples_line_resolved"] = resolved_samples
    stats["samples_line_unresolved"] = len(records) - resolved_samples
    return stats


def split_srcline(srcline: str) -> tuple[str, str]:
    s = (srcline or "").strip()
    if not s or s == "??:0":
        return "??", "0"
    if ":" in s:
        left, right = s.rsplit(":", 1)
        src = Path(left).name if left else "??"
        line = right if right else "0"
        return src if src else "??", line
    return Path(s).name if s else "??", "0"


def write_hierarchical_report(
    path: Path,
    total: int,
    sym_file_counts: Counter,
    line_counts: Counter,
    line_branch_counts: Counter,
):
    def pct(v: int, d: int) -> float:
        return (100.0 * v / d) if d > 0 else 0.0

    def format_branch_mix(items: list[tuple[str, int]], denom: int) -> str:
        if not items:
            return "N/A"
        return ", ".join(f"{bt} {cnt} ({pct(cnt, denom):.2f}%)" for bt, cnt in items)

    sym_totals: Counter = Counter()
    sym_branch_counts: Counter = Counter()
    for (sym, _srcfile), cnt in sym_file_counts.items():
        sym_totals[sym] += cnt
    for (sym, _srcfile, _line_no, bt), cnt in line_branch_counts.items():
        sym_branch_counts[(sym, bt)] += cnt

    lines: list[str] = []
    lines.append("# Hierarchical Miss Report")
    lines.append(f"total_samples: {total}")
    lines.append("")

    for sym, sym_cnt in sym_totals.most_common():
        sym_ratio = pct(sym_cnt, total)
        sym_bt_local: list[tuple[str, int]] = []
        for (k_sym, bt), cnt in sym_branch_counts.items():
            if k_sym == sym:
                sym_bt_local.append((bt, cnt))
        sym_bt_local.sort(key=lambda x: x[1], reverse=True)

        lines.append(f"symbol: {sym}")
        lines.append(f"  samples: {sym_cnt}")
        lines.append(f"  ratio_pct: {sym_ratio:.2f}")
        lines.append(f"  branch_mix: {format_branch_mix(sym_bt_local, sym_cnt)}")
        lines.append("  srcfiles:")

        local_srcfiles: list[tuple[str, int]] = []
        for (k_sym, srcfile), cnt in sym_file_counts.items():
            if k_sym == sym:
                local_srcfiles.append((srcfile, cnt))
        local_srcfiles.sort(key=lambda x: x[1], reverse=True)

        for srcfile, src_cnt in local_srcfiles:
            src_ratio_sym = pct(src_cnt, sym_cnt)
            lines.append(f"    - srcfile: {srcfile}")
            lines.append(f"      samples: {src_cnt}")
            lines.append(f"      ratio_within_symbol_pct: {src_ratio_sym:.2f}")
            lines.append("      lines:")

            local_lines: list[tuple[str, int]] = []
            for (k_sym, k_src, line_no), cnt in line_counts.items():
                if k_sym == sym and k_src == srcfile:
                    local_lines.append((line_no, cnt))
            local_lines.sort(key=lambda x: x[1], reverse=True)

            for line_no, line_cnt in local_lines:
                line_ratio_sym = pct(line_cnt, sym_cnt)
                bt_local: list[tuple[str, int]] = []
                for (k_sym, k_src, k_line, bt), cnt in line_branch_counts.items():
                    if k_sym == sym and k_src == srcfile and k_line == line_no:
                        bt_local.append((bt, cnt))
                bt_local.sort(key=lambda x: x[1], reverse=True)
                mix = format_branch_mix(bt_local, line_cnt)
                lines.append(
                    f"        - line: {line_no} | samples: {line_cnt} | "
                    f"ratio_within_symbol_pct: {line_ratio_sym:.2f} | branch_mix: {mix}"
                )

        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_target_branch_counts_csv(path: Path, records: list[dict]):
    counts: Counter = Counter()
    symbol_by_target: dict[str, str] = {}
    srcline_by_target: dict[str, str] = {}

    for rec in records:
        sym = rec.get("symbol", "UNKNOWN")
        srcline = rec.get("srcline", "??:0")
        bt = rec.get("branch_type", "UNKNOWN")
        target = f"{sym}:{srcline}"
        counts[(target, bt)] += 1
        symbol_by_target[target] = sym
        srcline_by_target[target] = srcline

    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["target", "symbol", "srcline", "branch_type", "count"])
        w.writeheader()
        for (target, bt), cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True):
            w.writerow(
                {
                    "target": target,
                    "symbol": symbol_by_target.get(target, "UNKNOWN"),
                    "srcline": srcline_by_target.get(target, "??:0"),
                    "branch_type": bt,
                    "count": cnt,
                }
            )


def build_detailed_md(
    path: Path,
    event_label: str,
    total: int,
    symbol_counts: Counter,
    srcline_counts: Counter,
    sym_branch_counts: Counter,
    srcline_branch_counts: Counter,
    line_stats: dict[str, int],
):
    def pct(v: int, d: int) -> float:
        return (100.0 * v / d) if d > 0 else 0.0

    lines = []
    lines.append("# Detailed Miss Target Report")
    lines.append("")
    if event_label:
        lines.append(f"- Event: `{event_label}`")
    lines.append(f"- Samples: {total}")
    lines.append(
        f"- SrcLine resolved: {line_stats['samples_line_resolved']} ({pct(line_stats['samples_line_resolved'], total):.2f}%)"
    )
    lines.append(
        f"- SrcLine unresolved: {line_stats['samples_line_unresolved']} ({pct(line_stats['samples_line_unresolved'], total):.2f}%)"
    )
    lines.append("")

    lines.append("## Top Symbols")
    lines.append("")
    lines.append("| Symbol | Samples | Ratio % |")
    lines.append("|---|---:|---:|")
    for sym, cnt in symbol_counts.most_common(30):
        lines.append(f"| {sym} | {cnt} | {pct(cnt, total):.2f} |")

    lines.append("")
    lines.append("## Top SrcLines")
    lines.append("")
    lines.append("| Symbol | SrcLine | Samples | Ratio % |")
    lines.append("|---|---|---:|---:|")
    for (sym, srcline), cnt in srcline_counts.most_common(40):
        lines.append(f"| {sym} | {srcline} | {cnt} | {pct(cnt, total):.2f} |")

    lines.append("")
    lines.append("## Branch-Type Mix By Top Symbol")
    lines.append("")
    lines.append("| Symbol | Branch Type | Samples | Within Symbol % |")
    lines.append("|---|---|---:|---:|")
    top_symbols = [s for s, _ in symbol_counts.most_common(12)]
    for sym in top_symbols:
        sym_total = symbol_counts[sym]
        local = []
        for (k_sym, bt), cnt in sym_branch_counts.items():
            if k_sym == sym:
                local.append((bt, cnt))
        local.sort(key=lambda x: x[1], reverse=True)
        for bt, cnt in local:
            lines.append(f"| {sym} | {bt} | {cnt} | {pct(cnt, sym_total):.2f} |")

    lines.append("")
    lines.append("## Branch-Type Mix By Top SrcLine")
    lines.append("")
    lines.append("| Symbol | SrcLine | Branch Type | Samples | Within SrcLine % |")
    lines.append("|---|---|---|---:|---:|")
    top_lines = [k for k, _ in srcline_counts.most_common(20)]
    for sym, srcline in top_lines:
        line_total = srcline_counts[(sym, srcline)]
        local = []
        for (k_sym, k_line, bt), cnt in srcline_branch_counts.items():
            if k_sym == sym and k_line == srcline:
                local.append((bt, cnt))
        local.sort(key=lambda x: x[1], reverse=True)
        for bt, cnt in local:
            lines.append(f"| {sym} | {srcline} | {bt} | {cnt} | {pct(cnt, line_total):.2f} |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Build branch-type and miss-target summaries from PEBS+LBR trace dumps")
    ap.add_argument("--lbr-raw", required=True)
    ap.add_argument("--lbr-sym", required=True)
    ap.add_argument("--out-branch-csv", required=True)
    ap.add_argument("--out-target-branch-csv", required=True)
    ap.add_argument("--out-summary-md", required=True)
    ap.add_argument("--out-hierarchical-report", required=True)
    ap.add_argument("--out-detailed-md", required=True)
    ap.add_argument("--event-label", default="")
    ap.add_argument("--sim-binary", default="")
    ap.add_argument("--addr2line-bin", default="")
    args = ap.parse_args()

    lbr_raw = Path(args.lbr_raw)
    lbr_sym = Path(args.lbr_sym)
    out_branch_csv = Path(args.out_branch_csv)
    out_target_branch_csv = Path(args.out_target_branch_csv)
    out_summary_md = Path(args.out_summary_md)
    out_hier_report = Path(args.out_hierarchical_report)
    out_detailed_md = Path(args.out_detailed_md)

    for p in [
        out_branch_csv,
        out_target_branch_csv,
        out_summary_md,
        out_hier_report,
        out_detailed_md,
    ]:
        p.parent.mkdir(parents=True, exist_ok=True)

    br_counts, br_samples = parse_lbr_types(lbr_raw)
    records = parse_first_lbr_records(lbr_sym)

    sim_binary = Path(args.sim_binary) if args.sim_binary else None
    if sim_binary is not None and not sim_binary.exists():
        sim_binary = None

    addr2line_bin = None
    try:
        addr2line_bin = select_addr2line_bin(args.addr2line_bin or None)
    except Exception:
        addr2line_bin = None

    line_stats = resolve_srclines(records, sim_binary, addr2line_bin)

    symbol_counts: Counter = Counter()
    srcline_counts: Counter = Counter()
    sym_branch_counts: Counter = Counter()
    srcline_branch_counts: Counter = Counter()
    sym_file_counts: Counter = Counter()
    line_counts: Counter = Counter()
    line_branch_counts: Counter = Counter()

    for rec in records:
        sym = rec["symbol"]
        bt = rec["branch_type"]
        srcline = rec["srcline"]
        srcfile, line_no = split_srcline(srcline)
        symbol_counts[sym] += 1
        srcline_counts[(sym, srcline)] += 1
        sym_branch_counts[(sym, bt)] += 1
        srcline_branch_counts[(sym, srcline, bt)] += 1
        sym_file_counts[(sym, srcfile)] += 1
        line_counts[(sym, srcfile, line_no)] += 1
        line_branch_counts[(sym, srcfile, line_no, bt)] += 1

    total_branch = sum(br_counts.values())
    with out_branch_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["branch_type", "count", "ratio_pct"])
        w.writeheader()
        for bt, cnt in br_counts.most_common():
            ratio = (100.0 * cnt / total_branch) if total_branch > 0 else 0.0
            w.writerow({"branch_type": bt, "count": cnt, "ratio_pct": f"{ratio:.6f}"})

    miss_fn_samples = sum(symbol_counts.values())

    write_target_branch_counts_csv(out_target_branch_csv, records)
    write_hierarchical_report(out_hier_report, miss_fn_samples, sym_file_counts, line_counts, line_branch_counts)
    build_detailed_md(
        out_detailed_md,
        args.event_label,
        miss_fn_samples,
        symbol_counts,
        srcline_counts,
        sym_branch_counts,
        srcline_branch_counts,
        line_stats,
    )

    top_branch = br_counts.most_common(1)[0][0] if br_counts else "N/A"
    top_branch_ratio = (100.0 * br_counts[top_branch] / total_branch) if br_counts and total_branch > 0 else 0.0

    top_target = symbol_counts.most_common(1)[0][0] if symbol_counts else "N/A"
    top_target_ratio = (100.0 * symbol_counts[top_target] / miss_fn_samples) if miss_fn_samples > 0 and top_target != "N/A" else 0.0

    lines = []
    lines.append("# PEBS Trace Summary")
    lines.append("")
    if args.event_label:
        lines.append(f"- Event: `{args.event_label}`")
    lines.append(f"- LBR samples parsed (raw): {br_samples}")
    lines.append(f"- Branch-type samples parsed: {total_branch}")
    lines.append(f"- First-target samples parsed: {miss_fn_samples}")
    lines.append(f"- Top branch type: `{top_branch}` ({top_branch_ratio:.2f}%)")
    lines.append(f"- Top miss target function: `{top_target}` ({top_target_ratio:.2f}%)")
    lines.append(f"- SrcLine resolved samples: {line_stats['samples_line_resolved']}")
    lines.append(f"- SrcLine unresolved samples: {line_stats['samples_line_unresolved']}")
    lines.append("")
    lines.append("## Outputs")
    lines.append(f"- `{out_branch_csv}`")
    lines.append(f"- `{out_target_branch_csv}`")
    lines.append(f"- `{out_hier_report}`")
    lines.append(f"- `{out_detailed_md}`")
    out_summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
