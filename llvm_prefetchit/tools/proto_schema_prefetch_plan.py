#!/usr/bin/env python3
"""Static protobuf field-type graph -> code-entry prefetch plan.

Uses a protoc descriptor and defined binary symbols, never execution profiles.
A parent's Clear/Merge/Size/Serialize operation predicts the corresponding child
operation, including calls whose concrete type protobuf's runtime erases.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from google.protobuf import descriptor_pb2
from static_prefetch_graph import descendants, code_lines


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('descriptor',type=Path)
    ap.add_argument('binary',type=Path)
    ap.add_argument('output',type=Path)
    ap.add_argument('--methods',default='Clear,MergeImpl,ByteSizeLong,_InternalSerialize')
    ap.add_argument('--max-children',type=int,default=4)
    ap.add_argument('--depth',type=int,default=1)
    ap.add_argument('--min-depth',type=int,default=1,
                    help='skip nearer descendants to test earlier ancestor placement')
    ap.add_argument('--lines',type=int,default=1)
    ap.add_argument('--start-line',type=int,default=0)
    ap.add_argument('--cap-lines-to-size',action='store_true',
                    help='omit line offsets beyond the target function size in the baseline binary')
    ap.add_argument('--compact',action='store_true',help='omit explicit burst padding')
    ap.add_argument('--constructors',action='store_true',
                    help='include child default constructors in MergeImpl and typed Add helpers')
    ap.add_argument('--copy-constructors',action='store_true',
                    help='prefetch descendant copy constructors at parent C2 function bodies')
    ap.add_argument('--copy-depth',type=int,default=0,
                    help='exact copy-constructor depth; 0 uses the main frontier')
    ap.add_argument('--own-lines',type=int,default=0,
                    help='extra size-capped body lookahead at each schema method entry')
    ap.add_argument('--own-start-line',type=int,default=8)
    ap.add_argument('--repeated-only',action='store_true')
    ap.add_argument('--line-budget',type=int,default=0,help='maximum hints per site; 0 = unlimited')
    ap.add_argument('--order',choices=['target','round-robin'],default='target')
    ap.add_argument('--constructor-sites',choices=['both','merge','add'],default='both')
    a = ap.parse_args()
    if not 1 <= a.min_depth <= a.depth or a.lines < 1 or a.max_children < 1 or min(a.start_line,a.line_budget,a.copy_depth,a.own_lines,a.own_start_line) < 0:
        ap.error('require 1 <= min-depth <= depth and positive lines/max-children')
    descriptor = descriptor_pb2.FileDescriptorSet.FromString(a.descriptor.read_bytes())
    graph = {}; cpp_names = {}
    def visit(message,path,package):
        full = '.'+package+'.'+'.'.join(path+[message.name])
        cpp_names[full] = '_'.join(path+[message.name])
        graph[full] = [f.type_name for f in message.field if f.type == f.TYPE_MESSAGE and
                       (not a.repeated_only or f.label == f.LABEL_REPEATED)]
        for child in message.nested_type: visit(child,path+[message.name],package)
    for file in descriptor.file:
        if file.package != 'fleetbench.proto': continue
        for message in file.message_type: visit(message,[],file.package)
    names = []
    for line in subprocess.check_output(['nm','--defined-only',str(a.binary)],text=True).splitlines():
        f = line.split()
        if len(f)==3 and f[1] in 'TW': names.append(f[2])
    sizes = {}
    if a.cap_lines_to_size or a.own_lines:
        for line in subprocess.check_output(['nm','-S','--defined-only',str(a.binary)],text=True).splitlines():
            f = line.split()
            if len(f)==4 and f[2] in 'TW': sizes[f[3]] = int(f[1],16)
    def lines_for(targets):
        return code_lines(targets,sizes,a.lines,a.start_line,a.cap_lines_to_size,
                          a.line_budget,a.order)
    demangled = subprocess.run(['c++filt'],input='\n'.join(names)+'\n',text=True,capture_output=True,check=True).stdout.splitlines()
    methods = set(a.methods.split(',')); symbols = {}; constructors = {}; add_helpers = {}; copies = {}
    for name,dem in zip(names,demangled):
        m = re.match(r'^fleetbench::proto::(\w+)::(\w+)\(',dem)
        if m and m[2] in methods: symbols[m[1],m[2]] = name
        if m and m[1] == m[2] and 'C1E' in name:
            if dem.endswith('(google::protobuf::Arena*)'): constructors[m[1]] = name
        if m and m[1] == m[2] and 'C2E' in name and ' const&)' in dem:
            copies[m[1]] = name
        if 'RepeatedPtrFieldBase::Add<' in dem:
            m = re.search(r'GenericTypeHandler<fleetbench::proto::(\w+)>',dem)
            if m: add_helpers[m[1]] = name
    sites = {}
    for full,children in graph.items():
        targets = descendants(graph,full,a.min_depth,a.depth)
        for method in sorted(methods):
            site = symbols.get((cpp_names[full],method))
            if not site: continue
            pairs = []
            children_added = 0
            for child in targets:
                cpp = cpp_names.get(child,'')
                candidate = [symbols.get((cpp,method))]
                if a.constructors and a.constructor_sites != 'add' and method == 'MergeImpl':
                    candidate.append(constructors.get(cpp))
                valid = [t for t in candidate if t and t != site]
                if valid:
                    pairs.extend([t,0,0] for t in valid)
                    children_added += 1
                    if children_added >= a.max_children: break
            pairs = lines_for([p[0] for p in pairs])
            if pairs:
                size = 7*len(pairs)
                sites[site] = {'k':size if a.compact else ((size+15)//16)*16,'t':pairs}
    if a.constructors and a.constructor_sites != 'merge':
        for cpp,site in add_helpers.items():
            target = constructors.get(cpp)
            if target:
                pairs = lines_for([target])
                if not pairs: continue
                size = 7*len(pairs)
                sites[site] = {'k':size if a.compact else ((size+15)//16)*16,'t':pairs}
    if a.copy_constructors:
        for full in graph:
            site = copies.get(cpp_names[full])
            if not site: continue
            targets = [copies.get(cpp_names.get(t,'')) for t in descendants(graph,full,a.copy_depth or a.min_depth,a.copy_depth or a.depth)]
            pairs = lines_for([t for t in targets if t and t != site][:a.max_children])
            if pairs:
                size=7*len(pairs)
                sites[site]={'k':size if a.compact else ((size+15)//16)*16,'t':pairs}
    if a.own_lines:
        for site in symbols.values():
            extra=code_lines([site],sizes,a.own_lines,a.own_start_line,True)
            if not extra: continue
            entry=sites.setdefault(site,{'k':0,'t':[]})
            entry['t'].extend(t for t in extra if t not in entry['t'])
            size=7*len(entry['t'])
            entry['k']=size if a.compact else ((size+15)//16)*16
    if not sites: raise RuntimeError('no matching schema/symbol pairs')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps({'sites':sites},indent=2,sort_keys=True))
    print(json.dumps({'sites':len(sites),'targets':sum(len(s['t']) for s in sites.values()),
                      'methods':sorted(methods),'depth':a.depth,'min_depth':a.min_depth,
                      'lines':a.lines,'start_line':a.start_line,'cap_lines_to_size':a.cap_lines_to_size,
                      'compact':a.compact,'constructors':a.constructors,
                      'copy_constructors':a.copy_constructors,
                      'copy_depth':a.copy_depth,
                      'own_lines':a.own_lines,'own_start_line':a.own_start_line,
                      'constructor_sites':a.constructor_sites,'line_budget':a.line_budget,'order':a.order,
                      'repeated_only':a.repeated_only}))


if __name__ == '__main__': main()
