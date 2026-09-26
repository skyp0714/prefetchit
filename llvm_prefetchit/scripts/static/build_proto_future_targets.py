#!/usr/bin/env python3
"""Build private protobuf future-target prototypes; never edit the dependency cache.

The virtual-member resolver deliberately targets x86-64's Itanium C++ ABI.
These are source prototypes, not a generic compiler transformation. The
workload, inputs, allocation and operation order are unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
REL = Path('src/google/protobuf')
POLICIES = {
    'base': (0, 1, 0, 0),
    'once1': (0, 1, 1, 1),
    'future1': (1, 1, 0, 1),
    'future4': (4, 1, 0, 1),
    'unique4': (1, 4, 1, 1),
    'clear4': (1, 4, 1, 0),
}

HELPER = r'''
// A3: x86-64 Itanium ABI resolver. Pointer loads require a live object.
// RepeatedPtrField guarantees live elements below current_size_. Clear does
// not remove siblings. No target method is called to discover its address.
static_assert(sizeof(void*) == 8, "A3 prototype requires x86-64");
template <class T, class Method>
inline __attribute__((always_inline)) uintptr_t A3MethodTarget(T* obj, Method method) {
  struct Member { ptrdiff_t pointer; ptrdiff_t adjustment; } member;
  static_assert(sizeof(method) == sizeof(member), "unsupported member pointer ABI");
  __builtin_memcpy(&member, &method, sizeof member);
  uintptr_t target = static_cast<uintptr_t>(member.pointer);
  if (target & 1) {
    const char* adjusted = reinterpret_cast<const char*>(obj) + member.adjustment;
    const char* table;
    __builtin_memcpy(&table, adjusted, sizeof table);
    __builtin_memcpy(&target, table + member.pointer - 1, sizeof target);
  }
  return target;
}
inline __attribute__((always_inline)) void A3CodeHint(uintptr_t target) {
  @HINTS@
}
'''


def patched(header, source, lead, lines, dedup, merge, enabled):
    if not enabled:
        return header, source
    assert '#if defined(PROTOBUF_CUSTOM_VTABLE)' not in header
    helper = HELPER.replace('@HINTS@', '\n  '.join(
        f'asm volatile("prefetcht1 {64*i}(%0)" : : "r"(target));' for i in range(lines)))
    header = header.replace('namespace internal {', 'namespace internal {\n' + helper, 1)
    anchor = '    // do/while loop to avoid initial test because we know n > 0\n'
    setup = '''    uintptr_t a3_last = 0;
    if constexpr (std::is_base_of<MessageLite, Value<TypeHandler>>::value) {
      auto* first = static_cast<MessageLite*>(cast<TypeHandler>(elems[0]));
      a3_last = A3MethodTarget(first, &MessageLite::Clear);
      A3CodeHint(a3_last);
    }
'''
    assert header.count(anchor) == 1
    header = header.replace(anchor, setup + anchor)
    if lead:
        anchor = '      TypeHandler::Clear(cast<TypeHandler>(elems[i++]));'
        body = f'''      if constexpr (std::is_base_of<MessageLite, Value<TypeHandler>>::value) {{
        if (n - i > {lead}) {{
          auto* next = static_cast<MessageLite*>(cast<TypeHandler>(elems[i + {lead}]));
          uintptr_t a3_target = A3MethodTarget(next, &MessageLite::Clear);
          if ({'a3_target != a3_last' if dedup else 'true'}) {{
            A3CodeHint(a3_target);
            a3_last = a3_target;
          }}
        }}
      }}
'''
        assert header.count(anchor) == 1
        header = header.replace(anchor, body + anchor)
    if merge:
        # The function pointer is available before reserve/allocation work.
        anchor = '    const RepeatedPtrFieldBase& from, Arena* arena, CopyFn copy_fn) {\n'
        assert source.count(anchor) == 1
        source = source.replace(anchor, anchor + '  A3CodeHint(reinterpret_cast<uintptr_t>(copy_fn));\n')
        for anchor in [
            'int RepeatedPtrFieldBase::MergeIntoClearedMessages(\n    const RepeatedPtrFieldBase& from) {\n',
            'void RepeatedPtrFieldBase::MergeFrom<MessageLite>(\n    const RepeatedPtrFieldBase& from, Arena* arena) {\n',
        ]:
            assert source.count(anchor) == 1
            body = '''  if (from.current_size_ > 0) {
    auto* first = reinterpret_cast<MessageLite* const*>(from.elements())[0];
    A3CodeHint(reinterpret_cast<uintptr_t>(GetClassData(*first)->merge_to_from));
  }
'''
            source = source.replace(anchor, anchor + body)
    return header, source


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--policy', choices=POLICIES, required=True)
    p.add_argument('--graph', type=Path)
    p.add_argument('--name', required=True)
    p.add_argument('--jobs', type=int, default=16)
    a = p.parse_args()
    out = a.out.resolve()
    for directory in ('bin', 'build', 'sources'):
        (out/directory).mkdir(parents=True, exist_ok=True)
    binary = out/'bin'/a.name
    if binary.exists():
        p.error('binary exists; use a new arm name')
    original = ROOT/'benchmarks/fleetbench/bazel-fleetbench/external/protobuf+'
    private = out/'protobuf'
    if not private.exists():
        shutil.copytree(original.resolve(), private, symlinks=True)
        for name in ('repeated_ptr_field.h', 'repeated_ptr_field.cc'):
            shutil.copy2(private/REL/name, out/'sources'/name)
    before = [(out/'sources'/name).read_text() for name in ('repeated_ptr_field.h', 'repeated_ptr_field.cc')]
    after = patched(*before, *POLICIES[a.policy], a.policy != 'base')
    for name, code in zip(('repeated_ptr_field.h', 'repeated_ptr_field.cc'), after):
        dest = private/REL/name
        dest.chmod(0o644)
        dest.write_text(code)
        (out/'sources'/f'{a.name}_{name}').write_text(code)
    cmd = ['bazel', 'build', '-c', 'opt', '--repo_env=CC=/usr/bin/clang',
           '--repo_env=CXX=/usr/bin/clang++', f'--jobs={a.jobs}', '--copt=-gline-tables-only',
           f'--override_repository=protobuf+={private}']
    if a.graph:
        plugin = ROOT/'llvm_prefetchit/build/PrefetchITPass.so'
        cmd += [f'--copt=-fpass-plugin={plugin}',
                f'--action_env=PREFETCHIT_PLUGIN_SHA256={hashlib.sha256(plugin.read_bytes()).hexdigest()}',
                f'--action_env=PREFETCHIT_COLD_PLAN={a.graph.resolve()}',
                '--action_env=PREFETCHIT_COLD_DIRECT_IN_PIC=1']
    cmd += ['//fleetbench/proto:proto_benchmark']
    meta = {'command': cmd, 'policy': a.policy, 'graph': str(a.graph),
            'source_sha256': [hashlib.sha256(x.encode()).hexdigest() for x in after]}
    (out/'build'/f'{a.name}.json').write_text(json.dumps(meta, indent=2))
    with (out/'build'/f'{a.name}.log').open('w') as log:
        subprocess.run(cmd, cwd=ROOT/'benchmarks/fleetbench', stdout=log,
                       stderr=subprocess.STDOUT, check=True, timeout=1800)
    shutil.copy2(ROOT/'benchmarks/fleetbench/bazel-bin/fleetbench/proto/proto_benchmark', binary)
    meta['sha256'] = hashlib.sha256(binary.read_bytes()).hexdigest()
    (out/'build'/f'{a.name}.json').write_text(json.dumps(meta, indent=2))
    if a.policy != 'base' or a.graph:
        subprocess.run(['python3', str(ROOT/'llvm_prefetchit/tools/make_nop_control_binary.py'),
                        '--input', str(binary), '--output', str(binary)+'_nop',
                        '--mnemonics', 'prefetcht1'], check=True)
    print(json.dumps({'arm': a.name, 'sha256': meta['sha256']}), flush=True)


if __name__ == '__main__':
    main()
