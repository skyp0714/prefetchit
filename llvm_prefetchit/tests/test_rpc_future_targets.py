import importlib.util
from pathlib import Path
import subprocess


def test_live_virtual_handler_semantics_and_probe(tmp_path):
    path=Path(__file__).resolve().parents[1]/'scripts/static/build_rpc_future_targets.py'
    spec=importlib.util.spec_from_file_location('rpc_builder',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source=r'''
#include <memory>
#include <cassert>
static int state=0, calls=0;
struct Other { virtual ~Other()=default; long pad=7; };
struct ExampleServiceIf { virtual ~ExampleServiceIf()=default; virtual void Run(int)=0; };
struct Impl: Other, ExampleServiceIf { void Run(int v) override { assert(state==1 && v==42); ++calls; state=2; } };
struct ExampleServiceProcessor {
  std::shared_ptr<ExampleServiceIf> iface_;
  explicit ExampleServiceProcessor(std::shared_ptr<ExampleServiceIf> p):iface_(p){}
  void process_Run(int);
};
void ExampleServiceProcessor::process_Run(int x)
{
  assert(state==0);
  state=1; // argument decode must precede every actual handler invocation
    iface_->Run(x);
}
int main() {
  ExampleServiceProcessor p(std::make_shared<Impl>());
  for(int i=0;i<256;++i) {state=0;p.process_Run(42);assert(state==2);}
  assert(calls==256);
  @PROBE@
}
'''
    for mode in ['base','late','early','diagnostic']:
        code,methods=module.transform(source,'ExampleService',mode)
        assert methods==['Run']
        code=code.replace('@PROBE@','assert(a3_lead_histogram[0].count==4);' if mode=='diagnostic' else '')
        cpp=tmp_path/(mode+'.cc');cpp.write_text(code);binary=tmp_path/mode
        subprocess.run(['clang++-19','-std=c++17','-O2','-fsanitize=address,undefined',str(cpp),'-o',str(binary)],check=True,capture_output=True)
        subprocess.run([str(binary)],check=True,capture_output=True)
