#!/usr/bin/env python3
import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path


FUNC_DEF_RE = re.compile(r"^void\s+([A-Za-z0-9_]+)\([^;]*\)\s*\{")


def parse_args():
    ap = argparse.ArgumentParser(
        description=(
            "Apply callsite PrefetchIT insertions to an already-generated Verilator "
            "C++ tree. This is intended to run after make has produced model_mk, "
            "because Verilator regeneration can overwrite pre-patched sources."
        )
    )
    ap.add_argument("--variant-dir", required=True)
    ap.add_argument("--variant-short", required=True)
    ap.add_argument("--config", default="DualMegaBoomAndSingleRocketConfig")
    ap.add_argument("--result-root", required=True, help="callsite prefetchit result directory")
    return ap.parse_args()


def strip_existing_prefetch(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        if "PREFETCHIT_CALLSITE" in ln:
            continue
        if 'asm volatile("prefetchit0 ' in ln:
            continue
        out.append(ln)
    return out


def brace_delta(line: str):
    return line.count("{") - line.count("}")


def find_enclosing_function_body_start(lines: list[str], idx: int):
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
            while pos < idx:
                ahead = lines[pos].strip()
                if ahead == "" or ahead.startswith("//"):
                    pos += 1
                    continue
                break
            return pos
    return body_start


def load_variant_points(result_root: Path, variant_short: str):
    csv_path = result_root / "injection_points_by_depth.csv"
    if not csv_path.is_file():
        raise RuntimeError(f"missing injection point CSV: {csv_path}")

    grouped = defaultdict(lambda: defaultdict(list))
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("variant_short", "").strip() != variant_short:
                continue
            rel = row.get("src_relpath", "").strip()
            line_s = row.get("src_line", "").strip()
            mangled = row.get("target_mangled", "").strip()
            if not rel or not line_s or not mangled:
                continue
            try:
                line_no = int(line_s)
            except ValueError:
                continue
            if line_no <= 0:
                continue
            grouped[rel][line_no].append(row)
    return grouped


def patch_variant(variant_dir: Path, config: str, variant_short: str, result_root: Path):
    cfg_tag = f"chipyard.harness.TestHarness.{config}"
    gen_cpp_dir = variant_dir / "generated-src" / cfg_tag / cfg_tag
    if not gen_cpp_dir.is_dir():
        raise RuntimeError(f"generated cpp dir not found: {gen_cpp_dir}")

    grouped = load_variant_points(result_root, variant_short)
    patched_files = 0
    inserted = 0
    missing_files = []
    skipped_lines = []
    skipped_outside_function = []

    for rel, line_map in grouped.items():
        fp = gen_cpp_dir / rel
        if not fp.is_file():
            missing_files.append(str(rel))
            continue

        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        lines = strip_existing_prefetch(lines)

        insertions = []
        for line_no, rows in line_map.items():
            if line_no < 1 or line_no > len(lines) + 1:
                skipped_lines.append(f"{rel}:{line_no}")
                continue
            insert_idx = find_statement_insert_index(lines, line_no)
            if insert_idx is None:
                skipped_outside_function.append(f"{rel}:{line_no}")
                continue
            safe_line = insert_idx + 1

            block = [
                (
                    f"    // PREFETCHIT_CALLSITE variant={variant_short} "
                    f"file={rel} line={safe_line} requested_line={line_no} sites={len(rows)}\n"
                )
            ]
            for row in rows:
                depth = row.get("depth", "")
                from_sym = row.get("from_symbol", "")
                from_off = row.get("from_offset", "")
                branch_type = row.get("branch_type", "")
                count = row.get("count", "")
                target = row.get("target_symbol", "")
                orig_line = row.get("original_src_line", line_no)
                mangled = row["target_mangled"].strip()
                block.append(
                    (
                        f"    // PREFETCHIT_CALLSITE depth={depth} "
                        f"branch={from_sym}+{from_off} "
                        f"type={branch_type} count={count} "
                        f"target={target} orig_line={orig_line} requested_line={line_no}\n"
                    )
                )
                block.append(f'    asm volatile("prefetchit0 {mangled}(%%rip)" ::: "memory");\n')
                inserted += 1

            insertions.append((insert_idx, block))

        if not insertions:
            continue

        insertions.sort(key=lambda x: x[0], reverse=True)
        for pos, block in insertions:
            lines[pos:pos] = block
        fp.write_text("".join(lines), encoding="utf-8")
        patched_files += 1

    return patched_files, inserted, missing_files, skipped_lines, skipped_outside_function


def main():
    args = parse_args()
    patched_files, inserted, missing_files, skipped_lines, skipped_outside_function = patch_variant(
        variant_dir=Path(args.variant_dir).resolve(),
        config=args.config,
        variant_short=args.variant_short,
        result_root=Path(args.result_root).resolve(),
    )

    print(f"[ok] variant={args.variant_short} patched_files={patched_files} inserted_prefetch={inserted}")
    if missing_files:
        print(f"[warn] missing source files ({len(missing_files)}):")
        for item in missing_files[:20]:
            print(f"  - {item}")
    if skipped_lines:
        print(f"[warn] skipped out-of-range lines ({len(skipped_lines)}):")
        for item in skipped_lines[:20]:
            print(f"  - {item}")
    if skipped_outside_function:
        print(f"[warn] skipped outside-function lines ({len(skipped_outside_function)}):")
        for item in skipped_outside_function[:20]:
            print(f"  - {item}")
    if args.variant_short != "baseline" and inserted <= 0:
        raise SystemExit("no callsite prefetchit insertions were applied")


if __name__ == "__main__":
    main()
