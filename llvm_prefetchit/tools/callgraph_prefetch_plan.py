#!/usr/bin/env python3
"""Defined-symbol direct call/tail-call graph adapter; no execution profiles.

Aliases share one graph node. Prefer Itanium base constructors/destructors as
injection sites because complete-object names often are LLVM aliases. Local
nodes can be traversed, but only global symbols become injection sites/targets.
Indirect calls are deliberately left unresolved.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from static_prefetch_graph import descendants, code_lines


def symbol_table(binary):
    groups = {}
    for line in subprocess.check_output(['nm', '-S', '--defined-only', str(binary)], text=True).splitlines():
        f = line.split()
        if len(f) == 4 and f[2] in 'TtWw':
            groups.setdefault(int(f[0], 16), []).append((f[3], int(f[1], 16), f[2].isupper()))
    def preference(s):
        return (not s[2], not bool(re.search(r'[CD]2E', s[0])), s[0])
    result={}
    for address,entries in groups.items():
        name,size,public=sorted(entries,key=preference)[0]
        # File-local symbols with identical names in different translation
        # units are distinct graph nodes, not aliases of each other.
        result[address]=(name if public else f'{name}@local:{address:x}',size,public)
    return result


def parse_edges(lines, symbols):
    graph = {entry[0]: [] for entry in symbols.values()}
    source = None
    for line in lines:
        header = re.match(r'^([0-9a-f]+) <.*>:$', line.strip())
        if header:
            entry = symbols.get(int(header[1], 16))
            source = entry[0] if entry else None
            continue
        call = re.match(r'^\s*[0-9a-f]+:\s+(?:callq?|jmpq?)\s+(?:0x)?([0-9a-f]+)\s+<', line)
        if source and call:
            entry = symbols.get(int(call[1], 16))
            if entry and entry[0] != source and entry[0] not in graph[source]:
                graph[source].append(entry[0])
    return graph


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--cache', type=Path)
    p.add_argument('--depth', type=int, default=2)
    p.add_argument('--min-depth', type=int, default=2)
    p.add_argument('--max-targets', type=int, default=8)
    p.add_argument('--lines', type=int, default=8)
    p.add_argument('--line-budget', type=int, default=0)
    p.add_argument('--order', choices=['target', 'round-robin'], default='target')
    a = p.parse_args()
    if not 1 <= a.min_depth <= a.depth or min(a.max_targets, a.lines) < 1 or a.line_budget < 0:
        p.error('invalid frontier or budget')
    sha = hashlib.sha256(a.binary.read_bytes()).hexdigest()
    data = json.loads(a.cache.read_text()) if a.cache and a.cache.exists() else None
    if data is None or data.get('format_version') != 2 or data['sha256'] != sha:
        symbols = symbol_table(a.binary)
        proc = subprocess.Popen(['llvm-objdump-19', '-d', '--no-show-raw-insn', str(a.binary)], stdout=subprocess.PIPE, text=True)
        graph = parse_edges(proc.stdout, symbols)
        if proc.wait(): raise RuntimeError('disassembly failed')
        data = {'format_version':2,'sha256': sha, 'graph': graph,
                'sizes': {v[0]: v[1] for v in symbols.values()},
                'globals': [v[0] for v in symbols.values() if v[2]]}
        if a.cache:
            a.cache.parent.mkdir(parents=True, exist_ok=True)
            a.cache.write_text(json.dumps(data))
    public = set(data['globals'])
    sites = {}
    for source in data['globals']:
        targets = [t for t in descendants(data['graph'], source, a.min_depth, a.depth)
                   if t != source and t in public][:a.max_targets]
        hints = code_lines(targets, data['sizes'], lines=a.lines, cap_to_size=True,
                           budget=a.line_budget, order=a.order)
        if hints: sites[source] = {'k': 7 * len(hints), 't': hints}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps({'sites': sites}, indent=2, sort_keys=True))
    print(json.dumps({'binary_sha256': sha, 'nodes': len(data['graph']),
                      'edges': sum(map(len, data['graph'].values())),
                      'sites': len(sites), 'hints': sum(len(s['t']) for s in sites.values())}))


if __name__ == '__main__': main()
