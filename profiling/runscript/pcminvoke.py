import argparse
import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

parser = argparse.ArgumentParser(description="Invocation wrapper around pcm-core")
parser.add_argument("-i", "--input", type=str, help="List of counters to track")
parser.add_argument("-o", "--output", type=str, default="out.csv", help="Name of output CSV file")
parser.add_argument("-t", "--timer", type=int, default=None, help="Sampling interval in seconds")
parser.add_argument("-c", "--core", type=int, default=None, help="Pin invoked task to a single core")

parser.add_argument("-w", "--workload-file", type=str, help="Text file with {outputname}:{workload} lines")
parser.add_argument("workload", nargs=argparse.REMAINDER, help="The workload command to run (preceded by --)")

args = parser.parse_args()

if args.input is None:
    parser.error("--input is required")

script_dir = Path(__file__).resolve().parent
profiling_dir = script_dir.parent
config_dir = profiling_dir / "config"
results_dir = profiling_dir / "results"
evt_file = config_dir / "gnr_evt_core.json"

with evt_file.open("r", encoding="utf-8") as fd:
    evtjson = json.load(fd)

ctrs = set()

input_path = Path(args.input)
if not input_path.is_absolute():
    cwd_path = Path.cwd() / input_path
    config_path = config_dir / input_path
    if cwd_path.exists():
        input_path = cwd_path
    elif config_path.exists():
        input_path = config_path
    else:
        input_path = profiling_dir / input_path

with input_path.open(encoding="utf-8") as f:
    for c in f:
        c = c.split("#")[0].strip()
        if len(c) > 0:
            ctrs.add(c)

if (len(ctrs) > 8):
    print("[err] ctrs.txt can specify no more than 8 active counters")

flags = []

for event in evtjson["Events"]:
    if event["EventName"] in ctrs:
        flags.append(f"cpu/umask={event['UMask']},event={event['EventCode']},name={event['EventName']}/")
        ctrs.remove(event["EventName"])

if (len(ctrs) > 0):
    print("[err] unmatched counters! listed below")
    print("---- ")
    print("\n".join(ctrs))
    exit()


tasks = []
if args.workload_file:
    workload_path = Path(args.workload_file)
    if not workload_path.is_absolute():
        cwd_path = Path.cwd() / workload_path
        config_path = config_dir / workload_path
        if cwd_path.exists():
            workload_path = cwd_path
        elif config_path.exists():
            workload_path = config_path
        else:
            workload_path = profiling_dir / workload_path

    with workload_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                out_name, wl_cmd = line.split(":", 1)
                tasks.append((out_name.strip(), wl_cmd.strip()))
elif args.workload:
    wl_args = args.workload
    if wl_args and wl_args[0] == "--":
        wl_args = wl_args[1:]
    if not wl_args:
        parser.error("workload command is missing")
    tasks.append((args.output, " ".join(wl_args)))

if not tasks:
    parser.error("no workload specified; use --workload-file or a workload command")



pcm_core_env = os.environ.get("PCM_CORE_BIN")
local_pcm = (
    profiling_dir.parent
    / "benchmarks"
    / "tools"
    / "pcm-latest-src"
    / "pcm"
    / "build"
    / "bin"
    / "pcm-core"
)
pcm_core_bin = None
if pcm_core_env:
    pcm_core_bin = Path(pcm_core_env)
elif local_pcm.exists():
    pcm_core_bin = local_pcm
else:
    pcm_core_path = shutil.which("pcm-core")
    if pcm_core_path:
        pcm_core_bin = Path(pcm_core_path)

if pcm_core_bin is None:
    raise SystemExit(
        "[err] pcm-core not found. Install Intel PCM or set PCM_CORE_BIN=/abs/path/to/pcm-core"
    )

for out_name, wl_cmd in tasks:
    out_path = Path(out_name)
    if not out_path.is_absolute():
        out_path = results_dir / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = f"{shlex.quote(str(pcm_core_bin))} "
    if args.timer is not None:
        cmd += f"{args.timer} "

    cmd += f"-csv={shlex.quote(str(out_path))}" + " -e ".join(
        [""]+flags) + " -- "

    if args.core is not None:
        print(f"Pinning task(s) to core {args.core}")
        cmd += f"taskset -c {args.core} bash -lc {shlex.quote(wl_cmd)}"
    else:
        cmd += wl_cmd

    print(f"[inf] running {cmd}")
    start = time.monotonic()
    result = subprocess.run(cmd, shell=True, cwd=profiling_dir, check=False)
    elapsed = time.monotonic() - start
    print(f"[inf] done {out_name}: rc={result.returncode} elapsed_sec={elapsed:.2f}")
    if result.returncode != 0:
        raise SystemExit(f"[err] workload failed for {out_name} with rc={result.returncode}")
