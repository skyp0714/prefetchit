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
import argparse, collections, os, re, struct, subprocess, sys
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
    # 0F 18 /2 with rip-relative ModRM 0x15 : prefetcht1 disp32(%rip), 7 bytes
    disp = target - (from_addr + 7)
    assert -2**31 <= disp < 2**31, "rip displacement out of range"
    return b'\x0f\x18\x15' + struct.pack('<i', disp)

def enc_prefetch_r11(off):
    # prefetcht1 off(%r11): 41 0F 18 /2 with base r11 (ModRM reg=010)
    if off == 0:
        return b'\x41\x0f\x18\x13'
    if -128 <= off < 128:
        return b'\x41\x0f\x18\x53' + struct.pack('<b', off)
    return b'\x41\x0f\x18\x93' + struct.pack('<i', off)

NOP = {4: b'\x0f\x1f\x40\x00', 5: b'\x0f\x1f\x44\x00\x00', 7: b'\x0f\x1f\x80\x00\x00\x00\x00',
       8: b'\x0f\x1f\x84\x00\x00\x00\x00\x00'}

def anchors_for(path, dso_dir):
    """DSO name -> (GOT slot in this file, symbol offset in that DSO) using this file's PLT imports."""
    secs = sections(lief.parse(path)); _, plt = parse_calls(path, secs)
    names = {}
    for sec in ('.plt', '.plt.sec'):
        if sec not in secs: continue
        out = subprocess.run(['objdump', '-d', '-j', sec, path], capture_output=True, text=True, check=True).stdout
        for line in out.splitlines():
            m = re.match(r'^([0-9a-f]+) <([^>]+)@plt>:', line)
            if m: names[int(m.group(1), 16)] = m.group(2)
    imported = {names[e]: slot for e, slot in plt.items() if e in names}
    res = {}
    for f in sorted(os.listdir(dso_dir)):
        fp = os.path.join(dso_dir, f)
        if not os.path.isfile(fp): continue
        nm = subprocess.run(['nm', '-D', '--defined-only', fp], capture_output=True, text=True).stdout
        for line in nm.splitlines():
            p = line.split()
            if len(p) == 3 and p[1] in ('T', 'W'):
                n = p[2].split('@')[0]
                if n in imported and f not in res:
                    res[f] = (imported[n], int(p[0], 16), n); break
    return res

PLAN_EXTRA = {}   # site -> list of (kind, value): ('rip', target_va) or ('anchor', (slot, disp))

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
    for kind, val in PLAN_EXTRA.get(site, []):
        if kind == 'rip':
            emit(enc_prefetch_rip(addr + len(code), val), True)
        else:
            slot, disp = val
            emit(b'\x4c\x8b\x1d' + struct.pack('<i', slot - (addr + len(code) + 7)), False)
            emit(enc_prefetch_r11(disp), True)
    for j in range(a.ret):
        emit(enc_prefetch_rip(addr + len(code), site + 5 + 64 * j), True)
    for k in range(a.seq_lines):
        emit(enc_prefetch_rip(addr + len(code), site + a.seq + 64 * k), True)
    if got is not None:
        if PLAN_EXTRA.get(site):
            emit(b'\x4c\x8b\x1d' + struct.pack('<i', got - (addr + len(code) + 7)), False)  # reload after anchors
        emit(b'\x41\xff\xe3', False)                       # jmp *%r11
    else:
        rel = callee - (addr + len(code) + 5)
        assert -2**31 <= rel < 2**31
        emit(b'\xe9' + struct.pack('<i', rel), False)      # jmp callee
    return code, nop

