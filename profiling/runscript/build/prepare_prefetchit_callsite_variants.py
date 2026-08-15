#!/usr/bin/env python3
import argparse
import csv
import glob
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


FUNC_DEF_RE = re.compile(r"^void\s+([A-Za-z0-9_]+)\([^;]*\)\s*\{")
ENTRY_MIN_SLASHES = 7


def parse_args():
    ap = argparse.ArgumentParser(
        description=(
            "Prepare pre-branch/callsite prefetchit variants. The injection site is "
            "the source line mapped from LBR[d].from, so the prefetch executes before "
            "the branch/call instruction instead of at the callee/function entry."
        )
    )
    ap.add_argument("--base-verilator-dir", required=True)
    ap.add_argument("--baseline-bin", required=True)
    ap.add_argument("--config", default="DualMegaBoomAndSingleRocketConfig")
    ap.add_argument("--trace-dir", required=True)
    ap.add_argument("--variant-root", required=True)
    ap.add_argument("--result-root", required=True)
    ap.add_argument("--variant-name-prefix", default="verilator_pf_callsite_")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--site-budget", type=int, default=10)
    ap.add_argument(
        "--variant-depth-groups",
        default="k10_pre_d4:4;k10_pre_d4_d8:4,8;k10_pre_d4_to_d8:4,5,6,7,8",
        help="Semicolon-separated variant:depths list.",
    )
    ap.add_argument(
        "--variant-specs",
        default="",
        help=(
            "Optional semicolon-separated name:top_n:site_budget:depths specs. "
            "Depths accept comma lists and ranges, e.g. "
            "k30_pre_d4_to_d16:30:10:4-16. When set, this overrides "
            "--top-n/--site-budget/--variant-depth-groups."
        ),
    )
    ap.add_argument("--prefer-prefix", default="VTestDriver___024root___")
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    ap.add_argument("--copy-tool", default="rsync", choices=["rsync", "cp"])
    return ap.parse_args()


def normalize_symbol(sym: str) -> str:
    s = sym.strip()
    s = re.sub(r"\+0x[0-9a-fA-F]+$", "", s)
    if "@" in s:
        s = s.split("@", 1)[0]
    if "(" in s:
        s = s.split("(", 1)[0]
    return s.strip()


def parse_symbol_offset(sym: str):
    s = sym.strip()
    m = re.match(r"^(.*)\+0x([0-9a-fA-F]+)$", s)
    if not m:
        return normalize_symbol(s), 0
    return normalize_symbol(m.group(1)), int(m.group(2), 16)


def parse_lbr_entries(line: str):
    out = []
    for tok in line.strip().split():
        if tok.count("/") < ENTRY_MIN_SLASHES:
            continue
        parts = tok.split("/")
        if len(parts) < 7:
            continue
        from_base, from_off = parse_symbol_offset(parts[0])
        to_base, to_off = parse_symbol_offset(parts[1])
        out.append(
            {
                "from_raw": parts[0],
                "to_raw": parts[1],
                "from_symbol": from_base,
                "from_offset": from_off,
                "to_symbol": to_base,
                "to_offset": to_off,
                "branch_type": parts[6],
            }
        )
    return out


def load_top_targets(target_csv: Path, top_n: int):
    counts = Counter()
    with target_csv.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            sym = row.get("symbol", "").strip()
            cnt = int(float(row.get("count", "0")))
            if sym and cnt > 0:
                counts[sym] += cnt
    return counts.most_common(top_n)


def parse_depth_list(raw: str):
    depths = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo = int(lo_s.strip())
            hi = int(hi_s.strip())
            if lo <= 0 or hi < lo:
                raise RuntimeError(f"bad depth range: {part}")
            depths.update(range(lo, hi + 1))
        else:
            depth = int(part)
            if depth <= 0:
                raise RuntimeError(f"bad depth: {part}")
            depths.add(depth)
    if not depths:
        raise RuntimeError(f"empty depth list: {raw}")
    return sorted(depths)


