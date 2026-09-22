#!/usr/bin/env python3
import argparse
import csv
import hashlib
import importlib.util
import re
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


LABEL_PREFIX = "__pf_target_"
PREFETCH_KIND = "dt0"
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]


def parse_args():
    ap = argparse.ArgumentParser(
        description=(
            "Prepare dt-only high-coverage prefetch variants. Resolved in-function "
            "targets receive source labels; line-0/unresolved/inlined targets are kept "
            "as direct function+offset operands with a static same-function shift estimate."
        )
    )
    ap.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    ap.add_argument("--base-verilator-dir", required=True)
    ap.add_argument("--baseline-bin", required=True)
    ap.add_argument("--config", default="DualMegaBoomAndSingleRocketConfig")
    ap.add_argument("--trace-dir", required=True)
    ap.add_argument("--variant-root", required=True)
    ap.add_argument("--result-root", required=True)
    ap.add_argument("--variant-name-prefix", default="verilator_pf_dtcov_")
    ap.add_argument(
        "--variant-specs",
        required=True,
        help=(
            "Semicolon list name:top_n:site_budget:depths:site_mode:lines. "
            "site_mode=all|same|cross. Example: k500_all:500:2:4-16:all:1"
        ),
    )
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    ap.add_argument("--copy-tool", default="rsync", choices=["rsync", "cp"])
    ap.add_argument("--target-symbol-pool", type=int, default=400)
    ap.add_argument("--target-address-pool", type=int, default=100000)
    ap.add_argument("--prefer-prefix", default="VTestDriver___024root___")
    ap.add_argument("--same-min-lead", type=int, default=256)
    ap.add_argument("--same-max-lead", type=int, default=4096)
    ap.add_argument("--prefetch-line-size", type=int, default=64)
    ap.add_argument("--prefetch-instr-len", type=int, default=7)
    ap.add_argument(
        "--target-operand-mode",
        choices=["label", "offset"],
        default="label",
        help=(
            "label keeps the older source-label target for resolved lines. "
            "offset uses profiled PC offsets for every target and adjusts them "
            "for prefetch instructions inserted earlier in the same function."
        ),
    )
    ap.add_argument("--coverage-top-list", default="10,30,50,100,200,300,400,500")
    ap.add_argument("--max-lbr-lines", type=int, default=0)
    return ap.parse_args()


def load_prepare_module(repo_root: Path):
    path = repo_root / "profiling/runscript/build/prepare_prefetch_exact_variants.py"
    spec = importlib.util.spec_from_file_location("prepare_prefetch_exact_variants", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_depth_list(raw: str):
    depths = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
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
        if len(parts) != 6:
            raise RuntimeError(f"bad variant spec: {item}")
        name, top_s, budget_s, depths_raw, mode, lines_s = parts
        mode = mode.strip().lower()
        if mode not in {"all", "same", "cross"}:
            raise RuntimeError(f"bad site mode: {mode}")
        top_n = int(top_s)
        budget = int(budget_s)
        lines = int(lines_s)
        if not name or top_n <= 0 or budget <= 0 or lines <= 0:
            raise RuntimeError(f"bad variant spec: {item}")
        specs.append(
            {
                "name": name.strip(),
                "top_n": top_n,
                "site_budget": budget,
                "depths": parse_depth_list(depths_raw),
                "site_mode": mode,
                "prefetch_lines": lines,
            }
        )
    if not specs:
        raise RuntimeError("no variant specs")
    return specs


def parse_top_list(raw: str):
    out = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            out.append(int(part))
    return sorted({x for x in out if x > 0})


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def copy_tree(src: Path, dst: Path, tool: str):
    if tool == "rsync" and shutil.which("rsync"):
        dst.mkdir(parents=True, exist_ok=True)
        subprocess.run(["rsync", "-a", "--delete", f"{src}/", f"{dst}/"], check=True)
    else:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)


def make_label(target_id: str):
    h = hashlib.sha1(target_id.encode("utf-8")).hexdigest()[:16]
    return f"{LABEL_PREFIX}{h}"


def target_id_line(sym: str, rel: str, line: int):
    return f"line|{sym}|{rel}|{line}"


def target_id_offset(sym: str, off: int):
    return f"offset|{sym}|0x{off:x}"


def format_symbol_operand(raw_symbol: str, off: int):
    if off == 0:
        return raw_symbol
    return f"{raw_symbol}+0x{off:x}"


def classify_lead(distance: int | None):
    if distance is None:
        return "cross_function"
    if distance < 0:
        return "negative"
    if distance < 64:
        return "0_63B"
    if distance < 256:
        return "64_255B"
    if distance < 1024:
        return "256B_1K"
    if distance < 4096:
        return "1K_4K"
    if distance < 65536:
        return "4K_64K"
    return "64K_plus"


