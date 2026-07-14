#!/usr/bin/env python3
"""Replace selected x86 prefetch instructions with equal-length NOPs."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


SECTION_RE = re.compile(
    r"\[\s*\d+\]\s+\.text\s+\S+\s+"
    r"([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)"
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


def command_output(command: list[str]) -> str:
    return subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout


def text_layout(binary: Path) -> tuple[int, int, int]:
    output = command_output(["readelf", "-W", "-S", str(binary)])
    match = SECTION_RE.search(output)
    if not match:
        raise SystemExit(f"could not locate .text in {binary}")
    address, offset, size = (int(value, 16) for value in match.groups())
    return address, offset, size


def find_instructions(binary: Path, mnemonics: set[str]) -> list[dict[str, object]]:
    output = command_output(["objdump", "-d", str(binary)])
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
    args = parser.parse_args()

    source = args.input.resolve()
    if not source.is_file():
        raise SystemExit(f"missing input binary: {source}")
    if source == args.output.resolve():
        raise SystemExit("input and output must differ")
    mnemonics = {value.lower() for value in args.mnemonic} or {"prefetcht1"}
    instructions = find_instructions(source, mnemonics)
    if args.expect_count >= 0 and len(instructions) != args.expect_count:
        raise SystemExit(
            f"expected {args.expect_count} matching instructions, found "
            f"{len(instructions)}"
        )
    if not instructions:
        raise SystemExit("no matching prefetch instructions found")

    text_address, text_offset, text_size = text_layout(source)
    source_data = source.read_bytes()
    output_data = bytearray(source_data)
    records = []
    for instruction in instructions:
        address = int(instruction["address"])
        old_bytes = bytes(instruction["bytes"])
        if len(old_bytes) not in NOP_BYTES:
            raise SystemExit(
                f"no canonical NOP sequence for {len(old_bytes)}-byte instruction "
                f"at 0x{address:x}"
            )
        if not text_address <= address < text_address + text_size:
            raise SystemExit(f"instruction 0x{address:x} is outside .text")
        file_offset = text_offset + address - text_address
        actual = bytes(output_data[file_offset : file_offset + len(old_bytes)])
        if actual != old_bytes:
            raise SystemExit(
                f"binary bytes disagree with objdump at 0x{address:x}: "
                f"expected={old_bytes.hex()} actual={actual.hex()}"
            )
        new_bytes = NOP_BYTES[len(old_bytes)]
        output_data[file_offset : file_offset + len(old_bytes)] = new_bytes
        records.append(
            {
                "address": f"0x{address:x}",
                "file_offset": f"0x{file_offset:x}",
                "mnemonic": instruction["mnemonic"],
                "size": len(old_bytes),
                "old_bytes": old_bytes.hex(),
                "new_bytes": new_bytes.hex(),
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output_data)
    shutil.copymode(source, args.output)
    os.utime(args.output, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns))

    manifest = {
        "input": str(source),
        "output": str(args.output.resolve()),
        "text_address": f"0x{text_address:x}",
        "text_offset": f"0x{text_offset:x}",
        "text_size": f"0x{text_size:x}",
        "masked_mnemonics": sorted(mnemonics),
        "masked_count": len(records),
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
