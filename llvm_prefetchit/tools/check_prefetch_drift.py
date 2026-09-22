#!/usr/bin/env python3
"""Measure prefetch target drift in an injected binary.

For every rip-relative prefetch inside FUNCTION (default: the Verilator
`eval_nba__0`), find the next call within a few instructions and report
`operand_target - return_continuation`. Callsite/RET plans should show
|drift| <= 64 for (almost) every pair; a linear negative drift means the
symbol+offset targets were not layout-compensated (see docs/design.md).

    check_prefetch_drift.py --binary SIM [--function SYM] [--max-pairs N]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

INSN_RE = re.compile(r"^\s*([0-9a-f]+):\s+(\S+)\s*(.*)$")
DISP_RE = re.compile(r"(-?0x[0-9a-f]+)\(%rip\)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--function", default="_Z35VTestDriver___024root___eval_nba__0P21VTestDriver___024root")
    ap.add_argument("--max-pairs", type=int, default=100000)
    ap.add_argument("--window", type=int, default=8, help="instructions to scan after a prefetch for the call")
    ap.add_argument("--nm", default="llvm-nm-19")
    ap.add_argument("--objdump", default="llvm-objdump-19")
    a = ap.parse_args()

    nm = subprocess.run([a.nm, "-S", "--defined-only", a.binary], capture_output=True, text=True, check=True).stdout
    sym = next((l.split() for l in nm.splitlines() if l.split()[-1] == a.function), None)
    if not sym:
        sys.exit(f"[err] symbol {a.function} not found")
    addr, size = int(sym[0], 16), int(sym[1], 16)
    dis = subprocess.run([a.objdump, "-d", "--no-show-raw-insn", f"--start-address={addr:#x}", f"--stop-address={addr + size:#x}", a.binary],
                         capture_output=True, text=True, check=True).stdout
    ins = [(int(m.group(1), 16), m.group(2), m.group(3)) for m in map(INSN_RE.match, dis.splitlines()) if m]
    drift = []
    for i, (pa, mn, op) in enumerate(ins):
        if not mn.startswith("prefetch"):
            continue
        m = DISP_RE.search(op)
        if not m or i + 1 >= len(ins):
            continue
        target = ins[i + 1][0] + int(m.group(1), 16)
        for j in range(i + 1, min(i + 1 + a.window, len(ins) - 1)):
            if ins[j][1].startswith("call"):
                drift.append((pa, target - ins[j + 1][0]))
                break
        if len(drift) >= a.max_pairs:
            break
    if not drift:
        print(f"[warn] no prefetch/call pairs in {a.function}")
        return 1
    ok = sum(1 for _, d in drift if -64 <= d <= 64)
    print(f"function {a.function}: {len(drift)} prefetch→call pairs, {ok} ({100 * ok / len(drift):.1f}%) within ±64 B of the continuation")
    for k in (0, 1, 2, 10, 100, 500, len(drift) - 1):
        if 0 <= k < len(drift):
            print(f"  pair #{k:<5d} at {drift[k][0]:#x}: target - continuation = {drift[k][1]:+d}")
    return 0 if ok >= 0.9 * len(drift) else 2


if __name__ == "__main__":
    raise SystemExit(main())
