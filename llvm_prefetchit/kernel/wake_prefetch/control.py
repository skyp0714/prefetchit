#!/usr/bin/env python3
"""Resolve a hash-bound ELF plan against one live process and hold registration.

No module loading, privilege changes, or address-space writes are performed.
Closing this controller's device FD disables the plan and releases all pins.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import signal
import struct
import time

MAX_PROFILES, MAX_LINES = 8, 64
PROFILE_SIZE = 24 + 8 * MAX_LINES
CONFIG_SIZE = 32 + MAX_PROFILES * PROFILE_SIZE
CONFIG_IOCTL = (1 << 30) | (CONFIG_SIZE << 16) | (ord("W") << 8) | 1
STATS_IOCTL = (2 << 30) | (16 << 16) | (ord("W") << 8) | 2


def executable_segments(data):
    if data[:6] != b"\x7fELF\x02\x01":
        raise ValueError("only little-endian ELF64 is supported")
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
    if header[2] != 62 or header[9] != 56:
        raise ValueError("requires x86-64 ELF program headers")
    segments = []
    for i in range(header[10]):
        kind, flags, offset, va, _, filesz, _, _ = struct.unpack_from("<IIQQQQQQ", data, header[5] + i * header[9])
        if kind == 1 and flags & 1:
            segments.append((offset, va, filesz))
    return segments


def runtime_address(elf_va, segments, mappings):
    candidates = set()
    for offset, va, size in segments:
        if va <= elf_va < va + size:
            file_offset = offset + elf_va - va
            for low, high, map_offset in mappings:
                if map_offset <= file_offset < map_offset + high - low:
                    candidates.add(low + file_offset - map_offset)
    if len(candidates) != 1:
        raise ValueError(f"ELF address {elf_va:#x} has {len(candidates)} executable runtime mappings")
    return candidates.pop()


def number(value):
    return int(value, 0) if isinstance(value, str) else int(value)


def resolve(plan, pid):
    maps = (Path("/proc") / str(pid) / "maps").read_text()
    mapped = {}
    for line in maps.splitlines():
        parts = line.split(None, 5)
        if len(parts) != 6 or "x" not in parts[1] or "w" in parts[1]:
            continue
        low, high = (int(x, 16) for x in parts[0].split("-"))
        mapped.setdefault(parts[5], []).append((low, high, int(parts[2], 16)))
    binaries = {}
    records = []

    def address(target):
        path = target["path"]
        if not path.startswith("/") or path not in mapped:
            raise ValueError(f"missing read-only executable mapping: {path}")
        if path not in binaries:
            data = (Path("/proc") / str(pid) / "root" / path.lstrip("/")).read_bytes()
            binaries[path] = hashlib.sha256(data).hexdigest(), executable_segments(data)
        digest, segments = binaries[path]
        if digest != target["sha256"]:
            raise ValueError(f"binary hash mismatch for {path}")
        return runtime_address(number(target["elf_va"]), segments, mapped[path])

    for profile in plan["profiles"]:
        lines = [address(t) for t in profile["targets"]]
        if any(x & 63 for x in lines) or len(set(lines)) != len(lines):
            raise ValueError("target lines must be unique and 64-byte aligned")
        ip_start, ip_end = 0, 0
        if "resume_ip" in profile:
            ip_start = address(profile["resume_ip"])
            ip_end = ip_start + 1  # exact saved return IP; never inferred from a future frame
        records.append(dict(syscall_nr=profile.get("syscall_nr", -1),
                            ip_start=ip_start, ip_end=ip_end, lines=lines))
    return records, dict(mapped_binary_hashes={k: v[0] for k, v in binaries.items()}, maps=maps)


def pack_config(pid, mode, profiles):
    if platform.machine() != "x86_64" or mode not in (0, 1) or not 0 < pid < 2**31:
        raise ValueError("requires x86-64, valid mode, and positive pid")
    if not 1 <= len(profiles) <= MAX_PROFILES:
        raise ValueError("requires 1..8 profiles")
    data = bytearray(struct.pack("<IIiIQQ", 1, mode, pid, len(profiles), 0, 0))
    for profile in profiles:
        lines = profile["lines"]
        nr, lo, hi = profile["syscall_nr"], profile["ip_start"], profile["ip_end"]
        if (not 1 <= len(lines) <= MAX_LINES or len(set(lines)) != len(lines)
                or any(x <= 0 or x & 63 or x >= 2**63 for x in lines)
                or nr < -1 or ((lo or hi) and not 0 <= lo < hi < 2**63)):
            raise ValueError("invalid profile")
        data += struct.pack("<iIQQ", nr, len(lines), lo, hi)
        data += struct.pack("<64Q", *(lines + [0] * (MAX_LINES - len(lines))))
    data += bytes(CONFIG_SIZE - len(data))
    return data


def stats(fd):
    data = bytearray(16)
    fcntl.ioctl(fd, STATS_IOCTL, data, True)
    switches, lines = struct.unpack("<QQ", data)
    return dict(matched_switches=switches, attempted_lines_including_nop=lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("plan", type=Path)
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--mode", choices=("nop", "t1"), default="nop")
    p.add_argument("--seconds", type=float, default=180.)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--validate-only", action="store_true")
    a = p.parse_args()
    if a.seconds <= 0 or a.out.exists():
        p.error("positive duration and a new output file required")
    plan = json.loads(a.plan.read_text())
    pidfd = os.pidfd_open(a.pid)  # pins the identity observed before maps are read
    fd = None
    result = dict(pid=a.pid, mode=a.mode, plan=str(a.plan),
                  plan_sha256=hashlib.sha256(a.plan.read_bytes()).hexdigest(),
                  registered=False, validated=False)
    try:
        profiles, audit = resolve(plan, a.pid)
        result.update(profiles=profiles, audit=audit)
        data = pack_config(a.pid, int(a.mode == "t1"), profiles)
        if select.select([pidfd], [], [], 0)[0]:
            raise RuntimeError("target exited during address resolution")
        result["validated"] = True
        if a.validate_only:
            return
        fd = os.open("/dev/wake_prefetch", os.O_RDWR | os.O_CLOEXEC)
        fcntl.ioctl(fd, CONFIG_IOCTL, data, True)
        if select.select([pidfd], [], [], 0)[0]:
            raise RuntimeError("target exited during registration")
        result.update(registered=True, start=time.time(), before=stats(fd))
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(result, indent=2) + "\n")
        stop = False

        def interrupt(signum, frame):
            nonlocal stop
            stop = True

        signal.signal(signal.SIGTERM, interrupt)
        signal.signal(signal.SIGINT, interrupt)
        deadline = time.monotonic() + a.seconds
        while not stop and time.monotonic() < deadline:
            if select.select([pidfd], [], [], min(.25, max(0, deadline-time.monotonic())))[0]:
                result["target_exited"] = True
                break
        result.update(end=time.time(), after=stats(fd))
    except BaseException as error:
        result["error"] = repr(error)
        raise
    finally:
        if fd is not None:
            os.close(fd)
            result["device_closed_plan_disabled"] = True
        os.close(pidfd)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