def target_reason(rel: Path | None, line_no: int, enclosing: str, sym: str, loc: str):
    if not rel or line_no <= 0:
        if loc and loc.endswith(":0"):
            return "line0"
        return "unresolved_or_external"
    if enclosing and enclosing != sym:
        return "inlined_or_different_enclosing_function"
    return "resolved_line"


def build_targets(
    prep,
    target_addr_counts: Counter,
    addr_by_dem: dict[str, int],
    dem_to_mangled: dict[str, str],
    addr2line_bin: str,
    sim_bin: Path,
    cfg_tag: str,
    source_root: Path,
    max_top_n: int,
):
    addr_meta = {}
    addrs = []
    for (sym, off), cnt in target_addr_counts.items():
        base = addr_by_dem.get(sym)
        if base is None:
            continue
        addr = base + off
        addr_meta[addr] = (sym, off, cnt)
        addrs.append(addr)

    resolved = prep.resolve_addr2line(addr2line_bin, sim_bin, sorted(set(addrs)))

    grouped = {}
    addr_to_id_all = {}
    debug_rows = []

    for addr in sorted(set(addrs)):
        sym, off, cnt = addr_meta[addr]
        func, loc = resolved.get(addr, ("", ""))
        rel, line_no = prep.generated_rel_from_loc(loc, cfg_tag)
        enclosing = prep.containing_function(source_root, rel, line_no) if rel and line_no > 0 else ""
        reason = target_reason(rel, line_no, enclosing, sym, loc)

        if reason == "resolved_line":
            tid = target_id_line(sym, str(rel), line_no)
            kind = "line"
            rel_s = str(rel)
            line_s = line_no
        else:
            tid = target_id_offset(sym, off)
            kind = "offset"
            rel_s = str(rel) if rel else ""
            line_s = line_no if line_no > 0 else 0

        if tid not in grouped:
            raw_symbol = dem_to_mangled.get(sym, sym)
            grouped[tid] = {
                "target_id": tid,
                "target_kind": kind,
                "target_symbol": sym,
                "target_raw_symbol": raw_symbol,
                "target_src_relpath": rel_s,
                "target_src_line": line_s,
                "target_reason": reason,
                "addr2line_function": func,
                "addr2line_location": loc,
                "enclosing_function": enclosing,
                "offset_counts": Counter(),
            }
        grouped[tid]["offset_counts"][off] += cnt
        addr_to_id_all[addr] = tid
        debug_rows.append(
            {
                "target_id": tid,
                "target_kind": kind,
                "target_symbol": sym,
                "target_offset": f"0x{off:x}",
                "count": cnt,
                "target_src_relpath": rel_s,
                "target_src_line": line_s,
                "target_reason": reason,
                "addr2line_function": func,
                "addr2line_location": loc,
                "enclosing_function": enclosing,
            }
        )

    target_rows = []
    target_by_id = {}
    for tid, meta in grouped.items():
        counts = meta.pop("offset_counts")
        total = sum(counts.values())
        primary_off = counts.most_common(1)[0][0]
        offsets = sorted(counts)
        label = make_label(tid) if meta["target_kind"] == "line" else ""
        row = {
            **meta,
            "target_rank": 0,
            "target_label": label,
            "target_count": total,
            "target_primary_offset": primary_off,
            "target_min_offset": offsets[0],
            "target_max_offset": offsets[-1],
            "unique_target_pcs": len(counts),
            "top_offsets": ";".join(f"0x{o:x}:{c}" for o, c in counts.most_common(8)),
        }
        target_rows.append(row)
        target_by_id[tid] = row

    target_rows.sort(key=lambda r: int(r["target_count"]), reverse=True)
    selected = target_rows[:max_top_n]
    selected_ids = {r["target_id"] for r in selected}
    for rank, row in enumerate(selected, start=1):
        row["target_rank"] = rank

    addr_to_selected_id = {
        addr: tid
        for addr, tid in addr_to_id_all.items()
        if tid in selected_ids
    }
    target_by_id = {r["target_id"]: r for r in selected}
    return selected, target_by_id, addr_to_selected_id, debug_rows


