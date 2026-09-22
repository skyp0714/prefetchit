#!/usr/bin/env python3
"""Where do L2I misses land relative to the last taken branch?  (sample-IP truth)

Uses lbr_raw_dump.txt (runtime addresses) + lbr_symbolic_dump.txt (first line only,
to recover the PIE load base) so every sample's precise IP can be compared with
LBR[0].to (= the address the trace-to-plan tools treat as the miss target).

    miss_stream_characterization.py --binary SIM --trace-dir T ... --out-dir D
"""
from __future__ import annotations

import argparse
import bisect
import csv
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

SYM_OFF_RE = re.compile(r"^(.*)\+0x([0-9a-fA-F]+)$")
FUNC_RE = re.compile(r"^([0-9a-fA-F]+)\s+<(.+)>:$")
INSN_RE = re.compile(r"^\s*([0-9a-fA-F]+):\s*(\S+)\s*(.*?)(?:\s+#.*)?$")
TEXT_TYPES = set("tTwW")


def nm_index(binary, nm):
    out = subprocess.run([nm, "-S", "-n", "--defined-only", "--demangle", str(binary)], check=True, text=True,
                         capture_output=True, errors="replace").stdout
    syms = []
    for line in out.splitlines():
        p = line.split(None, 3)
        if len(p) == 4 and p[2] in TEXT_TYPES:
            try:
                syms.append((int(p[0], 16), int(p[1], 16), p[3].strip()))
            except ValueError:
                pass
    syms.sort()
    return syms


def load_base(trace_dir: Path, syms):
    by_name = {n: a for a, _s, n in syms}
    by_noargs = {}
    for a, _s, n in syms:
        by_noargs.setdefault(n.split("(", 1)[0], a)
    with (trace_dir / "lbr_raw_dump.txt").open(errors="replace") as fr, (trace_dir / "lbr_symbolic_dump.txt").open(errors="replace") as fs:
        for raw, sym in zip(fr, fs):
            rt = raw.split()
            stt = sym.split()
            if len(rt) < 3 or len(stt) < 2:
                continue
            e_raw = [t for t in rt[1:] if t.count("/") >= 7]
            e_sym = [t for t in stt[1:] if t.count("/") >= 7]
            if len(e_raw) < 2 or len(e_sym) < 2 or len(e_raw) != len(e_sym):
                continue
            # entry 0 has the sample symbol glued to it in perf's output; use entries 1.. for the base
            for k in range(1, len(e_sym)):
                m = SYM_OFF_RE.match(e_sym[k].split("/")[0])
                if not m:
                    continue
                name, off = m.group(1), int(m.group(2), 16)
                base_addr = by_name.get(name) or by_noargs.get(name.split("(", 1)[0])
                if base_addr is None:
                    continue
                base = int(e_raw[k].split("/")[0], 16) - (base_addr + off)
                if base % 4096 == 0:   # PIE load base is page aligned; skip DSO/kernel entries
                    return base
    raise SystemExit(f"could not derive load base for {trace_dir}")


