#!/usr/bin/env python3
"""Static Thrift processor-to-concrete-handler edges, issued once per RPC.

Match generated Processor::process_METHOD symbols to CLASSHandler::METHOD.
Only uniquely matching namespace/class/method triples are accepted. This
adapter requires the standard generated naming convention and a known single
concrete handler in the final service executable; no profile is consumed.
"""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
from callgraph_prefetch_plan import symbol_table,parse_edges
from static_prefetch_graph import descendants,code_lines


def handler_edges(demangled):
    processors={};handlers={}
    for symbol,name in demangled.items():
        p=re.match(r'^(.+)::([^:]+)ServiceProcessor::process_(\w+)\(',name)
        h=re.match(r'^(.+)::([^:]+)Handler::(\w+)\(',name)
        if p:processors.setdefault(p.groups(),[]).append(symbol)
        if h:handlers.setdefault(h.groups(),[]).append(symbol)
    return {sources[0]:handlers[key][0] for key,sources in processors.items()
            if len(sources)==1 and len(handlers.get(key,[]))==1}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary',type=Path);p.add_argument('output',type=Path);p.add_argument('--depth',type=int,default=0);p.add_argument('--lines',type=int,default=4);p.add_argument('--budget',type=int,default=16);a=p.parse_args()
    if a.depth<0 or min(a.lines,a.budget)<1:p.error('invalid depth/lines/budget')
    symbols=symbol_table(a.binary);public={v[0]:v[1] for v in symbols.values() if v[2]}
    names=list(public);demangled=subprocess.check_output(['c++filt'],input='\n'.join(names)+'\n',text=True).splitlines();edges=handler_edges(dict(zip(names,demangled)))
    if not edges:raise RuntimeError('no unique processor/handler edges')
    graph={}
    if a.depth:
        proc=subprocess.Popen(['llvm-objdump-19','-d','--no-show-raw-insn',str(a.binary)],stdout=subprocess.PIPE,text=True)
        graph=parse_edges(proc.stdout,symbols)
        if proc.wait():raise RuntimeError('disassembly failed')
    sites={}
    for source,target in edges.items():
        future=[target]+[n for n in descendants(graph,target,1,a.depth) if n in public and n not in {source,target}] if a.depth else [target]
        hints=code_lines(future,public,lines=a.lines,cap_to_size=True,budget=a.budget,order='round-robin')
        if hints:sites[source]={'k':7*len(hints),'t':hints}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({'sites':sites},indent=2,sort_keys=True))
    a.output.with_suffix('.meta.json').write_text(json.dumps({'binary':str(a.binary.resolve()),'sha256':hashlib.sha256(a.binary.read_bytes()).hexdigest(),'resolved_edges':edges,'depth':a.depth,'lines':a.lines,'budget':a.budget,'sites':len(sites),'hints':sum(len(v['t']) for v in sites.values())},indent=2))
    print(a.output.name,len(sites),'sites',sum(len(v['t']) for v in sites.values()),'hints')
if __name__=='__main__':main()
