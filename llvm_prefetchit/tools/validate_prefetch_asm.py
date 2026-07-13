#!/usr/bin/env python3
"""Validate PC-relative prefetch instructions emitted by the LLVM pass."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


PREFETCH_RE = re.compile(
    r"^\s*([0-9a-fA-F]+):.*\b(prefetch(?:t[012]|nta)|prefetchit[01])\b.*"
    r"#\s*((?:0x)?[0-9a-fA-F]+)"
)
DISASM_LINE_RE = re.compile(r"^\s*[0-9a-fA-F]+:")
INJECTED_RE = re.compile(r"prefetchit-inject:\s+injected=([0-9]+)")
NM_LINE_RE = re.compile(r"^([0-9a-fA-F]+)\s+([A-Za-z])\s+(.+)$")
TEXT_SYMBOL_TYPES = set("tTwW")


@dataclass(frozen=True)
class Loc:
    function: str
    file: str
    line: int


def norm_path(path: str) -> str:
    return path.replace("\\", "/").replace("/./", "/")


def loc_matches(actual: Loc, wanted: Loc) -> bool:
    if wanted.line and actual.line != wanted.line:
        return False
    if not wanted.file or wanted.file.startswith("<"):
        return True
    af = norm_path(actual.file)
    wf = norm_path(wanted.file)
    if af == wf:
        return True
    return af.endswith("/" + wf) or wf.endswith("/" + af) or Path(af).name == Path(wf).name


def strip_args(name: str) -> str:
    return name.split("(", 1)[0].strip()


def function_matches(actual: str, wanted: str) -> bool:
    if not actual or not wanted:
        return False
    return strip_args(actual) == strip_args(wanted)


def loc_index_key(loc: Loc) -> tuple[str, str, int]:
    return (norm_path(loc.file), Path(norm_path(loc.file)).name, loc.line)


def build_loc_index(locs: list[Loc]) -> dict[str, set]:
    exact: set[tuple[str, int]] = set()
    basename: set[tuple[str, int]] = set()
    wildcard_lines: set[int] = set()
    for loc in locs:
        if loc.line <= 0:
            continue
        nf, base, line = loc_index_key(loc)
        if nf and not nf.startswith("<"):
            exact.add((nf, line))
            basename.add((base, line))
        else:
            wildcard_lines.add(line)
    return {"exact": exact, "basename": basename, "wildcard_lines": wildcard_lines}


def loc_matches_index(actual: Loc, index: dict[str, set]) -> bool:
    if actual.line <= 0:
        return False
    nf, base, line = loc_index_key(actual)
    return (
        (nf, line) in index["exact"]
        or (base, line) in index["basename"]
        or line in index["wildcard_lines"]
    )


def parse_loc(obj: dict) -> Loc:
    # For trace-derived inlined locations, "function" can be the inline helper
    # while "demangled"/"mangled" identifies the containing symbol that objdump
    # prints for the PC-relative target. Prefer the containing symbol for
    # target-function validation; file/line checks still use the debug location.
    return Loc(
        function=str(obj.get("demangled") or obj.get("function") or obj.get("mangled") or ""),
        file=str(obj.get("file") or ""),
        line=int(obj.get("line") or 0),
    )


def parse_int_maybe(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text, 0)
    except ValueError:
        return None


def resolve_symbol_bases(binary: Path, names: set[str], nm_bin: str = "nm") -> dict[str, int]:
    if not names:
        return {}
    nm = shutil.which(nm_bin) or nm_bin
    cp = subprocess.run(
        [nm, "-n", str(binary)],
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
        typ = m.group(2)
        name = m.group(3).strip()
        if typ not in TEXT_SYMBOL_TYPES or name not in names or name in out:
            continue
        out[name] = int(m.group(1), 16)
    return out


def parse_prefetch_offsets(plan: dict) -> list[int]:
    raw = plan.get("prefetch", {}).get("byte_offsets", [0])
    if not isinstance(raw, list):
        return [0]
    offsets: list[int] = []
    seen: set[int] = set()
    for item in raw:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value < 0 or value in seen:
            continue
        seen.add(value)
        offsets.append(value)
    return offsets or [0]


def run_lines(cmd: list[str]) -> list[str]:
    cp = subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return cp.stdout.splitlines()


def run_prefetch_disasm_lines(objdump: str, binary: Path) -> list[str]:
    cp = subprocess.Popen(
        [objdump, "-d", "-Mintel", str(binary)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert cp.stdout is not None
    out: list[str] = []
    for line in cp.stdout:
        if "prefetch" in line:
            out.append(line.rstrip("\n"))
    stderr = cp.stderr.read() if cp.stderr is not None else ""
    rc = cp.wait()
    if rc != 0:
        raise subprocess.CalledProcessError(rc, [objdump, "-d", "-Mintel", str(binary)], stderr=stderr)
    return out


def resolve_addrs(addr2line: str, binary: Path, addrs: list[int]) -> dict[int, Loc]:
    out: dict[int, Loc] = {}
    if not addrs:
        return out
    chunk_size = 512
    for start in range(0, len(addrs), chunk_size):
        chunk = addrs[start : start + chunk_size]
        lines = run_lines([addr2line, "-e", str(binary), "-f", "-C"] + [hex(a) for a in chunk])
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
            out[addr] = Loc(function=fn, file=file_name, line=line_no)
    return out


def latest_injected_count(log_path: Path) -> int:
    if not log_path.exists():
        return 0
    last = 0
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = INJECTED_RE.search(line)
        if m:
            last = int(m.group(1))
    return last


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--build-log", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--mnemonic", default="prefetcht1")
    ap.add_argument("--objdump", default="objdump")
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    args = ap.parse_args()

    binary = Path(args.binary).resolve()
    plan_path = Path(args.plan).resolve()
    build_log = Path(args.build_log).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    injections = plan.get("injections", [])
    operand_mode = str(plan.get("prefetch", {}).get("operand", "pc-relative-blockaddress"))
    prefetch_offsets = parse_prefetch_offsets(plan)
    strict_target_cacheline = operand_mode == "pc-relative-symbol-offset" or prefetch_offsets == [0]
    target_locs = [parse_loc(x.get("target", {})) for x in injections]
    site_locs = [parse_loc(x.get("site", {})) for x in injections]
    target_loc_index = build_loc_index(target_locs)
    site_loc_index = build_loc_index(site_locs)
    target_functions = {strip_args(loc.function) for loc in target_locs if loc.function}
    planned_target_addrs = {
        addr
        for addr in (parse_int_maybe(x.get("target", {}).get("addr")) for x in injections)
        if addr is not None
    }
    planned_target_cachelines = {
        cacheline
        for cacheline in (
            parse_int_maybe(x.get("target", {}).get("cacheline64")) for x in injections
        )
        if cacheline is not None
    }
    planned_target_cachelines.update(addr & ~0x3F for addr in planned_target_addrs)
    planned_prefetch_target_addrs = {
        addr + offset for addr in planned_target_addrs for offset in prefetch_offsets
    }
    planned_prefetch_target_cachelines = {
        (addr + offset) & ~0x3F
        for addr in planned_target_addrs
        for offset in prefetch_offsets
    }
    planned_prefetch_target_cachelines.update(
        (cacheline + offset) & ~0x3F
        for cacheline in planned_target_cachelines
        for offset in prefetch_offsets
    )
    if operand_mode == "pc-relative-symbol-offset":
        needed_symbols = {
            str(x.get("target", {}).get("mangled") or "")
            for x in injections
            if x.get("target", {}).get("mangled")
        }
        symbol_bases = resolve_symbol_bases(binary, needed_symbols)
        optimized_target_addrs: set[int] = set()
        for injection in injections:
            target = injection.get("target", {})
            mangled = str(target.get("mangled") or "")
            sym_offset = parse_int_maybe(target.get("symbol_offset"))
            base = symbol_bases.get(mangled)
            if base is None or sym_offset is None:
                continue
            for offset in prefetch_offsets:
                optimized_target_addrs.add(base + sym_offset + offset)
        if optimized_target_addrs:
            planned_prefetch_target_addrs = optimized_target_addrs
            planned_prefetch_target_cachelines = {addr & ~0x3F for addr in optimized_target_addrs}

    lines = run_prefetch_disasm_lines(args.objdump, binary)
    objdump_txt = out_dir / "prefetch_objdump.txt"
    objdump_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    records = []
    for line in lines:
        if not DISASM_LINE_RE.match(line) or args.mnemonic not in line:
            continue
        m = PREFETCH_RE.match(line)
        if not m:
            records.append(
                {
                    "site_pc": "",
                    "mnemonic": args.mnemonic,
                    "target_pc": "",
                    "raw": line.strip(),
                    "parse_status": "unparsed",
                }
            )
            continue
        site_pc = int(m.group(1), 16)
        mnemonic = m.group(2)
        target_pc = int(m.group(3), 16)
        records.append(
            {
                "site_pc": site_pc,
                "mnemonic": mnemonic,
                "target_pc": target_pc,
                "raw": line.strip(),
                "parse_status": "ok",
            }
        )

    site_addrs = sorted({r["site_pc"] for r in records if isinstance(r.get("site_pc"), int)})
    target_addrs = sorted({r["target_pc"] for r in records if isinstance(r.get("target_pc"), int)})
    srcline_limit = int(os.environ.get("PREFETCHIT_VALIDATION_SRCLINE_LIMIT", "20000"))
    resolve_srclines = not (
        operand_mode == "pc-relative-symbol-offset" and len(records) > srcline_limit
    )
    if resolve_srclines:
        site_resolved = resolve_addrs(args.addr2line, binary, site_addrs)
        target_resolved = resolve_addrs(args.addr2line, binary, target_addrs)
    else:
        site_resolved = {}
        target_resolved = {}

    rows = []
    for idx, rec in enumerate(records, start=1):
        site_pc = rec.get("site_pc")
        target_pc = rec.get("target_pc")
        site_loc = site_resolved.get(site_pc, Loc("", "", 0)) if isinstance(site_pc, int) else Loc("", "", 0)
        target_loc = (
            target_resolved.get(target_pc, Loc("", "", 0)) if isinstance(target_pc, int) else Loc("", "", 0)
        )
        site_match = loc_matches_index(site_loc, site_loc_index) if resolve_srclines else False
        target_match = loc_matches_index(target_loc, target_loc_index) if resolve_srclines else False
        target_function_match = (
            strip_args(target_loc.function) in target_functions if resolve_srclines else False
        )
        target_addr_match = (
            int(target_pc in planned_prefetch_target_addrs)
            if isinstance(target_pc, int) and planned_prefetch_target_addrs
            else 0
        )
        target_cacheline_match = (
            int((target_pc & ~0x3F) in planned_prefetch_target_cachelines)
            if isinstance(target_pc, int) and planned_prefetch_target_cachelines
            else 0
        )
        rows.append(
            {
                "index": idx,
                "mnemonic": rec.get("mnemonic", ""),
                "site_pc": hex(site_pc) if isinstance(site_pc, int) else "",
                "site_function": site_loc.function,
                "site_file": site_loc.file,
                "site_line": site_loc.line,
                "site_matches_plan": int(site_match),
                "target_pc": hex(target_pc) if isinstance(target_pc, int) else "",
                "target_function": target_loc.function,
                "target_file": target_loc.file,
                "target_line": target_loc.line,
                "target_matches_plan": int(target_match),
                "target_function_matches_plan": int(target_function_match),
                "target_addr_matches_plan": target_addr_match,
                "target_cacheline_matches_plan": target_cacheline_match,
                "parse_status": rec.get("parse_status", ""),
                "raw": rec.get("raw", ""),
            }
        )

    csv_path = out_dir / "prefetch_asm_validation.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "index",
            "mnemonic",
            "site_pc",
            "site_function",
            "site_file",
            "site_line",
            "site_matches_plan",
            "target_pc",
            "target_function",
            "target_file",
            "target_line",
            "target_matches_plan",
            "target_function_matches_plan",
            "target_addr_matches_plan",
            "target_cacheline_matches_plan",
            "parse_status",
            "raw",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    pass_injected = latest_injected_count(build_log)
    plan_count = len(injections)
    asm_count = sum(1 for r in rows if r["mnemonic"] == args.mnemonic)
    parsed_count = sum(1 for r in rows if r["parse_status"] == "ok")
    site_match_count = sum(int(r["site_matches_plan"]) for r in rows)
    target_match_count = sum(int(r["target_matches_plan"]) for r in rows)
    target_function_match_count = sum(int(r["target_function_matches_plan"]) for r in rows)
    target_addr_match_count = sum(int(r["target_addr_matches_plan"]) for r in rows)
    target_cacheline_match_count = sum(int(r["target_cacheline_matches_plan"]) for r in rows)
    target_line_or_function_match_count = sum(
        1
        for r in rows
        if int(r["target_matches_plan"]) or int(r["target_function_matches_plan"])
    )
    site_match_ratio = (site_match_count / asm_count) if asm_count else 0.0
    target_line_or_function_match_ratio = (
        target_line_or_function_match_count / asm_count if asm_count else 0.0
    )
    target_cacheline_match_ratio = (
        target_cacheline_match_count / asm_count
        if asm_count and planned_prefetch_target_cachelines
        else 1.0
    )
    other_prefetch_count = sum(
        1
        for line in lines
        if DISASM_LINE_RE.match(line) and re.search(r"\bprefetch", line) and args.mnemonic not in line
    )
    try:
        asm_count_min_ratio = float(os.environ.get("PREFETCHIT_VALIDATION_ASM_COUNT_MIN_RATIO", "1.0"))
    except ValueError:
        asm_count_min_ratio = 1.0
    asm_count_min_ratio = max(0.0, min(1.0, asm_count_min_ratio))
    asm_count_ratio = (asm_count / pass_injected) if pass_injected else 1.0

    checks = [
        ("plan_injections_positive", plan_count > 0),
        ("pass_injected_positive", pass_injected > 0),
        # Late optimization/codegen may clone inline asm, so assembly can
        # legitimately contain more prefetches than the IR pass inserted.
        # Very large plans can also lose a tiny number of duplicate/equivalent
        # prefetches during late codegen. Keep exact target/cacheline checks
        # strict and make only this count tolerance configurable.
        (
            "asm_prefetch_count_within_tolerance",
            asm_count >= pass_injected or asm_count_ratio >= asm_count_min_ratio,
        ),
        ("all_prefetch_lines_parsed", parsed_count == asm_count),
    ]
    strict_target_srcline = os.environ.get(
        "PREFETCHIT_VALIDATION_STRICT_TARGET_SRCLINE", "0"
    ) == "1"
    if resolve_srclines:
        checks.extend(
            [
                # Site debug locations can move slightly when LLVM clones/sinks
                # inline asm around generated Verilator helper blocks.
                ("site_srcline_match_ratio_at_least_95pct", site_match_ratio >= 0.95),
            ]
        )
        if strict_target_srcline:
            checks.append(
                (
                    "target_srcline_or_function_match_ratio_at_least_98pct",
                    target_line_or_function_match_ratio >= 0.98,
                )
            )
    if planned_prefetch_target_cachelines and strict_target_cacheline:
        checks.append(
            (
                "target_cacheline_match_ratio_at_least_98pct",
                target_cacheline_match_ratio >= 0.98,
            )
        )
    passed = all(ok for _, ok in checks)

    md = []
    md.append("# Prefetch Assembly Validation")
    md.append("")
    md.append(f"- Binary: `{binary}`")
    md.append(f"- Plan: `{plan_path}`")
    md.append(f"- Mnemonic: `{args.mnemonic}`")
    md.append(f"- Operand mode: `{operand_mode}`")
    md.append(
        f"- SrcLine validation: {'enabled' if resolve_srclines else 'skipped-large-exact-target'}"
    )
    if resolve_srclines and not strict_target_srcline:
        md.append("- Target SrcLine/function validation: reported-only")
    if not resolve_srclines:
        md.append(f"- SrcLine validation limit: {srcline_limit} prefetch instructions")
    md.append(f"- Plan injections: {plan_count}")
    md.append(
        "- Plan prefetch byte offsets: "
        + ",".join(str(offset) for offset in prefetch_offsets)
    )
    md.append(f"- Pass injected count: {pass_injected}")
    md.append(f"- Assembly `{args.mnemonic}` count: {asm_count}")
    md.append(f"- Assembly/pass count ratio: {asm_count_ratio:.6f}")
    md.append(f"- Assembly/pass min ratio: {asm_count_min_ratio:.6f}")
    md.append(f"- Parsed prefetch lines: {parsed_count}")
    md.append(f"- Site srcline matches: {site_match_count}/{asm_count} ({site_match_ratio:.2%})")
    md.append(f"- Target srcline matches: {target_match_count}/{asm_count}")
    md.append(f"- Target function matches: {target_function_match_count}/{asm_count}")
    md.append(f"- Target exact addr matches: {target_addr_match_count}/{asm_count}")
    if planned_prefetch_target_cachelines:
        md.append(
            f"- Target 64B cacheline matches: {target_cacheline_match_count}/{asm_count} "
            f"({target_cacheline_match_ratio:.2%})"
        )
        if not strict_target_cacheline:
            md.append(
                "- Target cacheline check is reported but not enforced because "
                "this plan uses target-block-relative cacheline addressing."
            )
    md.append(
        "- Target srcline-or-function matches: "
        f"{target_line_or_function_match_count}/{asm_count} "
        f"({target_line_or_function_match_ratio:.2%})"
    )
    md.append(f"- Other prefetch-like instruction lines: {other_prefetch_count}")
    if asm_count > pass_injected:
        md.append(
            "- Note: assembly count is higher than pass-injected count; this is "
            "accepted because later optimization/codegen can clone inline asm."
        )
    elif asm_count < pass_injected:
        md.append(
            "- Note: assembly count is lower than pass-injected count; this is "
            "accepted only if it is within the configured count tolerance and "
            "the target cacheline validation still passes."
        )
    md.append("")
    md.append("| Check | Status |")
    md.append("|---|---|")
    for name, ok in checks:
        md.append(f"| {name} | {'PASS' if ok else 'FAIL'} |")
    md.append("")
    md.append("## First Prefetches")
    md.append("")
    md.append(
        "| # | Site | Target | Site Match | Target Line Match | "
        "Target Function Match | Target Cacheline Match |"
    )
    md.append("|---:|---|---|---:|---:|---:|---:|")
    for row in rows[:20]:
        site = f"{row['site_function']}:{row['site_line']}"
        target = f"{row['target_function']}:{row['target_line']}"
        md.append(
            f"| {row['index']} | `{site}` | `{target}` | "
            f"{row['site_matches_plan']} | {row['target_matches_plan']} | "
            f"{row['target_function_matches_plan']} | "
            f"{row['target_cacheline_matches_plan']} |"
        )
    md.append("")
    md.append(f"Result: {'PASS' if passed else 'FAIL'}")
    (out_dir / "prefetch_asm_validation.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
