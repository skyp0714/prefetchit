#!/usr/bin/env python3
"""Create a same-layout NOP control copy of a binary: every prefetcht0/t1/t2/
prefetchnta instruction is replaced in-place with an equal-length multi-byte
NOP, so code layout and size are identical and only the prefetch semantics
are removed. Used for layout-controlled prefetch-vs-NOP A/B evaluations."""

import argparse
import shutil
import subprocess
import sys

MULTI_NOP = {
    1: bytes([0x90]),
    2: bytes([0x66, 0x90]),
    3: bytes([0x0F, 0x1F, 0x00]),
    4: bytes([0x0F, 0x1F, 0x40, 0x00]),
    5: bytes([0x0F, 0x1F, 0x44, 0x00, 0x00]),
    6: bytes([0x66, 0x0F, 0x1F, 0x44, 0x00, 0x00]),
    7: bytes([0x0F, 0x1F, 0x80, 0x00, 0x00, 0x00, 0x00]),
    8: bytes([0x0F, 0x1F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x00]),
}


def text_section(binary: str):
    out = subprocess.check_output(["readelf", "-SW", binary], text=True)
    for line in out.splitlines():
        if " .text " in line:
            parts = line.split()
            idx = parts.index(".text")
            addr = int(parts[idx + 2], 16)
            off = int(parts[idx + 3], 16)
            size = int(parts[idx + 4], 16)
            return addr, off, size
    raise SystemExit("no .text section found")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument(
        "--mnemonics", default="prefetcht0,prefetcht1,prefetcht2,prefetchnta"
    )
    args = ap.parse_args()

    mnemonics = tuple(m.strip() for m in args.mnemonics.split(",") if m.strip())
    vaddr, off, size = text_section(args.input)
    shutil.copy2(args.input, args.output)

    dis = subprocess.check_output(
        ["objdump", "-d", "--section=.text", args.input], text=True
    )
    patches = []
    lines = dis.splitlines()
    for i, line in enumerate(lines):
        if not any(f"\t{m} " in line or line.rstrip().endswith(m) for m in mnemonics):
            continue
        head, _, _ = line.partition("\t")
        addr = int(head.strip().rstrip(":"), 16)
        _, _, rest = line.partition("\t")
        byte_str, _, _ = rest.partition("\t")
        nbytes = len(byte_str.split())
        # objdump wraps byte listings at 7 bytes/line; absorb continuation
        # lines (address + bytes, no mnemonic) so 8-byte prefetches are
        # patched in full
        j = i + 1
        while j < len(lines):
            cont = lines[j]
            parts = cont.split("\t")
            if (len(parts) >= 2 and parts[0].strip().endswith(":")
                    and (len(parts) == 2 or not parts[2].strip())
                    and parts[1].strip()
                    and all(len(b) == 2 for b in parts[1].split())):
                nbytes += len(parts[1].split())
                j += 1
            else:
                break
        if nbytes not in MULTI_NOP:
            print(f"[warn] unsupported length {nbytes} at {hex(addr)}", file=sys.stderr)
            continue
        patches.append((addr, nbytes))

    with open(args.output, "r+b") as handle:
        for addr, nbytes in patches:
            file_off = off + (addr - vaddr)
            handle.seek(file_off)
            existing = handle.read(nbytes)
            body = existing
            # skip REX/segment/operand-size prefixes (e.g. 41 0f 18 for
            # r8-r15 base registers) before the 0F 18 opcode check
            while body and body[0] in (0x66, 0x67, 0x2E, 0x3E, 0x26, 0x64,
                                       0x65, 0x36) or (body and 0x40 <= body[0] <= 0x4F):
                body = body[1:]
            if not body.startswith(bytes([0x0F, 0x18])):
                print(
                    f"[warn] bytes at {hex(addr)} are not a prefetch: "
                    f"{existing.hex()}", file=sys.stderr
                )
                continue
            handle.seek(file_off)
            handle.write(MULTI_NOP[nbytes])

    check = subprocess.check_output(["objdump", "-d", args.output], text=True)
    remaining = sum(check.count(m) for m in mnemonics)
    print(f"[ok] patched={len(patches)} remaining_prefetch_mnemonics={remaining}")


if __name__ == "__main__":
    main()
