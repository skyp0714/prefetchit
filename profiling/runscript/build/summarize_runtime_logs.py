import csv
import re
from pathlib import Path

profiling_dir = Path(__file__).resolve().parent.parent.parent
results_dir = profiling_dir / "results"
log_dir = results_dir / "logs"
out_dir = results_dir / "benchmark_profiling" / "csv"
out_dir.mkdir(parents=True, exist_ok=True)

targets = [
    ("tomcat", "tomcat.log", "tomcat.wall_seconds"),
    ("finagle-http", "finagle-http.log", "finagle-http.wall_seconds"),
    ("finagle-chirper", "finagle-chirper.log", "finagle-chirper.wall_seconds"),
    ("verilator-qsort", "verilator-qsort.log", "verilator-qsort.wall_seconds"),
    ("602.gcc_s", "spec_602_gcc_s.log", "spec_602_gcc_s.wall_seconds"),
    ("605.mcf_s", "spec_605_mcf_s.log", "spec_605_mcf_s.wall_seconds"),
    ("641.leela_s", "spec_641_leela_s.log", "spec_641_leela_s.wall_seconds"),
]


def read_wall(path: Path):
    if not path.exists():
        return ""
    txt = path.read_text(encoding="utf-8").strip()
    return txt


def parse_detail(name: str, text: str):
    if name == "tomcat":
        m = re.search(r"PASSED in ([0-9]+) msec", text)
        return f"dacapo_pass_ms={m.group(1)}" if m else ""
    if name in ("finagle-http", "finagle-chirper"):
        vals = [float(v) for v in re.findall(r"iteration \d+ completed \(([0-9.]+) ms\)", text)]
        if not vals:
            return ""
        return f"iters={len(vals)} iter_sum_ms={sum(vals):.3f}"
    if name == "verilator-qsort":
        mcycle = re.search(r"mcycle\s*=\s*([0-9]+)", text)
        minstret = re.search(r"minstret\s*=\s*([0-9]+)", text)
        details = []
        if mcycle:
            details.append(f"mcycle={mcycle.group(1)}")
        if minstret:
            details.append(f"minstret={minstret.group(1)}")
        return " ".join(details)
    if name in ("602.gcc_s", "605.mcf_s", "641.leela_s"):
        m = re.search(r";\s*([0-9]+)\s+total seconds elapsed", text)
        return f"spec_elapsed_s={m.group(1)}" if m else ""
    return ""


rows = []
for name, log_name, wall_name in targets:
    log_path = log_dir / log_name
    wall_path = log_dir / wall_name
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    rows.append(
        {
            "benchmark": name,
            "wall_seconds": read_wall(wall_path),
            "detail": parse_detail(name, text),
            "log_file": str(log_path),
        }
    )

csv_path = out_dir / "runtime_summary.csv"
with csv_path.open("w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["benchmark", "wall_seconds", "detail", "log_file"])
    writer.writeheader()
    writer.writerows(rows)

txt_path = out_dir / "runtime_summary.txt"
with txt_path.open("w", encoding="utf-8") as f:
    f.write("Benchmark Runtime Summary\n")
    f.write("=========================\n")
    for row in rows:
        f.write(f"{row['benchmark']}\n")
        f.write(f"  wall_seconds: {row['wall_seconds'] or 'n/a'}\n")
        f.write(f"  detail: {row['detail'] or 'n/a'}\n")
        f.write(f"  log_file: {row['log_file']}\n")

print(f"Saved: {csv_path}")
print(f"Saved: {txt_path}")
