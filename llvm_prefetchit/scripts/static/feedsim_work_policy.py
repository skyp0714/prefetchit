"""Size-informed immutable future-target metadata for FeedSim's flat dispatcher."""
import hashlib, json, re, subprocess
from pathlib import Path
from feedsim_future_policy import ANCHOR, RESERVE

PREPARE = r'''
#include <cstdint>
#include <cstdlib>
#include <unordered_map>
// Registration-order sizes come from the unchanged generated copy functions.
template<class F, class RNG>
static void a3PrepareWorkTargets(std::vector<F>& calls, RNG& rng,
                                const uint32_t* sizes, size_t sizes_count,
                                size_t budget) {
  const size_t total = calls.size();
  if (total != sizes_count) std::abort();
  if (!total) return;
  std::unordered_map<F, uint32_t> size_by_address;
  size_by_address.reserve(total);
  for (size_t i = 0; i < total; ++i) size_by_address.emplace(calls[i], sizes[i]);
  if (size_by_address.size() != total) std::abort();
  std::shuffle(calls.begin(), calls.end(), rng);
  std::vector<uint32_t> shuffled_sizes(total);
  for (size_t i = 0; i < total; ++i) shuffled_sizes[i] = size_by_address.at(calls[i]);
  calls.reserve(2 * total);
  for (size_t i = 0; i < total; ++i) {
    size_t work = 0, ahead = 0;
    do {
      work += shuffled_sizes[(i + ahead) % total];
      ++ahead;
    } while (ahead < 16 && (ahead < 2 || work < budget));
    calls.push_back(calls[(i + ahead) % total]);
  }
}
'''

def copy_sizes(binary):
    entries={}
    proc=subprocess.Popen(['nm','-S','--defined-only',str(binary)],stdout=subprocess.PIPE,text=True)
    for line in proc.stdout:
        f=line.split()
        if len(f)!=4 or f[2] not in 'tTwW' or '.cold' in f[3]:continue
        m=re.search(r'vc_(\d{4})_(\d{4})',f[3])
        if not m:continue
        key=tuple(map(int,m.groups()));value=(f[3],int(f[1],16))
        assert key not in entries, ('ambiguous copy function',key)
        entries[key]=value
    assert proc.wait()==0 and entries
    variants=1+max(k[0] for k in entries);copies=1+max(k[1] for k in entries)
    assert len(entries)==variants*copies and all((i,j) in entries for i in range(variants) for j in range(copies))
    ordered=[entries[k] for k in sorted(entries)]
    assert all(size>0 for _,size in ordered)
    return ordered

def prepare_header(binary,out):
    ordered=copy_sizes(binary)
    sizes=[x[1] for x in ordered]
    (out/'a3_copy_sizes.inc').write_text('static constexpr uint32_t a3_copy_sizes[] = {\n'+','.join(map(str,sizes))+'\n};\n')
    meta={'function_count':len(ordered),'sizes_and_names_sha256':hashlib.sha256(json.dumps(ordered).encode()).hexdigest(),
          'size_min':min(sizes),'size_max':max(sizes),'size_mean':sum(sizes)/len(sizes),
          'source_binary':str(binary),'mapping':'registration order variant index then copy index; runtime immutable pointer-to-size association before unchanged shuffle'}
    (out/'work_sizes.json').write_text(json.dumps(meta,indent=2));return meta

def transform(code,budget,lines=1):
    assert budget>0 and lines in (1,3) and code.count(ANCHOR)==code.count(RESERVE)==1
    shuffle='  std::shuffle(flat_copies_.begin(), flat_copies_.end(), rng);'
    assert code.count(shuffle)==1
    include='#include "generated/extractor_helpers.h"'
    assert code.count(include)==1
    code=code.replace(include,include+'\n'+PREPARE+'\n#include "a3_copy_sizes.inc"\n')
    code=code.replace(shuffle,f'  a3PrepareWorkTargets(flat_copies_, rng, a3_copy_sizes, sizeof(a3_copy_sizes)/sizeof(a3_copy_sizes[0]), {budget});')
    code=code.replace('<< flat_copies_.size()', '<< flat_copies_.size() / 2')
    code=code.replace(RESERVE,RESERVE.replace('flat_copies_.size()','flat_copies_.size() / 2'))
    replacement='''  size_t prefetch_pos = start;
  for (int i = 0; i < count; ++i) {
    auto target = reinterpret_cast<const char*>(flat_copies_[total + prefetch_pos]);
@HINTS@
    if (++prefetch_pos == total) prefetch_pos = 0;
    flat_copies_[(start + static_cast<size_t>(i)) % total](&ctx);'''
    hints='\n'.join('    __builtin_prefetch(target'+(f' + {64*i}' if i else '')+', 0, 2);' for i in range(lines))
    return code.replace(ANCHOR,replacement.replace('@HINTS@',hints))
