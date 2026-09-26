"""Exercise exact source-injection fragments across short and wrapping queues."""
from pathlib import Path
import importlib.util,subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from make_tagged_prefetch_control import build as make_partial_control
import pytest
s=importlib.util.spec_from_file_location('policy',Path(__file__).resolve().parents[1]/'scripts/static/feedsim_future_policy.py');p=importlib.util.module_from_spec(s);s.loader.exec_module(p)
@pytest.mark.parametrize('mode',p.MODES)
def test_call_order_and_wrapping_under_sanitizers(tmp_path,mode):
 source=r'''
#include <atomic>
#include <vector>
#include <cstdio>
#include <cstdlib>
using std::size_t;
struct Context { long value=7; };
std::vector<int> seen;
void f0(Context*c){seen.push_back(0);c->value+=3;}
void f1(Context*c){seen.push_back(1);c->value+=5;}
void f2(Context*c){seen.push_back(2);c->value+=7;}
void f3(Context*c){seen.push_back(3);c->value+=11;}
void f4(Context*c){seen.push_back(4);c->value+=13;}
struct Suite {
 std::vector<void(*)(Context*)> flat_copies_;
 std::atomic<size_t> flat_pos_{4};
 long output=0;
 __attribute__((noinline)) void run(int count) {
  if (flat_copies_.empty()) return;
  Context ctx;
'''+p.RESERVE+r'''
  for (int i = 0; i < count; ++i) {
    flat_copies_[(start + static_cast<size_t>(i)) % total](&ctx);
  }
  output=ctx.value;
 }
};
int main(){
 void(*functions[])(Context*)={f0,f1,f2,f3,f4};int increments[]={3,5,7,11,13};
 for(int n:{1,2,5}){
  Suite s;for(int i=0;i<n;i++)s.flat_copies_.push_back(functions[i]);
  for(int count:{0,1,3,4,5,6,20,34}){
   auto start=s.flat_pos_.load();seen.clear();s.run(count);
   if(seen.size()!=size_t(count)||s.flat_pos_.load()!=start+count)abort();
   long expected=7;
   for(int i=0;i<count;i++){int id=(start+i)%n;if(seen[i]!=id)abort();expected+=increments[id];}
   if(s.output!=expected)abort();
  }
 }
 puts("order/state/wrap OK");
}
'''
 source=p.transform(source,mode);cpp=tmp_path/'test.cpp';binary=tmp_path/'test';cpp.write_text(source)
 subprocess.run(['clang++-19','-O2','-fsanitize=address,undefined','-fno-omit-frame-pointer','-ffunction-sections','-fdata-sections','-Wl,--gc-sections',str(cpp),'-o',str(binary)],check=True)
 assert subprocess.check_output([str(binary)],text=True).strip()=='order/state/wrap OK'
 if mode.startswith('prologue'):
  stripped=tmp_path/'stripped';subprocess.run(['objcopy','--strip-debug',str(binary),str(stripped)],check=True);binary=stripped
  control=tmp_path/'partial';meta=make_partial_control(binary,control,'_ZN5Suite3runEi')
  assert meta['removed_tagged_hints']>0 and meta['remaining_scope_T1']>0
  assert subprocess.check_output([str(control)],text=True).strip()=='order/state/wrap OK'