def parse_depth_groups(raw: str, top_n: int, site_budget: int):
    groups = []
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise RuntimeError(f"bad depth group entry: {item}")
        name, depths_raw = item.split(":", 1)
        depths = parse_depth_list(depths_raw)
        if not name or not depths:
            raise RuntimeError(f"bad depth group entry: {item}")
        groups.append(
            {
                "name": name.strip(),
                "depths": depths,
                "top_n": top_n,
                "site_budget": site_budget,
            }
        )
    if not groups:
        raise RuntimeError("--variant-depth-groups produced no variants")
    return groups


def parse_variant_specs(raw: str):
    specs = []
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":", 3)
        if len(parts) != 4:
            raise RuntimeError(f"bad variant spec entry: {item}")
        name, top_s, budget_s, depths_raw = parts
        top_n = int(top_s)
        site_budget = int(budget_s)
        if not name or top_n <= 0 or site_budget <= 0:
            raise RuntimeError(f"bad variant spec entry: {item}")
        specs.append(
            {
                "name": name.strip(),
                "depths": parse_depth_list(depths_raw),
                "top_n": top_n,
                "site_budget": site_budget,
            }
        )
    if not specs:
        raise RuntimeError("--variant-specs produced no variants")
    return specs


def build_symbol_maps(sim_bin: Path):
    raw = subprocess.run(
        ["nm", "-n", str(sim_bin)],
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.splitlines()
    dem = subprocess.run(
        ["nm", "-n", "-C", str(sim_bin)],
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.splitlines()

    line_re = re.compile(r"^([0-9a-fA-F]+)\s+([A-Za-z])\s+(.+)$")
    raw_by_key = {}
    dem_by_key = {}
    addr_by_dem = {}
    for ln in raw:
        m = line_re.match(ln)
        if m:
            raw_by_key[(m.group(1), m.group(2))] = m.group(3).strip()
    for ln in dem:
        m = line_re.match(ln)
        if not m:
            continue
        addr = int(m.group(1), 16)
        name = m.group(3).strip()
        dem_by_key[(m.group(1), m.group(2))] = name
        base = normalize_symbol(name)
        addr_by_dem.setdefault(base, addr)

    dem_to_mangled = {}
    for k, raw_name in raw_by_key.items():
        dem_name = dem_by_key.get(k)
        if dem_name:
            dem_to_mangled[normalize_symbol(dem_name)] = raw_name
    return addr_by_dem, dem_to_mangled


def collect_callsite_counts(lbr_file: Path, top_target_bases: list[str], depths: list[int]):
    max_depth = max(depths)
    depth_set = set(depths)
    target_set = set(top_target_bases)
    counts = Counter()
    target_seen = Counter()

    with lbr_file.open("r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            entries = parse_lbr_entries(raw)
            if not entries:
                continue
            miss_target = entries[0]["to_symbol"]
            if miss_target not in target_set:
                continue
            target_seen[miss_target] += 1
            upto = min(len(entries), max_depth)
            for depth in depth_set:
                idx = depth - 1
                if idx >= upto:
                    continue
                e = entries[idx]
                key = (
                    depth,
                    miss_target,
                    e["from_symbol"],
                    e["from_offset"],
                    e["to_symbol"],
                    e["to_offset"],
                    e["branch_type"],
                )
                counts[key] += 1
    return counts, target_seen


def resolve_addr2line(addr2line_bin: str, sim_bin: Path, addrs: list[int]):
    if not addrs:
        return {}
    args = [addr2line_bin, "-e", str(sim_bin), "-f", "-C"] + [hex(a) for a in addrs]
    proc = subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = proc.stdout.splitlines()
    out = {}
    for i, addr in enumerate(addrs):
        j = i * 2
        if j + 1 >= len(lines):
            continue
        func = lines[j].strip()
        loc = lines[j + 1].strip()
        out[addr] = (func, loc)
    return out


def generated_rel_from_loc(loc: str, cfg_tag: str):
    if not loc or loc.startswith("??"):
        return None, 0
    if ":" not in loc:
        return None, 0
    path_s, line_s = loc.rsplit(":", 1)
    try:
        line_no = int(line_s)
    except ValueError:
        return None, 0
    if line_no <= 0:
        return None, 0
    p = Path(path_s)
    parts = p.parts
    needle = (cfg_tag, cfg_tag)
    for i in range(len(parts) - 1):
        if tuple(parts[i : i + 2]) == needle:
            return Path(*parts[i + 2 :]), line_no
    return None, 0


def copy_tree(src: Path, dst: Path, tool: str):
    if tool == "rsync" and shutil.which("rsync"):
        dst.mkdir(parents=True, exist_ok=True)
        subprocess.run(["rsync", "-a", "--delete", f"{src}/", f"{dst}/"], check=True)
    else:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)


def strip_existing_prefetch(lines: list[str]):
    out = []
    for ln in lines:
        if "PREFETCHIT_CALLSITE" in ln:
            continue
        if "PREFETCHIT_MANUAL" in ln:
            continue
        if 'asm volatile("prefetchit0 ' in ln:
            continue
        out.append(ln)
    return out


def brace_delta(line: str):
    # Good enough for generated Verilator C++; avoids placing asm outside a function.
    return line.count("{") - line.count("}")


def find_enclosing_function_body_start(lines: list[str], idx: int):
    """Return the first line index inside the enclosing function body, or None."""
    in_func = False
    depth = 0
    body_start = None
    last = max(0, min(idx, len(lines) - 1))
    for i in range(0, last + 1):
        line = lines[i]
        if not in_func:
            if FUNC_DEF_RE.match(line):
                in_func = True
                depth = brace_delta(line)
                body_start = i + 1
                if depth <= 0:
                    in_func = False
                    body_start = None
            continue

        depth += brace_delta(line)
        if depth <= 0:
            if i >= idx:
                return body_start
            in_func = False
            body_start = None

    return body_start if in_func else None


def find_statement_insert_index(lines: list[str], line_no: int):
    """Return a safe statement-boundary insertion index before a mapped source line."""
    idx = max(0, min(line_no - 1, len(lines)))
    if not lines:
        return None
    body_start = find_enclosing_function_body_start(lines, min(idx, len(lines) - 1))
    if body_start is None:
        return None
    idx = max(idx, body_start)
    for j in range(idx - 1, body_start - 1, -1):
        stripped = lines[j].strip()
        if not stripped or stripped.startswith("//"):
            continue
        if stripped.endswith(";") or stripped.endswith("{") or stripped.endswith("}") or FUNC_DEF_RE.match(lines[j]):
            pos = j + 1
            # Keep Verilator's section comments attached to the following statement.
            while pos < idx:
                ahead = lines[pos].strip()
                if ahead == "" or ahead.startswith("//"):
                    pos += 1
                    continue
                break
            return pos
    return body_start


def align_grouped_to_statement_start(variant_dir: Path, cfg_tag: str, grouped):
    gen_cpp_dir = variant_dir / "generated-src" / cfg_tag / cfg_tag
    out = defaultdict(lambda: defaultdict(list))
    for rel, line_map in grouped.items():
        fp = gen_cpp_dir / rel
        if not fp.exists():
            continue
        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        lines = strip_existing_prefetch(lines)
        for line_no, rows in line_map.items():
            insert_idx = find_statement_insert_index(lines, line_no)
            if insert_idx is None:
                continue
            safe_line = insert_idx + 1
            for row in rows:
                row2 = dict(row)
                row2["original_src_line"] = line_no
                row2["insertion_src_line"] = safe_line
                out[rel][safe_line].append(row2)
    return out


def patch_variant(variant_dir: Path, cfg_tag: str, insertions_by_rel_line, variant_short: str):
    gen_cpp_dir = variant_dir / "generated-src" / cfg_tag / cfg_tag
    patched_files = 0
    inserted = 0
    for rel, line_map in insertions_by_rel_line.items():
        fp = gen_cpp_dir / rel
        if not fp.exists():
            continue
        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        lines = strip_existing_prefetch(lines)

        insertions = []
        for line_no, site_rows in line_map.items():
            if line_no < 1 or line_no > len(lines) + 1:
                continue
            block = [
                (
                    f"    // PREFETCHIT_CALLSITE variant={variant_short} "
                    f"file={rel} line={line_no} sites={len(site_rows)}\n"
                )
            ]
            for row in site_rows:
                block.append(
                    (
                        f"    // PREFETCHIT_CALLSITE depth={row['depth']} "
                        f"branch={row['from_symbol']}+0x{row['from_offset']:x} "
                        f"type={row['branch_type']} count={row['count']} "
                        f"target={row['target_symbol']} "
                        f"orig_line={row.get('original_src_line', line_no)}\n"
                    )
                )
                block.append(f'    asm volatile("prefetchit0 {row["target_mangled"]}(%%rip)" ::: "memory");\n')
                inserted += 1
            insertions.append((line_no - 1, block))

        if not insertions:
            continue
        insertions.sort(key=lambda x: x[0], reverse=True)
        for pos, block in insertions:
            lines[pos:pos] = block
        fp.write_text("".join(lines), encoding="utf-8")
        patched_files += 1
    return patched_files, inserted


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def main():
    args = parse_args()
    base_dir = Path(args.base_verilator_dir).resolve()
    sim_bin = Path(args.baseline_bin).resolve()
    trace_dir = Path(args.trace_dir).resolve()
    variant_root = Path(args.variant_root).resolve()
    result_root = Path(args.result_root).resolve()
    cfg_tag = f"chipyard.harness.TestHarness.{args.config}"

    if args.top_n <= 0 or args.site_budget <= 0:
        raise RuntimeError("--top-n and --site-budget must be positive")
    if not (base_dir / "generated-src" / cfg_tag / cfg_tag).is_dir():
        raise RuntimeError(f"missing generated source tree under {base_dir}")
    if not sim_bin.exists():
        raise RuntimeError(f"missing baseline binary: {sim_bin}")

    if args.variant_specs.strip():
        groups = parse_variant_specs(args.variant_specs)
    else:
        groups = parse_depth_groups(args.variant_depth_groups, args.top_n, args.site_budget)
    all_depths = sorted({d for spec in groups for d in spec["depths"]})
    max_top_n = max(spec["top_n"] for spec in groups)
    max_site_budget = max(spec["site_budget"] for spec in groups)

    lbr_file = trace_dir / "lbr_symbolic_dump.txt"
    target_csv = trace_dir / "target_branch_counts.csv"
    if not lbr_file.exists() or not target_csv.exists():
        raise RuntimeError(f"missing trace inputs under {trace_dir}")

    top = load_top_targets(target_csv, max_top_n)
    top_bases = [normalize_symbol(sym) for sym, _ in top]
    target_rank = {base: rank for rank, base in enumerate(top_bases, start=1)}
    addr_by_dem, dem_to_mangled = build_symbol_maps(sim_bin)

    target_to_mangled = {}
    for sym, _ in top:
        base = normalize_symbol(sym)
        target_to_mangled[base] = dem_to_mangled.get(base, "")

    counts, target_seen = collect_callsite_counts(lbr_file, top_bases, all_depths)

    selected = []
    candidate_rows = []
    coverage_rows = []
    addrs_needed = set()

    by_depth_target = defaultdict(list)
    for key, cnt in counts.items():
        depth, target, from_sym, from_off, to_sym, to_off, branch_type = key
        if from_sym not in addr_by_dem:
            continue
        if target_to_mangled.get(target, "") == "":
            continue
        if args.prefer_prefix and not from_sym.startswith(args.prefer_prefix):
            continue
        by_depth_target[(depth, target)].append((cnt, from_sym, from_off, to_sym, to_off, branch_type))

    for depth in all_depths:
        for target in top_bases:
            total = int(target_seen.get(target, 0))
            ranked = sorted(by_depth_target.get((depth, target), []), reverse=True)
            covered = 0
            for rank, item in enumerate(ranked, start=1):
                cnt, from_sym, from_off, to_sym, to_off, branch_type = item
                candidate_rows.append(
                    {
                        "depth": depth,
                        "target_symbol": target,
                        "candidate_rank": rank,
                        "count": cnt,
                        "from_symbol": from_sym,
                        "from_offset": f"0x{from_off:x}",
                        "to_symbol": to_sym,
                        "to_offset": f"0x{to_off:x}",
                        "branch_type": branch_type,
                    }
                )
                if rank > max_site_budget:
                    continue
                addr = addr_by_dem[from_sym] + from_off
                addrs_needed.add(addr)
                covered += cnt
                selected.append(
                    {
                        "depth": depth,
                        "target_rank": target_rank.get(target, 0),
                        "target_symbol": target,
                        "count": cnt,
                        "target_seen_samples": total,
                        "candidate_rank": rank,
                        "from_symbol": from_sym,
                        "from_offset": from_off,
                        "to_symbol": to_sym,
                        "to_offset": to_off,
                        "branch_type": branch_type,
                        "addr": addr,
                        "target_mangled": target_to_mangled[target],
                    }
                )
            coverage_rows.append(
                {
                    "site_budget": max_site_budget,
                    "depth": depth,
                    "target_symbol": target,
                    "target_rank": target_rank.get(target, 0),
                    "target_seen_samples": total,
                    "covered_samples": covered,
                    "coverage_pct": f"{(100.0 * covered / total) if total else 0.0:.4f}",
                    "selected_site_count": min(len(ranked), max_site_budget),
                }
            )

    resolved = resolve_addr2line(args.addr2line, sim_bin, sorted(addrs_needed))

    resolved_rows = []
    usable_by_depth = defaultdict(list)
    unresolved = []
    for row in selected:
        func, loc = resolved.get(row["addr"], ("", ""))
        rel, line_no = generated_rel_from_loc(loc, cfg_tag)
        out = dict(row)
        out["addr"] = f"0x{row['addr']:x}"
        out["addr2line_function"] = func
        out["addr2line_location"] = loc
        out["src_relpath"] = str(rel) if rel else ""
        out["src_line"] = line_no
        if rel and line_no > 0:
            usable_by_depth[int(row["depth"])].append((rel, line_no, row))
        else:
            unresolved.append(out)
        resolved_rows.append(out)

    result_root.mkdir(parents=True, exist_ok=True)
    variant_root.mkdir(parents=True, exist_ok=True)

    top_rows = []
    for rank, (sym, cnt) in enumerate(top, start=1):
        base = normalize_symbol(sym)
        top_rows.append(
            {
                "rank": rank,
                "symbol": sym,
                "base_symbol": base,
                "count": cnt,
                "mangled_symbol": target_to_mangled.get(base, ""),
                "target_seen_samples": int(target_seen.get(base, 0)),
            }
        )
    write_csv(result_root / "selected_top_targets.csv", top_rows, ["rank", "symbol", "base_symbol", "count", "mangled_symbol", "target_seen_samples"])
    write_csv(result_root / "candidate_rankings.csv", candidate_rows, ["depth", "target_symbol", "candidate_rank", "count", "from_symbol", "from_offset", "to_symbol", "to_offset", "branch_type"])
    write_csv(result_root / "coverage_by_target.csv", coverage_rows, ["site_budget", "depth", "target_symbol", "target_rank", "target_seen_samples", "covered_samples", "coverage_pct", "selected_site_count"])
    write_csv(
        result_root / "resolved_callsite_selection.csv",
        resolved_rows,
        [
            "depth",
            "target_rank",
            "target_symbol",
            "count",
            "target_seen_samples",
            "candidate_rank",
            "from_symbol",
            "from_offset",
            "to_symbol",
            "to_offset",
            "branch_type",
            "addr",
            "target_mangled",
            "addr2line_function",
            "addr2line_location",
            "src_relpath",
            "src_line",
        ],
    )
    write_csv(
        result_root / "unresolved_callsite_selection.csv",
        unresolved,
        [
            "depth",
            "target_rank",
            "target_symbol",
            "count",
            "target_seen_samples",
            "candidate_rank",
            "from_symbol",
            "from_offset",
            "to_symbol",
            "to_offset",
            "branch_type",
            "addr",
            "target_mangled",
            "addr2line_function",
            "addr2line_location",
            "src_relpath",
            "src_line",
        ],
    )

    variant_rows = []
    point_rows = []
    count_rows = []
    for spec in groups:
        variant_short = spec["name"]
        depths = spec["depths"]
        top_n = spec["top_n"]
        site_budget = spec["site_budget"]
        variant_name = f"{args.variant_name_prefix}{variant_short}"
        variant_dir = variant_root / variant_name
        copy_tree(base_dir, variant_dir, args.copy_tool)

        grouped = defaultdict(lambda: defaultdict(list))
        seen = set()
        for depth in depths:
            for rel, line_no, row in usable_by_depth.get(depth, []):
                if int(row.get("target_rank", 0)) > top_n:
                    continue
                if int(row.get("candidate_rank", 0)) > site_budget:
                    continue
                key = (str(rel), line_no, row["target_symbol"], row["from_symbol"], row["from_offset"], depth)
                if key in seen:
                    continue
                seen.add(key)
                grouped[rel][line_no].append(row)

        grouped = align_grouped_to_statement_start(variant_dir, cfg_tag, grouped)
        patched_files, inserted = patch_variant(variant_dir, cfg_tag, grouped, variant_short)
        variant_rows.append(
            {
                "variant": variant_name,
                "variant_short": variant_short,
                "top_n": top_n,
                "site_budget": site_budget,
                "depths": "|".join(str(d) for d in depths),
                "patched_file_count": patched_files,
                "inserted_prefetch_instructions": inserted,
            }
        )
        count_rows.append(
            {
                "variant_short": variant_short,
                "top_n": top_n,
                "site_budget": site_budget,
                "depth": "|".join(str(d) for d in depths),
                "unique_inject_functions": len(
                    {
                        r["from_symbol"]
                        for d in depths
                        for _, _, r in usable_by_depth.get(d, [])
                        if int(r.get("target_rank", 0)) <= top_n and int(r.get("candidate_rank", 0)) <= site_budget
                    }
                ),
                "unique_source_lines": sum(len(v) for v in grouped.values()),
                "inserted_prefetch_instructions": inserted,
            }
        )
        for rel, line_map in grouped.items():
            for line_no, rows in line_map.items():
                for row in rows:
                    point_rows.append(
                        {
                            "variant": variant_name,
                            "variant_short": variant_short,
                            "target_rank": row["target_rank"],
                            "depth": row["depth"],
                            "target_symbol": row["target_symbol"],
                            "candidate_rank": row["candidate_rank"],
                            "count": row["count"],
                            "from_symbol": row["from_symbol"],
                            "from_offset": f"0x{row['from_offset']:x}",
                            "to_symbol": row["to_symbol"],
                            "branch_type": row["branch_type"],
                            "src_relpath": str(rel),
                            "src_line": line_no,
                            "original_src_line": row.get("original_src_line", line_no),
                            "target_mangled": row["target_mangled"],
                        }
                    )

    write_csv(result_root / "variant_dirs.csv", variant_rows, ["variant", "variant_short", "top_n", "site_budget", "depths", "patched_file_count", "inserted_prefetch_instructions"])
    write_csv(result_root / "injection_counts_by_depth.csv", count_rows, ["variant_short", "top_n", "site_budget", "depth", "unique_inject_functions", "unique_source_lines", "inserted_prefetch_instructions"])
    write_csv(result_root / "injection_points_by_depth.csv", point_rows, ["variant", "variant_short", "target_rank", "depth", "target_symbol", "candidate_rank", "count", "from_symbol", "from_offset", "to_symbol", "branch_type", "src_relpath", "src_line", "original_src_line", "target_mangled"])

    with (result_root / "injection_summary.md").open("w", encoding="utf-8") as f:
        f.write("# Callsite PrefetchIT Variants\n\n")
        f.write("- Placement: before source line mapped from `LBR[depth].from`\n")
        f.write("- Variant-specific target count and site budget are listed below.\n\n")
        f.write("| Variant | Top Targets | Site Budget | Depths | Patched Files | Prefetch Instructions |\n")
        f.write("|---|---:|---:|---:|---:|---:|\n")
        for row in variant_rows:
            display_depths = str(row["depths"]).replace("|", ",")
            f.write(
                f"| {row['variant']} | {row['top_n']} | {row['site_budget']} | {display_depths} | {row['patched_file_count']} | "
                f"{row['inserted_prefetch_instructions']} |\n"
            )

    print(f"[ok] result_root={result_root}")
    print(f"[ok] variant_root={variant_root}")
    for row in variant_rows:
        print(
            "[variant] "
            f"{row['variant_short']} depths={row['depths']} "
            f"patched_files={row['patched_file_count']} "
            f"prefetchit={row['inserted_prefetch_instructions']}"
        )
    if unresolved:
        print(f"[warn] unresolved selected callsites: {len(unresolved)}")


if __name__ == "__main__":
    main()
