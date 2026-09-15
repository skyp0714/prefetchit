#!/usr/bin/env python3
"""Audit final baseline vs prefetcht1 vs prefetchit1 comparison artifacts."""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from pathlib import Path


REQUIRED_LABELS = ("baseline", "prefetcht1", "prefetchit1")
VALIDATION_PASS_RE = re.compile(r"\bPASS\b|exact.*target|target.*exact|Result:\s*PASS", re.IGNORECASE)


def fail(msg: str) -> None:
    raise SystemExit(f"[fail] {msg}")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        fail(f"missing {path}")
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        fail(f"empty {path}")
    return rows


def finite_metric(row: dict[str, str], key: str, label: str, *, positive: bool = True) -> float:
    try:
        val = float(row.get(key, "nan"))
    except ValueError:
        fail(f"{label}: nonnumeric {key}={row.get(key)!r}")
    if not math.isfinite(val):
        fail(f"{label}: invalid {key}={val!r}")
    if positive and val <= 0.0:
        fail(f"{label}: non-positive {key}={val!r}")
    if not positive and val < 0.0:
        fail(f"{label}: negative {key}={val!r}")
    return val


def audit_summary(compare_dir: Path) -> list[str]:
    summary = read_csv(compare_dir / "prefetch_compare_summary.csv")
    labels = {row.get("label", "") for row in summary}
    missing = [label for label in REQUIRED_LABELS if label not in labels]
    if missing:
        fail(f"summary missing labels: {', '.join(missing)}")
    messages = []
    for label in REQUIRED_LABELS:
        row = next(r for r in summary if r.get("label") == label)
        n = int(float(row.get("n", "0")))
        if n <= 0:
            fail(f"{label}: invalid n={row.get('n')!r}")
        elapsed = finite_metric(row, "elapsed_sec_mean", label)
        mpki = finite_metric(row, "l2i_mpki_mean", label)
        finite_metric(row, "elapsed_sec_stdev", label, positive=False) if n > 1 else None
        finite_metric(row, "l2i_mpki_stdev", label, positive=False) if n > 1 else None
        for key in ("elapsed_sec_delta_pct", "l2i_mpki_delta_pct"):
            try:
                delta = float(row.get(key, "nan"))
            except ValueError:
                fail(f"{label}: nonnumeric {key}={row.get(key)!r}")
            if not math.isfinite(delta):
                fail(f"{label}: invalid {key}={delta!r}")
        messages.append(f"{label}: n={n}, runtime={elapsed:.6f}s, l2i_mpki={mpki:.6f}")
    return messages


def audit_iterations(compare_dir: Path) -> list[str]:
    rows = read_csv(compare_dir / "prefetch_compare_iterations.csv")
    counts: dict[str, int] = {label: 0 for label in REQUIRED_LABELS}
    for row in rows:
        label = row.get("label", "")
        if label not in counts:
            continue
        counts[label] += 1
        finite_metric(row, "elapsed_sec", f"iteration {label}")
        finite_metric(row, "l2i_mpki", f"iteration {label}")
    missing = [label for label, count in counts.items() if count == 0]
    if missing:
        fail(f"iterations missing labels: {', '.join(missing)}")
    return [", ".join(f"{label}={counts[label]}" for label in REQUIRED_LABELS)]


def audit_plot(compare_dir: Path) -> list[str]:
    plot = compare_dir / "prefetch_compare_boxplot.png"
    if not plot.is_file():
        fail(f"missing {plot}")
    size = plot.stat().st_size
    if size < 10_000:
        fail(f"plot too small: {plot} size={size}")
    return [f"boxplot bytes={size}"]


