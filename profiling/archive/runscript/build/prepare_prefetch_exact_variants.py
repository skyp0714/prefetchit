#!/usr/bin/env python3
import argparse
import csv
import hashlib
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


FUNC_DEF_RE = re.compile(r"^(?:VL_INLINE_OPT\s+)?(?:void|VlCoroutine)\s+([A-Za-z0-9_]+)\([^;]*\)\s*\{")
ENTRY_MIN_SLASHES = 7
LABEL_PREFIX = "__pf_target_"


def parse_args():
    ap = argparse.ArgumentParser(
        description=(
            "Prepare exact target-label prefetch variants from PEBS+LBR traces. "
            "Each selected miss source line gets a stable label; insertion sites prefetch label(+N*line_size)."
        )
    )
    ap.add_argument("--base-verilator-dir", required=True)
    ap.add_argument("--baseline-bin", required=True)
    ap.add_argument("--config", default="DualMegaBoomAndSingleRocketConfig")
    ap.add_argument("--trace-dir", required=True)
    ap.add_argument("--variant-root", required=True)
    ap.add_argument("--result-root", required=True)
    ap.add_argument("--variant-name-prefix", default="verilator_pf_exact_")
    ap.add_argument("--variant-specs", required=True, help="name:top_n:site_budget:depths:kind:lines;... kind=it0|dt0|both")
    ap.add_argument("--prefer-prefix", default="VTestDriver___024root___")
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    ap.add_argument("--copy-tool", default="rsync", choices=["rsync", "cp"])
    ap.add_argument("--target-symbol-pool", type=int, default=200)
    ap.add_argument("--target-address-pool", type=int, default=50000)
    ap.add_argument("--prefetch-line-size", type=int, default=64)
    ap.add_argument("--max-lbr-lines", type=int, default=0, help="Debug/testing limit; 0 means full trace.")
    ap.add_argument(
        "--exclude-inlined-targets",
        action="store_true",
        help=(
            "Drop targets whose addr2line source line is inside a different generated function than the sampled target symbol. "
            "Those locations are usually inlined source and source-level global labels duplicate during compilation."
        ),
    )
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


def is_lbr_token(tok: str) -> bool:
    return tok.count("/") >= ENTRY_MIN_SLASHES


def parse_lbr_entries_limited(line: str, max_depth: int):
    out = []
    # Skip the first two perf fields when present. The first symbolic branch token can
    # have the sample symbol glued in front of its from-side, but its to-side remains valid.
    for tok in line.strip().split()[2:]:
        if not is_lbr_token(tok):
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
        if len(out) >= max_depth:
            break
    return out


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


def parse_variant_specs(raw: str):
    specs = []
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":", 5)
        if len(parts) not in (4, 6):
            raise RuntimeError(f"bad variant spec: {item}; expected name:top:budget:depths[:kind:lines]")
        name, top_s, budget_s, depths_raw = parts[:4]
        top_n = int(top_s)
        site_budget = int(budget_s)
        kind = "it0"
        lines = 1
        if len(parts) == 6:
            kind = parts[4].strip().lower()
            lines = int(parts[5])
        if not name or top_n <= 0 or site_budget <= 0 or lines <= 0:
            raise RuntimeError(f"bad variant spec: {item}")
        if kind not in {"it0", "dt0", "both", "prefetchit0", "prefetcht0", "it", "dt", "t0"}:
            raise RuntimeError(f"bad prefetch kind in variant spec: {kind}")
        specs.append(
            {
                "name": name.strip(),
                "depths": parse_depth_list(depths_raw),
                "top_n": top_n,
                "site_budget": site_budget,
                "prefetch_kind": kind,
                "prefetch_lines": lines,
            }
        )
    if not specs:
        raise RuntimeError("--variant-specs produced no variants")
    return specs


