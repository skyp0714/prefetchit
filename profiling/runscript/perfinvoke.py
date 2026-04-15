import argparse
import csv
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

parser = argparse.ArgumentParser(description="Invocation wrapper around perf stat")
parser.add_argument("-i", "--input", type=str, required=True, help="Event list file (alias|perf_event)")
parser.add_argument("-o", "--output", type=str, default="out.csv", help="Name of output CSV file")
parser.add_argument("-c", "--core", type=int, default=None, help="Pin invoked task to a single core")
parser.add_argument("-w", "--workload-file", type=str, help="Text file with {outputname}:{workload} lines")
parser.add_argument(
    "--perf-bin",
    type=str,
    default=os.environ.get("PERF_BIN", "perf"),
    help="perf executable path",
)
parser.add_argument(
    "--all-user",
    dest="all_user",
    action="store_true",
    default=os.environ.get("PERF_USER_ONLY", "1") == "1",
    help="Count only user-mode events (default: on, can disable with PERF_USER_ONLY=0)",
)
parser.add_argument(
    "--keep-perfraw",
    dest="keep_perfraw",
    action="store_true",
    default=os.environ.get("KEEP_PERFRAW", "0") == "1",
    help="Keep .perfraw files after CSV row is written (default: delete)",
)
parser.add_argument(
    "--resume",
    dest="resume",
    action="store_true",
    default=os.environ.get("PERFINVOKE_RESUME", "1") == "1",
    help="Skip workload when output CSV already has a successful row",
)
parser.add_argument(
    "--no-resume",
    dest="resume",
    action="store_false",
    help="Always rerun workload even if output CSV already exists",
)
parser.add_argument("workload", nargs=argparse.REMAINDER, help="The workload command to run (preceded by --)")

args = parser.parse_args()

script_dir = Path(__file__).resolve().parent
profiling_dir = script_dir.parent
config_dir = profiling_dir / "config"
results_dir = profiling_dir / "results"
cleanup_script = script_dir / "cleanup_benchmark_orphans.sh"


def resolve_path(path_str: str) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p
    cwd_path = Path.cwd() / p
    config_path = config_dir / p
    if cwd_path.exists():
        return cwd_path
    if config_path.exists():
        return config_path
    return profiling_dir / p


def parse_event_file(path: Path):
    events = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line:
                continue
            if "|" not in line:
                raise ValueError(f"Invalid event line (need alias|perf_event): {line}")
            alias, spec = line.split("|", 1)
            alias = alias.strip()
            spec = spec.strip()
            if not alias or not spec:
                raise ValueError(f"Invalid event line: {line}")
            events.append((alias, spec))
    if not events:
        raise ValueError(f"No events found in {path}")
    return events


def parse_workload_meta(cmd: str):
    tokens = shlex.split(cmd)
    meta = {"PERF_DELAY_MS": "0"}
    kept = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", tok):
            key, value = tok.split("=", 1)
            if key in meta:
                meta[key] = value
            else:
                kept.append(tok)
            i += 1
            continue
        kept.extend(tokens[i:])
        break
    if not kept:
        raise ValueError(f"Workload command is empty after parsing metadata: {cmd}")
    return meta, shlex.join(kept)


