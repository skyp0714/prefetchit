#!/usr/bin/env python3
"""Per-request hot-set burst (post-link, no rebuild): rewrite chosen PLT entries of an executable so that
every call through them first prefetches a fixed set of hot code lines (from an L2I-miss trace), across
all DSOs, then continues to the real callee.

  PLT entry <site@plt>  ->  jmp stub_site
  stub_site:  prefetcht1 line(%rip)                       for lines in this executable
              mov  anchor_d@GOT(%rip),%r11 ; prefetcht1 (line_off - anchor_off)(%r11) ...   per DSO d
              mov  site@GOT(%rip),%r11 ; jmp *%r11
The anchor for DSO d is any non-IFUNC function symbol the executable imports from d (its GOT slot holds
d's runtime address of that symbol, so line_off - anchor_off is a load-independent displacement).
Requires eager binding (LD_BIND_NOW=1): the lazy-binding bytes of the rewritten PLT entries are destroyed.

Usage: postlink_hotset_burst.py EXE OUT --twin OUT_NOP --hotlines hotlines.txt --dso-dir DIR
         --sites mongoc_client_pool_pop,mongoc_client_pool_push --lines N [--exe-name UserTimelineService]
hotlines.txt: "dso file_offset samples" per line (sorted by samples desc), '#' comments.
"""
import argparse, os, re, struct, subprocess, sys
import lief

FUNC_RE = re.compile(r'^([0-9a-f]+) <([^>]+)>:')
PLT_JMP_RE = re.compile(r'^\s*([0-9a-f]+):\s+ff 25 ([0-9a-f]{2}) ([0-9a-f]{2}) ([0-9a-f]{2}) ([0-9a-f]{2})\s+jmp')
NOP = {4: b'\x0f\x1f\x40\x00', 5: b'\x0f\x1f\x44\x00\x00', 7: b'\x0f\x1f\x80\x00\x00\x00\x00', 8: b'\x0f\x1f\x84\x00\x00\x00\x00\x00'}

def plt_entries(path):
    out = subprocess.run(['objdump', '-d', '-j', '.plt', path], capture_output=True, text=True, check=True).stdout
    ents = {}; cur = None; name = None
    for line in out.splitlines():
        m = FUNC_RE.match(line)
        if m: cur = int(m.group(1), 16); name = m.group(2).replace('@plt', ''); continue
        m = PLT_JMP_RE.match(line)
        if m and cur is not None and name and name != '.plt':
            at = int(m.group(1), 16); disp = struct.unpack('<i', bytes(int(m.group(i), 16) for i in range(2, 6)))[0]
            ents[name] = (cur, at + 6 + disp); cur = None
    return ents

def dso_syms(path):
    out = subprocess.run(['nm', '-D', '--defined-only', path], capture_output=True, text=True).stdout
    syms = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) == 3 and p[1] in ('T', 'W'):
            syms.setdefault(p[2].split('@')[0], int(p[0], 16))
    return syms

def pf_rip(at, target):
    return b'\x0f\x18\x15' + struct.pack('<i', target - (at + 7))