def build_symbol_maps(sim_bin: Path):
    raw = subprocess.run(["nm", "-n", str(sim_bin)], check=True, text=True, capture_output=True, encoding="utf-8", errors="replace").stdout.splitlines()
    dem = subprocess.run(["nm", "-n", "-C", str(sim_bin)], check=True, text=True, capture_output=True, encoding="utf-8", errors="replace").stdout.splitlines()
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
        addr_by_dem.setdefault(normalize_symbol(name), addr)
    dem_to_mangled = {}
    for k, raw_name in raw_by_key.items():
        dem_name = dem_by_key.get(k)
        if dem_name:
            dem_to_mangled[normalize_symbol(dem_name)] = raw_name
    return addr_by_dem, dem_to_mangled


def load_top_symbol_pool(target_csv: Path, pool_size: int):
    counts = Counter()
    with target_csv.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            sym = normalize_symbol(row.get("symbol", ""))
            try:
                cnt = int(float(row.get("count", "0")))
            except ValueError:
                cnt = 0
            if sym and cnt > 0:
                counts[sym] += cnt
    return [sym for sym, _ in counts.most_common(pool_size)]


def resolve_addr2line(addr2line_bin: str, sim_bin: Path, addrs: list[int], chunk: int = 2000):
    out = {}
    if not addrs:
        return out
    for i in range(0, len(addrs), chunk):
        sub = addrs[i : i + chunk]
        args = [addr2line_bin, "-e", str(sim_bin), "-f", "-C"] + [hex(a) for a in sub]
        proc = subprocess.run(args, check=True, text=True, capture_output=True, encoding="utf-8", errors="replace")
        lines = proc.stdout.splitlines()
        for j, addr in enumerate(sub):
            pos = j * 2
            if pos + 1 >= len(lines):
                continue
            out[addr] = (lines[pos].strip(), lines[pos + 1].strip())
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
    parts = Path(path_s).parts
    needle = (cfg_tag, cfg_tag)
    for i in range(len(parts) - 1):
        if tuple(parts[i : i + 2]) == needle:
            return Path(*parts[i + 2 :]), line_no
    return None, 0


def containing_function(source_root: Path, rel: Path, line_no: int) -> str:
    fp = source_root / rel
    if not fp.is_file() or line_no <= 0:
        return ""
    current = ""
    with fp.open("r", encoding="utf-8", errors="ignore") as f:
        for idx, line in enumerate(f, start=1):
            m = FUNC_DEF_RE.match(line)
            if m:
                current = m.group(1)
            if idx >= line_no:
                break
    return current


def copy_tree(src: Path, dst: Path, tool: str):
    if tool == "rsync" and shutil.which("rsync"):
        dst.mkdir(parents=True, exist_ok=True)
        subprocess.run(["rsync", "-a", "--delete", f"{src}/", f"{dst}/"], check=True)
    else:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)


def make_label(target_symbol: str, rel: str, line_no: int) -> str:
    h = hashlib.sha1(f"{target_symbol}|{rel}|{line_no}".encode("utf-8")).hexdigest()[:16]
    return f"{LABEL_PREFIX}{h}"


def count_target_addresses(lbr_file: Path, symbol_pool: set[str], addr_by_dem: dict[str, int], address_pool: int, max_lbr_lines: int = 0):
    counts = Counter()
    total_samples = 0
    accepted = 0
    with lbr_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line_idx, raw in enumerate(f, start=1):
            if max_lbr_lines and line_idx > max_lbr_lines:
                break
            entries = parse_lbr_entries_limited(raw, 1)
            if not entries:
                continue
            total_samples += 1
            e0 = entries[0]
            target_sym = e0["to_symbol"]
            if target_sym not in symbol_pool:
                continue
            base = addr_by_dem.get(target_sym)
            if base is None:
                continue
            accepted += 1
            counts[(target_sym, e0["to_offset"])] += 1
    return Counter(dict(counts.most_common(address_pool))), total_samples, accepted


