#!/usr/bin/env python3
"""Replace selected x86 prefetch instructions with equal-length controls."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


SECTION_RE = re.compile(
    r"\[\s*\d+\]\s+(\S+)\s+\S+\s+"
    r"([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+"
    r"\S+\s+([A-Z]+)\s+"
)
INSTRUCTION_RE = re.compile(
    r"^\s*([0-9a-fA-F]+):\s+"
    r"((?:[0-9a-fA-F]{2}\s+)+)"
    r"([a-zA-Z0-9_.]+)\b"
)

NOP_BYTES = {
    1: bytes.fromhex("90"),
    2: bytes.fromhex("66 90"),
    3: bytes.fromhex("0f 1f 00"),
    4: bytes.fromhex("0f 1f 40 00"),
    5: bytes.fromhex("0f 1f 44 00 00"),
    6: bytes.fromhex("66 0f 1f 44 00 00"),
    7: bytes.fromhex("0f 1f 80 00 00 00 00"),
    8: bytes.fromhex("0f 1f 84 00 00 00 00 00"),
    9: bytes.fromhex("66 0f 1f 84 00 00 00 00 00"),
}

# Keep one PREFETCHT1 uop while redirecting it to the already-hot stack line.
# Longer source instructions are padded with canonical NOPs so all following
# instruction and symbol addresses remain unchanged.
STACK_PREFETCH_BYTES = {
    4: bytes.fromhex("0f 18 14 24"),
    5: bytes.fromhex("0f 18 54 24 00"),
    6: bytes.fromhex("0f 18 54 24 00 90"),
    7: bytes.fromhex("0f 18 14 24 0f 1f 00"),
    8: bytes.fromhex("0f 18 14 24 0f 1f 40 00"),
    9: bytes.fromhex("0f 18 14 24 0f 1f 44 00 00"),
}


def command_output(command: list[str]) -> str:
    return subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout


def parse_address(value: str) -> int:
    try:
        address = int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid address: {value}") from exc
    if address < 0:
        raise argparse.ArgumentTypeError("addresses must be non-negative")
    return address


def executable_layouts(binary: Path) -> list[dict[str, int | str]]:
    output = command_output(["readelf", "-W", "-S", str(binary)])
    layouts = []
    for match in SECTION_RE.finditer(output):
        name, address, offset, size, flags = match.groups()
        if "X" not in flags:
            continue
        layouts.append(
            {
                "name": name,
                "address": int(address, 16),
                "offset": int(offset, 16),
                "size": int(size, 16),
            }
        )
    if not layouts:
        raise SystemExit(f"could not locate executable sections in {binary}")
    return layouts


def find_instructions(binary: Path, mnemonics: set[str]) -> list[dict[str, object]]:
    # GNU objdump otherwise wraps instructions longer than seven bytes and
    # places the remaining bytes on a continuation line. Keep each complete
    # instruction on one line so its replacement length cannot be truncated.
    output = command_output(["objdump", "-d", "--insn-width=16", str(binary)])
    instructions: list[dict[str, object]] = []
    for line in output.splitlines():
        match = INSTRUCTION_RE.match(line)
        if not match:
            continue
        address_text, bytes_text, mnemonic = match.groups()
        if mnemonic.lower() not in mnemonics:
            continue
        instruction_bytes = bytes.fromhex(bytes_text)
        instructions.append(
            {
                "address": int(address_text, 16),
                "mnemonic": mnemonic.lower(),
                "bytes": instruction_bytes,
            }
        )
    return instructions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument(
        "--mnemonic",
        action="append",
        default=[],
        help="mnemonic to mask; repeat as needed (default: prefetcht1)",
    )
    parser.add_argument(
        "--expect-count",
        type=int,
        default=-1,
        help="fail unless exactly this many instructions are found",
    )
    parser.add_argument(
        "--replacement",
        choices=("nop", "stack-prefetch"),
        default="nop",
        help=(
            "equal-length replacement: canonical NOPs, or a PREFETCHT1 to "
            "the hot stack line plus NOP padding"
        ),
    )
    address_group = parser.add_mutually_exclusive_group()
    address_group.add_argument(
        "--keep-address",
        action="append",
        type=parse_address,
        default=[],
        help=(
            "virtual address of a matching prefetch to retain; repeat as needed. "
            "All other matching prefetches are masked"
        ),
    )
    address_group.add_argument(
        "--mask-address",
        action="append",
        type=parse_address,
        default=[],
        help=(
            "virtual address of a matching prefetch to mask; repeat as needed. "
            "All other matching prefetches are retained"
        ),
    )
    args = parser.parse_args()

    source = args.input.resolve()
    if not source.is_file():
        raise SystemExit(f"missing input binary: {source}")
    if source == args.output.resolve():
        raise SystemExit("input and output must differ")
    mnemonics = {value.lower() for value in args.mnemonic} or {"prefetcht1"}
    matching_instructions = find_instructions(source, mnemonics)
    if args.expect_count >= 0 and len(matching_instructions) != args.expect_count:
        raise SystemExit(
            f"expected {args.expect_count} matching instructions, found "
            f"{len(matching_instructions)}"
        )
    if not matching_instructions:
        raise SystemExit("no matching prefetch instructions found")

    matching_addresses = {
        int(instruction["address"]) for instruction in matching_instructions
    }
    requested_addresses = set(args.keep_address or args.mask_address)
    missing_addresses = requested_addresses - matching_addresses
    if missing_addresses:
        formatted = ", ".join(f"0x{address:x}" for address in sorted(missing_addresses))
        raise SystemExit(f"requested prefetch addresses were not found: {formatted}")

    if args.keep_address:
        instructions = [
            instruction
            for instruction in matching_instructions
            if int(instruction["address"]) not in requested_addresses
        ]
    elif args.mask_address:
        instructions = [
            instruction
            for instruction in matching_instructions
            if int(instruction["address"]) in requested_addresses
        ]
    else:
        instructions = matching_instructions

    executable_sections = executable_layouts(source)
    source_data = source.read_bytes()
    output_data = bytearray(source_data)
    replacement_bytes = (
        NOP_BYTES if args.replacement == "nop" else STACK_PREFETCH_BYTES
    )
    records = []
    for instruction in instructions:
        address = int(instruction["address"])
        old_bytes = bytes(instruction["bytes"])
        if len(old_bytes) not in replacement_bytes:
            raise SystemExit(
                f"no {args.replacement} sequence for "
                f"{len(old_bytes)}-byte instruction "
                f"at 0x{address:x}"
            )
        section = next(
            (
                layout
                for layout in executable_sections
                if int(layout["address"])
                <= address
                < int(layout["address"]) + int(layout["size"])
            ),
            None,
        )
        if section is None:
            raise SystemExit(
                f"instruction 0x{address:x} is outside executable sections"
            )
        file_offset = (
            int(section["offset"]) + address - int(section["address"])
        )
        actual = bytes(output_data[file_offset : file_offset + len(old_bytes)])
        if actual != old_bytes:
            raise SystemExit(
                f"binary bytes disagree with objdump at 0x{address:x}: "
                f"expected={old_bytes.hex()} actual={actual.hex()}"
            )
        new_bytes = replacement_bytes[len(old_bytes)]
        output_data[file_offset : file_offset + len(old_bytes)] = new_bytes
        records.append(
            {
                "address": f"0x{address:x}",
                "file_offset": f"0x{file_offset:x}",
                "section": section["name"],
                "mnemonic": instruction["mnemonic"],
                "size": len(old_bytes),
                "old_bytes": old_bytes.hex(),
                "new_bytes": new_bytes.hex(),
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        args.output.unlink()
    args.output.write_bytes(output_data)
    shutil.copymode(source, args.output)
    os.utime(args.output, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns))

    text_section = next(
        (section for section in executable_sections if section["name"] == ".text"),
        executable_sections[0],
    )
    manifest = {
        "input": str(source),
        "output": str(args.output.resolve()),
        "text_address": f"0x{int(text_section['address']):x}",
        "text_offset": f"0x{int(text_section['offset']):x}",
        "text_size": f"0x{int(text_section['size']):x}",
        "executable_sections": [
            {
                "name": section["name"],
                "address": f"0x{int(section['address']):x}",
                "offset": f"0x{int(section['offset']):x}",
                "size": f"0x{int(section['size']):x}",
            }
            for section in executable_sections
        ],
        "masked_mnemonics": sorted(mnemonics),
        "replacement": args.replacement,
        "matching_count": len(matching_instructions),
        "masked_count": len(records),
        "kept_count": len(matching_instructions) - len(records),
        "keep_addresses": [
            f"0x{address:x}" for address in sorted(set(args.keep_address))
        ],
        "mask_addresses": [
            f"0x{address:x}" for address in sorted(set(args.mask_address))
        ],
        "instructions": records,
    }
    manifest_path = args.manifest or args.output.with_suffix(
        args.output.suffix + ".mask.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"[ok] {source} -> {args.output}: masked={len(records)} "
        f"manifest={manifest_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
