#!/usr/bin/env python3
import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path


FUNC_DEF_RE = re.compile(r"^(?:VL_INLINE_OPT\s+)?(?:void|VlCoroutine)\s+([A-Za-z0-9_]+)\([^;]*\)\s*\{")
PREFETCH_MARKER = "PREFETCH_EXACT"
LABEL_PREFIX = "__pf_target_"


def parse_args():
    ap = argparse.ArgumentParser(
        description=(
            "Apply exact target-label based prefetch insertions to generated Verilator C++. "
            "Target labels are placed at resolved miss source lines; callsites prefetch those labels."
        )
    )
    ap.add_argument("--variant-dir", required=True)
    ap.add_argument("--variant-short", required=True)
    ap.add_argument("--config", default="DualMegaBoomAndSingleRocketConfig")
    ap.add_argument("--result-root", required=True)
    return ap.parse_args()


def strip_existing_prefetch(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        if PREFETCH_MARKER in ln:
            continue
        if LABEL_PREFIX in ln:
            continue
        if 'asm volatile("prefetchit0 ' in ln:
            continue
        if 'asm volatile("prefetcht0 ' in ln:
            continue
        out.append(ln)
    return out


def brace_delta(line: str) -> int:
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


def find_preceding_function_body_start(lines: list[str], idx: int):
    for i in range(max(0, min(idx, len(lines) - 1)), -1, -1):
        if FUNC_DEF_RE.match(lines[i]):
            return i + 1
    return None


def find_preceding_function_def_index(lines: list[str], idx: int):
    for i in range(max(0, min(idx, len(lines) - 1)), -1, -1):
        if FUNC_DEF_RE.match(lines[i]):
            return i
    return None


def find_next_function_def_index(lines: list[str], idx: int):
    start = max(0, min(idx, len(lines) - 1))
    for i in range(start, len(lines)):
        if FUNC_DEF_RE.match(lines[i]):
            return i
    return None


def find_nearby_next_function_body_start(lines: list[str], idx: int, window: int = 8):
    start = max(0, min(idx, len(lines) - 1))
    end = min(len(lines), start + window + 1)
    for i in range(start, end):
        if FUNC_DEF_RE.match(lines[i]):
            return i + 1
    return None


def find_statement_insert_index(lines: list[str], line_no: int):
    idx = max(0, min(line_no - 1, len(lines)))
    if not lines:
        return None
    body_start = find_enclosing_function_body_start(lines, min(idx, len(lines) - 1))
    if body_start is None:
        # Addr2line can point at the signature line. Prefer the current/nearby
        # function start rather than falling back to a previous already-closed
        # function, which would place asm at file scope.
        body_start = find_nearby_next_function_body_start(lines, min(idx, len(lines) - 1))
    if body_start is None:
        # Very large generated Verilator functions can confuse the simple brace
        # counter. Fall back to the nearest preceding function only when there is
        # no intervening function definition before this source location.
        bounded_idx = min(idx, len(lines) - 1)
        prev_def = find_preceding_function_def_index(lines, bounded_idx)
        next_def = find_next_function_def_index(lines, prev_def + 1 if prev_def is not None else bounded_idx)
        if prev_def is not None and (next_def is None or next_def > bounded_idx):
            body_start = prev_def + 1
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
            rel = row.get("insert_src_relpath", row.get("src_relpath", "")).strip()
            line_s = row.get("insert_src_line", row.get("src_line", "")).strip()
            label = row.get("target_label", "").strip()
            if not rel or not line_s or not label:
                continue
            try:
                line_no = int(line_s)
            except ValueError:
                continue
            if line_no <= 0:
                continue
            grouped[rel][line_no].append(row)
    return grouped


def load_variant_labels(result_root: Path, variant_short: str):
    csv_path = result_root / "target_labels.csv"
    if not csv_path.is_file():
        raise RuntimeError(f"missing target label CSV: {csv_path}")

    grouped = defaultdict(lambda: defaultdict(list))
    seen = set()
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("variant_short", "").strip() != variant_short:
                continue
            rel = row.get("target_src_relpath", "").strip()
            line_s = row.get("target_src_line", "").strip()
            label = row.get("target_label", "").strip()
            if not rel or not line_s or not label:
                continue
            try:
                line_no = int(line_s)
            except ValueError:
                continue
            if line_no <= 0:
                continue
            key = (rel, line_no, label)
            if key in seen:
                continue
            seen.add(key)
            grouped[rel][line_no].append(row)
    return grouped


def prefetch_mnemonics(kind: str):
    kind = kind.strip().lower()
    if kind in ("it", "it0", "prefetchit0"):
        return ["prefetchit0"]
    if kind in ("dt", "dt0", "t0", "prefetcht0"):
        return ["prefetcht0"]
    if kind == "both":
        return ["prefetchit0", "prefetcht0"]
    raise RuntimeError(f"unsupported prefetch kind: {kind}")


def make_label_block(rows: list[dict], rel: str, requested_line: int, safe_line: int):
    block = []
    for row in rows:
        label = row["target_label"].strip()
        target = row.get("target_symbol", "")
        count = row.get("target_count", row.get("count", ""))
        block.append(
            f"    // {PREFETCH_MARKER} target_label={label} file={rel} line={safe_line} requested_line={requested_line} target={target} count={count}\n"
        )
        block.append(
            f'    asm volatile(".globl {label}\\n.hidden {label}\\n{label}:" ::: "memory");\n'
        )
    return block


def make_prefetch_block(rows: list[dict], variant_short: str, rel: str, requested_line: int, safe_line: int):
    block = [
        f"    // {PREFETCH_MARKER} variant={variant_short} file={rel} line={safe_line} requested_line={requested_line} sites={len(rows)}\n"
    ]
    inserted = 0
    for row in rows:
        label = row["target_label"].strip()
        kind = row.get("prefetch_kind", "it0").strip().lower()
        line_count = int(row.get("prefetch_lines", "1") or "1")
        line_size = int(row.get("prefetch_line_size", "64") or "64")
        if line_count <= 0:
            continue
        for mnemonic in prefetch_mnemonics(kind):
            for i in range(line_count):
                off = i * line_size
                label_expr = label if off == 0 else f"{label}+{off}"
                block.append(
                    (
                        f"    // {PREFETCH_MARKER} depth={row.get('depth','')} "
                        f"branch={row.get('from_symbol','')}+{row.get('from_offset','')} "
                        f"type={row.get('branch_type','')} count={row.get('count','')} "
                        f"target_label={label} target={row.get('target_symbol','')} "
                        f"target_line={row.get('target_src_relpath','')}:{row.get('target_src_line','')} "
                        f"kind={mnemonic} line_offset={off}\n"
                    )
                )
                block.append(f'    asm volatile("{mnemonic} {label_expr}(%%rip)" ::: "memory");\n')
                inserted += 1
    return block, inserted


def patch_variant(variant_dir: Path, config: str, variant_short: str, result_root: Path):
    cfg_tag = f"chipyard.harness.TestHarness.{config}"
    gen_cpp_dir = variant_dir / "generated-src" / cfg_tag / cfg_tag
    if not gen_cpp_dir.is_dir():
        raise RuntimeError(f"generated cpp dir not found: {gen_cpp_dir}")

    prefetch_grouped = load_variant_points(result_root, variant_short)
    label_grouped = load_variant_labels(result_root, variant_short)

    all_rels = sorted(set(prefetch_grouped.keys()) | set(label_grouped.keys()))
    patched_files = 0
    inserted_prefetch = 0
    inserted_labels = 0
    missing_files = []
    skipped_lines = []
    skipped_outside_function = []

    for rel in all_rels:
        fp = gen_cpp_dir / rel
        if not fp.is_file():
            missing_files.append(str(rel))
            continue

        lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        lines = strip_existing_prefetch(lines)

        blocks_by_pos = defaultdict(lambda: {"prefetch": [], "label": []})

        for line_no, rows in prefetch_grouped.get(rel, {}).items():
            if line_no < 1 or line_no > len(lines) + 1:
                skipped_lines.append(f"{rel}:{line_no}")
                continue
            insert_idx = find_statement_insert_index(lines, line_no)
            if insert_idx is None:
                skipped_outside_function.append(f"prefetch:{rel}:{line_no}")
                continue
            block, n = make_prefetch_block(rows, variant_short, rel, line_no, insert_idx + 1)
            if n > 0:
                blocks_by_pos[insert_idx]["prefetch"].extend(block)
                inserted_prefetch += n

        for line_no, rows in label_grouped.get(rel, {}).items():
            if line_no < 1 or line_no > len(lines) + 1:
                skipped_lines.append(f"{rel}:{line_no}")
                continue
            insert_idx = find_statement_insert_index(lines, line_no)
            if insert_idx is None:
                skipped_outside_function.append(f"label:{rel}:{line_no}")
                continue
            block = make_label_block(rows, rel, line_no, insert_idx + 1)
            if block:
                # At identical source position, prefetch goes first and label stays closest to the original target statement.
                blocks_by_pos[insert_idx]["label"].extend(block)
                inserted_labels += len(rows)

        if not blocks_by_pos:
            continue

        for pos in sorted(blocks_by_pos.keys(), reverse=True):
            item = blocks_by_pos[pos]
            block = item["prefetch"] + item["label"]
            lines[pos:pos] = block
        fp.write_text("".join(lines), encoding="utf-8")
        patched_files += 1

    return patched_files, inserted_prefetch, inserted_labels, missing_files, skipped_lines, skipped_outside_function


def main():
    args = parse_args()
    patched_files, inserted_prefetch, inserted_labels, missing_files, skipped_lines, skipped_outside_function = patch_variant(
        variant_dir=Path(args.variant_dir).resolve(),
        config=args.config,
        variant_short=args.variant_short,
        result_root=Path(args.result_root).resolve(),
    )

    print(
        f"[ok] variant={args.variant_short} patched_files={patched_files} "
        f"inserted_prefetch={inserted_prefetch} inserted_labels={inserted_labels}"
    )
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
    if args.variant_short != "baseline" and inserted_prefetch <= 0:
        raise SystemExit("no exact prefetch insertions were applied")
    if args.variant_short != "baseline" and inserted_labels <= 0:
        raise SystemExit("no exact prefetch target labels were applied")


if __name__ == "__main__":
    main()