def build_target_line_selection(
    target_addr_counts,
    addr_by_dem,
    addr2line_bin,
    sim_bin,
    cfg_tag,
    max_top_n,
    source_root: Path,
    exclude_inlined_targets: bool,
):
    addrs = []
    addr_meta = {}
    for (sym, off), cnt in target_addr_counts.items():
        base = addr_by_dem.get(sym)
        if base is None:
            continue
        addr = base + off
        addrs.append(addr)
        addr_meta[addr] = (sym, off, cnt)
    resolved = resolve_addr2line(addr2line_bin, sim_bin, sorted(set(addrs)))

    line_counts = Counter()
    addr_to_key = {}
    target_rows = []
    unresolved = []
    filtered_inlined = []
    for addr in sorted(set(addrs)):
        sym, off, cnt = addr_meta[addr]
        func, loc = resolved.get(addr, ("", ""))
        rel, line_no = generated_rel_from_loc(loc, cfg_tag)
        if not rel or line_no <= 0:
            unresolved.append({"target_symbol": sym, "target_offset": f"0x{off:x}", "count": cnt, "addr": f"0x{addr:x}", "addr2line_function": func, "addr2line_location": loc})
            continue
        enclosing = containing_function(source_root, rel, line_no)
        if exclude_inlined_targets and enclosing and enclosing != sym:
            filtered_inlined.append(
                {
                    "target_symbol": sym,
                    "target_offset": f"0x{off:x}",
                    "count": cnt,
                    "addr": f"0x{addr:x}",
                    "target_src_relpath": str(rel),
                    "target_src_line": line_no,
                    "enclosing_function": enclosing,
                    "addr2line_function": func,
                    "addr2line_location": loc,
                }
            )
            continue
        key = (sym, str(rel), line_no)
        addr_to_key[addr] = key
        line_counts[key] += cnt

    selected_keys = [key for key, _ in line_counts.most_common(max_top_n)]
    selected_set = set(selected_keys)
    key_to_label = {}
    for rank, key in enumerate(selected_keys, start=1):
        sym, rel, line_no = key
        label = make_label(sym, rel, line_no)
        key_to_label[key] = label
        target_rows.append(
            {
                "target_rank": rank,
                "target_symbol": sym,
                "target_src_relpath": rel,
                "target_src_line": line_no,
                "target_label": label,
                "target_count": line_counts[key],
            }
        )
    addr_to_selected_key = {addr: key for addr, key in addr_to_key.items() if key in selected_set}
    return target_rows, key_to_label, addr_to_selected_key, unresolved, filtered_inlined, line_counts