def collect_candidate_counts(prep, lbr_file: Path, depths: list[int], addr_by_dem: dict[str, int], addr_to_target_id: dict[int, str], prefer_prefix: str, max_lbr_lines: int):
    max_depth = max(depths)
    depth_set = set(depths)
    counts = Counter()
    target_seen = Counter()
    total = 0
    accepted = 0
    with lbr_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line_idx, raw in enumerate(f, start=1):
            if max_lbr_lines and line_idx > max_lbr_lines:
                break
            entries = prep.parse_lbr_entries_limited(raw, max_depth)
            if not entries:
                continue
            total += 1
            e0 = entries[0]
            base = addr_by_dem.get(e0["to_symbol"])
            if base is None:
                continue
            target_id = addr_to_target_id.get(base + e0["to_offset"])
            if not target_id:
                continue
            accepted += 1
            target_seen[target_id] += 1
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
                    target_id,
                    from_sym,
                    e["from_offset"],
                    e["to_symbol"],
                    e["to_offset"],
                    e["branch_type"],
                )
                counts[key] += 1
    return counts, target_seen, total, accepted


def resolve_candidates(prep, candidate_counts: Counter, target_by_id: dict, addr_by_dem: dict[str, int], addr2line_bin: str, sim_bin: Path, cfg_tag: str):
    addrs = set()
    for depth, target_id, from_sym, from_off, _to_sym, _to_off, _bt in candidate_counts:
        addrs.add(addr_by_dem[from_sym] + from_off)
    resolved = prep.resolve_addr2line(addr2line_bin, sim_bin, sorted(addrs))

    rows = []
    unresolved = []
    for key, cnt in candidate_counts.items():
        depth, target_id, from_sym, from_off, to_sym, to_off, branch_type = key
        target = target_by_id[target_id]
        addr = addr_by_dem[from_sym] + from_off
        func, loc = resolved.get(addr, ("", ""))
        rel, line_no = prep.generated_rel_from_loc(loc, cfg_tag)
        site_class = "same_function" if from_sym == target["target_symbol"] else "cross_function"
        lead = ""
        lead_bucket = "cross_function"
        if site_class == "same_function":
            lead_i = int(target["target_primary_offset"]) - int(from_off)
            lead = lead_i
            lead_bucket = classify_lead(lead_i)

        row = {
            "depth": depth,
            "target_id": target_id,
            "target_rank": target["target_rank"],
            "target_kind": target["target_kind"],
            "target_symbol": target["target_symbol"],
            "target_raw_symbol": target["target_raw_symbol"],
            "target_src_relpath": target["target_src_relpath"],
            "target_src_line": target["target_src_line"],
            "target_label": target["target_label"],
            "target_reason": target["target_reason"],
            "target_count": target["target_count"],
            "target_primary_offset": target["target_primary_offset"],
            "count": cnt,
            "from_symbol": from_sym,
            "from_offset": from_off,
            "to_symbol": to_sym,
            "to_offset": to_off,
            "branch_type": branch_type,
            "site_class": site_class,
            "lead_bytes": lead,
            "lead_bucket": lead_bucket,
            "addr": addr,
            "addr2line_function": func,
            "addr2line_location": loc,
            "insert_src_relpath": str(rel) if rel else "",
            "insert_src_line": line_no,
        }
        if not rel or line_no <= 0:
            unresolved.append(dict(row))
        rows.append(row)
    return rows, unresolved


def candidate_passes_spec(row: dict, spec: dict, same_min: int, same_max: int):
    mode = spec["site_mode"]
    if mode == "cross":
        return row["site_class"] == "cross_function"
    if row["site_class"] == "same_function":
        lead = row["lead_bytes"]
        return isinstance(lead, int) and same_min <= lead <= same_max
    return mode == "all"


