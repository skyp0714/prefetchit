#!/usr/bin/env python3
"""Route selected direct calls through register/flag-neutral prefetch leaf stubs.

Original instructions stay at their original addresses. An E8 call still pushes
its original return address; its stub issues RIP hints and jumps to the original
callee. No prologue instructions are stolen. A merged GNU unwind lookup table
keeps every old FDE and adds leaf CFA rules for the new stubs.

This is a restricted ELF64 experiment, not a general binary rewriter. Unsupported
unwind encodings, relocations over patches, or non-E8 sites are rejected.
"""
import argparse
import bisect
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

PH = struct.Struct('<IIQQQQQQ')
SH = struct.Struct('<IIQQQQIIQQ')
EH_FRAME = 0x6474e550
NOP7 = bytes.fromhex('0f1f8000000000')


def align(value, size=4096):
    return (value + size - 1) // size * size


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Elf:
    def __init__(self, data):
        self.data = data
        assert data[:6] == b'\x7fELF\x02\x01'
        assert struct.unpack_from('<H', data, 18)[0] == 62
        assert struct.unpack_from('<H', data, 16)[0] in (2, 3)
        phoff, shoff = struct.unpack_from('<QQ', data, 32)
        phents, phnum, shents, shnum, self.shstr = struct.unpack_from('<HHHHH', data, 54)
        assert phents == PH.size and shents == SH.size and 0 < phnum < 128 and 0 < shnum < 65500
        self.ph = [list(PH.unpack_from(data, phoff + i * PH.size)) for i in range(phnum)]
        self.sh = [list(SH.unpack_from(data, shoff + i * SH.size)) for i in range(shnum)]
        string = self.sh[self.shstr]
        self.strings = data[string[4]:string[4] + string[5]]
        self.names = [self.strings[s[0]:].split(b'\0', 1)[0].decode() for s in self.sh]

    def section(self, name):
        row = self.sh[self.names.index(name)]
        return row, self.data[row[4]:row[4] + row[5]]

    def offset(self, va, length=1, executable=False):
        matches = [p for p in self.ph if p[0] == 1 and p[3] <= va and va + length <= p[3] + p[5]]
        assert len(matches) == 1, 'VA outside unique file-backed LOAD'
        p = matches[0]
        assert not executable or p[1] & 1, 'Non-executable target/site'
        return p[2] + va - p[3]


def decode_eh_header(raw, address):
    # Common GNU x86-64 ABI: pcrel sdata4 pointer, udata4 count,
    # datarel sdata4 (initial PC, FDE pointer) table. Fail closed otherwise.
    assert raw[:4] == bytes.fromhex('011b033b'), 'Unsupported GNU EH header encoding'
    eh = address + 4 + struct.unpack_from('<i', raw, 4)[0]
    count = struct.unpack_from('<I', raw, 8)[0]
    assert 12 + 8 * count <= len(raw)
    rows = [(address + pc, address + fde) for pc, fde in struct.iter_unpack('<ii', raw[12:12 + 8 * count])]
    assert rows == sorted(rows), 'Unsorted original unwind search table'
    return eh, rows


def encode_eh_header(address, eh, rows):
    rows = sorted(rows)
    return (bytes.fromhex('011b033b') + struct.pack('<iI', eh - address - 4, len(rows)) +
            b''.join(struct.pack('<ii', pc - address, fde - address) for pc, fde in rows))


def instruction_boundaries(binary, wanted):
    found = set()
    process = subprocess.Popen(['objdump', '-d', '--insn-width=16', str(binary)], stdout=subprocess.PIPE, text=True)
    for line in process.stdout:
        match = re.match(r'^\s*([0-9a-f]+):\s', line)
        if match and int(match[1], 16) in wanted:
            found.add(int(match[1], 16))
    assert process.wait() == 0 and found == wanted, 'Site/target is not an original instruction boundary'


