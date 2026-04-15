import argparse
import csv
from pathlib import Path
from typing import Dict, Optional, Tuple

from main_csv_utils import (
    fmt_metric,
    load_rows,
    mpki_from_events,
    safe_float,
    safe_int,
    upsert_rows,
    write_rows,
)

JVM_BENCHES = ("tomcat", "finagle-http", "finagle-chirper")
JVM_MODES = ((1, "jvm1c"), (86, "jvm86c"))

CORE_FILE_FOR_JVM_1C = {
    "tomcat": "tomcat_core.csv",
    "finagle-http": "finagle_http_core.csv",
    "finagle-chirper": "finagle_chirper_core.csv",
}

NON_JVM = {
    "verilator-qsort": "verilator_qsort_core.csv",
    "602.gcc_s": "spec602_core.csv",
    "605.mcf_s": "spec605_core.csv",
    "641.leela_s": "spec641_core.csv",
}


def read_single_csv(path: Path) -> Optional[Dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("r", encoding="utf-8", newline="") as f:
        return next(csv.DictReader(f), None)


def load_ctx_map(path: Path) -> Dict[Tuple[str, int], Dict[str, str]]:
    out: Dict[Tuple[str, int], Dict[str, str]] = {}
    if not path.exists() or path.stat().st_size == 0:
        return out
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            bench = row.get("Benchmark", "")
            core = safe_int(row.get("CoreCount", "-1"), -1)
            if bench not in JVM_BENCHES or core < 0:
                continue
            inst = safe_float(row.get("Instructions", "0"), 0.0)
            rc = safe_int(row.get("ReturnCode", "1"), 1)
            if inst <= 0.0 or rc != 0:
                continue
            out[(bench, core)] = row
    return out


def build_row(
    benchmark: str,
    mode: str,
    existing: Optional[Dict[str, str]],
    primary: Optional[Dict[str, str]],
    tlb_source: Optional[Dict[str, str]],
    source_label: str,
) -> Optional[Dict[str, str]]:
    row = dict(existing or {})
    row["Benchmark"] = benchmark
    row["Mode"] = mode

    # Primary source (typically provides instructions/event0/event1).
    if primary:
        for key in ("Instructions", "Event0", "Event1", "DelayMS", "ElapsedSec", "ReturnCode"):
            if key in primary and primary.get(key, "") != "":
                row[key] = str(primary.get(key, ""))

    # Event2/3 can come from primary, tlb_source, or existing fallback.
    if primary:
        if primary.get("Event2", "") != "":
            row["Event2"] = str(primary.get("Event2", ""))
        if primary.get("Event3", "") != "":
            row["Event3"] = str(primary.get("Event3", ""))

    if tlb_source:
        if tlb_source.get("Event2", "") != "":
            row["Event2"] = str(tlb_source.get("Event2", ""))
        if tlb_source.get("Event3", "") != "":
            row["Event3"] = str(tlb_source.get("Event3", ""))

    inst = safe_float(row.get("Instructions", "0"), 0.0)
    e0 = safe_float(row.get("Event0", "0"), 0.0)
    e1 = safe_float(row.get("Event1", "0"), 0.0)
    e2 = safe_float(row.get("Event2", "0"), 0.0)
    e3 = safe_float(row.get("Event3", "0"), 0.0)

    if inst <= 0.0:
        # No usable source and no existing usable row.
        return None

    l1, l2, itlb, stlb = mpki_from_events(inst, e0, e1, e2, e3)
    if mode == "shared":
        row["CoreCount"] = ""
    else:
        row["CoreCount"] = row.get("CoreCount", mode.replace("jvm", "").replace("c", ""))
    row["L1I_MPKI"] = fmt_metric(l1)
    row["L2_MPKI"] = fmt_metric(l2)
    row["iTLB_MPKI"] = fmt_metric(itlb)
    row["sTLB_MPKI"] = fmt_metric(stlb)
    row["SourceCSV"] = source_label
    return row


def main():
    ap = argparse.ArgumentParser(description="Build/refresh main_frontend_all.csv from available measurements")
    ap.add_argument("--results-dir", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--ctx-csv", default=None, help="Optional JVM context CSV for jvm86c (legacy)")
    ap.add_argument("--ctx4-csv", default=None, help="Optional TLB source CSV for jvm86c (legacy)")
    args = ap.parse_args()

    results = Path(args.results_dir)
    out_csv = Path(args.output)

    existing_rows = load_rows(out_csv)
    existing_map = {(r.get("Benchmark", ""), r.get("Mode", "")): r for r in existing_rows}

    ctx_csv = Path(args.ctx_csv) if args.ctx_csv else (results / "contextswitch_core0_mpki.csv")
    ctx4_csv = Path(args.ctx4_csv) if args.ctx4_csv else (results / "contextswitch_core0_frontend4_jvm.csv")
    ctx_rows = load_ctx_map(ctx_csv)
    ctx4_rows = load_ctx_map(ctx4_csv)

    updates = []

    # JVM rows: prefer fresh source if present, otherwise preserve existing row.
    for bench in JVM_BENCHES:
        one_core_src = read_single_csv(results / CORE_FILE_FOR_JVM_1C[bench])
        for core, mode in JVM_MODES:
            existing = existing_map.get((bench, mode))
            primary = None
            tlb = None
            label_parts = []

            if core == 1 and one_core_src:
                rc = safe_int(one_core_src.get("ReturnCode", "1"), 1)
                inst = safe_float(one_core_src.get("Instructions", "0"), 0.0)
                if rc == 0 and inst > 0:
                    primary = one_core_src
                    label_parts.append(str(results / CORE_FILE_FOR_JVM_1C[bench]))

            if core == 86:
                primary = ctx_rows.get((bench, 86), primary)
                tlb = ctx4_rows.get((bench, 86))
                if primary:
                    label_parts.append(str(ctx_csv))
                if tlb:
                    label_parts.append(f"tlb={ctx4_csv}")

            if not label_parts and existing and existing.get("SourceCSV", ""):
                label_parts = [existing.get("SourceCSV", "")]

            row = build_row(
                benchmark=bench,
                mode=mode,
                existing=existing,
                primary=primary,
                tlb_source=tlb,
                source_label="|".join(label_parts) if label_parts else "preserved_existing",
            )
            if row:
                updates.append(row)

    # Non-JVM shared rows.
    for bench, filename in NON_JVM.items():
        existing = existing_map.get((bench, "shared"))
        src = read_single_csv(results / filename)
        if src:
            rc = safe_int(src.get("ReturnCode", "1"), 1)
            inst = safe_float(src.get("Instructions", "0"), 0.0)
            if rc == 0 and inst > 0:
                row = build_row(
                    benchmark=bench,
                    mode="shared",
                    existing=existing,
                    primary=src,
                    tlb_source=None,
                    source_label=str(results / filename),
                )
                if row:
                    updates.append(row)
                continue

        if existing and safe_float(existing.get("Instructions", "0"), 0.0) > 0.0:
            updates.append(existing)

    merged = upsert_rows(existing_rows, updates)
    write_rows(out_csv, merged)

    print(f"[ok] saved {out_csv}")
    print(f"[ok] rows={len(merged)}")


if __name__ == "__main__":
    main()
