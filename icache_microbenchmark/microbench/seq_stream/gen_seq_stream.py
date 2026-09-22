#!/usr/bin/env python3
"""Stage-1 microbenchmark: software sequential-lookahead prefetch on a straight-line code stream.

Generates one huge straight-line function (Verilator-like: byte loads/stores/ALU on a
small state buffer in %rdi, so data stays in L1D and only the *code* streams through
L2/L3), with `prefetcht1 D(%rip)` inserted every ~S bytes (or a same-length NOP for the
control).  Used to find the lookahead distance D and issue density that turn L2I misses
into hits on this core, independent of Verilator's build time.

    gen_seq_stream.py --code-mb 16 --distance 1024 --spacing 64 --out stream.s [--nop]
"""
import argparse, random

# instruction templates with known encodings (bytes) using %rdi-relative disp32 addressing
TEMPLATES = [
    ("movzbl {o}(%rdi), %eax", 7),
    ("movzbl {o}(%rdi), %ecx", 7),
    ("andb %al, %cl", 2),
    ("orb {o}(%rdi), %cl", 6),
    ("movb %cl, {o}(%rdi)", 6),
    ("movl {o}(%rdi), %edx", 6),
    ("shrl $0x1f, %edx", 3),
    ("xorl %edx, %eax", 2),
    ("movb %al, {o}(%rdi)", 6),
    ("cmpb $0x0, {o}(%rdi)", 7),
    ("sete %cl", 3),
    ("movb %cl, {o}(%rdi)", 6),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-mb", type=float, default=16)
    ap.add_argument("--distance", type=int, default=0, help="lookahead bytes (0 = no prefetch/NOP at all)")
    ap.add_argument("--spacing", type=int, default=64, help="bytes between prefetch sites")
    ap.add_argument("--lines", type=int, default=1)
    ap.add_argument("--nop", action="store_true", help="emit same-length NOPs instead of prefetches (control)")
    ap.add_argument("--state-bytes", type=int, default=16384)
    ap.add_argument("--seed", type=int, default=1)
    # Verilator-like control flow: taken forward jumps (if-guards) and calls to small
    # straight-line helper functions (nba_sequent-like) that return to the next insn.
    ap.add_argument("--jump-every", type=int, default=0, help="bytes between taken forward jumps (0 = none)")
    ap.add_argument("--jump-skip", type=int, default=32, help="bytes skipped by each forward jump")
    ap.add_argument("--call-every", type=int, default=0, help="bytes between calls to helper functions (0 = none)")
    ap.add_argument("--callee-bytes", type=int, default=800, help="helper function size (straight-line)")
    ap.add_argument("--callees", type=int, default=2000, help="number of distinct helper functions (called round-robin)")
    ap.add_argument("--burst-lines", type=int, default=0, help="prefetch the callee's first L lines before each call (0 = off)")
    ap.add_argument("--burst-lead", type=int, default=0, help="issue the burst this many bytes before the call")
    ap.add_argument("--data-mb", type=float, default=0, help="stream a data buffer of this size alongside the code (advance %rdi 64 B per ~64 B of code)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    total = int(a.code_mb * 1024 * 1024)
    out = [".text", ".globl stream_fn", ".type stream_fn,@function", ".p2align 6", "stream_fn:"]
    pos = 0
    next_site = 0
    nsites = 0
    next_jump = a.jump_every
    next_call = a.call_every
    burst_done = False
    next_data = 64
    labels = 0
    while pos < total:
        if a.jump_every and pos >= next_jump:
            labels += 1
            out.append(f"  jmp .Lj{labels}")
            pos += 5
            skipped = 0
            while skipped < a.jump_skip:
                t, n = rnd.choice(TEMPLATES)
                out.append("  " + t.format(o=rnd.randrange(0x100, a.state_bytes - 8)))
                skipped += n
            pos += skipped
            out.append(f".Lj{labels}:")
            next_jump += a.jump_every
        if a.call_every and a.burst_lines and pos >= next_call - a.burst_lead and not burst_done:
            h = (next_call // a.call_every) % a.callees
            for l in range(a.burst_lines):
                out.append("  .byte 0x0f,0x1f,0x80,0x00,0x00,0x00,0x00" if a.nop else f"  prefetcht1 helper_{h}+{64*l}(%rip)")
                pos += 7
            burst_done = True
        if a.call_every and pos >= next_call:
            out.append(f"  call helper_{(next_call // a.call_every) % a.callees}")
            pos += 5
            next_call += a.call_every
            burst_done = False
        if a.data_mb and pos >= next_data:
            out.append("  addq $64, %rdi")
            pos += 4
            next_data += 64
        if a.distance and pos >= next_site:
            for l in range(a.lines):
                if a.nop:
                    out.append("  .byte 0x0f,0x1f,0x80,0x00,0x00,0x00,0x00")
                else:
                    out.append(f"  prefetcht1 {a.distance + 64 * l}(%rip)")
                pos += 7
            nsites += 1
            next_site += a.spacing
        t, n = rnd.choice(TEMPLATES)
        out.append("  " + t.format(o=rnd.randrange(0x100, a.state_bytes - 8)))
        pos += n
    out += ["  ret", ".size stream_fn, .-stream_fn"]
    if a.call_every:
        for c in range(a.callees):
            out += [".p2align 4", f"helper_{c}:"]
            b = 0
            hpos = 0
            hnext = 0
            while b < a.callee_bytes:
                if a.distance and hpos >= hnext:
                    for l in range(a.lines):
                        out.append("  .byte 0x0f,0x1f,0x80,0x00,0x00,0x00,0x00" if a.nop else f"  prefetcht1 {a.distance + 64 * l}(%rip)")
                        b += 7; hpos += 7
                    nsites += 1
                    hnext += a.spacing
                t, n = rnd.choice(TEMPLATES)
                out.append("  " + t.format(o=rnd.randrange(0x100, a.state_bytes - 8)))
                b += n; hpos += n
            out.append("  ret")
    out += [f".section .note.GNU-stack,\"\",@progbits"]
    with open(a.out, "w") as f:
        f.write("\n".join(out) + "\n")
    print(f"[ok] {a.out}: ~{pos/1048576:.1f} MB code, {nsites} prefetch sites x {a.lines} lines, "
          f"{'NOP' if a.nop else 'prefetcht1'} D={a.distance} S={a.spacing}")


if __name__ == "__main__":
    main()
