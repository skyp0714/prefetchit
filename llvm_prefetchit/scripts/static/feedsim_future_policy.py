"""Private-source future-target experiments; generated extractors stay unchanged."""
ANCHOR='  for (int i = 0; i < count; ++i) {\n    flat_copies_[(start + static_cast<size_t>(i)) % total](&ctx);'
RESERVE='''  const size_t total = flat_copies_.size();
  size_t start = flat_pos_.fetch_add(static_cast<size_t>(count),
                                     std::memory_order_relaxed) %
      total;'''
LEAD4='''  size_t prefetch_pos = (start + 4) % total;
  for (int i = 0; i < count; ++i) {
    auto target = reinterpret_cast<const char*>(flat_copies_[prefetch_pos]);
    __builtin_prefetch(target, 0, 2);
    if (++prefetch_pos == total) prefetch_pos = 0;
    flat_copies_[(start + static_cast<size_t>(i)) % total](&ctx);'''
MODES=['lead4','prologue','prologue4','staged','batch4']
def tagged_hint(expression):
 return ('    asm volatile("1: prefetcht1 (%0)\\n\\t'
         '.pushsection .a3_prologue_sites, \\"R\\", @progbits\\n\\t'
         '.quad 1b\\n\\t.popsection" : : "r"('+expression+'));\n')
def transform(code,mode):
 assert mode in MODES and code.count(ANCHOR)==1 and code.count(RESERVE)==1
 replacement=LEAD4
 if mode.startswith('prologue'):
  # The relaxed slot reservation is hoisted before local context preparation.
  # The array is immutable after initializeFlatDispatch; no target is executed.
  # Matching NOP controls retain this reservation ordering, and the default
  # successful-work setting excludes exceptions during context allocation.
  code=code.replace(RESERVE,'')
  offsets=[0,64,128,192] if mode=='prologue4' else [0]
  warm='\n  size_t initial_pos = start;\n  for (int warm_i = 0; warm_i < count && warm_i < 4; ++warm_i) {\n    auto initial_target = reinterpret_cast<const char*>(flat_copies_[initial_pos]);\n'
  warm+=''.join(tagged_hint(f'initial_target + {offset}') for offset in offsets)
  warm+='    if (++initial_pos == total) initial_pos = 0;\n  }\n'
  marker='  if (flat_copies_.empty()) return;'
  assert code.count(marker)==1;code=code.replace(marker,marker+'\n'+RESERVE+warm)
 elif mode=='staged':
  replacement='''  size_t prefetch_pos = (start + 4) % total;
  size_t far_pos = (start + 12) % total;
  for (int i = 0; i < count; ++i) {
    auto far_target = reinterpret_cast<const char*>(flat_copies_[far_pos]);
    auto target = reinterpret_cast<const char*>(flat_copies_[prefetch_pos]);
    __builtin_prefetch(far_target, 0, 2);
    __builtin_prefetch(target + 64, 0, 2);
    __builtin_prefetch(target + 128, 0, 2);
    if (++far_pos == total) far_pos = 0;
    if (++prefetch_pos == total) prefetch_pos = 0;
    flat_copies_[(start + static_cast<size_t>(i)) % total](&ctx);'''
 elif mode=='batch4':
  replacement='''  size_t prefetch_pos = (start + 4) % total;
  for (int i = 0; i < count; ++i) {
    if ((i & 3) == 0) {
      for (int batch = 0; batch < 4; ++batch) {
        auto target = reinterpret_cast<const char*>(flat_copies_[prefetch_pos]);
        __builtin_prefetch(target, 0, 2);
        if (++prefetch_pos == total) prefetch_pos = 0;
      }
    }
    flat_copies_[(start + static_cast<size_t>(i)) % total](&ctx);'''
 return code.replace(ANCHOR,replacement)