def parse_perf_output(path: Path, aliases):
    counts = {a: 0.0 for a in aliases}
    counts["instructions"] = 0.0
    with path.open(encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue
            value = parts[0].strip()
            event = parts[2].strip()
            if event not in counts:
                continue
            if value.startswith("<") or value in ("not counted", "not supported"):
                counts[event] = 0.0
                continue
            value = value.replace(" ", "")
            try:
                counts[event] = float(value)
            except ValueError:
                counts[event] = 0.0
    return counts


def csv_row_completed(path: Path):
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            row = next(reader, None)
    except Exception:
        return False
    if not row:
        return False
    try:
        inst = float(row.get("Instructions", "0") or 0)
        rc = int(float(row.get("ReturnCode", "1") or 1))
    except ValueError:
        return False
    return inst > 0 and rc == 0


tasks = []
if args.workload_file:
    workload_path = resolve_path(args.workload_file)
    with workload_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                raise ValueError(f"Invalid workload line (need out:cmd): {line}")
            out_name, wl_cmd = line.split(":", 1)
            tasks.append((out_name.strip(), wl_cmd.strip()))
elif args.workload:
    wl_args = args.workload
    if wl_args and wl_args[0] == "--":
        wl_args = wl_args[1:]
    if not wl_args:
        parser.error("workload command is missing")
    tasks.append((args.output, " ".join(wl_args)))
else:
    parser.error("no workload specified; use --workload-file or workload command")

event_file = resolve_path(args.input)
events = parse_event_file(event_file)
aliases = [a for a, _ in events]
event_specs = [spec for _, spec in events] + ["instructions"]

for out_name, wl_cmd in tasks:
    meta, run_cmd = parse_workload_meta(wl_cmd)
    delay_ms = int(meta.get("PERF_DELAY_MS", "0"))

    out_path = Path(out_name)
    if not out_path.is_absolute():
        out_path = results_dir / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    perf_raw = out_path.with_suffix(".perfraw")

    if args.resume and csv_row_completed(out_path):
        print(f"[inf] skip {out_name}: completed row already exists in {out_path}")
        continue

    def cleanup_orphans():
        if cleanup_script.exists():
            subprocess.run(
                [str(cleanup_script), "1"],
                cwd=profiling_dir,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    cleanup_orphans()

    perf_cmd = [
        args.perf_bin,
        "stat",
        "--no-big-num",
        "-x,",
        "-o",
        str(perf_raw),
    ]
    if args.all_user:
        perf_cmd.append("--all-user")
    perf_cmd.extend(["-e", ",".join(event_specs)])
    if delay_ms > 0:
        perf_cmd.extend(["-D", str(delay_ms)])
    perf_cmd.append("--")
    if args.core is not None:
        print(f"Pinning task to core {args.core}")
        perf_cmd.extend(["taskset", "-c", str(args.core), "setsid", "bash", "-lc", run_cmd])
    else:
        perf_cmd.extend(["setsid", "bash", "-lc", run_cmd])

    print(f"[inf] running {' '.join(shlex.quote(x) for x in perf_cmd)}")
    start = time.monotonic()
    result = None
    try:
        result = subprocess.run(perf_cmd, cwd=profiling_dir, check=False)
    finally:
        cleanup_orphans()
    elapsed = time.monotonic() - start
    rc = result.returncode if result is not None else 1
    print(f"[inf] done {out_name}: rc={rc} elapsed_sec={elapsed:.2f}")
    if rc != 0:
        raise SystemExit(f"[err] workload failed for {out_name} with rc={rc}")

    counts = parse_perf_output(perf_raw, aliases)
    row = {
        "Benchmark": out_path.stem,
        "Instructions": counts["instructions"],
        "Event0": counts[aliases[0]] if len(aliases) > 0 else 0.0,
        "Event1": counts[aliases[1]] if len(aliases) > 1 else 0.0,
        "Event2": counts[aliases[2]] if len(aliases) > 2 else 0.0,
        "Event3": counts[aliases[3]] if len(aliases) > 3 else 0.0,
        "DelayMS": delay_ms,
        "ElapsedSec": round(elapsed, 3),
        "ReturnCode": result.returncode,
    }

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "Benchmark",
                "Instructions",
                "Event0",
                "Event1",
                "Event2",
                "Event3",
                "DelayMS",
                "ElapsedSec",
                "ReturnCode",
            ],
        )
        writer.writeheader()
        writer.writerow(row)

    if not args.keep_perfraw:
        try:
            perf_raw.unlink(missing_ok=True)
        except OSError:
            pass