def collect_callsite_counts(lbr_file: Path, depths: list[int], addr_by_dem: dict[str, int], addr_to_target_key: dict[int, tuple], key_to_label: dict, prefer_prefix: str, max_lbr_lines: int = 0):
    max_depth = max(depths)
    depth_set = set(depths)
    counts = Counter()
    target_seen = Counter()
    samples = 0
    accepted = 0
    with lbr_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line_idx, raw in enumerate(f, start=1):
            if max_lbr_lines and line_idx > max_lbr_lines:
                break
            entries = parse_lbr_entries_limited(raw, max_depth)
            if not entries:
                continue
            samples += 1
            e0 = entries[0]
            base = addr_by_dem.get(e0["to_symbol"])
            if base is None:
                continue
            target_key = addr_to_target_key.get(base + e0["to_offset"])
            if target_key is None:
                continue
            accepted += 1
            target_seen[target_key] += 1
            for depth in depth_set:
                idx = depth - 1
                if idx >= len(entries):
                    continue
                e = entries[idx]
                from_sym = e["from_symbol"]
                if from_sym not in addr_by_dem:
                    continue
                if prefer_prefix and not from_sym.startswith(prefer_prefix):
                    continue
                key = (
                    depth,
                    target_key,
                    from_sym,
                    e["from_offset"],
                    e["to_symbol"],
                    e["to_offset"],
                    e["branch_type"],
                )
                counts[key] += 1
    return counts, target_seen, samples, accepted


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

    if args.target_symbol_pool <= 0 or args.target_address_pool <= 0 or args.prefetch_line_size <= 0:
        raise RuntimeError("pool sizes and line size must be positive")
    source_root = base_dir / "generated-src" / cfg_tag / cfg_tag
    if not source_root.is_dir():
        raise RuntimeError(f"missing generated source tree under {base_dir}")
    if not sim_bin.exists():
        raise RuntimeError(f"missing baseline binary: {sim_bin}")

    groups = parse_variant_specs(args.variant_specs)
    all_depths = sorted({d for spec in groups for d in spec["depths"]})
    max_top_n = max(spec["top_n"] for spec in groups)
    max_site_budget = max(spec["site_budget"] for spec in groups)

    lbr_file = trace_dir / "lbr_symbolic_dump.txt"
    target_csv = trace_dir / "target_branch_counts.csv"
    if not lbr_file.exists() or not target_csv.exists():
        raise RuntimeError(f"missing trace inputs under {trace_dir}")

    print(f"[phase] symbol maps from {sim_bin}")
    addr_by_dem, dem_to_mangled = build_symbol_maps(sim_bin)
    symbol_pool = set(load_top_symbol_pool(target_csv, max(args.target_symbol_pool, max_top_n)))
    print(f"[phase] first pass: collect target addresses from {lbr_file}")
    target_addr_counts, total_samples, accepted_samples = count_target_addresses(
        lbr_file, symbol_pool, addr_by_dem, args.target_address_pool, args.max_lbr_lines
    )
    print(f"[inf] lbr_samples={total_samples} accepted_by_symbol_pool={accepted_samples} unique_target_addrs_kept={len(target_addr_counts)}")

    print("[phase] resolve target source lines")
    target_rows, key_to_label, addr_to_target_key, unresolved_targets, filtered_inlined_targets, line_counts = build_target_line_selection(
        target_addr_counts,
        addr_by_dem,
        args.addr2line,
        sim_bin,
        cfg_tag,
        max_top_n,
        source_root,
        args.exclude_inlined_targets,
    )
    if not target_rows:
        raise RuntimeError("no exact target source lines were resolved")
    print(
        f"[inf] selected_exact_targets={len(target_rows)} unresolved_target_addrs={len(unresolved_targets)} "
        f"filtered_inlined_targets={len(filtered_inlined_targets)}"
    )

    print("[phase] second pass: collect callsite candidates")
    candidate_counts, target_seen, second_total, second_accepted = collect_callsite_counts(
        lbr_file, all_depths, addr_by_dem, addr_to_target_key, key_to_label, args.prefer_prefix, args.max_lbr_lines
    )
    print(f"[inf] lbr_samples={second_total} accepted_exact_targets={second_accepted} unique_candidate_keys={len(candidate_counts)}")

    target_rank = {(r["target_symbol"], r["target_src_relpath"], int(r["target_src_line"])): int(r["target_rank"]) for r in target_rows}
    target_by_key = {(r["target_symbol"], r["target_src_relpath"], int(r["target_src_line"])): r for r in target_rows}

    by_depth_target = defaultdict(list)
    candidate_rows = []
    for key, cnt in candidate_counts.items():
        depth, target_key, from_sym, from_off, to_sym, to_off, branch_type = key
        by_depth_target[(depth, target_key)].append((cnt, from_sym, from_off, to_sym, to_off, branch_type))

    selected = []
    coverage_rows = []
    addrs_needed = set()
    selected_target_keys = list(target_rank.keys())
    for depth in all_depths:
        for target_key in selected_target_keys:
            total = int(target_seen.get(target_key, 0))
            ranked = sorted(by_depth_target.get((depth, target_key), []), reverse=True)
            covered = 0
            for rank, item in enumerate(ranked, start=1):
                cnt, from_sym, from_off, to_sym, to_off, branch_type = item
                candidate_rows.append(
                    {
                        "depth": depth,
                        "target_rank": target_rank[target_key],
                        "target_symbol": target_key[0],
                        "target_src_relpath": target_key[1],
                        "target_src_line": target_key[2],
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
                        "target_key": target_key,
                        "target_rank": target_rank[target_key],
                        "target_symbol": target_key[0],
                        "target_src_relpath": target_key[1],
                        "target_src_line": target_key[2],
                        "target_label": key_to_label[target_key],
                        "target_count": target_by_key[target_key]["target_count"],
                        "count": cnt,
                        "target_seen_samples": total,
                        "candidate_rank": rank,
                        "from_symbol": from_sym,
                        "from_offset": from_off,
                        "to_symbol": to_sym,
                        "to_offset": to_off,
                        "branch_type": branch_type,
                        "addr": addr,
                    }
                )
            coverage_rows.append(
                {
                    "site_budget": max_site_budget,
                    "depth": depth,
                    "target_rank": target_rank[target_key],
                    "target_symbol": target_key[0],
                    "target_src_relpath": target_key[1],
                    "target_src_line": target_key[2],
                    "target_seen_samples": total,
                    "covered_samples": covered,
                    "coverage_pct": f"{(100.0 * covered / total) if total else 0.0:.4f}",
                    "selected_site_count": min(len(ranked), max_site_budget),
                }
            )

    print(f"[phase] resolve insertion source lines: {len(addrs_needed)} addresses")
    resolved_insert = resolve_addr2line(args.addr2line, sim_bin, sorted(addrs_needed))
    resolved_rows = []
    usable_by_depth = defaultdict(list)
    unresolved_insertions = []
    for row in selected:
        func, loc = resolved_insert.get(row["addr"], ("", ""))
        rel, line_no = generated_rel_from_loc(loc, cfg_tag)
        out = dict(row)
        out.pop("target_key", None)
        out["addr"] = f"0x{row['addr']:x}"
        out["from_offset"] = f"0x{row['from_offset']:x}"
        out["to_offset"] = f"0x{row['to_offset']:x}"
        out["addr2line_function"] = func
        out["addr2line_location"] = loc
        out["insert_src_relpath"] = str(rel) if rel else ""
        out["insert_src_line"] = line_no
        if rel and line_no > 0:
            usable_by_depth[int(row["depth"])].append((rel, line_no, row))
        else:
            unresolved_insertions.append(out)
        resolved_rows.append(out)

    result_root.mkdir(parents=True, exist_ok=True)
    variant_root.mkdir(parents=True, exist_ok=True)

    write_csv(result_root / "selected_exact_targets.csv", target_rows, ["target_rank", "target_symbol", "target_src_relpath", "target_src_line", "target_label", "target_count"])
    write_csv(result_root / "unresolved_exact_targets.csv", unresolved_targets, ["target_symbol", "target_offset", "count", "addr", "addr2line_function", "addr2line_location"])
    write_csv(
        result_root / "filtered_inlined_targets.csv",
        filtered_inlined_targets,
        [
            "target_symbol",
            "target_offset",
            "count",
            "addr",
            "target_src_relpath",
            "target_src_line",
            "enclosing_function",
            "addr2line_function",
            "addr2line_location",
        ],
    )
    write_csv(result_root / "candidate_rankings.csv", candidate_rows, ["depth", "target_rank", "target_symbol", "target_src_relpath", "target_src_line", "candidate_rank", "count", "from_symbol", "from_offset", "to_symbol", "to_offset", "branch_type"])
    write_csv(result_root / "coverage_by_target.csv", coverage_rows, ["site_budget", "depth", "target_rank", "target_symbol", "target_src_relpath", "target_src_line", "target_seen_samples", "covered_samples", "coverage_pct", "selected_site_count"])
    write_csv(
        result_root / "resolved_callsite_selection.csv",
        resolved_rows,
        [
            "depth", "target_rank", "target_symbol", "target_src_relpath", "target_src_line", "target_label", "target_count",
            "count", "target_seen_samples", "candidate_rank", "from_symbol", "from_offset", "to_symbol", "to_offset", "branch_type",
            "addr", "addr2line_function", "addr2line_location", "insert_src_relpath", "insert_src_line",
        ],
    )
    write_csv(
        result_root / "unresolved_callsite_selection.csv",
        unresolved_insertions,
        [
            "depth", "target_rank", "target_symbol", "target_src_relpath", "target_src_line", "target_label", "target_count",
            "count", "target_seen_samples", "candidate_rank", "from_symbol", "from_offset", "to_symbol", "to_offset", "branch_type",
            "addr", "addr2line_function", "addr2line_location", "insert_src_relpath", "insert_src_line",
        ],
    )

    variant_rows = []
    point_rows = []
    label_rows = []
    count_rows = []
    for spec in groups:
        variant_short = spec["name"]
        depths = spec["depths"]
        top_n = spec["top_n"]
        site_budget = spec["site_budget"]
        kind = spec["prefetch_kind"]
        lines = spec["prefetch_lines"]
        variant_name = f"{args.variant_name_prefix}{variant_short}"
        variant_dir = variant_root / variant_name
        print(f"[phase] copy variant tree {variant_name}")
        copy_tree(base_dir, variant_dir, args.copy_tool)

        seen = set()
        variant_points = []
        variant_label_keys = set()
        for depth in depths:
            for rel, line_no, row in usable_by_depth.get(depth, []):
                if int(row.get("target_rank", 0)) > top_n:
                    continue
                if int(row.get("candidate_rank", 0)) > site_budget:
                    continue
                key = (str(rel), line_no, row["target_symbol"], row["target_src_relpath"], row["target_src_line"], row["from_symbol"], row["from_offset"], depth)
                if key in seen:
                    continue
                seen.add(key)
                variant_points.append((rel, line_no, row))
                variant_label_keys.add(row["target_key"])

        for rel, line_no, row in variant_points:
            point_rows.append(
                {
                    "variant": variant_name,
                    "variant_short": variant_short,
                    "target_rank": row["target_rank"],
                    "depth": row["depth"],
                    "target_symbol": row["target_symbol"],
                    "target_src_relpath": row["target_src_relpath"],
                    "target_src_line": row["target_src_line"],
                    "target_label": row["target_label"],
                    "target_count": row["target_count"],
                    "candidate_rank": row["candidate_rank"],
                    "count": row["count"],
                    "from_symbol": row["from_symbol"],
                    "from_offset": f"0x{row['from_offset']:x}",
                    "to_symbol": row["to_symbol"],
                    "to_offset": f"0x{row['to_offset']:x}",
                    "branch_type": row["branch_type"],
                    "insert_src_relpath": str(rel),
                    "insert_src_line": line_no,
                    "prefetch_kind": kind,
                    "prefetch_lines": lines,
                    "prefetch_line_size": args.prefetch_line_size,
                }
            )

        for key in sorted(variant_label_keys, key=lambda k: target_rank[k]):
            tr = target_by_key[key]
            label_rows.append(
                {
                    "variant": variant_name,
                    "variant_short": variant_short,
                    "target_rank": tr["target_rank"],
                    "target_symbol": tr["target_symbol"],
                    "target_src_relpath": tr["target_src_relpath"],
                    "target_src_line": tr["target_src_line"],
                    "target_label": tr["target_label"],
                    "target_count": tr["target_count"],
                }
            )

        mnemonic_multiplier = 2 if kind == "both" else 1
        inserted_prefetch = len(variant_points) * lines * mnemonic_multiplier
        variant_rows.append(
            {
                "variant": variant_name,
                "variant_short": variant_short,
                "top_n": top_n,
                "site_budget": site_budget,
                "depths": "|".join(str(d) for d in depths),
                "prefetch_kind": kind,
                "prefetch_lines": lines,
                "prefetch_line_size": args.prefetch_line_size,
                "target_label_count": len(variant_label_keys),
                "injection_site_count": len(variant_points),
                "inserted_prefetch_instructions": inserted_prefetch,
            }
        )
        count_rows.append(
            {
                "variant_short": variant_short,
                "top_n": top_n,
                "site_budget": site_budget,
                "depth": "|".join(str(d) for d in depths),
                "prefetch_kind": kind,
                "prefetch_lines": lines,
                "target_label_count": len(variant_label_keys),
                "unique_inject_functions": len({r["from_symbol"] for _, _, r in variant_points}),
                "unique_source_lines": len({(str(rel), line_no) for rel, line_no, _ in variant_points}),
                "injection_site_count": len(variant_points),
                "inserted_prefetch_instructions": inserted_prefetch,
            }
        )

    write_csv(result_root / "variant_dirs.csv", variant_rows, ["variant", "variant_short", "top_n", "site_budget", "depths", "prefetch_kind", "prefetch_lines", "prefetch_line_size", "target_label_count", "injection_site_count", "inserted_prefetch_instructions"])
    write_csv(result_root / "injection_counts_by_depth.csv", count_rows, ["variant_short", "top_n", "site_budget", "depth", "prefetch_kind", "prefetch_lines", "target_label_count", "unique_inject_functions", "unique_source_lines", "injection_site_count", "inserted_prefetch_instructions"])
    write_csv(result_root / "target_labels.csv", label_rows, ["variant", "variant_short", "target_rank", "target_symbol", "target_src_relpath", "target_src_line", "target_label", "target_count"])
    write_csv(result_root / "injection_points_by_depth.csv", point_rows, ["variant", "variant_short", "target_rank", "depth", "target_symbol", "target_src_relpath", "target_src_line", "target_label", "target_count", "candidate_rank", "count", "from_symbol", "from_offset", "to_symbol", "to_offset", "branch_type", "insert_src_relpath", "insert_src_line", "prefetch_kind", "prefetch_lines", "prefetch_line_size"])

    with (result_root / "injection_summary.md").open("w", encoding="utf-8") as f:
        f.write("# Exact Target Prefetch Variants\n\n")
        f.write("- Target: label inserted at resolved `LBR[0].to` source line.\n")
        f.write("- Placement: before source line mapped from `LBR[depth].from`.\n")
        f.write("- Prefetch target operand: `__pf_target_<hash> + N*line_size(%rip)`.\n\n")
        f.write(f"- total_lbr_samples_first_pass: {total_samples}\n")
        f.write(f"- accepted_by_top_symbol_pool: {accepted_samples}\n")
        f.write(f"- exact_targets_selected: {len(target_rows)}\n")
        f.write(f"- filtered_inlined_targets: {len(filtered_inlined_targets)}\n")
        f.write(f"- candidate_samples_second_pass: {second_accepted}\n\n")
        f.write("| Variant | Kind | Lines | Top Targets | Site Budget | Depths | Labels | Sites | Prefetch Instrs |\n")
        f.write("|---|---|---:|---:|---:|---|---:|---:|---:|\n")
        for row in variant_rows:
            f.write(
                f"| {row['variant']} | {row['prefetch_kind']} | {row['prefetch_lines']} | {row['top_n']} | {row['site_budget']} | "
                f"{str(row['depths']).replace('|', ',')} | {row['target_label_count']} | {row['injection_site_count']} | {row['inserted_prefetch_instructions']} |\n"
            )

    print(f"[ok] result_root={result_root}")
    print(f"[ok] variant_root={variant_root}")
    for row in variant_rows:
        print(
            "[variant] "
            f"{row['variant_short']} kind={row['prefetch_kind']} lines={row['prefetch_lines']} "
            f"depths={row['depths']} labels={row['target_label_count']} "
            f"sites={row['injection_site_count']} prefetch_instr={row['inserted_prefetch_instructions']}"
        )
    if unresolved_targets:
        print(f"[warn] unresolved target addresses: {len(unresolved_targets)}")
    if unresolved_insertions:
        print(f"[warn] unresolved insertion addresses: {len(unresolved_insertions)}")


if __name__ == "__main__":
    main()
