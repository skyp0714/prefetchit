#!/usr/bin/env python3
import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

FUNC_DEF_RE = re.compile(r"^void\s+([A-Za-z0-9_]+)\([^;]*\)\s*\{")


def parse_args():
    ap = argparse.ArgumentParser(description="Apply prefetchit patch to one prepared variant directory")
    ap.add_argument("--variant-dir", required=True)
    ap.add_argument("--variant-short", required=True, help="e.g., baseline, k10_d2, k100_d32")
    ap.add_argument("--config", default="DualMegaBoomAndSingleRocketConfig")
    ap.add_argument("--result-root", required=True, help="prefetchit_variants result directory")
    return ap.parse_args()


def index_function_defs(gen_cpp_dir: Path):
    func_to_file = {}
    for fp in gen_cpp_dir.glob("*.cpp"):
        with fp.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = FUNC_DEF_RE.match(line)
                if not m:
                    continue
                fn = m.group(1)
                if fn not in func_to_file:
                    func_to_file[fn] = fp
    return func_to_file


def find_function_body(lines, func):
    def_idx = -1
    for i, ln in enumerate(lines):
        m = FUNC_DEF_RE.match(ln)
        if m and m.group(1) == func:
            def_idx = i
            break
    if def_idx < 0:
        return -1, -1

    end_idx = len(lines)
    for i in range(def_idx + 1, len(lines)):
        if FUNC_DEF_RE.match(lines[i]):
            end_idx = i
            break
    return def_idx, end_idx


def load_target_to_mangled(result_root: Path):
    out = {}
    with (result_root / "selected_top_targets.csv").open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            base = row.get("base_symbol", "").strip()
            mangled = row.get("mangled_symbol", "").strip()
            if base and mangled:
                out[base] = mangled
    return out


def load_variant_func_targets(result_root: Path, variant_short: str):
    func_targets = defaultdict(list)
    csv_path = result_root / "injection_points_by_depth.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("variant_short", "") != variant_short:
                continue
            fn = row.get("inject_function", "").strip()
            targets = [x.strip() for x in row.get("prefetch_targets", "").split("|") if x.strip()]
            if not fn or not targets:
                continue
            func_targets[fn].extend(targets)

    dedup = {}
    for fn, tlist in func_targets.items():
        uniq = []
        for t in tlist:
            if t not in uniq:
                uniq.append(t)
        dedup[fn] = uniq
    return dedup


def load_callsite_points(result_root: Path, variant_short: str):
    csv_path = result_root / "injection_points_by_depth.csv"
    points = defaultdict(lambda: defaultdict(list))
    if not csv_path.exists():
        return None

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        required = {"variant_short", "src_relpath", "src_line", "target_mangled"}
        if not required.issubset(fields):
            return None

        seen = set()
        for row in reader:
            if row.get("variant_short", "") != variant_short:
                continue
            rel = row.get("src_relpath", "").strip()
            target_mangled = row.get("target_mangled", "").strip()
            try:
                line_no = int(row.get("src_line", "0"))
            except ValueError:
                line_no = 0
            if not rel or line_no <= 0 or not target_mangled:
                continue

            key = (
                rel,
                line_no,
                row.get("depth", "").strip(),
                row.get("target_symbol", "").strip(),
                row.get("from_symbol", "").strip(),
                row.get("from_offset", "").strip(),
                target_mangled,
            )
            if key in seen:
                continue
            seen.add(key)
            points[rel][line_no].append(row)

    return points


def strip_existing_prefetch(lines):
    out = []
    for ln in lines:
        if "PREFETCHIT_MANUAL" in ln:
            continue
        if "PREFETCHIT_CALLSITE" in ln:
            continue
        if 'asm volatile("prefetchit0 ' in ln:
            continue
        out.append(ln)
    return out