def patch_plt_inplace(a, path, data, twin, va2off):
    """Rewrite classic 16-byte PLT entries (`jmp *GOT(%rip); push idx; jmp plt0`) and IBT-style
    .plt.sec entries (`endbr64; bnd jmp *GOT(%rip); nop`) in place as
    `mov GOT(%rip),%r11 (7) ; prefetcht1 off(%r11) (5) ; jmp *%r11 (3) ; int3`.
    The lazy-binding push/jmp bytes are destroyed, so the file must be loaded with eager binding."""
    secs = sections(lief.parse(path))
    n = 0
    for sec in ('.plt', '.plt.sec'):
        if sec not in secs: continue
        out = subprocess.run(['objdump', '-d', '-j', sec, path], capture_output=True, text=True, check=True).stdout
        cur = None
        for line in out.splitlines():
            m = FUNC_RE.match(line)
            if m: cur = int(m.group(1), 16); continue
            m = PLT_JMP_RE.match(line)
            m2 = re.match(r'^\s*([0-9a-f]+):\s+f2 ff 25 ([0-9a-f]{2}) ([0-9a-f]{2}) ([0-9a-f]{2}) ([0-9a-f]{2})\s+bnd jmp', line)
            if cur is None or (not m and not m2): continue
            if m:
                at = int(m.group(1), 16); disp = struct.unpack('<i', bytes(int(m.group(i), 16) for i in range(2, 6)))[0]; slot = at + 6 + disp
            else:
                at = int(m2.group(1), 16); disp = struct.unpack('<i', bytes(int(m2.group(i), 16) for i in range(2, 6)))[0]; slot = at + 7 + disp
            entry = cur
            if sec == '.plt' and entry == secs['.plt'][0]:
                cur = None; continue   # PLT0 (resolver trampoline)
            code = b'\x4c\x8b\x1d' + struct.pack('<i', slot - (entry + 7))
            pf = enc_prefetch_r11(a.plt_inplace_off)
            assert len(pf) == 5
            code += pf + b'\x41\xff\xe3' + b'\xcc'
            assert len(code) == 16
            nop = code[:7] + NOP[5] + code[12:]
            off = va2off(entry)
            data[off:off + 16] = code
            if twin is not None: twin[off:off + 16] = nop
            n += 1; cur = None
    return n

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
    ap.add_argument('--plan', help='JSON plan: [{"site": <file offset of a call rel32>, "targets": [[dso, file_offset], ...]}, ...]; '
                                   'same-file targets use rip-relative prefetches, other DSOs use a GOT anchor imported from that DSO')
    ap.add_argument('--dso-dir', help='directory with the DSO files (to resolve GOT anchors for --plan)')
    ap.add_argument('--self-name', help='name of this file as used in the plan targets (default: basename of IN)')
    ap.add_argument('--plt-inplace', action='store_true',
                    help='rewrite each 16-byte PLT entry in place as `mov GOT(%%rip),%%r11; prefetcht1 OFF(%%r11); jmp *%%r11` '
                         '(no new code; requires eager binding: run with LD_BIND_NOW=1 or DT_BIND_NOW)')
    ap.add_argument('--plt-inplace-off', type=int, default=64, help='prefetch offset from the callee entry (|off|<128)')
    a = ap.parse_args()
    if not a.direct and not a.plt and not a.plt_inplace: a.direct = a.plt = True
    if a.seq and a.seq_lines == 0: a.seq_lines = 1
    if not a.seq: a.seq_lines = 0

    # 1) add the stub segment first (LIEF may shift all segments of a DYN file
    #    by one page to grow the PHDR), then parse call sites from the written file
    #    so every address below refers to the final layout.
    calls, plt, secs, total, sizes = None, None, None, 0, []
    only = None
    plan = None
    if a.plan:
        import json
        plan = json.load(open(a.plan))
        only = {int(e['site']) for e in plan}
        a.direct = a.plt = True
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
      if not sel and not a.plt_inplace and not a.plan:
          print('no sites selected', file=sys.stderr); sys.exit(1)
      return sel
    sel = select(a.inp)
    if plan is not None:
        # reserve space: per plan site up to (targets*(7+5+8) + 32) bytes
        maxt = max(len(e['targets']) for e in plan)
        sizes = [((maxt * 20 + 48) + a.align - 1) // a.align * a.align] * len(plan)
        sel = sel[:0]
    else:
      sizes = []
    for site, tgt, got in sel:
        a.burst_from = a.burst_from if a.burst_from is not None else (1 if got is not None else 0)
        c, _ = build_stub(0x10000000, site, tgt, got if got is not None else 0, a)
        sizes.append((len(c) + a.align - 1) // a.align * a.align)
    total = sum(sizes)
    if total == 0:
        # in-place PLT only: no new segment, patch a copy of the input
        import shutil; shutil.copyfile(a.inp, a.out)
        data = bytearray(open(a.out, 'rb').read()); twin = bytearray(data) if a.twin else None
        b2 = lief.parse(a.out)
        def va2off(va):
            for sg in b2.segments:
                if sg.type == lief.ELF.Segment.TYPE.LOAD and sg.virtual_address <= va < sg.virtual_address + sg.physical_size:
                    return va - sg.virtual_address + sg.file_offset
            raise KeyError(hex(va))
        n = patch_plt_inplace(a, a.out, data, twin, va2off)
        open(a.out, 'wb').write(data); os.chmod(a.out, 0o755)
        if twin is not None: open(a.twin, 'wb').write(twin); os.chmod(a.twin, 0o755)
        print(f'{os.path.basename(a.inp)}: plt-inplace entries={n} (no stub segment)')
        return
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
    shift = sections(b2)['.text'][0] - sections(lief.parse(a.inp))['.text'][0]
    if plan is not None:
        # plan sites are file offsets in the ORIGINAL file; in the original the text VA == file offset + (VA - offset) of .text
        s_in = sections(lief.parse(a.inp))['.text']; off2va = s_in[0] - s_in[2]
        only_va = {int(e['site']) + off2va + shift for e in plan}
        only.clear(); only.update(only_va)
        self_name = a.self_name or os.path.basename(a.inp)
        anch = anchors_for(a.out, a.dso_dir) if a.dso_dir else {}
        missing = collections.Counter(); placed = 0
        for e in plan:
            site_va = int(e['site']) + off2va + shift
            lst = []
            for dso, toff in e['targets']:
                if dso == self_name:
                    lst.append(('rip', int(toff) + off2va + shift))
                elif dso in anch:
                    slot, soff, _ = anch[dso]; lst.append(('anchor', (slot, int(toff) - soff)))
                else:
                    missing[dso] += 1; continue
                placed += 1
            if lst: PLAN_EXTRA[site_va] = lst
        print(f'plan: {len(plan)} sites, {placed} targets placed, unresolvable targets by DSO: {dict(missing)}; anchors: { {d: v[2] for d, v in anch.items()} }', file=sys.stderr)
    sel = select(a.out)   # re-select on the final layout (addresses may have shifted)
    if plan is not None:
        sel = [x for x in sel if x[0] in PLAN_EXTRA]
        sizes = []
        for site, tgt, got in sel:
            a.burst_from = a.burst_from if a.burst_from is not None else (1 if got is not None else 0)
            c, _ = build_stub(0x10000000, site, tgt, got if got is not None else 0, a)
            sizes.append((len(c) + a.align - 1) // a.align * a.align)
        assert sum(sizes) <= total, 'plan stubs larger than reserved segment'
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
    nplt_inplace = patch_plt_inplace(a, a.out, data, twin, va2off) if a.plt_inplace else 0
    open(a.out, 'wb').write(data)
    if twin is not None: open(a.twin, 'wb').write(twin)
    os.chmod(a.out, 0o755)
    if a.twin: os.chmod(a.twin, 0o755)
    print(f'{os.path.basename(a.inp)}: sites={len(sel)} (plt {nplt}, direct {len(sel)-nplt}) prefetches={npf} '
          f'stub_segment={base:#x}+{total} bytes; burst={a.burst} ret={a.ret} seq={a.seq}x{a.seq_lines}'
          + (f'; plt-inplace entries={nplt_inplace}' if a.plt_inplace else ''))

if __name__ == '__main__':
    main()