def pf_r11(off):
    if -128 <= off < 128: return b'\x41\x0f\x18\x53' + struct.pack('<b', off)
    return b'\x41\x0f\x18\x93' + struct.pack('<i', off)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('exe'); ap.add_argument('out'); ap.add_argument('--twin')
    ap.add_argument('--hotlines', required=True); ap.add_argument('--dso-dir', required=True)
    ap.add_argument('--sites', required=True); ap.add_argument('--lines', type=int, default=500)
    ap.add_argument('--exe-name', default=None); ap.add_argument('--exclude-dso', default='')
    a = ap.parse_args()
    exe_name = a.exe_name or os.path.basename(a.exe)
    excl = set(a.exclude_dso.split(',')) - {''}
    hot = []
    for ln in open(a.hotlines):
        if ln.startswith('#') or not ln.strip(): continue
        d, o, c = ln.split()[:3]
        if d in excl: continue
        hot.append((d, int(o, 16), int(c)))
        if len(hot) >= a.lines: break
    plt = plt_entries(a.exe)
    sites = []
    for s in a.sites.split(','):
        if s not in plt: sys.exit(f'site {s} not in PLT')
        sites.append((s, plt[s][0], plt[s][1]))
    # anchors per DSO
    dsos = sorted({d for d, _, _ in hot if d != exe_name})
    anchor = {}
    for d in dsos:
        p = os.path.join(a.dso_dir, d)
        if not os.path.exists(p): sys.exit(f'missing DSO file {p}')
        syms = dso_syms(p)
        cand = [(n, syms[n]) for n in plt if n in syms]
        if not cand: sys.exit(f'no imported non-IFUNC symbol from {d}')
        n, off = cand[0]; anchor[d] = (n, plt[n][1], off)
    # stub layout (addresses resolved after segment placement): compute size first
    def build(stub_addr, site_slot):
        code = b''; nop = b''
        def emit(ins, pf):
            nonlocal code, nop
            code += ins; nop += (NOP[len(ins)] if pf else ins)
        for d, o, _ in hot:
            if d == exe_name: emit(pf_rip(stub_addr + len(code), o), True)
        for d in dsos:
            n, slot, aoff = anchor[d]
            emit(b'\x4c\x8b\x1d' + struct.pack('<i', slot - (stub_addr + len(code) + 7)), False)
            for dd, o, _ in hot:
                if dd == d: emit(pf_r11(o - aoff), True)
        emit(b'\x4c\x8b\x1d' + struct.pack('<i', site_slot - (stub_addr + len(code) + 7)), False)
        emit(b'\x41\xff\xe3', False)
        return code, nop
    size1 = len(build(0x10000000, 0x10000000)[0]); size1 = (size1 + 15) // 16 * 16
    total = size1 * len(sites)
    b = lief.parse(a.exe)
    seg = lief.ELF.Segment(); seg.type = lief.ELF.Segment.TYPE.LOAD
    seg.flags = lief.ELF.Segment.FLAGS.R | lief.ELF.Segment.FLAGS.X; seg.alignment = 0x1000
    seg.content = list(b'\xcc' * total); b.add(seg); b.write(a.out)
    b2 = lief.parse(a.out)
    stubseg = next(s for s in b2.segments if s.type == lief.ELF.Segment.TYPE.LOAD and bytes(s.content[:8]) == b'\xcc' * 8 and (int(s.flags) & int(lief.ELF.Segment.FLAGS.X)))
    base, foff = stubseg.virtual_address, stubseg.file_offset
    def va2off(va):
        for s in b2.segments:
            if s.type == lief.ELF.Segment.TYPE.LOAD and s.virtual_address <= va < s.virtual_address + s.physical_size:
                return va - s.virtual_address + s.file_offset
        raise KeyError(hex(va))
    # exe addresses must be unchanged (EXEC) — verify a PLT entry
    assert plt_entries(a.out) == plt, 'layout changed by LIEF (PIE?); this tool expects a non-PIE executable'
    data = bytearray(open(a.out, 'rb').read()); twin = bytearray(data) if a.twin else None
    npf = 0
    for i, (name, entry, slot) in enumerate(sites):
        sa = base + i * size1
        code, nop = build(sa, slot)
        off = sa - base + foff
        data[off:off + len(code)] = code
        if twin is not None: twin[off:off + len(nop)] = nop
        eo = va2off(entry)
        jmp = b'\xe9' + struct.pack('<i', sa - (entry + 5)) + b'\xcc' * 11
        data[eo:eo + 16] = jmp
        if twin is not None: twin[eo:eo + 16] = jmp
        npf = code.count(b'\x0f\x18')
    open(a.out, 'wb').write(data); os.chmod(a.out, 0o755)
    if twin is not None: open(a.twin, 'wb').write(twin); os.chmod(a.twin, 0o755)
    cov = sum(c for _, _, c in hot)
    print(f'{exe_name}: sites={[s for s,_,_ in sites]} lines={len(hot)} ({npf} prefetches/site, stub {size1} B) '
          f'dsos={ {d: anchor[d][0] for d in dsos} } hot-sample-coverage={cov}')

if __name__ == '__main__':
    main()