def patch_callsite_variant(variant_dir: Path, config: str, variant_short: str, result_root: Path):
    if variant_short == "baseline":
        return 0, 0, []

    points = load_callsite_points(result_root, variant_short)
    if points is None:
        return None

    cfg_tag = f"chipyard.harness.TestHarness.{config}"
    gen_cpp_dir = variant_dir / "generated-src" / cfg_tag / cfg_tag
    if not gen_cpp_dir.is_dir():
        raise RuntimeError(f"generated cpp dir not found: {gen_cpp_dir}")

    patched_files = 0
    inserted = 0
    missing = []

    for rel, line_map in points.items():
        fp = gen_cpp_dir / rel
        if not fp.exists():
            missing.append(f"{rel}:missing_file")
            continue

        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        lines = strip_existing_prefetch(lines)

        insertions = []
        for line_no, rows in line_map.items():
            if line_no < 1 or line_no > len(lines) + 1:
                missing.append(f"{rel}:{line_no}:line_out_of_range")
                continue

            block = [
                (
                    f"    // PREFETCHIT_CALLSITE variant={variant_short} "
                    f"file={rel} line={line_no} sites={len(rows)}\n"
                )
            ]
            local_added = 0
            for row in rows:
                target_mangled = row.get("target_mangled", "").strip()
                if not target_mangled:
                    continue
                block.append(
                    (
                        f"    // PREFETCHIT_CALLSITE depth={row.get('depth', '')} "
                        f"branch={row.get('from_symbol', '')}+{row.get('from_offset', '')} "
                        f"type={row.get('branch_type', '')} count={row.get('count', '')} "
                        f"target={row.get('target_symbol', '')} "
                        f"orig_line={row.get('original_src_line', line_no)}\n"
                    )
                )
                block.append(f'    asm volatile("prefetchit0 {target_mangled}(%%rip)" ::: "memory");\n')
                local_added += 1

            if local_added > 0:
                inserted += local_added
                insertions.append((line_no - 1, block))

        if not insertions:
            continue

        insertions.sort(key=lambda x: x[0], reverse=True)
        for pos, block in insertions:
            lines[pos:pos] = block

        fp.write_text("".join(lines), encoding="utf-8")
        patched_files += 1

    return patched_files, inserted, missing


def patch_variant(variant_dir: Path, config: str, variant_short: str, result_root: Path):
    if variant_short == "baseline":
        return 0, 0, []

    target_to_mangled = load_target_to_mangled(result_root)
    func_targets = load_variant_func_targets(result_root, variant_short)

    cfg_tag = f"chipyard.harness.TestHarness.{config}"
    gen_cpp_dir = variant_dir / "generated-src" / cfg_tag / cfg_tag
    if not gen_cpp_dir.is_dir():
        raise RuntimeError(f"generated cpp dir not found: {gen_cpp_dir}")

    func_to_file = index_function_defs(gen_cpp_dir)

    file_to_funcs = defaultdict(dict)
    missing_func = []
    for func, targets in func_targets.items():
        fp = func_to_file.get(func)
        if not fp:
            missing_func.append(func)
            continue
        file_to_funcs[fp][func] = targets

    patched_files = 0
    inserted = 0

    for fp, fmap in file_to_funcs.items():
        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        lines = strip_existing_prefetch(lines)

        insertions = []
        for func, targets in fmap.items():
            def_idx, end_idx = find_function_body(lines, func)
            if def_idx < 0:
                continue

            auto_idx = -1
            for i in range(def_idx, end_idx):
                if "auto& vlSelfRef =" in lines[i]:
                    auto_idx = i
                    break
            if auto_idx < 0:
                auto_idx = def_idx

            block = [f"    // PREFETCHIT_MANUAL variant={variant_short} func={func} count={len(targets)}\n"]
            local_added = 0
            for tgt in targets:
                mangled = target_to_mangled.get(tgt, "")
                if not mangled:
                    continue
                block.append(f'    asm volatile("prefetchit0 {mangled}(%%rip)" ::: "memory");\n')
                local_added += 1

            if local_added > 0:
                inserted += local_added
                insertions.append((auto_idx + 1, block))

        if not insertions:
            continue

        insertions.sort(key=lambda x: x[0], reverse=True)
        for pos, block in insertions:
            lines[pos:pos] = block

        fp.write_text("".join(lines), encoding="utf-8")
        patched_files += 1

    return patched_files, inserted, missing_func


def main():
    args = parse_args()
    callsite_result = patch_callsite_variant(
        variant_dir=Path(args.variant_dir).resolve(),
        config=args.config,
        variant_short=args.variant_short,
        result_root=Path(args.result_root).resolve(),
    )
    if callsite_result is not None:
        patched_files, inserted, missing_func = callsite_result
        print(f"[ok] mode=callsite variant={args.variant_short} patched_files={patched_files} inserted_prefetch={inserted}")
        if missing_func:
            print(f"[warn] missing callsite locations ({len(missing_func)}):")
            for item in missing_func[:20]:
                print(f"  - {item}")
        return

    patched_files, inserted, missing_func = patch_variant(
        variant_dir=Path(args.variant_dir).resolve(),
        config=args.config,
        variant_short=args.variant_short,
        result_root=Path(args.result_root).resolve(),
    )

    print(f"[ok] variant={args.variant_short} patched_files={patched_files} inserted_prefetch={inserted}")
    if missing_func:
        print(f"[warn] missing inject functions ({len(missing_func)}):")
        for fn in missing_func[:20]:
            print(f"  - {fn}")


if __name__ == "__main__":
    main()
