import importlib.util
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

ctl = module("wake_ctl", ROOT / "kernel/wake_prefetch/control.py")

def test_pie_and_nonzero_elf_segment():
    segments = [(0x1000, 0x401000, 0x4000)]
    assert ctl.runtime_address(0x402040, segments, [(0x70001000, 0x70005000, 0x1000)]) == 0x70002040
    assert ctl.runtime_address(0x402040, segments, [(0x401000, 0x405000, 0x1000)]) == 0x402040
    with pytest.raises(ValueError, match="2 executable"):
        ctl.runtime_address(0x402040, segments, [(0x401000, 0x405000, 0x1000),
                                                (0x70001000, 0x70005000, 0x1000)])
    with pytest.raises(ValueError, match="0 executable"):
        ctl.runtime_address(0x408000, segments, [(0x401000, 0x405000, 0x1000)])

def test_c_uapi_matches_python_and_real_elf(tmp_path):
    source = tmp_path / "abi.c"
    source.write_text('#include <stdio.h>\n#include "wake_prefetch.h"\n'
                      'int main(void) { printf("%zu %zu %lu %lu %zu %lu %zu %lu\\n", '
                      'sizeof(struct wpf_config), sizeof(struct wpf_profile), '
                      '(unsigned long)WPF_CONFIG, (unsigned long)WPF_STATS, '
                      'sizeof(struct wpf_detail), (unsigned long)WPF_DETAIL, '
                      'sizeof(struct wpf_waves), (unsigned long)WPF_WAVES); }\n')
    binary = tmp_path / "abi"
    subprocess.run(["cc", "-I", str(ROOT / "kernel/wake_prefetch"), str(source), "-o", str(binary)], check=True)
    actual = list(map(int, subprocess.check_output([str(binary)], text=True).split()))
    assert actual == [ctl.CONFIG_SIZE, ctl.PROFILE_SIZE, ctl.CONFIG_IOCTL, ctl.STATS_IOCTL,
                      ctl.DETAIL_SIZE, ctl.DETAIL_IOCTL, ctl.WAVES_SIZE, ctl.WAVES_IOCTL]
    assert ctl.executable_segments(binary.read_bytes())
    profile = dict(syscall_nr=7, ip_start=0x402123, ip_end=0x402124, lines=[0x403000, 0x403080])
    data = ctl.pack_config(123, 0, [profile])
    assert len(data) == actual[0]
    assert struct.unpack_from("<iIQQ", data, 32) == (7, 2, 0x402123, 0x402124)
    assert struct.unpack_from("<QQ", data, 56) == (0x403000, 0x403080)

def test_live_pie_resolution_checks_hash_and_mapping(tmp_path):
    source = tmp_path / "sleeper.c"
    source.write_text('#include <unistd.h>\nint main(void) { sleep(30); return 0; }\n')
    binary = tmp_path / "sleeper"
    subprocess.run(["cc", "-fPIE", "-pie", str(source), "-o", str(binary)], check=True)
    data = binary.read_bytes()
    _, va, size = ctl.executable_segments(data)[0]
    line = (va + 63) & ~63
    assert line < va + size
    target = dict(path=str(binary), sha256=hashlib.sha256(data).hexdigest(), elf_va=hex(line))
    plan = dict(profiles=[dict(targets=[target])])
    proc = subprocess.Popen([str(binary)])
    try:
        profiles, audit = ctl.resolve(plan, proc.pid)
        assert profiles[0]["lines"][0] & 63 == 0
        assert profiles[0]["lines"][0] > line
        assert audit["mapped_binary_hashes"][str(binary)] == target["sha256"]
        target["sha256"] = "0" * 64
        with pytest.raises(ValueError, match="hash mismatch"):
            ctl.resolve(plan, proc.pid)
    finally:
        proc.terminate()
        proc.wait(timeout=5)

@pytest.mark.parametrize("lines", [[], [0x400001], [0x400000, 0x400000], [0], list(range(64, 64*66, 64))])
def test_reject_bad_targets(lines):
    with pytest.raises(ValueError):
        ctl.pack_config(123, 1, [dict(syscall_nr=-1, ip_start=0, ip_end=0, lines=lines)])


def test_emission_v2_encoding_and_v1_compatibility():
    profiles = [dict(syscall_nr=-1, ip_start=0, ip_end=0, lines=[0x400000])]
    legacy = ctl.pack_config(123, 1, profiles)
    encoded = ctl.pack_config(123, 1, profiles, spacing=16, group=4, split_after=8, hint='t0', diagnostic=2)
    assert struct.unpack_from('<IIiIQQ', legacy) == (1, 1, 123, 1, 0, 0)
    assert struct.unpack_from('<IIiIQQ', encoded) == (2, 1, 123, 1, 16 | 4<<8 | 8<<16 | 1<<24 | 2<<32, 0)
    assert encoded[32:] == legacy[32:]
    for options in (dict(spacing=1), dict(group=3), dict(group=0), dict(split_after=64),
                    dict(split_after=-1), dict(hint='invalid'), dict(diagnostic=3)):
        with pytest.raises(ValueError, match='emission'):
            ctl.pack_config(123, 1, profiles, **options)


def test_bounded_periodic_waves_and_incompatible_options():
    profiles = [dict(syscall_nr=-1, ip_start=0, ip_end=0, lines=[0x400000])]
    data = ctl.pack_config(123, 1, profiles, interval_ns=2000, batch=4, max_age_us=32)
    assert struct.unpack_from('<IIiIQQ', data) == (3, 1, 123, 1, 1<<8, 2000 | 4<<32 | 32<<40)
    for options in (dict(interval_ns=999, batch=4, max_age_us=32),
                    dict(interval_ns=2000, batch=17, max_age_us=32),
                    dict(interval_ns=2000, batch=4, max_age_us=65),
                    dict(interval_ns=2000, batch=4, max_age_us=32, split_after=4),
                    dict(interval_ns=2000, batch=4, max_age_us=32, diagnostic=1),
                    dict(batch=4)):
        with pytest.raises(ValueError, match='wave emission'):
            ctl.pack_config(123, 1, profiles, **options)
