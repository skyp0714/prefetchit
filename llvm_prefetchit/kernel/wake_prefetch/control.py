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
DETAIL_SIZE = (6 + 3 * 16) * 8
DETAIL_IOCTL = (2 << 30) | (DETAIL_SIZE << 16) | (ord("W") << 8) | 3
WAVES_SIZE = 22 * 8
WAVES_IOCTL = (2 << 30) | (WAVES_SIZE << 16) | (ord("W") << 8) | 4
HISTOGRAM_UPPER_TSC = [64, 96, 128, 192, 256, 384, 512, 768,
                       1024, 1536, 2048, 4096, 8192, 16384, 32768, None]


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


def pack_config(pid, mode, profiles, spacing=0, group=1, split_after=0, hint='t1', diagnostic=0,
                interval_ns=0, batch=0, max_age_us=0):
    if platform.machine() != "x86_64" or mode not in (0, 1) or not 0 < pid < 2**31:
        raise ValueError("requires x86-64, valid mode, and positive pid")
    if not 1 <= len(profiles) <= MAX_PROFILES:
        raise ValueError("requires 1..8 profiles")
    if (spacing not in (0, 4, 16) or group not in (1, 2, 4, 8, 16)
            or not isinstance(split_after, int) or not 0 <= split_after < MAX_LINES
            or hint not in ('t1', 't0', 'nta') or diagnostic not in (0, 1, 2)):
        raise ValueError('invalid bounded emission options')
    version = 1 if (spacing, group, split_after, hint, diagnostic) == (0, 1, 0, 't1', 0) else 2
    wave_options = 0
    if interval_ns or batch or max_age_us:
        if (not all(isinstance(v, int) for v in (interval_ns, batch, max_age_us))
                or not 1000 <= interval_ns <= 16000 or not 1 <= batch <= 16
                or not 4 <= max_age_us <= 64 or spacing or split_after or diagnostic):
            raise ValueError('invalid bounded wave emission options')
        version = 3
        wave_options = interval_ns | batch << 32 | max_age_us << 40
    options = (spacing | group << 8 | split_after << 16 |
               ('t1', 't0', 'nta').index(hint) << 24 | diagnostic << 32) if version >= 2 else 0
    data = bytearray(struct.pack("<IIiIQQ", version, mode, pid, len(profiles), options, wave_options))
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


def detail(fd):
    data = bytearray(DETAIL_SIZE)
    fcntl.ioctl(fd, DETAIL_IOCTL, data, True)
    values = struct.unpack('<54Q', data)
    result = dict(zip(('second_switches', 'second_lines', 'cancelled',
                       'pre_samples', 'post_samples', 'lead_samples'), values[:6]))
    for i, name in enumerate(('pre', 'post', 'lead')):
        result[name] = list(values[6+i*16:22+i*16])
    result['histogram_upper_exclusive_tsc_ticks'] = HISTOGRAM_UPPER_TSC
    result['semantics'] = 'Sampled pinned-alias data-load latency and switch completion delay; not instruction-fetch latency or core cycles'
    return result


def waves(fd):
    data = bytearray(WAVES_SIZE)
    fcntl.ioctl(fd, WAVES_IOCTL, data, True)
    values = struct.unpack('<22Q', data)
    result = dict(zip(('callbacks', 'emitted', 'lines', 'cancelled', 'expired', 'wrong_task'), values[:6]))
    result['age_2us_bins'] = list(values[6:])
    result['semantics'] = 'Delayed hint attempts, age since next-task selection; last bin >=30us'
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("plan", type=Path)
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--mode", choices=("nop", "t1"), default="nop")
    p.add_argument("--seconds", type=float, default=180.)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--validate-only", action="store_true")
    p.add_argument('--spacing', type=int, choices=(0, 4, 16), default=0)
    p.add_argument('--group', type=int, choices=(1, 2, 4, 8, 16), default=1)
    p.add_argument('--split-after', type=int, default=0)
    p.add_argument('--hint', choices=('t1', 't0', 'nta'), default='t1')
    p.add_argument('--diagnostic', type=int, choices=(0, 1, 2), default=0)
    p.add_argument('--interval-ns', type=int, default=0)
    p.add_argument('--batch', type=int, default=0)
    p.add_argument('--max-age-us', type=int, default=0)
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
        options = {k: getattr(a, k) for k in ('spacing', 'group', 'split_after', 'hint', 'diagnostic',
                                            'interval_ns', 'batch', 'max_age_us')}
        result['options'] = options
        data = pack_config(a.pid, int(a.mode == "t1"), profiles, **options)
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
        result.update(end=time.time(), after=stats(fd), detail=detail(fd))
        if a.interval_ns: result['waves'] = waves(fd)
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