def find_prefetch_validation(exact_dir: Path, mnemonic: str) -> Path:
    candidates = sorted(exact_dir.glob(f"**/assembly_validation/prefetch_asm_validation.*"))
    preferred = [p for p in candidates if mnemonic in str(p)]
    for path in preferred + candidates:
        if path.suffix.lower() in {".md", ".csv"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            if mnemonic in text or mnemonic in str(path):
                return path
    fail(f"missing assembly validation for {mnemonic} under {exact_dir}")


def audit_validation_file(path: Path, mnemonic: str) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if mnemonic not in text and mnemonic not in str(path):
        fail(f"{mnemonic}: validation file does not mention mnemonic: {path}")
    if path.suffix.lower() == ".md":
        if "Result: PASS" not in text:
            fail(f"{mnemonic}: validation md lacks Result: PASS: {path}")
        for phrase in ("Target exact addr matches", "Target 64B cacheline matches"):
            if phrase not in text:
                fail(f"{mnemonic}: validation md missing {phrase}: {path}")
    elif path.suffix.lower() == ".csv":
        rows = read_csv(path)
        exact = cacheline = parsed = 0
        for row in rows:
            if row.get("parse_status") == "ok":
                parsed += 1
            exact += int(float(row.get("target_addr_matches_plan", "0") or 0))
            cacheline += int(float(row.get("target_cacheline_matches_plan", "0") or 0))
        if parsed <= 0 or exact <= 0 or cacheline <= 0:
            fail(f"{mnemonic}: validation csv lacks positive exact/cacheline evidence: {path}")
    elif not VALIDATION_PASS_RE.search(text):
        fail(f"{mnemonic}: weak validation evidence in {path}")
    return [f"{mnemonic} validation={path}"]


def extract_report_path(report: Path, label: str) -> Path | None:
    if not report.is_file():
        return None
    text = report.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(rf"{re.escape(label)}[^`]*`([^`]+)`", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    return Path(match.group(1))


def validation_from_binary_path(binary: Path, mnemonic: str) -> Path | None:
    # Binaries are stored as RUN_DIR/bin/simulator...; validation is RUN_DIR/assembly_validation/....
    parents = list(binary.parents)[:5]
    for parent in parents:
        candidate = parent / "assembly_validation" / "prefetch_asm_validation.md"
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8", errors="replace")
            if mnemonic in text or mnemonic in str(candidate):
                return candidate
    return None


def audit_residual_trace(exact_dir: Path) -> list[str]:
    trace_dir = exact_dir / "residual_trace"
    if not trace_dir.exists():
        return ["residual_trace=missing (allowed only if trace collection failed gracefully)"]
    summaries = sorted(trace_dir.glob("**/trace_summary.md"))
    if not summaries:
        return ["residual_trace=no trace_summary.md (allowed only if trace collection failed gracefully)"]
    msgs = []
    for path in summaries[:8]:
        text = path.read_text(encoding="utf-8", errors="replace")
        if "LBR samples parsed" in text:
            msgs.append(f"trace_summary={path}")
    return msgs or [f"residual_trace summaries={len(summaries)}"]


def write_report(out: Path, messages: list[str]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Final Prefetch Compare Audit", ""]
    lines.extend(f"- {msg}" for msg in messages)
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exact-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    exact_dir = args.exact_dir.resolve()
    compare_dir = exact_dir / "final_compare"
    messages: list[str] = []
    messages.extend(audit_summary(compare_dir))
    messages.extend(audit_iterations(compare_dir))
    messages.extend(audit_plot(compare_dir))
    # The best prefetcht1 validation lives in the selected run dir; exact report points to it.
    report = exact_dir / "exact_prefetch_compare_report.md"
    if report.is_file():
        messages.append(f"report={report}")
    else:
        fail(f"missing {report}")

    pft_bin = extract_report_path(report, "Prefetcht1 binary")
    if pft_bin is not None:
        pft_val = validation_from_binary_path(pft_bin, "prefetcht1")
        if pft_val is not None:
            messages.extend(audit_validation_file(pft_val, "prefetcht1"))
        else:
            fail(f"prefetcht1: could not locate validation from {pft_bin}")
    else:
        messages.append("prefetcht1 validation=not found in report")

    pfi = find_prefetch_validation(exact_dir, "prefetchit1")
    messages.extend(audit_validation_file(pfi, "prefetchit1"))
    messages.extend(audit_residual_trace(exact_dir))
    write_report(args.out.resolve(), messages)
    print(f"[ok] audit passed: {args.out.resolve()}")


if __name__ == "__main__":
    main()
