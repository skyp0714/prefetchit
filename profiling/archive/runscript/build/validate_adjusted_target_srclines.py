#!/usr/bin/env python3
import argparse
import csv
import importlib.util
from collections import Counter
from pathlib import Path


DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]


def parse_args():
    ap = argparse.ArgumentParser(
        description=(
            "Check whether adjusted direct prefetch target PCs in an optimized binary "
            "still resolve to the original profiled source line."
        )
    )
    ap.add_argument("--repo-root", default=str(DEFAULT_REPO_ROOT))
    ap.add_argument("--asm-csv", required=True)
    ap.add_argument("--injection-csv", required=True)
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--summary-md", required=True)
    ap.add_argument("--config", default="DualMegaBoomAndSingleRocketConfig")
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    return ap.parse_args()


def load_prepare(repo_root: Path):
    path = repo_root / "profiling/runscript/build/prepare_prefetch_exact_variants.py"
    spec = importlib.util.spec_from_file_location("prepare_prefetch_exact_variants", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_csv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def parse_hex(raw: str) -> int:
    raw = str(raw).strip()
    if not raw:
        return 0
    return int(raw, 16) if raw.startswith("0x") else int(raw)


def main():
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    prep = load_prepare(repo_root)
    cfg_tag = f"chipyard.harness.TestHarness.{args.config}"
    asm_rows = read_csv(Path(args.asm_csv).resolve())
    injection_rows = read_csv(Path(args.injection_csv).resolve())
    bin_by_variant = {r["variant"]: Path(r["binary"]).resolve() for r in asm_rows}

    # Deduplicate by target id. Multiple injection sites can prefetch the same target.
    target_rows = {}
    for row in injection_rows:
        if row.get("target_kind") != "line":
            continue
        if row.get("target_reason") != "resolved_line":
            continue
        variant = row.get("variant_short", "")
        if variant not in bin_by_variant:
            continue
        key = (variant, row.get("target_id", ""))
        if key not in target_rows:
            target_rows[key] = row

    by_variant = {}
    for variant, binary in bin_by_variant.items():
        if variant == "baseline":
            continue
        rows = [r for (v, _tid), r in target_rows.items() if v == variant]
        if not rows:
            continue
        addr_by_dem, _ = prep.build_symbol_maps(binary)
        addrs = []
        meta = {}
        for row in rows:
            base = addr_by_dem.get(row["target_symbol"])
            if base is None:
                continue
            adjusted = row.get("target_adjusted_offset", "").strip()
            off = parse_hex(adjusted or row.get("target_primary_offset", "0"))
            addr = base + off
            addrs.append(addr)
            meta[addr] = row
        resolved = prep.resolve_addr2line(args.addr2line, binary, sorted(set(addrs)))
        by_variant[variant] = (binary, resolved, meta)

    out_rows = []
    summary = Counter()
    for variant, (_binary, resolved, meta) in by_variant.items():
        for addr, row in sorted(meta.items()):
            func, loc = resolved.get(addr, ("", ""))
            rel, line_no = prep.generated_rel_from_loc(loc, cfg_tag)
            got_rel = str(rel) if rel else ""
            got_line = int(line_no or 0)
            exp_rel = row.get("target_src_relpath", "")
            exp_line = int(row.get("target_src_line", "0") or 0)
            status = "ok" if got_rel == exp_rel and got_line == exp_line else "mismatch"
            summary[(variant, status)] += 1
            out_rows.append(
                {
                    "variant": variant,
                    "target_rank": row.get("target_rank", ""),
                    "target_id": row.get("target_id", ""),
                    "target_symbol": row.get("target_symbol", ""),
                    "target_primary_offset": row.get("target_primary_offset", ""),
                    "target_adjusted_offset": row.get("target_adjusted_offset", ""),
                    "optimized_addr": f"0x{addr:x}",
                    "expected_src": f"{exp_rel}:{exp_line}",
                    "addr2line_function": func,
                    "addr2line_location": loc,
                    "resolved_src": f"{got_rel}:{got_line}" if got_rel else "",
                    "status": status,
                }
            )

    out_csv = Path(args.out_csv).resolve()
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "variant",
            "target_rank",
            "target_id",
            "target_symbol",
            "target_primary_offset",
            "target_adjusted_offset",
            "optimized_addr",
            "expected_src",
            "addr2line_function",
            "addr2line_location",
            "resolved_src",
            "status",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    lines = ["# Adjusted Target Source-Line Validation", ""]
    lines.append("| Variant | OK | Mismatch |")
    lines.append("|---|---:|---:|")
    for variant in sorted({k[0] for k in summary}):
        lines.append(f"| {variant} | {summary[(variant, 'ok')]} | {summary[(variant, 'mismatch')]} |")
    lines.append("")
    lines.append(f"- Detail CSV: `{out_csv}`")
    Path(args.summary_md).resolve().write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
