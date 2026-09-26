"""Direct IR edges survive large-code-model lowering; unknown calls stay unknown."""
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('feed_builder',ROOT/'scripts/static/build_feedsim_factorial.py')
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_ir_calls_and_local_identity():
    ir='''define void @root(ptr %fp) {
  call void @known()
  call void %fp(ptr @callback)
  invoke void @local() to label %ok unwind label %error
  call void @"quoted.name"()
  call void asm sideeffect "call @not_ir()", ""()
  ; call void @comment()
  ret void
}
define internal void @local() {
  tail call void @known()
  ret void
}
define void @"quoted.name"() {
  ret void
}
'''
    a=builder.ir_edges(ir,'a');b=builder.ir_edges(ir,'b')
    assert a['root']==['known','local@ir:a','quoted.name']
    assert a['local@ir:a']==['known']
    assert a['quoted.name']==[]
    assert 'local@ir:b' in b and 'local@ir:a' not in b
