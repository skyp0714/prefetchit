#!/usr/bin/env python3
"""Create a same-layout NOP control copy of a binary: every prefetcht0/t1/t2/
prefetchnta instruction is replaced in-place with an equal-length multi-byte
NOP, so code layout and size are identical and only the prefetch semantics
are removed. Used for layout-controlled prefetch-vs-NOP A/B evaluations."""

import argparse
import os
import re
import shutil
import stat
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
    9: bytes([0x66, 0x0F, 0x1F, 0x84, 0x00, 0x00, 0x00, 0x00, 0x00]),
}


def executable_sections(binary: str, section_name=None):
    out = subprocess.check_output(["readelf", "-SW", binary], text=True)
    sections = []
    for line in out.splitlines():
        m = re.search(r'\[\s*\d+\]\s+(\S+)\s+PROGBITS\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+\S+\s+(\S+)', line)
        if m and 'X' in m[5] and (section_name is None or m[1] == section_name):
            sections.append(tuple(int(m[i],16) for i in (2,3,4)))
    if not sections: raise SystemExit("no executable sections found")
    return sections


def selected_prefetch(line, mnemonics, addressing='all'):
    parts = line.split('\t', 2)
    # objdump can print prefixes as separate words: "data16 prefetcht1 ...".
    if len(parts) != 3:
        return False
    instruction = parts[2].split('#', 1)[0]
    if not any(m in instruction.split() for m in mnemonics):
        return False
    if addressing == 'rip':
        return '(%rip)' in instruction
    if addressing == 'register':
        return '(%rip)' not in instruction and '(' in instruction and '%' in instruction
    return True


def disassemble(binary, symbol=None, section=None):
    section_args = ['-j', section] if section else []
    llvm = shutil.which("llvm-objdump-19") if symbol else None
    if llvm:
        symbols = symbol if isinstance(symbol, list) else [symbol]
        raw = subprocess.check_output([llvm, "-d", "--disassemble-symbols=" + ','.join(symbols)] + section_args + [binary], text=True)
        lines = []
        for line in raw.splitlines():
            match = re.match(r"^\s*([0-9a-fA-F]+):\s*((?:[0-9a-fA-F]{2}\s+)+)(.*)$", line)
            if match:
                line = match[1] + ":\t" + match[2].strip() + "\t" + match[3]
            lines.append(line)
        return "\n".join(lines)
    if isinstance(symbol, list):
        return '\n'.join(disassemble(binary, name, section) for name in symbol)
    command = ["objdump", "-d"] + section_args + (["--disassemble=" + symbol] if symbol else [])
    return subprocess.check_output(command + [binary], text=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument(
        "--mnemonics", default="prefetcht0,prefetcht1,prefetcht2,prefetchnta,prefetchit0,prefetchit1"
    )
    scope = ap.add_mutually_exclusive_group()
    scope.add_argument("--symbol", help="limit replacements and verification to one exact disassembly symbol")
    scope.add_argument("--symbols-file", help="newline-delimited exact symbols, all must exist")
    ap.add_argument("--addressing", choices=['all', 'rip', 'register'], default='all',
                    help="select addressing form; useful for audited direct-graph/indirect-target factorial controls")
    ap.add_argument('--section', help='explicit executable section for relocatable ELF files with overlapping section VAs')
    args = ap.parse_args()

    mnemonics = tuple(m.strip() for m in args.mnemonics.split(",") if m.strip())
    sections = executable_sections(args.input, args.section)
    if os.path.exists(args.output):
        if os.path.samefile(args.input, args.output):
            ap.error("input and output must be different files")
        os.chmod(args.output, os.stat(args.output).st_mode | stat.S_IWUSR)
    shutil.copy2(args.input, args.output)
    # Bazel outputs are read-only; make only the control copy writable.
    os.chmod(args.output, os.stat(args.output).st_mode | stat.S_IWUSR)

    symbols = args.symbol
    if args.symbols_file:
        with open(args.symbols_file) as handle:
            symbols = sorted(set(s.strip() for s in handle if s.strip()))
        if not symbols:
            ap.error('empty symbol list')
    dis = disassemble(args.input, symbols, args.section)
    required = symbols if isinstance(symbols, list) else ([symbols] if symbols else [])
    if any(f"<{name}>:" not in dis for name in required):
        ap.error("requested disassembly symbol not found")
    patches = []
    lines = dis.splitlines()
    for i, line in enumerate(lines):
        if not selected_prefetch(line, mnemonics, args.addressing):
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
            matches = [(vaddr, off, size) for vaddr, off, size in sections
                       if vaddr <= addr and addr+nbytes <= vaddr+size]
            if len(matches) != 1:
                raise SystemExit(f"cannot map executable address {addr:#x}")
            vaddr, off, size = matches[0]
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

    check = disassemble(args.output, symbols, args.section)
    remaining = sum(selected_prefetch(line, mnemonics, args.addressing) for line in check.splitlines())
    print(f"[ok] patched={len(patches)} remaining_prefetch_mnemonics={remaining}")
    if remaining:
        raise SystemExit("control binary still contains requested prefetch instructions")


if __name__ == "__main__":
    main()