def build(binary, plan, output, boundaries=None, hybrid=None):
    binary, output = Path(binary), Path(output)
    twin = Path(str(output) + '.nop')
    assert not output.exists() and not twin.exists()
    assert shutil.disk_usage('/').free > 7 * 2**30
    assert shutil.disk_usage(binary.parent).free > 2 * binary.stat().st_size + 2**30
    original = binary.read_bytes()
    if hybrid is not None:
        assert set(hybrid)<= {'diagnostic'}
        import runpy
        hybrid_source=Path(__file__).with_name('hybrid_call_assembly.py')
        emit_hybrid=runpy.run_path(str(hybrid_source))['emit']
    assert sha(original) == plan['sha256'], 'Input fingerprint mismatch'
    elf = Elf(original)
    eh_ph = [p for p in elf.ph if p[0] == EH_FRAME]
    assert len(eh_ph) == 1, 'Exactly one original GNU EH header required'
    old_eh, old_entries = decode_eh_header(original[eh_ph[0][2]:eh_ph[0][2] + eh_ph[0][5]], eh_ph[0][3])
    calls = plan['calls']
    assert calls and len({r['site'] for r in calls}) == len(calls)
    canonical = {}; stub_indices = []
    for index, row in enumerate(calls):
        # Sharing identical leaf stubs reduces appended instruction footprint
        # while each original call still pushes its own original return address.
        key = (row['callee'], tuple(row['targets']))
        if hybrid is not None:key += (tuple(row['burst_targets']),bool(row.get('hybrid_gate',True)))
        stub_indices.append(canonical.setdefault(key, index))
    wanted = set()
    for row in calls:
        site = row['site']; off = elf.offset(site, 5, True)
        raw = original[off:off + 5]
        assert raw[0] == 0xe8 and raw.hex() == row['expected'], 'Only fingerprinted E8 rel32 calls are supported'
        assert site + 5 + struct.unpack_from('<i', raw, 1)[0] == row['callee']
        assert 1 <= len(row['targets']) <= 8 and len(set(row['targets'])) == len(row['targets'])
        wanted.update([site, row['callee'], *row['targets']])
        burst=row.get('burst_targets',[]) if hybrid is not None else []
        if hybrid is not None:
            assert 1<=len(burst)<=16 and len(set(burst))==len(burst)
            assert set(row['targets'])<=set(burst)
            wanted.update(burst)
        for target in row['targets']+burst:
            elf.offset(target, 1, True)
    if boundaries is None:
        instruction_boundaries(binary, wanted)
    else:
        assert all(v in boundaries for v in wanted)
    patch_bytes = sorted(r['site'] + i for r in calls for i in range(1, 5))
    for s in elf.sh:
        if s[1] not in (4, 9) or not s[2] & 2:
            continue
        size = 24 if s[1] == 4 else 16
        assert s[9] == size and s[5] % size == 0
        for pos in range(s[4], s[4] + s[5], size):
            va = struct.unpack_from('<Q', original, pos)[0]
            index = bisect.bisect_left(patch_bytes, va)
            assert index == len(patch_bytes) or patch_bytes[index] >= va + 8, 'Runtime relocation overlaps call patch'
    ph = [list(p) for p in elf.ph]
    assert sum(p[0] == 6 for p in ph) == 1, 'An existing PT_PHDR is required'
    count = len(ph) + (2 if hybrid is not None else 1)
    rxoff = align(len(original))
    rxva = align(max(p[3] + p[6] for p in ph if p[0] == 1))
    codeva = rxva + align(count * PH.size, 64)
    lines = ['.text']; definitions = [];hybrid_hints={};hybrid_jumps={}
    for i, row in enumerate(calls):
        if stub_indices[i] != i:
            continue
        lines += [f'.balign 16\n.global pf_call_{i}\n.type pf_call_{i},@function\npf_call_{i}:', '.cfi_startproc']
        if hybrid is None:
            for j, target in enumerate(row['targets']):
                definitions.append(f'pf_target_{i}_{j} = 0x{target:x};')
                lines += [f'prefetcht1 pf_target_{i}_{j}(%rip)']
        else:
            emitted,defs,hybrid_hints[i],hybrid_jumps[i]=emit_hybrid(i,row,hybrid.get('diagnostic',False))
            lines+=emitted;definitions+=defs
        definitions.append(f'pf_callee_{i} = 0x{row["callee"]:x};')
        if hybrid is None:lines += [f'jmp pf_callee_{i}']
        lines += ['.cfi_endproc', f'.size pf_call_{i},.-pf_call_{i}']
    lines += ['.section .note.GNU-stack,"",@progbits']
    output.parent.mkdir(parents=True, exist_ok=True)
    source = Path(str(output) + '.stubs.s')
    source.write_text('\n'.join(lines) + '\n')
    script = Path(str(output) + '.stubs.ld')
    # Leave RIP operands undefined in assembly so they get PC-relative
    # relocations. An assembler .set absolute would encode a displacement.
    reservation=''
    if hybrid is not None:
        # Leave enough space for the merged, larger GNU unwind search table.
        reservation=(f'. = ALIGN(. + {12+8*(len(old_entries)+len(canonical))},4096); '
            '.prefetch_clock (NOLOAD) : { pf_clock_base = .; . += 262144; } '
            '.prefetch_state (NOLOAD) : { pf_state_base = .; . += 262144; } '
            f'.prefetch_sites (NOLOAD) : {{ pf_site_stats = .; . += {align(len(calls)*32)}; }} ')
    script.write_text('\n'.join(definitions)+'\n'+('SECTIONS { . = 0x%x; .text : { *(.text) } . = ALIGN(8); .eh_frame : { *(.eh_frame) } . = ALIGN(4); .eh_frame_hdr : { *(.eh_frame_hdr) } ' % codeva)+reservation+'/DISCARD/ : { *(.note*) *(.comment) } }\n')
    temporary = []
    commands = []
    generated = []
    try:
        with tempfile.TemporaryDirectory(prefix='call-stub-', dir=output.parent) as temp:
            temp = Path(temp); obj = temp/'stubs.o'; linked = temp/'stubs.elf'
            commands = [['clang-19', '-c', str(source), '-o', str(obj)],
                        ['ld', '--build-id=none', '--eh-frame-hdr', '-T', str(script), '-e', 'pf_call_0', str(obj), '-o', str(linked)]]
            try:
                for command in commands:
                    subprocess.run(command, check=True)
            finally:
                for path in (obj, linked):
                    if path.exists():
                        raw = path.read_bytes(); temporary.append(dict(path=str(path), bytes=len(raw), sha256=sha(raw)))
            built = Elf(linked.read_bytes())
            assert 'There are no relocations' in subprocess.check_output(['readelf', '-r', str(linked)], text=True)
            text_s, code = built.section('.text')
            frame_s, frame = built.section('.eh_frame')
            hdr_s, hdr = built.section('.eh_frame_hdr')
            _, entries = decode_eh_header(hdr, hdr_s[3])
            assert len(entries) == len(canonical)
            symbols = {s[2]:int(s[0], 16) for line in subprocess.check_output(['nm', str(linked)], text=True).splitlines() if len(s := line.split()) == 3}
            Path(str(output) + '.stubs.asm').write_text(subprocess.check_output(['objdump', '-d', str(linked)], text=True))
        merged_va = align(frame_s[3] + len(frame), 4)
        merged = encode_eh_header(merged_va, old_eh, old_entries + entries)
        rxsize = merged_va + len(merged) - rxva
        data = bytearray(original)
        data.extend(b'\0' * (rxoff + rxsize - len(data)))
        for p in ph:
            if p[0] == 6:
                p[:] = [6, 4, rxoff, rxva, rxva, count * PH.size, count * PH.size, 8]
            elif p[0] == EH_FRAME:
                p[:] = [EH_FRAME, 4, rxoff + merged_va - rxva, merged_va, merged_va, len(merged), len(merged), 4]
        ph.append([1, 5, rxoff, rxva, rxva, rxsize, rxsize, 4096])
        if hybrid is not None:
            clockva=symbols['pf_clock_base'];stateva=symbols['pf_state_base']
            assert clockva%4096==0 and stateva-clockva==262144 and rxva+rxsize<=clockva
            sitesva=symbols['pf_site_stats'];sitesbytes=align(len(calls)*32)
            assert sitesva==clockva+524288
            rwoff=align(len(data));data.extend(b'\0'*(rwoff-len(data)))
            ph.append([1,6,rwoff,clockva,clockva,0,524288+sitesbytes,4096])
        for i, p in enumerate(ph):
            PH.pack_into(data, rxoff + i * PH.size, *p)
        for va, raw in [(text_s[3], code), (frame_s[3], frame), (merged_va, merged)]:
            off = rxoff + va - rxva
            data[off:off + len(raw)] = raw
        patches = []; hints = []; seen_hints = set()
        for i, row in enumerate(calls):
            stub = symbols[f'pf_call_{stub_indices[i]}']; off = elf.offset(row['site'], 5, True)
            replacement = b'\xe8' + struct.pack('<i', stub - row['site'] - 5)
            data[off:off + 5] = replacement
            patches.append(dict(**row, offset=off, stub=stub, replacement=replacement.hex()))
            emitted_hints=([dict(va=stub+j*7,target=target,kind='t1') for j,target in enumerate(row['targets'])]
                if hybrid is None else [dict(h,va=symbols[h['symbol']]) for h in hybrid_hints[stub_indices[i]]])
            for h in emitted_hints:
                va=h['va'];target=h['target'];hintoff = rxoff + va - rxva
                raw = bytes(data[hintoff:hintoff + 7])
                assert raw[:3] == bytes.fromhex('0f183d' if h['kind']=='it0' else '0f1815') and va + 7 + struct.unpack_from('<i', raw, 3)[0] == target
                if hintoff not in seen_hints:
                    entry=dict(va=va, offset=hintoff, target=target, original=raw.hex(), nop=NOP7.hex())
                    if hybrid is not None:entry['kind']=h['kind']
                    hints.append(entry)
                    seen_hints.add(hintoff)
            jumpvas=([stub+len(row['targets'])*7] if hybrid is None else [symbols[s] for s in hybrid_jumps[stub_indices[i]]])
            for jumpva in jumpvas:
                jumpoff = rxoff + jumpva - rxva
                assert data[jumpoff] == 0xe9 and jumpva + 5 + struct.unpack_from('<i', data, jumpoff + 1)[0] == row['callee']
        # Expose stubs to offline disassembly and the merged unwind table to
        # ELF readers. Old allocated sections and symbol addresses stay fixed.
        sh = [list(s) for s in elf.sh]; strings = bytearray(elf.strings)
        def name(text):
            value = len(strings); strings.extend(text.encode() + b'\0'); return value
        sh.append([name('.text.prefetch_calls'), 1, 6, codeva, rxoff + codeva - rxva, len(code), 0, 0, 16, 0])
        sh.append([name('.eh_frame.prefetch_calls'), 1, 2, frame_s[3], rxoff + frame_s[3] - rxva, len(frame), 0, 0, 8, 0])
        if hybrid is not None:
            for label,va in [('.prefetch_clock',clockva),('.prefetch_state',stateva)]:
                sh.append([name(label),8,3,va,rwoff,262144,0,0,4096,0])
            sh.append([name('.prefetch_sites'),8,3,sitesva,rwoff,sitesbytes,0,0,4096,0])
        old_hdr = sh[elf.names.index('.eh_frame_hdr')]
        old_hdr[3:6] = [merged_va, rxoff + merged_va - rxva, len(merged)]
        sh[elf.shstr][4:6] = [len(data), len(strings)]
        data.extend(strings)
        shoff = align(len(data), 8); data.extend(b'\0' * (shoff - len(data)))
        for s in sh:
            data.extend(SH.pack(*s))
        struct.pack_into('<QQ', data, 32, rxoff, shoff)
        struct.pack_into('<H', data, 56, len(ph)); struct.pack_into('<H', data, 60, len(sh))
        # Every original byte except ELF table pointers/counts and E8 operands
        # must be exactly reversible. In particular no original data changes.
        reverse = bytearray(data[:len(original)])
        reverse[32:48] = original[32:48]; reverse[56:62] = original[56:62]
        for row in patches:
            reverse[row['offset']:row['offset'] + 5] = bytes.fromhex(row['expected'])
        assert reverse == original
        nop = bytearray(data)
        for row in hints:
            nop[row['offset']:row['offset'] + 7] = NOP7
        for path, raw in [(output, data), (twin, nop)]:
            path.write_bytes(raw); path.chmod(0o755); generated.append(path)
        check = Elf(data)
        new_hdr = next(p for p in check.ph if p[0] == EH_FRAME)
        recovered_eh, recovered = decode_eh_header(data[new_hdr[2]:new_hdr[2] + new_hdr[5]], new_hdr[3])
        assert recovered_eh == old_eh and recovered == sorted(old_entries + entries)
        record = dict(source=str(binary), source_sha256=sha(original), sha256=sha(data), nop_sha256=sha(nop),
                      plan=plan, patches=patches, hints=hints, commands=commands,
                      source_tool_sha256=sha(Path(__file__).read_bytes()), source_assembly_sha256=sha(source.read_bytes()),
                      source_linker_script_sha256=sha(script.read_bytes()),
                      original_instruction_addresses_unchanged=True, original_bytes_reversible=True,
                      original_return_addresses_preserved=True, registers_and_flags_untouched=hybrid is None,
                      registers_and_flags_preserved=True,
                      extra_instruction_bytes=len(code), extra_mapped_bytes=rxsize+(524288+sitesbytes if hybrid is not None else 0), extra_file_bytes=len(data)-len(original),
                      old_fdes=len(old_entries), added_fdes=len(entries),
                      unique_stubs=len(canonical), call_sites=len(calls),
                      original_build_id_retained=True, perf_identity='Use SHA and runtime maps, not the unchanged original build ID.',
                      temporary_artifacts=temporary, temporary_bytes_removed=sum(r['bytes'] for r in temporary))
        if hybrid is not None:
            record['hybrid']=dict(hybrid,clock_va=clockva,state_va=stateva,array_bytes=262144,clock_abi=2,
                site_stats_va=sitesva,site_stats_bytes=sitesbytes,site_stride=32,
                site_groups=[dict(index=i,sites=[row['site'] for j,row in enumerate(calls) if stub_indices[j]==i],
                    gated=bool(calls[i].get('hybrid_gate',True))) for i in sorted(set(stub_indices))],
                assembly_generator_sha256=sha(hybrid_source.read_bytes()),
                timing='First instrumented call in a newly observed CPU scheduler epoch, only before dense_us deadline. Not the first user instruction or a fetch-queue occupancy measurement.',
                races='Per-CPU shared words are best effort under preemption/migration; RDTSCP identity and epoch checks reject observed races. Optional hint issuance is not atomic with scheduling.')
        Path(str(output) + '.json').write_text(json.dumps(record, indent=2) + '\n')
        return record
    except BaseException as error:
        removed = []
        for path in generated:
            raw = path.read_bytes(); removed.append(dict(path=str(path), bytes=len(raw), sha256=sha(raw)))
            path.unlink()
        Path(str(output) + '.failure.json').write_text(json.dumps(dict(error=repr(error), source_sha256=sha(original), plan=plan,
            commands=commands, removed=removed, temporary_artifacts=temporary, source_assembly=str(source)), indent=2) + '\n')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path); parser.add_argument('plan', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args()
    assert shutil.disk_usage('/').free > 7 * 2**30
    assert shutil.disk_usage(args.output.parent).free > 2 * args.binary.stat().st_size + 2**30
    build(args.binary, json.loads(args.plan.read_text()), args.output)
