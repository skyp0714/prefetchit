#!/usr/bin/env python3
"""Post-link prefetch insertion without moving code: retarget `call rel32`
sites to small stubs in a new RX segment. Each stub issues prefetcht1s and
jumps to the original callee.

Stub kinds
  direct call (callee inside this image):
      prefetcht1 [callee+64*i](%rip)   i in burst lines   (7 B each)
      prefetcht1 [site+5+64*j](%rip)   j in ret lines     (continuation)
      prefetcht1 [site+D+64*k](%rip)   k in seq lines     (caller stream)
      jmp callee                                           (5 B)
  PLT call (callee in another DSO, via GOT):
      mov GOTslot(%rip),%r11                               (7 B)
      prefetcht1 64*i(%r11)            i in burst lines (i>=1)
      [ret / seq lines as above, rip-relative]
      jmp *%r11                                            (3 B)
r11 is a caller-saved scratch register in the SysV ABI, so clobbering it at a
call boundary is safe. The call instruction itself is unchanged in length, so
no code moves; the NOP twin replaces every prefetcht1 in the stubs by a NOP of
the same length (identical layout, identical dynamic instruction count).

Usage:
  postlink_call_stubs.py IN OUT [--twin OUT_NOP] [--burst N] [--burst-lead L]
      [--ret M] [--seq D --seq-lines K] [--direct] [--plt]
      [--sites FILE] [--exclude-sites FILE] [--funcs REGEX] [--max-sites N]
Sites default to all direct calls in .text (--direct) and/or all PLT calls (--plt).
--sites FILE restricts to the listed call addresses (hex, one per line).
"""
import argparse, os, re, struct, subprocess, sys
import lief

CALL_RE = re.compile(r'^\s*([0-9a-f]+):\s+e8 ([0-9a-f]{2}) ([0-9a-f]{2}) ([0-9a-f]{2}) ([0-9a-f]{2})\s+call')
FUNC_RE = re.compile(r'^([0-9a-f]+) <([^>]+)>:')
PLT_JMP_RE = re.compile(r'^\s*([0-9a-f]+):\s+ff 25 ([0-9a-f]{2}) ([0-9a-f]{2}) ([0-9a-f]{2}) ([0-9a-f]{2})\s+jmp')

def sections(b):
    return {s.name: (s.virtual_address, s.size, s.offset) for s in b.sections}

def parse_calls(path, secs):
    """Return list of (site, target, func) for e8 calls in .text, and dict of PLT entry -> GOT slot."""
    text_va, text_sz, _ = secs['.text']
    out = subprocess.run(['objdump', '-d', '-j', '.text', path],
                         capture_output=True, text=True, check=True).stdout
    calls = []; func = '?'
    for line in out.splitlines():
        m = FUNC_RE.match(line)
        if m: func = m.group(2); continue
        m = CALL_RE.match(line)
        if not m: continue
        site = int(m.group(1), 16)
        disp = struct.unpack('<i', bytes(int(m.group(i), 16) for i in range(2, 6)))[0]
        calls.append((site, site + 5 + disp, func))
    plt = {}
    for sec in ('.plt', '.plt.sec'):
        if sec not in secs: continue
        out = subprocess.run(['objdump', '-d', '-j', sec, path], capture_output=True, text=True, check=True).stdout
        cur = None
        for line in out.splitlines():
            m = FUNC_RE.match(line)
            if m: cur = int(m.group(1), 16); continue
            m = PLT_JMP_RE.match(line)
            if m and cur is not None:
                at = int(m.group(1), 16)
                disp = struct.unpack('<i', bytes(int(m.group(i), 16) for i in range(2, 6)))[0]
                # instruction length is 6 bytes; GOT slot = at+6+disp
                plt.setdefault(cur, at + 6 + disp)
    return calls, plt

def enc_prefetch_rip(from_addr, target):
    # 0F 18 0D disp32 : prefetcht1 disp32(%rip), 7 bytes
    disp = target - (from_addr + 7)
    assert -2**31 <= disp < 2**31, "rip displacement out of range"
    return b'\x0f\x18\x0d' + struct.pack('<i', disp)

