"""Check metadata expansion preserves shuffle, reservation and actual calls."""
import importlib.util, subprocess, sys
from pathlib import Path
import pytest
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts/static'
sys.path.insert(0,str(SCRIPTS))
s=importlib.util.spec_from_file_location('work',SCRIPTS/'feedsim_work_policy.py')
w=importlib.util.module_from_spec(s);s.loader.exec_module(w)

@pytest.mark.parametrize('budget',[128,4096,16384])
@pytest.mark.parametrize('lines',[1,3])
def test_work_metadata_and_calls(tmp_path,budget,lines):
 source=r'''
#include <algorithm>
#include <atomic>
#include <cstdio>
#include <random>
#include <vector>
using std::size_t;
struct Context { long value=7; };
std::vector<int> seen;
void f0(Context*c){seen.push_back(0);c->value+=3;}
void f1(Context*c){seen.push_back(1);c->value+=5;}
void f2(Context*c){seen.push_back(2);c->value+=7;}
void f3(Context*c){seen.push_back(3);c->value+=11;}
void f4(Context*c){seen.push_back(4);c->value+=13;}
#include "generated/extractor_helpers.h"
struct Suite {
 std::vector<void(*)(Context*)> flat_copies_;
 std::atomic<size_t> flat_pos_{4};
 long output=0;
 void init(){std::mt19937 rng(122);
  std::shuffle(flat_copies_.begin(), flat_copies_.end(), rng);
 }
 __attribute__((noinline)) void run(int count){
  if (flat_copies_.empty()) return;
  Context ctx;
'''+w.RESERVE+r'''
  for (int i = 0; i < count; ++i) {
    flat_copies_[(start + static_cast<size_t>(i)) % total](&ctx);
  }
  output=ctx.value;
 }
};
int main(){
 using F=void(*)(Context*);
 std::vector<F> functions={f0,f1,f2,f3,f4};int increments[]={3,5,7,11,13};
 std::mt19937 rng(122);auto expected=functions;std::shuffle(expected.begin(),expected.end(),rng);
 Suite s;s.flat_copies_=functions;s.init();if(!seen.empty()||s.flat_copies_.size()!=10)abort();
 for(int i=0;i<5;i++)if(s.flat_copies_[i]!=expected[i])abort();
 for(int i=5;i<10;i++)if(std::find(functions.begin(),functions.end(),s.flat_copies_[i])==functions.end())abort();
 for(int count:{0,1,3,4,5,6,20,34}){
  auto start=s.flat_pos_.load();seen.clear();s.run(count);
  if(seen.size()!=size_t(count)||s.flat_pos_.load()!=start+count)abort();
  long value=7;
  for(int i=0;i<count;i++){int id=std::find(functions.begin(),functions.end(),expected[(start+i)%5])-functions.begin();if(seen[i]!=id)abort();value+=increments[id];}
  if(s.output!=value)abort();
 }
 std::vector<F> empty;a3PrepareWorkTargets(empty,rng,a3_copy_sizes,0,4096);if(!empty.empty())abort();
 std::vector<F> one={f0};uint32_t tiny[]={32};a3PrepareWorkTargets(one,rng,tiny,1,4096);if(one.size()!=2||one[0]!=f0||one[1]!=f0)abort();
 puts("shuffle/reservation/state/wrap OK");
}
'''
 (tmp_path/'generated').mkdir();(tmp_path/'generated/extractor_helpers.h').write_text('')
 (tmp_path/'a3_copy_sizes.inc').write_text('static constexpr uint32_t a3_copy_sizes[]={32,8192,512,128,2048};\n')
 cpp=tmp_path/'test.cpp';binary=tmp_path/'test';cpp.write_text(w.transform(source,budget,lines))
 subprocess.run(['clang++-19','-O2','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(cpp),'-o',str(binary)],check=True)
 assert subprocess.check_output([str(binary)],text=True).strip()=='shuffle/reservation/state/wrap OK'
