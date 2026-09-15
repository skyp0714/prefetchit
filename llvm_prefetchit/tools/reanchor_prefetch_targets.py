#!/usr/bin/env python3
"""Post-link re-anchoring of injected prefetch targets.

`symbol+offset` targets are baseline-binary offsets. Injecting prefetches
changes code generation inside the function (not only by the injected bytes:
alignment, scheduling, register allocation), so after compilation the planned
offset no longer points at the planned instruction. Instead of trusting
offsets, anchor every target on the *k-th call instruction of its function*:
the pass never adds or removes calls, so the k-th call in the baseline is the
k-th call in the injected binary. For return-continuation targets (RET /
callsite plans) the target is exactly the end of that call; other targets keep
their small delta from the preceding call.

    reanchor_prefetch_targets.py --baseline BASE --binary INJ --plan RESOLVED.json --output OUT

RESOLVED.json is the plan rewritten by tools/resolve_plan_layout_shift.py (its
`target.symbol_offset` is what the pass emitted; `target.layout_shift` recovers
the baseline offset). The output is a byte-patched copy (only disp32 fields of
prefetch instructions change, so layout is identical and NOP twins still hold).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

INSN_RE = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(\S+)?\s*(.*)$")
DISP_RE = re.compile(r"(-?0x[0-9a-f]+)\(%rip\)")
PREFETCH_OPCODES = {b"\x0f\x18", b"\x0f\x0d"}


def to_int(v) -> int | None:
    try:
        return int(str(v), 0)
    except (TypeError, ValueError):
        return None


def symbols(binary: str, nm: str) -> dict[str, tuple[int, int]]:
    out = subprocess.run([nm, "-S", "--defined-only", binary], capture_output=True, text=True, check=True).stdout
    syms = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[2] in "tTwW":
            syms[parts[3]] = (int(parts[0], 16), int(parts[1], 16))
    return syms


def disassemble(binary: str, objdump: str, start: int, end: int):
    out = subprocess.run([objdump, "-d", f"--start-address={start:#x}", f"--stop-address={end:#x}", binary],
                         capture_output=True, text=True, check=True).stdout
    ins = []
    for line in out.splitlines():
        m = INSN_RE.match(line)
        if not m:
            continue
        addr = int(m.group(1), 16)
        raw = bytes.fromhex(m.group(2).replace(" ", ""))
        mn = m.group(3) or ""
        ins.append((addr, raw, mn, m.group(4)))
    # objdump wraps long instructions over several lines; merge continuation rows (no mnemonic)
    merged = []
    for addr, raw, mn, op in ins:
        if not mn and merged:
            a0, r0, m0, o0 = merged[-1]
            merged[-1] = (a0, r0 + raw, m0, o0)
        else:
            merged.append((addr, raw, mn, op))
    return merged


def text_offset_map(binary: str) -> list[tuple[int, int, int]]:
    out = subprocess.run(["readelf", "-lW", binary], capture_output=True, text=True, check=True).stdout
    segs = []
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0] == "LOAD":
            off, vaddr, _paddr, filesz = (int(x, 16) for x in parts[1:5])
            segs.append((vaddr, vaddr + filesz, off - vaddr))
    return segs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--plan", type=Path, required=True, help="resolved plan (tools/resolve_plan_layout_shift.py)")
    ap.add_argument("--output", required=True)
    ap.add_argument("--nm", default="llvm-nm-19")
    ap.add_argument("--objdump", default="llvm-objdump-19")
    ap.add_argument("--max-delta", type=int, default=4096, help="give up on a target farther than this from its anchor call")
    a = ap.parse_args()

    plan = json.loads(a.plan.read_text())
    offs_default = plan.get("prefetch", {}).get("byte_offsets", [0])
    base_syms = symbols(a.baseline, a.nm)
    new_syms = symbols(a.binary, a.nm)

    # emitted operand address (new binary) -> (function, baseline target offset)
    wanted: dict[int, tuple[str, int]] = {}
    for inj in plan.get("injections", []):
        t = inj["target"]
        fn = t.get("mangled", "")
        emitted = to_int(t.get("symbol_offset"))
        if fn not in new_syms or emitted is None:
            continue
        base_off = emitted - int(t.get("layout_shift", 0))
        for bo in inj.get("prefetch", {}).get("byte_offsets") or offs_default:
            wanted[new_syms[fn][0] + emitted + bo] = (fn, base_off, bo)
    functions = sorted({fn for fn, _, _ in wanted.values()})
    # prefetches live in the *site* functions; scan those too (PGO sites are spread over callers)
    site_functions = sorted({inj["site"].get("mangled", "") for inj in plan.get("injections", [])} & set(new_syms))
    print(f"[inf] {len(wanted)} distinct emitted operands over {len(functions)} target functions; scanning {len(set(site_functions) | set(functions))} functions for prefetches")

    # disassemble both binaries per function; index calls
    anchors_new: dict[str, list[tuple[int, int]]] = {}   # fn -> [(call_addr, call_end)]
    anchors_base: dict[str, list[tuple[int, int]]] = {}
    for fn in functions:
        for label, binary, syms, store in (("base", a.baseline, base_syms, anchors_base), ("new", a.binary, new_syms, anchors_new)):
            start, size = syms[fn]
            ins = disassemble(binary, a.objdump, start, start + size)
            store[fn] = [(addr, addr + len(raw)) for addr, raw, mn, _ in ins if mn.startswith("call")]
        nb, nn = len(anchors_base[fn]), len(anchors_new[fn])
        print(f"[inf] {fn[:60]}: calls base={nb} new={nn}" + ("" if nb == nn else "  <-- MISMATCH, skipping"))
        if nb != nn:
            anchors_base.pop(fn); anchors_new.pop(fn)

    # compute new target for every wanted operand
    import bisect
    fixes: dict[int, int] = {}
    skipped = 0
    for emitted_addr, (fn, base_off, bo) in wanted.items():
        if fn not in anchors_base:
            skipped += 1; continue
        base_target = base_syms[fn][0] + base_off
        ends = [e for _, e in anchors_base[fn]]
        k = bisect.bisect_right(ends, base_target) - 1     # last call whose end <= target
        if k < 0:
            skipped += 1; continue
        delta = base_target - ends[k]
        if delta > a.max_delta:
            skipped += 1; continue
        fixes[emitted_addr] = anchors_new[fn][k][1] + delta + bo
    print(f"[inf] re-anchored {len(fixes)} operands, skipped {skipped}")

    # patch every prefetch whose operand address is in `fixes`
    shutil.copy(a.binary, a.output)  # copy() keeps the executable bit
    segs = text_offset_map(a.output)
    def file_off(vaddr: int) -> int:
        for lo, hi, delta in segs:
            if lo <= vaddr < hi:
                return vaddr + delta
        raise SystemExit(f"[err] vaddr {vaddr:#x} not in a LOAD segment")
    data = bytearray(Path(a.output).read_bytes())
    patched = unchanged = seen = unmatched = 0
    for fn in sorted(set(site_functions) | set(functions)):
        if fn not in new_syms:
            continue
        start, size = new_syms[fn]
        for addr, raw, mn, op in disassemble(a.binary, a.objdump, start, start + size):
            if not mn.startswith("prefetch"):
                continue
            m = DISP_RE.search(op)
            if not m:
                continue
            operand = addr + len(raw) + int(m.group(1), 16)
            seen += 1
            if operand not in fixes:
                unmatched += 1
                continue
            new_disp = fixes[operand] - (addr + len(raw))
            if new_disp == int(m.group(1), 16):
                unchanged += 1; continue
            # disp32 is the last 4 bytes of the instruction (0F 18 /r disp32, optional REX prefix)
            pos = file_off(addr) + len(raw) - 4
            data[pos:pos + 4] = struct.pack("<i", new_disp)
            patched += 1
    Path(a.output).write_bytes(data)
    print(f"[ok] {a.output}: {seen} prefetches seen, patched {patched}, {unchanged} already exact, {unmatched} not in plan map")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
