"""Exercise the prototype's actual virtual resolver and guarded Clear loop.

ASan covers lookahead beyond short arrays; different dynamic types distinguish
code-address resolution from prefetching object/vtable data.
"""
import importlib.util
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('future_builder', ROOT/'scripts/static/build_proto_future_targets.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_future_virtual_targets_and_short_arrays(tmp_path):
    fixture = r'''
#include <cstdint>
#include <cstddef>
#include <type_traits>
#include <vector>
#include <cassert>
struct MessageLite { virtual ~MessageLite() = default; virtual void Clear() = 0; };
struct A final: MessageLite { int count=0; void Clear() override { ++count; } };
struct B final: MessageLite { int count=0; void Clear() override { count+=2; } };
struct Left { virtual ~Left() = default; long padding[4]{}; };
struct Both final: Left, MessageLite { int count=0; void Clear() override { count+=3; } };
namespace internal {
struct Handler { using Type = MessageLite; static void Clear(MessageLite* p) { p->Clear(); } };
class Field {
 public:
  int current_size_;
  std::vector<void*> storage;
  explicit Field(int n): current_size_(n), storage(n) {}
  void* const* elements() const { return storage.data(); }
  void ExchangeCurrentSize(int n) { current_size_ = n; }
  template<class H> using Value = typename H::Type;
  template<class H> static Value<H>* cast(void* p) { return static_cast<Value<H>*>(p); }
  template<class TypeHandler> void ClearNonEmpty() {
    const int n = current_size_;
    void* const* elems = elements();
    int i = 0;
    // do/while loop to avoid initial test because we know n > 0
    do {
      TypeHandler::Clear(cast<TypeHandler>(elems[i++]));
    } while (i < n);
    ExchangeCurrentSize(0);
  }
};
}
int main() {
  A a; B b; Both both;
  auto ta=internal::A3MethodTarget(static_cast<MessageLite*>(&a), &MessageLite::Clear);
  auto tb=internal::A3MethodTarget(static_cast<MessageLite*>(&b), &MessageLite::Clear);
  auto tc=internal::A3MethodTarget(static_cast<MessageLite*>(&both), &MessageLite::Clear);
  assert(ta && tb && tc && ta != tb && tb != tc);
  assert(ta != reinterpret_cast<uintptr_t>(&a));
  for (int n : {0,1,2,3,4,5,8,17}) {
    internal::Field f(n);
    std::vector<A> aa(n); std::vector<B> bb(n); std::vector<Both> cc(n);
    for(int i=0;i<n;++i) f.storage[i] = i%3==0 ? static_cast<MessageLite*>(&aa[i]) :
      i%3==1 ? static_cast<MessageLite*>(&bb[i]) : static_cast<MessageLite*>(&cc[i]);
    if(n) f.ClearNonEmpty<internal::Handler>();
    assert(f.current_size_==0);
    for(int i=0;i<n;++i) assert(aa[i].count+bb[i].count+cc[i].count == i%3+1);
  }
}
'''
    for policy in ('once1', 'future1', 'future4', 'unique4'):
        lead, lines, dedup, _ = builder.POLICIES[policy]
        code, _ = builder.patched(fixture, '', lead, lines, dedup, 0, True)
        source=tmp_path/f'{policy}.cc'; binary=tmp_path/policy
        source.write_text(code)
        subprocess.run(['clang++-19','-std=c++17','-O2','-g',
                        '-fsanitize=address,undefined',str(source),'-o',str(binary)], check=True)
        subprocess.run([str(binary)],check=True)