class Text:
    """instruction map for the functions we care about: call sites, taken-branch sites."""

    def __init__(self, binary, objdump, syms):
        self.addrs = [s[0] for s in syms]
        self.sizes = [s[1] for s in syms]
        self.names = [s[2] for s in syms]
        self.calls: list[int] = []      # addresses of call instructions
        self.call_next: dict[int, int] = {}
        self.branches: list[int] = []   # any control transfer
        proc = subprocess.Popen([objdump, "-d", "--no-show-raw-insn", "--section=.text", str(binary)], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, errors="replace")
        pending_call = None
        for line in proc.stdout:
            im = INSN_RE.match(line)
            if not im:
                continue
            addr = int(im.group(1), 16)
            mn = im.group(2)
            if pending_call is not None:
                self.call_next[pending_call] = addr
                pending_call = None
            if mn.startswith("call"):
                self.calls.append(addr)
                pending_call = addr
                self.branches.append(addr)
            elif mn.startswith("j") or mn.startswith("ret"):
                self.branches.append(addr)
        proc.wait()
        self.calls.sort()
        self.branches.sort()

    def func(self, addr):
        i = bisect.bisect_right(self.addrs, addr) - 1
        if i >= 0 and addr < self.addrs[i] + max(self.sizes[i], 1):
            return self.names[i]
        return None

    def next_branch_after(self, addr):
        i = bisect.bisect_right(self.branches, addr)
        return self.branches[i] if i < len(self.branches) else None

    def next_call_after(self, addr):
        i = bisect.bisect_right(self.calls, addr)
        return self.calls[i] if i < len(self.calls) else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--trace-dir", type=Path, action="append", required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--nm", default="llvm-nm-19")
    ap.add_argument("--objdump", default="llvm-objdump-19")
    a = ap.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)
    syms = nm_index(a.binary, a.nm)
    text = Text(a.binary, a.objdump, syms)

    hist = defaultdict(Counter)        # type -> line delta (ip line - to0 line) bucket
    same_func = Counter()
    n_type = Counter()
    ret_delta_bytes = []
    ret_run_to_next_branch = Counter()  # bytes from continuation to next static branch, bucketed
    ip_lines_after_ret = Counter()      # ip line - continuation line for RET (exact small values)
    call_ip_lines = Counter()
    from_to_same_line = Counter()
    for td in a.trace_dir:
        base = load_base(td, syms)
        print(f"[ok] {td.name}: load base {base:#x} (page aligned: {base % 4096 == 0})")
        with (td / "lbr_raw_dump.txt").open(errors="replace") as f:
            for line in f:
                t = line.split()
                if len(t) < 3:
                    continue
                try:
                    ip = int(t[0], 16) - base
                except ValueError:
                    continue
                e = [x for x in t[1:] if x.count("/") >= 7]
                if not e:
                    continue
                p = e[0].split("/")
                try:
                    frm = int(p[0], 16) - base
                    to = int(p[1], 16) - base
                except ValueError:
                    continue
                typ = p[6].upper()
                n_type[typ] += 1
                d = (ip >> 6) - (to >> 6)
                b = "<0" if d < 0 else (str(d) if d <= 4 else ("5-8" if d <= 8 else ("9-16" if d <= 16 else ">16")))
                hist[typ][b] += 1
                if text.func(ip) == text.func(to):
                    same_func[typ] += 1
                if (frm >> 6) == (to >> 6):
                    from_to_same_line[typ] += 1
                if typ == "RET":
                    ret_delta_bytes.append(ip - to)
                    nb = text.next_branch_after(to)
                    run = (nb - to) if nb else 0
                    ret_run_to_next_branch["<64" if run < 64 else ("64-255" if run < 256 else ("256-1023" if run < 1024 else ("1-4K" if run < 4096 else ">4K")))] += 1
                    ip_lines_after_ret[min(max(d, -1), 20)] += 1
                elif typ == "CALL":
                    call_ip_lines[min(max(d, -1), 20)] += 1
    total = sum(n_type.values())
    print(f"[ok] samples={total}")
    rows = []
    for typ, c in sorted(n_type.items(), key=lambda kv: -kv[1]):
        h = hist[typ]
        row = {"type": typ, "share_pct": f"{100 * c / total:.1f}", "ip_on_to0_line_pct": f"{100 * h['0'] / c:.1f}",
               "ip_1_line_after_pct": f"{100 * h['1'] / c:.1f}", "ip_2to4_pct": f"{100 * (h['2'] + h['3'] + h['4']) / c:.1f}",
               "ip_5to16_pct": f"{100 * (h['5-8'] + h['9-16']) / c:.1f}", "ip_gt16_pct": f"{100 * h['>16'] / c:.1f}",
               "ip_before_pct": f"{100 * h['<0'] / c:.1f}", "same_func_pct": f"{100 * same_func[typ] / c:.1f}",
               "from_to_same_line_pct": f"{100 * from_to_same_line[typ] / c:.1f}"}
        rows.append(row)
        print(row)
    with (a.out_dir / "miss_vs_lbr0_by_type.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("[ok] RET: ip line - continuation line:", sorted(ip_lines_after_ret.items()))
    print("[ok] RET: static straight-line run from continuation to next branch:", dict(ret_run_to_next_branch))
    print("[ok] CALL: ip line - callee entry line:", sorted(call_ip_lines.items()))
    # weighted average of lines missed after RET/CALL — tells how many +64 offsets a callsite prefetch needs
    for name, cnt in (("RET", ip_lines_after_ret), ("CALL", call_ip_lines)):
        tot = sum(cnt.values())
        cum = 0
        out = []
        for k in range(0, 9):
            cum += cnt.get(k, 0)
            out.append(f"<= +{k}: {100 * cum / tot:.1f}%")
        print(f"[ok] {name} cumulative coverage by lines from LBR[0].to: " + ", ".join(out))


if __name__ == "__main__":
    raise SystemExit(main())
