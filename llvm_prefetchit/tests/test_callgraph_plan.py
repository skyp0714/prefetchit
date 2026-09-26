import importlib.util
from pathlib import Path
import sys

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('callgraph_plan', TOOLS / 'callgraph_prefetch_plan.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_edges_accept_only_defined_direct_entries():
    symbols = {0x100: ('a', 20, True), 0x200: ('b', 30, True), 0x300: ('c', 30, False)}
    lines = ['00000100 <a>:', ' 100: callq 0x200 <b>', ' 104: callq *%rax',
             ' 106: jne 0x300 <c>', ' 108: jmp 0x204 <b+4>',
             ' 10a: callq 0x200 <b>', '00000200 <b>:', ' 200: jmp 0x300 <c>']
    assert module.parse_edges(lines, symbols) == {'a': ['b'], 'b': ['c'], 'c': []}


def test_local_names_are_distinct_and_constructor_aliases_share_a_node(monkeypatch):
    output='100 20 t local\n200 20 t local\n300 20 T root\n400 20 T ctorC1E\n400 20 T ctorC2E\n'
    monkeypatch.setattr(module.subprocess,'check_output',lambda *args,**kw: output)
    symbols=module.symbol_table('fixture')
    assert symbols[0x100][0]=='local@local:100'
    assert symbols[0x200][0]=='local@local:200'
    assert symbols[0x400][0]=='ctorC2E'
