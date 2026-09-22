#!/usr/bin/env python3
"""Unified profile-free prefetch planner: one command, choose the branch kinds.

    static_plan.py --binary SIM --kinds ret            # RET/callsite family (Verilator 1.078x)
    static_plan.py --binary SIM --kinds cond           # COND family (tail-sparse/fetch-gap ...)
    static_plan.py --binary SIM --kinds ret,cond       # both, merged into one plan

The output is a single ``prefetchit.plan.v1`` JSON that ``opt-19
-passes=prefetchit-inject -prefetchit-plan=...`` consumes (or
``llvm_prefetchit/scripts/static/run_prefetcht1_l2_eval.sh EXTERNAL_PLAN=...``).
Selection never reads a profile; ``--trace-dir`` (optional, repeatable) is
only used to score the selected RET targets/sites against PEBS/LBR truth.

The per-kind engines are unchanged (``tools/ret/``, ``tools/cond/``); this
driver only wires them together and merges the plans with
``llvm_prefetchit/tools/merge_prefetch_plans.py``.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RET = HERE / "ret"
COND = HERE / "cond"
LLVM_TOOLS = HERE.parent.parent / "llvm_prefetchit" / "tools"


def run(cmd: list[str], log: Path) -> None:
    print("[run]", " ".join(str(c) for c in cmd), flush=True)
    with log.open("w", encoding="utf-8") as f:
        proc = subprocess.run([str(c) for c in cmd], stdout=f, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        sys.stderr.write(log.read_text(errors="replace")[-4000:])
        raise SystemExit(f"[err] step failed (rc={proc.returncode}): {log}")


def count_injections(plan: Path) -> int:
    return len(json.loads(plan.read_text()).get("injections", []))


def plan_ret(a: argparse.Namespace, out: Path, traces: list[str]) -> Path:
    targets = out / "ret_targets.csv"
    if not targets.exists():
        run([sys.executable, RET / "static_return_target_candidates.py",
             "--binary", a.binary, "--out-csv", targets, "--mode", a.ret_mode,
             "--external-penalty", a.ret_external_penalty, "--one-shot-penalty", a.ret_one_shot_penalty,
             "--synthetic-external-size", "512", "--ras-size", a.ret_ras_size, "--max-depth", "96",
             "--nested-base-count", a.ret_nested_base_count,
             "--nm", a.nm, "--objdump", a.objdump], out / "ret_targets.log")
    sites_dir = out / "ret_sites"
    site_csv = sites_dir / "site_plans" / f"top{a.ret_top_k}_budget{a.ret_site_budget}_{a.ret_site_strategy}.csv"
    if not site_csv.exists():
        run([sys.executable, RET / "static_injection_site_experiment.py",
             "--binary", a.binary, "--targets", targets, *traces, "--out-dir", sites_dir,
             "--top-k", a.ret_top_k, "--strategy", a.ret_site_strategy,
             "--site-budget-list", a.ret_site_budget, "--nm", a.nm, "--objdump", a.objdump],
            out / "ret_sites.log")
    plan = out / "ret.plan.json"
    run([sys.executable, RET / "static_site_plan_to_prefetch_plan.py",
         "--binary", a.binary, "--targets", targets, "--site-plan", site_csv, "--output", plan,
         "--top-k", a.ret_top_k, "--prefetch-mnemonic", a.prefetch_mnemonic,
         "--prefetch-byte-offsets", a.prefetch_byte_offsets, "--label", f"{a.label}_ret",
         "--nm", a.nm, "--addr2line", a.addr2line, "--pretty"], out / "ret_plan.log")
    return plan


def plan_cond(a: argparse.Namespace, out: Path) -> Path:
    cand = out / f"cond_{a.cond_mode}.csv"
    if not cand.exists():
        run([sys.executable, COND / "static_cond_target_candidates.py",
             "--binary", a.binary, "--out-csv", cand, "--mode", a.cond_mode,
             "--candidate-targets", a.cond_candidate_targets,
             "--target-window-lines", a.cond_target_window_lines,
             "--nm", a.nm, "--objdump", a.objdump], out / "cond_candidates.log")
    plan = out / "cond.plan.json"
    cmd = [sys.executable, COND / "static_cond_candidates_to_plan.py",
           "--binary", a.binary, "--candidates", cand, "--output", plan, "--top-k", a.cond_top_k,
           "--site-policy", a.cond_site_policy, "--prev-branches", a.cond_prev_branches,
           "--site-budget-per-target", a.cond_site_budget, "--prefetch-mnemonic", a.prefetch_mnemonic,
           "--prefetch-byte-offsets", a.prefetch_byte_offsets, "--label", f"{a.label}_cond",
           "--nm", a.nm, "--objdump", a.objdump, "--addr2line", a.addr2line]
    if a.cond_site_branch_types:
        cmd += ["--site-branch-types", a.cond_site_branch_types]
    if a.cond_skip_same_cacheline:
        cmd.append("--skip-same-cacheline-site-target")
    run(cmd, out / "cond_plan.log")
    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binary", type=Path, required=True, help="baseline binary (symbols + debug info)")
    ap.add_argument("--kinds", default="ret", help="comma list of ret,cond")
    ap.add_argument("--out-dir", type=Path, required=True, help="work dir for candidates/site CSVs/logs")
    ap.add_argument("--output", type=Path, required=True, help="merged prefetchit.plan.v1 JSON")
    ap.add_argument("--label", default="static")
    ap.add_argument("--trace-dir", action="append", default=[], help="optional PEBS/LBR trace dirs (scoring only)")
    ap.add_argument("--prefetch-mnemonic", default="prefetcht1")
    ap.add_argument("--prefetch-byte-offsets", default="0,64")
    # RET family (static_return_algorithm_v2.md); defaults = the Verilator reference plan
    ap.add_argument("--ret-mode", default="footprint", choices=["combined", "depth", "footprint", "loop", "nested", "nested_rr"])
    ap.add_argument("--ret-top-k", type=int, default=1000)
    ap.add_argument("--ret-site-strategy", default="callsite",
                    help="callsite | callee-ret | distance-Nk | spread-distance-Nk | same-func-calls-Nk | caller-chain-dD | callee-calls-dD | mixed-call-ret-d1")
    ap.add_argument("--ret-site-budget", type=int, default=1)
    ap.add_argument("--ret-ras-size", type=int, default=32)
    ap.add_argument("--ret-external-penalty", type=int, default=5)
    ap.add_argument("--ret-one-shot-penalty", type=int, default=500)
    ap.add_argument("--ret-nested-base-count", type=int, default=3000)
    # COND family (static_cond_algorithm_v1.md); defaults = the best measured COND static point
    ap.add_argument("--cond-mode", default="fetch-gap", help="tail-sparse | fetch-gap | entry-window | span | combined | ...")
    ap.add_argument("--cond-top-k", type=int, default=100000)
    ap.add_argument("--cond-site-policy", default="current", choices=["current", "prev", "current-prev"])
    ap.add_argument("--cond-prev-branches", type=int, default=0)
    ap.add_argument("--cond-site-budget", type=int, default=1)
    ap.add_argument("--cond-candidate-targets", default="both", choices=["taken", "source", "both"])
    ap.add_argument("--cond-target-window-lines", type=int, default=16)
    ap.add_argument("--cond-site-branch-types", default="")
    ap.add_argument("--cond-skip-same-cacheline", action="store_true", default=True)
    ap.add_argument("--nm", default="llvm-nm-19")
    ap.add_argument("--objdump", default="llvm-objdump-19")
    ap.add_argument("--addr2line", default="llvm-addr2line-19")
    a = ap.parse_args()

    kinds = [k.strip() for k in a.kinds.split(",") if k.strip()]
    bad = [k for k in kinds if k not in ("ret", "cond")]
    if bad or not kinds:
        raise SystemExit(f"[err] --kinds must be a subset of ret,cond (got {a.kinds})")
    if not a.binary.exists():
        raise SystemExit(f"[err] missing binary {a.binary}")
    a.out_dir.mkdir(parents=True, exist_ok=True)
    traces = [x for t in a.trace_dir for x in ("--trace-dir", t)]

    plans: list[Path] = []
    if "ret" in kinds:
        plans.append(plan_ret(a, a.out_dir, traces))
    if "cond" in kinds:
        plans.append(plan_cond(a, a.out_dir))

    a.output.parent.mkdir(parents=True, exist_ok=True)
    if len(plans) == 1:
        shutil.copyfile(plans[0], a.output)
    else:
        cmd = [sys.executable, LLVM_TOOLS / "merge_prefetch_plans.py", "--output", a.output, "--label", a.label]
        for p in plans:
            cmd += ["--plan", p]
        run(cmd, a.out_dir / "merge.log")
    for p in plans:
        print(f"[ok] {p.name}: {count_injections(p)} injections")
    print(f"[ok] {a.output}: {count_injections(a.output)} injections (kinds={','.join(kinds)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
