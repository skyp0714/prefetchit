#!/usr/bin/env python3
"""Count eligible predictions during frozen-model training, never in its held-out window."""
from pathlib import Path
import argparse,hashlib,json
from build_scylla_future_targets import aggressive,build,SITE,EXPECTED

def assembly(freeze_after=1000000):
    assert freeze_after>0
    code=aggressive(True,freeze_after)
    reset=' movq $1, 16(%r9)\n30:'
    emit=' cmp %r11, %r10\n je 99f\n'
    assert code.count(reset)==code.count(emit)==1
    code=code.replace(reset,' movq $1, 16(%r9)\n movq $0, 24(%r9)\n30:')
    code=code.replace(emit,emit+' cmpq $0, 176(%r8)\n je .Ltraining_count_frozen\n incq 24(%r9)\n.Ltraining_count_frozen:\n')
    return code

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary',type=Path);p.add_argument('out',type=Path);p.add_argument('--gate',type=Path,required=True);a=p.parse_args()
    digest=hashlib.sha256(a.binary.read_bytes()).hexdigest();assert digest=='81a6d6c9c35181d5dbd202f72b9bb90f36eae9f3f92047148e4f803023bc8c36'
    gate=json.loads(a.gate.read_text());assert gate['met'] and gate['queued_next_fraction']<.8 and gate['owner_collisions']==0 and gate['diagnostic_mpki']>=1
    plan={'sha256':digest,'data_bytes':4198400,'freeze_after_dispatches_per_reactor':1000000,'gate':gate,
          'training_frequency':'Fourth QWORD per tagged transition counts eligible empty-queue confidence>=2 nonself predictions only while training remains. Reset on key/successor replacement; frozen afterward. Thus retained stable-segment counts, not complete lifetime call frequencies.',
          'hooks':[{'site':SITE,'expected':EXPECTED,'assembly':assembly(),'label':'training_prediction_frequency'}]}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.with_suffix('.plan.json').write_text(json.dumps(plan,indent=2));build(a.binary,plan,a.out)
if __name__=='__main__':main()
