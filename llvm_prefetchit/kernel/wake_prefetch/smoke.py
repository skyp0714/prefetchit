#!/usr/bin/env python3
"""Root-only lifecycle smoke test. Loads this module, tests a private helper, unloads.

No performance claim: the helper exercises registration, callback, and teardown.
Generated helper binaries are hashed and removed even if a test fails.
"""
import argparse
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

import control

SOURCE = r'''
#include <signal.h>
#include <stdio.h>
#include <unistd.h>
static volatile sig_atomic_t change;
static void handler(int n) { change = 1; }
int main(void) {
    signal(SIGUSR1, handler);
    puts("ready"); fflush(stdout);
    for (;;) {
        if (change) { execl("/bin/sleep", "sleep", "10", NULL); return 2; }
        usleep(1000);
    }
}
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if os.geteuid() or args.out.exists():
        ap.error('root and fresh output directory required')
    if Path('/sys/module/wake_prefetch').exists():
        ap.error('module already loaded; do not interfere with another experiment')
    if shutil.disk_usage(args.out.parent).free < 1024**3:
        ap.error('at least 1 GiB of free space required')
    args.out.mkdir(parents=True)
    source = args.out / 'helper.c'
    binary = args.out / 'helper'
    source.write_text(SOURCE)
    result = dict(tests=[], performance_measurement=False, module_loaded=False)
    proc = None
    fd = None
    loaded = False

    def reject(call, expected):
        try:
            value = call()
        except OSError as error:
            assert error.errno == expected, repr(error)
        else:
            if isinstance(value, int):
                os.close(value)
            raise AssertionError('Expected rejection')

    try:
        subprocess.run(['cc', '-O2', '-fPIE', '-pie', str(source), '-o', str(binary)], check=True)
        data = binary.read_bytes()
        _, va, size = control.executable_segments(data)[0]
        target = dict(path=str(binary.resolve()), elf_va=hex((va+63) & ~63),
                      sha256=hashlib.sha256(data).hexdigest())
        plan = dict(profiles=[dict(targets=[target])])
        (args.out / 'plan.json').write_text(json.dumps(plan, indent=2)+'\n')
        proc = subprocess.Popen([str(binary.resolve())], stdout=subprocess.PIPE, text=True)
        assert proc.stdout.readline().strip() == 'ready'
        profiles, audit = control.resolve(plan, proc.pid)
        result['mapping_audit'] = audit
        module = Path(__file__).resolve().parent / 'wake_prefetch.ko'
        result['module_sha256'] = hashlib.sha256(module.read_bytes()).hexdigest()
        subprocess.run(['insmod', str(module)], check=True)
        loaded = True
        result['module_loaded'] = True
        for mode in (0, 1):
            fd = os.open('/dev/wake_prefetch', os.O_RDWR | os.O_CLOEXEC)
            reject(lambda: os.open('/dev/wake_prefetch', os.O_RDWR), errno.EBUSY)
            packed = control.pack_config(proc.pid, mode, profiles)
            fcntl.ioctl(fd, control.CONFIG_IOCTL, packed, True)
            reject(lambda: fcntl.ioctl(fd, control.CONFIG_IOCTL, packed, True), errno.EBUSY)
            before = control.stats(fd)
            time.sleep(.25)
            after = control.stats(fd)
            assert after['matched_switches'] > before['matched_switches']
            assert after['attempted_lines_including_nop'] == after['matched_switches']
            result['tests'].append(dict(test='nop' if mode == 0 else 't1', before=before, after=after))
            os.close(fd)
            fd = os.open('/dev/wake_prefetch', os.O_RDWR | os.O_CLOEXEC)
            before = control.stats(fd)
            time.sleep(.05)
            assert control.stats(fd) == before, 'close did not disable callback'
            result['tests'].append(dict(test='close_disables_plan', mode=mode, passed=True))
            os.close(fd)
            fd = None
        fd = os.open('/dev/wake_prefetch', os.O_RDWR | os.O_CLOEXEC)
        packed = control.pack_config(proc.pid, 1, profiles)
        fcntl.ioctl(fd, control.CONFIG_IOCTL, packed, True)
        os.kill(proc.pid, signal.SIGUSR1)
        for _ in range(100):
            if Path(f'/proc/{proc.pid}/exe').resolve() == Path('/bin/sleep').resolve():
                break
            time.sleep(.01)
        else:
            raise AssertionError('helper did not exec')
        before = control.stats(fd)
        time.sleep(.05)
        assert control.stats(fd) == before
        result['tests'].append(dict(test='exec_mm_mismatch_disables_plan', passed=True))
        proc.terminate(); proc.wait(timeout=5); proc = None
        os.close(fd); fd = None
        result['passed'] = True
    except BaseException as error:
        result.update(passed=False, error=repr(error))
        raise
    finally:
        if fd is not None:
            os.close(fd)
        if proc is not None:
            proc.terminate(); proc.wait(timeout=5)
        try:
            if loaded:
                subprocess.run(['rmmod', 'wake_prefetch'], check=True)
            result['module_unloaded'] = not Path('/sys/module/wake_prefetch').exists()
        finally:
            removed = []
            free = shutil.disk_usage(args.out).free
            if binary.exists():
                removed.append(dict(path=str(binary), bytes=binary.stat().st_size,
                                    sha256=hashlib.sha256(binary.read_bytes()).hexdigest()))
                binary.unlink()
            result['cleanup'] = dict(removed=removed, free_before=free,
                                     free_after=shutil.disk_usage(args.out).free)
            (args.out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(passed=result['passed'], tests=len(result['tests']),
                         module_unloaded=result['module_unloaded'])))


if __name__ == '__main__':
    main()
