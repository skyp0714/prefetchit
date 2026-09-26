"""Small descriptor/symbol fixtures exercise static descendant selection."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

descriptor_pb2 = pytest.importorskip('google.protobuf.descriptor_pb2')
TOOL = Path(__file__).resolve().parents[1]/'tools/proto_schema_prefetch_plan.py'


def plan(tmp_path, monkeypatch, options, copies=False):
    monkeypatch.syspath_prepend(str(TOOL.parent))
    spec = importlib.util.spec_from_file_location('schema_planner', TOOL)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    descriptor = descriptor_pb2.FileDescriptorSet()
    file = descriptor.file.add(); file.package = 'fleetbench.proto'
    for name, child in [('Parent','Child'), ('Child','Leaf'), ('Leaf',None)]:
        message = file.message_type.add(); message.name = name
        if child:
            field = message.field.add(); field.name = 'child'; field.number = 1
            field.type = field.TYPE_MESSAGE; field.label = field.LABEL_OPTIONAL
            field.type_name = '.fleetbench.proto.'+child
    desc = tmp_path/'descriptor.pb'; desc.write_bytes(descriptor.SerializeToString())
    names = ['parent','child','leaf']
    demangled = [f'fleetbench::proto::{n}::Clear()' for n in ('Parent','Child','Leaf')]
    sizes = [100,70,8]
    if copies:
        for n in ('Parent','Child','Leaf'):
            for kind in ('C1E','C2E'):
                names.append(n+kind)
                demangled.append(f'fleetbench::proto::{n}::{n}(google::protobuf::Arena*, fleetbench::proto::{n} const&)')
                sizes.append(70)
    def nm(cmd,**kw):
        if '-S' in cmd:
            return '\n'.join(f'{i:x} {size:x} T {n}'
                             for i,(n,size) in enumerate(zip(names,sizes)))
        return '\n'.join(f'{i:x} T {n}' for i,n in enumerate(names))
    monkeypatch.setattr(mod.subprocess, 'check_output', nm)
    class Result:
        stdout = '\n'.join(demangled)
    monkeypatch.setattr(mod.subprocess, 'run', lambda *a,**kw: Result())
    output = tmp_path/'plan.json'
    monkeypatch.setattr(sys, 'argv', [str(TOOL), str(desc), 'binary', str(output),
                                    '--methods','Clear',*options])
    mod.main()
    return json.loads(output.read_text())['sites']


def test_grandchild_only_moves_target_one_ancestor_earlier(tmp_path,monkeypatch):
    sites = plan(tmp_path,monkeypatch,['--depth','2','--min-depth','2','--lines','2','--compact'])
    assert sites == {'parent':{'k':14,'t':[['leaf',0,0],['leaf',64,0]]}}


def test_default_keeps_immediate_children_and_padding(tmp_path,monkeypatch):
    sites = plan(tmp_path,monkeypatch,[])
    assert sites == {'parent':{'k':16,'t':[['child',0,0]]},
                     'child':{'k':16,'t':[['leaf',0,0]]}}


def test_size_cap_excludes_offsets_past_target_end(tmp_path,monkeypatch):
    sites = plan(tmp_path,monkeypatch,['--depth','2','--lines','4','--cap-lines-to-size','--compact'])
    assert sites['parent']['t'] == [['child',0,0],['child',64,0],['leaf',0,0]]
    assert sites['child']['t'] == [['leaf',0,0]]


def test_copy_sites_use_function_body_not_complete_object_alias(tmp_path,monkeypatch):
    sites=plan(tmp_path,monkeypatch,['--depth','2','--min-depth','2','--compact',
                                   '--copy-constructors','--copy-depth','1'],copies=True)
    assert sites['parent']['t'] == [['leaf',0,0]]
    assert sites['ParentC2E']['t'] == [['ChildC2E',0,0]]
    assert sites['ChildC2E']['t'] == [['LeafC2E',0,0]]
    assert not any('C1E' in name for name in sites)


def test_body_lookahead_is_size_capped_even_without_descendants(tmp_path,monkeypatch):
    sites=plan(tmp_path,monkeypatch,['--depth','2','--min-depth','2','--compact',
                                   '--own-start-line','1','--own-lines','2'])
    assert sites['parent']['t'] == [['leaf',0,0],['parent',64,0]]
    assert sites['child']['t'] == [['child',64,0]]
    assert 'leaf' not in sites