def build_variant_points(candidate_rows: list[dict], target_by_id: dict, specs: list[dict], args):
    by_depth_target = defaultdict(list)
    for row in candidate_rows:
        if not row["insert_src_relpath"] or int(row["insert_src_line"] or 0) <= 0:
            continue
        by_depth_target[(int(row["depth"]), row["target_id"])].append(row)

    point_rows = []
    label_rows = []
    variant_rows = []
    count_rows = []
    coverage_rows = []

    for spec in specs:
        variant_short = spec["name"]
        depths = spec["depths"]
        top_n = spec["top_n"]
        site_budget = spec["site_budget"]
        lines = spec["prefetch_lines"]
        variant_name = f"{args.variant_name_prefix}{variant_short}"

        selected_points = []
        labels = set()
        seen = set()
        for depth in depths:
            for target_id, target in sorted(target_by_id.items(), key=lambda kv: int(kv[1]["target_rank"])):
                if int(target["target_rank"]) > top_n:
                    continue
                candidates = [
                    r
                    for r in by_depth_target.get((depth, target_id), [])
                    if candidate_passes_spec(r, spec, args.same_min_lead, args.same_max_lead)
                ]
                candidates.sort(key=lambda r: int(r["count"]), reverse=True)
                covered = 0
                for selected_rank, row in enumerate(candidates[:site_budget], start=1):
                    key = (
                        row["insert_src_relpath"],
                        int(row["insert_src_line"]),
                        row["target_id"],
                        row["from_symbol"],
                        int(row["from_offset"]),
                        depth,
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    out = dict(row)
                    out["selected_site_rank"] = selected_rank
                    selected_points.append(out)
                    covered += int(row["count"])
                    if args.target_operand_mode == "label" and row["target_kind"] == "line":
                        labels.add(row["target_id"])
                coverage_rows.append(
                    {
                        "variant_short": variant_short,
                        "site_mode": spec["site_mode"],
                        "site_budget": site_budget,
                        "depth": depth,
                        "target_rank": target["target_rank"],
                        "target_id": target_id,
                        "target_kind": target["target_kind"],
                        "target_symbol": target["target_symbol"],
                        "target_count": target["target_count"],
                        "selected_site_count": min(len(candidates), site_budget),
                        "selected_site_count_after_dedup": len([r for r in selected_points if r["depth"] == depth and r["target_id"] == target_id]),
                        "covered_candidate_weight": covered,
                    }
                )

        # Estimate direct symbol+offset target drift from prefetch instructions
        # emitted earlier in the same function. Source labels do not need this,
        # but PC-offset mode applies it to every target so the operand follows
        # the profiled miss PC after source-level asm insertion grows .text.
        shift_by_target = Counter()
        for row in selected_points:
            emit_count = int(lines)
            for target_id, target in target_by_id.items():
                if args.target_operand_mode == "label" and target["target_kind"] != "offset":
                    continue
                if row["from_symbol"] != target["target_symbol"]:
                    continue
                if int(row["from_offset"]) < int(target["target_primary_offset"]):
                    shift_by_target[target_id] += emit_count * int(args.prefetch_instr_len)

        for row in selected_points:
            target = target_by_id[row["target_id"]]
            target_shift = int(shift_by_target.get(row["target_id"], 0))
            if args.target_operand_mode == "label" and target["target_kind"] == "line":
                operand_type = "label"
                operand = target["target_label"]
                adjusted_offset = ""
            else:
                operand_type = "symbol_offset"
                adjusted = int(target["target_primary_offset"]) + target_shift
                adjusted_offset = f"0x{adjusted:x}"
                operand = format_symbol_operand(target["target_raw_symbol"], adjusted)

            point_rows.append(
                {
                    "variant": variant_name,
                    "variant_short": variant_short,
                    "target_rank": target["target_rank"],
                    "depth": row["depth"],
                    "target_id": row["target_id"],
                    "target_kind": target["target_kind"],
                    "target_symbol": target["target_symbol"],
                    "target_raw_symbol": target["target_raw_symbol"],
                    "target_src_relpath": target["target_src_relpath"],
                    "target_src_line": target["target_src_line"],
                    "target_label": target["target_label"],
                    "target_operand_type": operand_type,
                    "target_operand": operand,
                    "target_primary_offset": f"0x{int(target['target_primary_offset']):x}",
                    "target_adjusted_offset": adjusted_offset,
                    "target_shift_bytes_est": target_shift,
                    "target_reason": target["target_reason"],
                    "target_count": target["target_count"],
                    "selected_site_rank": row["selected_site_rank"],
                    "count": row["count"],
                    "from_symbol": row["from_symbol"],
                    "from_offset": f"0x{int(row['from_offset']):x}",
                    "to_symbol": row["to_symbol"],
                    "to_offset": f"0x{int(row['to_offset']):x}",
                    "branch_type": row["branch_type"],
                    "site_class": row["site_class"],
                    "lead_bytes": row["lead_bytes"],
                    "lead_bucket": row["lead_bucket"],
                    "insert_src_relpath": row["insert_src_relpath"],
                    "insert_src_line": row["insert_src_line"],
                    "prefetch_kind": PREFETCH_KIND,
                    "prefetch_lines": lines,
                    "prefetch_line_size": args.prefetch_line_size,
                }
            )

        for target_id in sorted(labels, key=lambda tid: int(target_by_id[tid]["target_rank"])):
            target = target_by_id[target_id]
            label_rows.append(
                {
                    "variant": variant_name,
                    "variant_short": variant_short,
                    "target_rank": target["target_rank"],
                    "target_id": target_id,
                    "target_kind": target["target_kind"],
                    "target_symbol": target["target_symbol"],
                    "target_src_relpath": target["target_src_relpath"],
                    "target_src_line": target["target_src_line"],
                    "target_label": target["target_label"],
                    "target_operand_type": "label",
                    "target_operand": target["target_label"],
                    "target_count": target["target_count"],
                }
            )

        target_ids_used = {r["target_id"] for r in selected_points}
        line_target_count = sum(1 for tid in target_ids_used if target_by_id[tid]["target_kind"] == "line")
        offset_target_count = sum(1 for tid in target_ids_used if target_by_id[tid]["target_kind"] == "offset")
        selected_sample_count = sum(int(t["target_count"]) for t in target_by_id.values() if int(t["target_rank"]) <= top_n)
        variant_rows.append(
            {
                "variant": variant_name,
                "variant_short": variant_short,
                "top_n": top_n,
                "site_budget": site_budget,
                "site_mode": spec["site_mode"],
                "depths": "|".join(str(d) for d in depths),
                "prefetch_kind": PREFETCH_KIND,
                "prefetch_lines": lines,
                "prefetch_line_size": args.prefetch_line_size,
                "target_count_selected_by_rank": top_n,
                "target_count_used_by_sites": len(target_ids_used),
                "line_target_count_used": line_target_count,
                "offset_target_count_used": offset_target_count,
                "selected_target_samples": selected_sample_count,
                "injection_site_count": len(selected_points),
                "inserted_prefetch_instructions": len(selected_points) * lines,
            }
        )
        count_rows.append(
            {
                "variant_short": variant_short,
                "top_n": top_n,
                "site_budget": site_budget,
                "site_mode": spec["site_mode"],
                "depth": "|".join(str(d) for d in depths),
                "prefetch_kind": PREFETCH_KIND,
                "prefetch_lines": lines,
                "target_count_used_by_sites": len(target_ids_used),
                "line_target_count_used": line_target_count,
                "offset_target_count_used": offset_target_count,
                "unique_inject_functions": len({r["from_symbol"] for r in selected_points}),
                "unique_source_lines": len({(r["insert_src_relpath"], r["insert_src_line"]) for r in selected_points}),
                "injection_site_count": len(selected_points),
                "inserted_prefetch_instructions": len(selected_points) * lines,
            }
        )

    return variant_rows, point_rows, label_rows, count_rows, coverage_rows


def compute_true_coverage(prep, lbr_file: Path, addr_by_dem: dict, addr_to_target_id: dict, point_rows: list[dict], variant_rows: list[dict], max_lbr_lines: int):
    site_index = defaultdict(set)
    target_to_variants = defaultdict(set)
    max_depth = 1
    for row in point_rows:
        depth = int(row["depth"])
        max_depth = max(max_depth, depth)
        target_id = row["target_id"]
        variant = row["variant_short"]
        target_to_variants[target_id].add(variant)
        key = (
            depth,
            target_id,
            row["from_symbol"],
            int(row["from_offset"], 16),
            row["to_symbol"],
            int(row["to_offset"], 16),
            row["branch_type"],
        )
        site_index[key].add(variant)

    total = 0
    selected = Counter()
    covered = Counter()
    instances = Counter()
    with lbr_file.open("r", encoding="utf-8", errors="ignore") as f:
        for line_idx, raw in enumerate(f, start=1):
            if max_lbr_lines and line_idx > max_lbr_lines:
                break
            entries = prep.parse_lbr_entries_limited(raw, max_depth)
            if not entries:
                continue
            total += 1
            e0 = entries[0]
            base = addr_by_dem.get(e0["to_symbol"])
            if base is None:
                continue
            target_id = addr_to_target_id.get(base + e0["to_offset"])
            if target_id is None:
                continue
            variants = target_to_variants.get(target_id, set())
            for v in variants:
                selected[v] += 1
            hit = set()
            for idx, e in enumerate(entries, start=1):
                key = (
                    idx,
                    target_id,
                    e["from_symbol"],
                    e["from_offset"],
                    e["to_symbol"],
                    e["to_offset"],
                    e["branch_type"],
                )
                for v in site_index.get(key, set()):
                    hit.add(v)
                    instances[v] += 1
            for v in hit:
                covered[v] += 1

    rows = []
    for row in variant_rows:
        v = row["variant_short"]
        sel = selected[v]
        cov = covered[v]
        rows.append(
            {
                "variant_short": v,
                "total_lbr_samples": total,
                "selected_target_samples": sel,
                "covered_selected_samples_once": cov,
                "matched_site_instances": instances[v],
                "selected_target_pct_of_all_l2_samples": f"{(100.0 * sel / total) if total else 0.0:.4f}",
                "covered_pct_of_all_l2_samples": f"{(100.0 * cov / total) if total else 0.0:.4f}",
                "covered_pct_of_selected_target_samples": f"{(100.0 * cov / sel) if sel else 0.0:.4f}",
                "avg_matched_sites_per_selected_sample": f"{(instances[v] / sel) if sel else 0.0:.4f}",
            }
        )
    return rows


def main():
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    prep = load_prepare_module(repo_root)
    base_dir = Path(args.base_verilator_dir).resolve()
    sim_bin = Path(args.baseline_bin).resolve()
    trace_dir = Path(args.trace_dir).resolve()
    lbr_file = trace_dir / "lbr_symbolic_dump.txt"
    target_csv = trace_dir / "target_branch_counts.csv"
    variant_root = Path(args.variant_root).resolve()
    result_root = Path(args.result_root).resolve()
    cfg_tag = f"chipyard.harness.TestHarness.{args.config}"
    source_root = base_dir / "generated-src" / cfg_tag / cfg_tag

    if not source_root.is_dir():
        raise RuntimeError(f"missing generated source tree: {source_root}")
    if not lbr_file.is_file() or not target_csv.is_file():
        raise RuntimeError(f"missing trace inputs under {trace_dir}")

    specs = parse_variant_specs(args.variant_specs)
    top_list = parse_top_list(args.coverage_top_list)
    max_top_n = max([s["top_n"] for s in specs] + top_list)
    all_depths = sorted({d for spec in specs for d in spec["depths"]})

    print(f"[phase] symbol maps from {sim_bin}")
    addr_by_dem, dem_to_mangled = prep.build_symbol_maps(sim_bin)
    symbol_pool = set(prep.load_top_symbol_pool(target_csv, max(args.target_symbol_pool, max_top_n)))

    print(f"[phase] collect target addresses from {lbr_file}")
    target_addr_counts, total_samples, accepted_samples = prep.count_target_addresses(
        lbr_file,
        symbol_pool,
        addr_by_dem,
        args.target_address_pool,
        args.max_lbr_lines,
    )
    print(f"[inf] lbr_samples={total_samples} accepted_by_symbol_pool={accepted_samples} unique_target_addrs={len(target_addr_counts)}")

    print("[phase] build selected targets, keeping line0/unresolved as offset targets")
    target_rows, target_by_id, addr_to_target_id, debug_target_rows = build_targets(
        prep,
        target_addr_counts,
        addr_by_dem,
        dem_to_mangled,
        args.addr2line,
        sim_bin,
        cfg_tag,
        source_root,
        max_top_n,
    )
    selected_ids = set(target_by_id)
    addr_to_selected_id = {addr: tid for addr, tid in addr_to_target_id.items() if tid in selected_ids}
    selected_total = sum(int(r["target_count"]) for r in target_rows[:max_top_n])
    print(f"[inf] selected_targets={len(target_rows)} selected_samples={selected_total} ({(100.0 * selected_total / total_samples) if total_samples else 0.0:.2f}% of all)")

    print("[phase] collect LBR callsite candidates")
    candidate_counts, target_seen, second_total, second_accepted = collect_candidate_counts(
        prep,
        lbr_file,
        all_depths,
        addr_by_dem,
        addr_to_selected_id,
        args.prefer_prefix,
        args.max_lbr_lines,
    )
    print(f"[inf] lbr_samples={second_total} accepted_selected_targets={second_accepted} unique_candidate_keys={len(candidate_counts)}")

    print("[phase] resolve candidate insertion source lines")
    candidate_rows, unresolved_insertions = resolve_candidates(
        prep,
        candidate_counts,
        target_by_id,
        addr_by_dem,
        args.addr2line,
        sim_bin,
        cfg_tag,
    )

    print("[phase] build variant point tables")
    variant_rows, point_rows, label_rows, count_rows, coverage_rows = build_variant_points(candidate_rows, target_by_id, specs, args)

    print("[phase] true sample-level coverage")
    true_cov_rows = compute_true_coverage(prep, lbr_file, addr_by_dem, addr_to_selected_id, point_rows, variant_rows, args.max_lbr_lines)

    result_root.mkdir(parents=True, exist_ok=True)
    variant_root.mkdir(parents=True, exist_ok=True)

    # Copy variant source trees last, after metadata generation has succeeded.
    for row in variant_rows:
        variant_dir = variant_root / row["variant"]
        print(f"[phase] copy variant tree {row['variant']}")
        copy_tree(base_dir, variant_dir, args.copy_tool)

    selected_target_rows = []
    for row in target_rows:
        selected_target_rows.append(
            {
                "target_rank": row["target_rank"],
                "target_id": row["target_id"],
                "target_kind": row["target_kind"],
                "target_symbol": row["target_symbol"],
                "target_raw_symbol": row["target_raw_symbol"],
                "target_src_relpath": row["target_src_relpath"],
                "target_src_line": row["target_src_line"],
                "target_label": row["target_label"],
                "target_reason": row["target_reason"],
                "target_count": row["target_count"],
                "target_primary_offset": f"0x{int(row['target_primary_offset']):x}",
                "target_min_offset": f"0x{int(row['target_min_offset']):x}",
                "target_max_offset": f"0x{int(row['target_max_offset']):x}",
                "unique_target_pcs": row["unique_target_pcs"],
                "top_offsets": row["top_offsets"],
            }
        )

    cumulative_rows = []
    counts = [int(r["target_count"]) for r in target_rows]
    for n in top_list:
        s = sum(counts[: min(n, len(counts))])
        cumulative_rows.append(
            {
                "top_n": n,
                "samples": s,
                "pct_of_all_l2_samples": f"{(100.0 * s / total_samples) if total_samples else 0.0:.4f}",
                "pct_of_accepted_symbol_pool": f"{(100.0 * s / accepted_samples) if accepted_samples else 0.0:.4f}",
            }
        )

    write_csv(
        result_root / "selected_dtcov_targets.csv",
        selected_target_rows,
        [
            "target_rank", "target_id", "target_kind", "target_symbol", "target_raw_symbol",
            "target_src_relpath", "target_src_line", "target_label", "target_reason",
            "target_count", "target_primary_offset", "target_min_offset", "target_max_offset",
            "unique_target_pcs", "top_offsets",
        ],
    )
    write_csv(
        result_root / "target_address_resolution_debug.csv",
        debug_target_rows,
        [
            "target_id", "target_kind", "target_symbol", "target_offset", "count",
            "target_src_relpath", "target_src_line", "target_reason",
            "addr2line_function", "addr2line_location", "enclosing_function",
        ],
    )
    write_csv(
        result_root / "target_cumulative_coverage.csv",
        cumulative_rows,
        ["top_n", "samples", "pct_of_all_l2_samples", "pct_of_accepted_symbol_pool"],
    )
    write_csv(
        result_root / "resolved_callsite_selection.csv",
        [
            {
                **r,
                "from_offset": f"0x{int(r['from_offset']):x}",
                "to_offset": f"0x{int(r['to_offset']):x}",
                "addr": f"0x{int(r['addr']):x}",
                "target_primary_offset": f"0x{int(r['target_primary_offset']):x}",
            }
            for r in candidate_rows
        ],
        [
            "depth", "target_id", "target_rank", "target_kind", "target_symbol", "target_raw_symbol",
            "target_src_relpath", "target_src_line", "target_label", "target_reason",
            "target_count", "target_primary_offset", "count", "from_symbol", "from_offset",
            "to_symbol", "to_offset", "branch_type", "site_class", "lead_bytes", "lead_bucket",
            "addr", "addr2line_function", "addr2line_location", "insert_src_relpath", "insert_src_line",
        ],
    )
    write_csv(
        result_root / "unresolved_callsite_selection.csv",
        [
            {
                **r,
                "from_offset": f"0x{int(r['from_offset']):x}",
                "to_offset": f"0x{int(r['to_offset']):x}",
                "addr": f"0x{int(r['addr']):x}",
                "target_primary_offset": f"0x{int(r['target_primary_offset']):x}",
            }
            for r in unresolved_insertions
        ],
        [
            "depth", "target_id", "target_rank", "target_kind", "target_symbol", "target_raw_symbol",
            "target_src_relpath", "target_src_line", "target_label", "target_reason",
            "target_count", "target_primary_offset", "count", "from_symbol", "from_offset",
            "to_symbol", "to_offset", "branch_type", "site_class", "lead_bytes", "lead_bucket",
            "addr", "addr2line_function", "addr2line_location", "insert_src_relpath", "insert_src_line",
        ],
    )

    write_csv(
        result_root / "variant_dirs.csv",
        variant_rows,
        [
            "variant", "variant_short", "top_n", "site_budget", "site_mode", "depths",
            "prefetch_kind", "prefetch_lines", "prefetch_line_size", "target_count_selected_by_rank",
            "target_count_used_by_sites", "line_target_count_used", "offset_target_count_used",
            "selected_target_samples", "injection_site_count", "inserted_prefetch_instructions",
        ],
    )
    write_csv(
        result_root / "injection_counts_by_depth.csv",
        count_rows,
        [
            "variant_short", "top_n", "site_budget", "site_mode", "depth", "prefetch_kind",
            "prefetch_lines", "target_count_used_by_sites", "line_target_count_used",
            "offset_target_count_used", "unique_inject_functions", "unique_source_lines",
            "injection_site_count", "inserted_prefetch_instructions",
        ],
    )
    write_csv(
        result_root / "target_labels.csv",
        label_rows,
        [
            "variant", "variant_short", "target_rank", "target_id", "target_kind", "target_symbol",
            "target_src_relpath", "target_src_line", "target_label", "target_operand_type",
            "target_operand", "target_count",
        ],
    )
    write_csv(
        result_root / "injection_points_by_depth.csv",
        point_rows,
        [
            "variant", "variant_short", "target_rank", "depth", "target_id", "target_kind",
            "target_symbol", "target_raw_symbol", "target_src_relpath", "target_src_line",
            "target_label", "target_operand_type", "target_operand", "target_primary_offset",
            "target_adjusted_offset", "target_shift_bytes_est", "target_reason", "target_count",
            "selected_site_rank", "count", "from_symbol", "from_offset", "to_symbol", "to_offset",
            "branch_type", "site_class", "lead_bytes", "lead_bucket", "insert_src_relpath",
            "insert_src_line", "prefetch_kind", "prefetch_lines", "prefetch_line_size",
        ],
    )
    write_csv(
        result_root / "coverage_by_target.csv",
        coverage_rows,
        [
            "variant_short", "site_mode", "site_budget", "depth", "target_rank", "target_id",
            "target_kind", "target_symbol", "target_count", "selected_site_count",
            "selected_site_count_after_dedup", "covered_candidate_weight",
        ],
    )
    write_csv(
        result_root / "true_lbr_sample_coverage.csv",
        true_cov_rows,
        [
            "variant_short", "total_lbr_samples", "selected_target_samples",
            "covered_selected_samples_once", "matched_site_instances",
            "selected_target_pct_of_all_l2_samples", "covered_pct_of_all_l2_samples",
            "covered_pct_of_selected_target_samples", "avg_matched_sites_per_selected_sample",
        ],
    )

    with (result_root / "injection_summary.md").open("w", encoding="utf-8") as f:
        f.write("# DT Coverage Prefetch Variants\n\n")
        f.write("- Prefetch kind: `prefetcht0` only.\n")
        if args.target_operand_mode == "label":
            f.write("- Resolved same-enclosing-function targets use source labels.\n")
            f.write("- line0/unresolved/inlined targets are kept as direct `mangled_symbol+offset(%rip)` operands.\n")
        else:
            f.write("- All targets use direct `mangled_symbol+adjusted_offset(%rip)` operands.\n")
            f.write("- Adjusted offsets are baseline profiled PC offsets plus same-function inserted-prefetch byte shifts.\n")
        f.write(f"- Same-function lead window: {args.same_min_lead}..{args.same_max_lead} bytes.\n")
        f.write(f"- Total LBR samples: {total_samples}\n")
        f.write(f"- Accepted by symbol pool: {accepted_samples}\n\n")
        f.write("## Cumulative Target Coverage\n\n")
        f.write("| Top N | Samples | All L2 Samples | Accepted Symbol Pool |\n")
        f.write("|---:|---:|---:|---:|\n")
        for row in cumulative_rows:
            f.write(f"| {row['top_n']} | {row['samples']} | {row['pct_of_all_l2_samples']}% | {row['pct_of_accepted_symbol_pool']}% |\n")
        f.write("\n## Variants\n\n")
        f.write("| Variant | Mode | Top N | Sites | Prefetches | Used Targets | Offset Targets | Selected/All | Covered/All |\n")
        f.write("|---|---|---:|---:|---:|---:|---:|---:|---:|\n")
        cov_by_v = {r["variant_short"]: r for r in true_cov_rows}
        for row in variant_rows:
            cov = cov_by_v.get(row["variant_short"], {})
            f.write(
                f"| {row['variant_short']} | {row['site_mode']} | {row['top_n']} | {row['injection_site_count']} | "
                f"{row['inserted_prefetch_instructions']} | {row['target_count_used_by_sites']} | "
                f"{row['offset_target_count_used']} | {cov.get('selected_target_pct_of_all_l2_samples','0')}% | "
                f"{cov.get('covered_pct_of_all_l2_samples','0')}% |\n"
            )

    print(f"[ok] result_root={result_root}")
    print(f"[ok] variant_root={variant_root}")
    for row in variant_rows:
        print(
            f"[variant] {row['variant_short']} mode={row['site_mode']} top={row['top_n']} "
            f"sites={row['injection_site_count']} prefetch={row['inserted_prefetch_instructions']} "
            f"offset_targets={row['offset_target_count_used']}"
        )


if __name__ == "__main__":
    main()
