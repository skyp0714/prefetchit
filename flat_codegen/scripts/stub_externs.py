#!/usr/bin/env python3
"""Replace hw.module.extern declarations in a firtool --ir-hw MLIR file with
sequential stub implementations so arcilator can compile chipyard harnesses.

- Clocked externs (SimDRAM/SimUART/...): outputs sliced from a free-running
  counter register -> sequential (breaks false comb loops through blackboxes)
  and non-constant (defeats const-prop pruning).
- Unclocked externs (plusarg_reader, IO cells): constant-0 outputs.
- !seq.clock outputs derived via seq.to_clock from a counter bit.

Usage: stub_externs.py file.mlir   (in-place)
"""
import re
import sys

PORT_RE = re.compile(r'(in|out)\s+(%?[A-Za-z0-9_$.]+)\s*:\s*([^,)]+)')
DECL_RE = re.compile(
    r'^(\s*)hw\.module\.extern\s+private\s+@([A-Za-z0-9_$]+)'
    r'(<[^>]*>)?\(([^)]*)\)\s*attributes\s*\{[^}]*\}\s*$')


def parse_ports(portstr):
    ports = []
    for m in PORT_RE.finditer(portstr):
        direction, name, ty = m.group(1), m.group(2).lstrip('%'), m.group(3).strip()
        ports.append((direction, name, ty))
    return ports


def intwidth(ty):
    m = re.fullmatch(r'i(\d+)', ty)
    return int(m.group(1)) if m else None


def build_stub(indent, name, params, ports):
    ins = [(n, t) for d, n, t in ports if d == 'in']
    outs = [(n, t) for d, n, t in ports if d == 'out']
    clock_in = next((n for n, t in ins if t == '!seq.clock'), None)
    reset_in = next((n for n, t in ins if n == 'reset' and t == 'i1'), None)

    header_ports = ', '.join(
        (f'in %{n} : {t}' if d == 'in' else f'out {n} : {t}')
        for d, n, t in ports)
    lines = [f'{indent}hw.module private @{name}{params or ""}({header_ports}) {{']
    body = []
    results = []
    if clock_in:
        body.append(f'{indent}  %stub_c0 = hw.constant 0 : i64')
        body.append(f'{indent}  %stub_c1 = hw.constant 1 : i64')
        body.append(f'{indent}  %stub_next = comb.add %stub_cnt, %stub_c1 : i64')
        if reset_in:
            body.append(f'{indent}  %stub_cnt = seq.firreg %stub_next clock '
                        f'%{clock_in} reset sync %{reset_in}, %stub_c0 : i64')
        else:
            body.append(f'{indent}  %stub_cnt = seq.firreg %stub_next clock '
                        f'%{clock_in} : i64')
    bit_idx = 0
    for n, t in outs:
        w = intwidth(t)
        if t == '!seq.clock':
            if clock_in:
                body.append(f'{indent}  %stub_b_{n} = comb.extract %stub_cnt '
                            f'from {bit_idx % 32} : (i64) -> i1')
                body.append(f'{indent}  %stub_o_{n} = seq.to_clock %stub_b_{n}')
                bit_idx += 1
            else:
                body.append(f'{indent}  %stub_z_{n} = hw.constant 0 : i1')
                body.append(f'{indent}  %stub_o_{n} = seq.to_clock %stub_z_{n}')
            results.append((f'%stub_o_{n}', t))
        elif w is not None:
            if clock_in:
                src_w = min(w, 64 - (bit_idx % 8))
                if w <= 64:
                    body.append(f'{indent}  %stub_o_{n} = comb.extract %stub_cnt '
                                f'from {bit_idx % 8} : (i64) -> {t}')
                    bit_idx += 1
                else:
                    body.append(f'{indent}  %stub_o_{n} = hw.constant 0 : {t}')
            else:
                body.append(f'{indent}  %stub_o_{n} = hw.constant 0 : {t}')
            results.append((f'%stub_o_{n}', t))
        else:
            raise RuntimeError(f'unhandled out type {t} in {name}')
    if results:
        vals = ', '.join(v for v, _ in results)
        tys = ', '.join(t for _, t in results)
        body.append(f'{indent}  hw.output {vals} : {tys}')
    else:
        body.append(f'{indent}  hw.output')
    lines.extend(body)
    lines.append(f'{indent}}}')
    return '\n'.join(lines)


def main():
    path = sys.argv[1]
    out_lines = []
    replaced = 0
    for line in open(path):
        m = DECL_RE.match(line.rstrip('\n'))
        if m:
            indent, name, params, portstr = m.groups()
            ports = parse_ports(portstr)
            try:
                out_lines.append(build_stub(indent, name, params, ports) + '\n')
                replaced += 1
                continue
            except RuntimeError as e:
                print(f'[skip] {name}: {e}')
        out_lines.append(line)
    open(path, 'w').writelines(out_lines)
    print(f'replaced {replaced} extern modules with stubs')


if __name__ == '__main__':
    main()
