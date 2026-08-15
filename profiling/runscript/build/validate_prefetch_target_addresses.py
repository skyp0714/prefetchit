#!/usr/bin/env python3
import argparse
import csv
import importlib.util
import re
import subprocess
from collections import Counter
from pathlib import Path


LINE_RE = re.compile(
    r"^\s*(?:\d+:)?\s*([0-9a-fA-F]+):\s+((?:[0-9a-fA-F]{2}\s+)+)\s+"
    r"(prefetch(?:it[01]|t[012]))\s+([+-]?(?:0x[0-9a-fA-F]+|\d+))\(%rip\)\s+#\s+"
    r"0x([0-9a-fA-F]+)(?:\s+<([^>]+)>)?"
)


def parse_args():
    ap = argparse.ArgumentParser(
        description="Validate that objdump prefetch targets match intended adjusted target addresses."
    )
    ap.add_argument("--repo-root", default="/home/hnpark2/prefetchit")
    ap.add_argument("--asm-csv", required=True)
    ap.add_argument("--injection-csv", required=True)
    ap.add_argument("--out-csv", required=True)
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


def prefetch_mnemonic_count(kind: str) -> int:
    kind = kind.strip().lower()
    if kind in {"both", "it0+dt0", "dt0+it0"}:
        return 2
    return 1


def nm_raw_addresses(binary: Path):
    raw = subprocess.run(
        ["nm", "-an", str(binary)],
        check=False,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    out = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            try:
                out[parts[2]] = int(parts[0], 16)
            except ValueError:
                pass
    return out


def build_expected(prep, binary: Path, rows: list[dict], variant: str):
    addr_by_dem, _ = prep.build_symbol_maps(binary)
    labels = nm_raw_addresses(binary)
    expected = Counter()
    examples = []

    for row in rows:
        if row.get("variant_short") != variant:
            continue
        line_count = int(row.get("prefetch_lines", "1") or "1")
        line_size = int(row.get("prefetch_line_size", "64") or "64")
        repeat = prefetch_mnemonic_count(row.get("prefetch_kind", "dt0"))
        operand_type = row.get("target_operand_type", "")

        if operand_type == "label":
            label = row.get("target_label", "").strip()
            base = labels.get(label)
            if base is None:
                continue
        else:
            sym = row.get("target_symbol", "")
            base = addr_by_dem.get(sym)
            if base is None:
                continue
            adjusted = row.get("target_adjusted_offset", "").strip()
            off = parse_hex(adjusted or row.get("target_primary_offset", "0"))
            base += off

        for i in range(line_count):
            addr = base + i * line_size
            expected[addr] += repeat
            if len(examples) < 8:
                examples.append(f"0x{addr:x}:{row.get('target_id','')}")
    return expected, examples


def parse_actual(snippet: Path):
    actual = Counter()
    unparsed = 0
    if not snippet.is_file():
        return actual, unparsed
    for line in snippet.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "prefetch" not in line:
            continue
        m = LINE_RE.match(line)
        if not m:
            unparsed += 1
            continue
        actual[int(m.group(5), 16)] += 1
    return actual, unparsed


def main():
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    asm_rows = read_csv(Path(args.asm_csv).resolve())
    injection_rows = read_csv(Path(args.injection_csv).resolve())
    prep = load_prepare(repo_root)

    out_rows = []
    failed = False
    for row in asm_rows:
        variant = row["variant"]
        binary = Path(row["binary"]).resolve()
        actual, unparsed = parse_actual(Path(row["disasm_snippet"]).resolve())
        if variant == "baseline":
            expected = Counter()
            expected_examples = []
        else:
            expected, expected_examples = build_expected(prep, binary, injection_rows, variant)

        expected_addr_set = set(expected)
        remaining = expected.copy()
        in_expected = 0
        known_extra = Counter()
        unknown = Counter()
        for addr, count in actual.items():
            matched = min(count, remaining.get(addr, 0))
            in_expected += matched
            remaining[addr] -= matched
            extra = count - matched
            if extra > 0:
                if addr in expected_addr_set:
                    known_extra[addr] += extra
                else:
                    unknown[addr] += extra

        missing = +remaining
        status = "ok"
        if unparsed > 0 or missing or known_extra:
            status = "warn"
        if unknown:
            status = "fail"
            failed = True

        out_rows.append(
            {
                "variant": variant,
                "variant_prefixed": row["variant_prefixed"],
                "binary": str(binary),
                "expected_prefetch_count": sum(expected.values()),
                "actual_prefetch_count": sum(actual.values()),
                "actual_in_expected_count": in_expected,
                "actual_known_extra_count": sum(known_extra.values()),
                "actual_unknown_count": sum(unknown.values()),
                "expected_missing_count": sum(missing.values()),
                "unparsed_prefetch_lines": unparsed,
                "status": status,
                "known_extra_examples": ";".join(f"0x{k:x}:{v}" for k, v in known_extra.most_common(8)),
                "unknown_examples": ";".join(f"0x{k:x}:{v}" for k, v in unknown.most_common(8)),
                "missing_examples": ";".join(f"0x{k:x}:{v}" for k, v in missing.most_common(8)),
                "expected_examples": ";".join(expected_examples),
            }
        )

    out_path = Path(args.out_csv).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "variant",
            "variant_prefixed",
            "binary",
            "expected_prefetch_count",
            "actual_prefetch_count",
            "actual_in_expected_count",
            "actual_known_extra_count",
            "actual_unknown_count",
            "expected_missing_count",
            "unparsed_prefetch_lines",
            "status",
            "known_extra_examples",
            "unknown_examples",
            "missing_examples",
            "expected_examples",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    if failed:
        raise SystemExit(f"prefetch target validation failed: {out_path}")


if __name__ == "__main__":
    main()
