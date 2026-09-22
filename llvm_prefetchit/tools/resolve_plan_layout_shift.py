#!/usr/bin/env python3
"""Rewrite a plan's targets to the layout-compensated offsets the pass emitted.

The pass writes `<plan>.shifts.json` (index, byte_offset, layout_shift) next to
the plan it consumed. This tool applies those shifts to `target.symbol_offset`,
`target.addr` and `target.cacheline64`, producing a plan that describes the
*injected* binary, so `validate_prefetch_asm.py` can check exact addresses.

    resolve_plan_layout_shift.py --plan P.json [--shifts P.json.shifts.json] --output P.resolved.json

Without a sidecar (`--replicate`), the shift is recomputed from the plan with
the pass rule (7 bytes per rip-relative prefetch injected at a site offset
below the target offset in the target's function); this is exact only when
the pass reported `duplicate=0`.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def to_int(v) -> int | None:
    try:
        return int(str(v), 0)
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", type=Path, required=True)
    ap.add_argument("--shifts", type=Path, help="default: <plan>.shifts.json")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--replicate", action="store_true", help="recompute shifts from the plan instead of the sidecar")
    ap.add_argument("--prefetch-bytes", type=int, default=7)
    a = ap.parse_args()

    plan = json.loads(a.plan.read_text())
    inj = plan.get("injections", [])
    shifts: dict[int, int] = {}
    if not a.replicate:
        sidecar = a.shifts or Path(str(a.plan) + ".shifts.json")
        if not sidecar.exists():
            raise SystemExit(f"[err] no sidecar {sidecar}; rebuild with the compensating pass or use --replicate")
        for row in json.loads(sidecar.read_text()):
            shifts[int(row["index"])] = int(row["layout_shift"])
    else:
        offs_default = plan.get("prefetch", {}).get("byte_offsets", [0])
        sites = defaultdict(list)
        for i in inj:
            so = to_int(i["site"].get("symbol_offset"))
            if so is None:
                continue
            n = len(i.get("prefetch", {}).get("byte_offsets") or offs_default)
            sites[i["site"].get("mangled", "")].append((so, n * a.prefetch_bytes))
        for v in sites.values():
            v.sort()
        for idx, i in enumerate(inj):
            to = to_int(i["target"].get("symbol_offset"))
            fn = i["target"].get("mangled", "")
            if to is None or fn not in sites:
                continue
            shifts[idx] = sum(b for off, b in sites[fn] if off < to)

    applied = 0
    for idx, i in enumerate(inj):
        sh = shifts.get(idx, 0)
        if not sh:
            continue
        t = i["target"]
        so = to_int(t.get("symbol_offset"))
        if so is not None:
            t["symbol_offset"] = hex(so + sh)
        ad = to_int(t.get("addr"))
        if ad is not None:
            t["addr"] = hex(ad + sh)
            t["cacheline64"] = hex((ad + sh) & ~0x3F)
        t["layout_shift"] = sh
        applied += 1
    plan["layout_compensation"] = {"source": "replicate" if a.replicate else "sidecar", "applied": applied}
    a.output.write_text(json.dumps(plan, indent=1))
    print(f"[ok] {a.output}: {applied}/{len(inj)} targets shifted (max {max(shifts.values(), default=0)} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