def enc_prefetch_r11(off):
    # prefetcht1 off(%r11): 41 0F 18 /1 with base r11
    if off == 0:
        return b'\x41\x0f\x18\x0b'
    if -128 <= off < 128:
        return b'\x41\x0f\x18\x4b' + struct.pack('<b', off)
    return b'\x41\x0f\x18\x8b' + struct.pack('<i', off)

NOP = {4: b'\x0f\x1f\x40\x00', 5: b'\x0f\x1f\x44\x00\x00', 7: b'\x0f\x1f\x80\x00\x00\x00\x00',
       8: b'\x0f\x1f\x84\x00\x00\x00\x00\x00'}

def build_stub(addr, site, callee, got, a):
    """Return (bytes, nop_bytes). addr = stub address."""
    code = b''; nop = b''
    def emit(ins, is_pf):
        nonlocal code, nop
        code += ins
        nop += (NOP[len(ins)] if is_pf else ins)
    if got is not None:
        # mov got(%rip),%r11  : 4C 8B 1D disp32
        ins = b'\x4c\x8b\x1d' + struct.pack('<i', got - (addr + len(code) + 7))
        emit(ins, False)
        for i in range(a.burst_from, a.burst):
            emit(enc_prefetch_r11(64 * i), True)
    else:
        for i in range(a.burst_from, a.burst):
            emit(enc_prefetch_rip(addr + len(code), callee + a.burst_lead + 64 * i), True)
    for j in range(a.ret):
        emit(enc_prefetch_rip(addr + len(code), site + 5 + 64 * j), True)
    for k in range(a.seq_lines):
        emit(enc_prefetch_rip(addr + len(code), site + a.seq + 64 * k), True)
    if got is not None:
        emit(b'\x41\xff\xe3', False)                       # jmp *%r11
    else:
        rel = callee - (addr + len(code) + 5)
        assert -2**31 <= rel < 2**31
        emit(b'\xe9' + struct.pack('<i', rel), False)      # jmp callee
    return code, nop

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inp'); ap.add_argument('out')
    ap.add_argument('--twin')
    ap.add_argument('--burst', type=int, default=0, help='callee entry lines [burst_from, burst)')
    ap.add_argument('--burst-from', type=int, default=None, help='first callee line (default 0 direct, 1 plt)')
    ap.add_argument('--burst-lead', type=int, default=0)
    ap.add_argument('--ret', type=int, default=0, help='continuation lines after the call')
    ap.add_argument('--seq', type=int, default=0, help='caller-stream lookahead distance (bytes)')
    ap.add_argument('--seq-lines', type=int, default=1)
    ap.add_argument('--direct', action='store_true'); ap.add_argument('--plt', action='store_true')
    ap.add_argument('--sites'); ap.add_argument('--exclude-sites')
    ap.add_argument('--funcs', help='regex on containing function name (objdump symbol)')
    ap.add_argument('--max-sites', type=int, default=0)
    ap.add_argument('--align', type=int, default=16)
    a = ap.parse_args()
    if not a.direct and not a.plt: a.direct = a.plt = True
    if a.seq and a.seq_lines == 0: a.seq_lines = 1
    if not a.seq: a.seq_lines = 0

    # 1) add the stub segment first (LIEF may shift all segments of a DYN file
    #    by one page to grow the PHDR), then parse call sites from the written file
    #    so every address below refers to the final layout.
    calls, plt, secs, total, sizes = None, None, None, 0, []
    only = None
    if a.sites: only = {int(x.split()[0], 16) for x in open(a.sites) if x.strip() and not x.startswith('#')}
    excl = set()
    if a.exclude_sites: excl = {int(x.split()[0], 16) for x in open(a.exclude_sites) if x.strip() and not x.startswith('#')}
    frx = re.compile(a.funcs) if a.funcs else None

    def select(path):
      b0 = lief.parse(path); secs = sections(b0)
      calls, plt = parse_calls(path, secs)
      text_va, text_sz, _ = secs['.text']
      plt_ranges = [(secs[s][0], secs[s][0] + secs[s][1]) for s in ('.plt', '.plt.sec') if s in secs]
      def in_plt(t): return any(lo <= t < hi for lo, hi in plt_ranges)
      sel = []
      for site, tgt, func in calls:
          if only is not None and site not in only: continue
          if site in excl: continue
          if frx and not frx.search(func): continue
          if in_plt(tgt):
              if not a.plt: continue
              entry = tgt
              if entry not in plt:
                  continue
              sel.append((site, tgt, plt[entry]))
          elif text_va <= tgt < text_va + text_sz:
              if not a.direct: continue
              sel.append((site, tgt, None))
      if a.max_sites and len(sel) > a.max_sites: sel = sel[:a.max_sites]
      if not sel:
          print('no sites selected', file=sys.stderr); sys.exit(1)
      return sel
    sel = select(a.inp)
    sizes = []
    for site, tgt, got in sel:
        a.burst_from = a.burst_from if a.burst_from is not None else (1 if got is not None else 0)
        c, _ = build_stub(0x10000000, site, tgt, got if got is not None else 0, a)
        sizes.append((len(c) + a.align - 1) // a.align * a.align)
    total = sum(sizes)
    b = lief.parse(a.inp)

    seg = lief.ELF.Segment()
    seg.type = lief.ELF.Segment.TYPE.LOAD
    seg.flags = lief.ELF.Segment.FLAGS.R | lief.ELF.Segment.FLAGS.X
    seg.alignment = 0x1000
    seg.content = list(b'\xcc' * total)
    seg = b.add(seg)
    b.write(a.out)
    # re-parse to get final addresses/offsets
    b2 = lief.parse(a.out)
    sel = select(a.out)   # re-select on the final layout (addresses may have shifted)
    assert len(sel) == len(sizes)
    stubseg = None
    for s in b2.segments:
        if s.type == lief.ELF.Segment.TYPE.LOAD and s.virtual_size >= total and bytes(s.content[:8]) == b'\xcc' * 8 \
           and (int(s.flags) & int(lief.ELF.Segment.FLAGS.X)):
            stubseg = s; break
    assert stubseg is not None, 'stub segment not found after write'
    base = stubseg.virtual_address; foff = stubseg.file_offset
    def va2off(va):
        for s in b2.segments:
            if s.type == lief.ELF.Segment.TYPE.LOAD and s.virtual_address <= va < s.virtual_address + s.physical_size:
                return va - s.virtual_address + s.file_offset
        raise KeyError(hex(va))

    data = bytearray(open(a.out, 'rb').read())
    twin = bytearray(data) if a.twin else None
    cur = base; npf = 0; nplt = 0
    burst_from_arg = a.burst_from
    for (site, tgt, got), sz in zip(sel, sizes):
        a.burst_from = burst_from_arg if burst_from_arg is not None else (1 if got is not None else 0)
        code, nop = build_stub(cur, site, tgt, got, a)
        assert len(code) <= sz
        off = cur - base + foff
        data[off:off + len(code)] = code
        if twin is not None: twin[off:off + len(nop)] = nop
        # retarget the call
        so = va2off(site)
        assert data[so] == 0xe8, f'site {site:#x} is not a call'
        rel = cur - (site + 5)
        assert -2**31 <= rel < 2**31
        data[so + 1:so + 5] = struct.pack('<i', rel)
        if twin is not None: twin[so + 1:so + 5] = struct.pack('<i', rel)
        npf += code.count(b'\x0f\x18'); nplt += (got is not None)
        cur += sz
    open(a.out, 'wb').write(data)
    if twin is not None: open(a.twin, 'wb').write(twin)
    os.chmod(a.out, 0o755)
    if a.twin: os.chmod(a.twin, 0o755)
    print(f'{os.path.basename(a.inp)}: sites={len(sel)} (plt {nplt}, direct {len(sel)-nplt}) prefetches={npf} '
          f'stub_segment={base:#x}+{total} bytes; burst={a.burst} ret={a.ret} seq={a.seq}x{a.seq_lines}')

if __name__ == '__main__':
    main()
