#!/usr/bin/env python3
"""Resume the frozen L1I order after a post-ROI metric-accounting failure."""
import argparse
import json
from pathlib import Path
import signal
import dense_build as b
import fullset as h
from fullset_study import summarize
import split_lead_study as lead
import split_supplement_confirmation as confirmation

ORIGINAL_CHECK=lead.study.check_td
RULE=('Keep the original 2% top-down closure/subset limits. A failing top-down '
      'window retains raw counters and is marked invalid for top-down summaries, '
      'without aborting clean E2E or unrelated PMU windows. No counter normalization '
      'or performance-based retry. The original trial function and all ELF bytes '
      'are unchanged; only this post-ROI diagnostic check is wrapped.')


def annotate(row,privilege='u'):
    try:
        ORIGINAL_CHECK(row,privilege)
    except AssertionError as error:
        row['topdown_valid']=False
        row['topdown_quality_error']=repr(error)
    else:
        row['topdown_valid']=True


def trial(spec):
    lead.study.check_td=annotate
    lead.trial(dict(spec,topdown_quality_rule=RULE,quality_wrapper_sha256=b.sha(__file__)))


def amendment(root):
    destination=root/'l1_topdown_quality_amendment.json';assert not destination.exists()
    stage=root/'l1_screen';protocol=json.loads((stage/'protocol.json').read_text())
    assert all(b.sha(path)==sha for path,sha in protocol['source_hashes'].items())
    rows=json.loads((stage/'screen/rows.json').read_text())
    assert [(r['block'],r['arm']) for r in rows]==[(0,n) for n in protocol['orders'][0]]
    failure=stage/'screen/01_extra_nop/failure.json'
    assert json.loads(failure.read_text())['error']=='AssertionError((5481471738.0, 5632373263.0))'
    platform=stage/'screen/01_extra_nop_platform';checks=[]
    for before in platform.rglob('*_before.json'):
        after=before.with_name(before.name.replace('_before','_restored'))
        checks.append(after.exists() and json.loads(before.read_text())==json.loads(after.read_text()))
    assert len(checks)==36 and all(checks)
    b.save(destination,dict(rule=RULE,source_sha256=b.sha(__file__),
        original_protocol_sha256=b.sha(stage/'protocol.json'),
        source_hashes=protocol['source_hashes'],binary_hashes=protocol['binary_hashes'],
        completed_prefix_sha256=b.sha(stage/'screen/rows.json'),completed_prefix_rows=len(rows),
        failed_attempt=str(failure.parent),failed_record_sha256=b.sha(failure),
        original_closure_error_pct=100*(5632373263/5481471738-1),restoration_checks=len(checks),
        reason='Post-ROI top-down closure sanity failed. The prior harness stopped the client before saving endpoint metrics. No clean-ROI result can be recovered; preserve this attempt without inventing or imputing values.',
        action='Retain all four completed rows. Re-run only block 1 extra_nop once at seed 89602, in 01_extra_nop_retry1. Then finish the original remaining order. No further automatic retries.',
        confirmation='If the pre-existing L1 confirmation rule qualifies, use the same post-ROI quality wrapper for every fresh original/candidate trial. Its original trigger, source hashes, seeds and order remain fixed.'))


def resume(root):
    fixed=json.loads((root/'l1_topdown_quality_amendment.json').read_text())
    assert b.sha(__file__)==fixed['source_sha256']
    stage=root/'l1_screen';protocol=json.loads((stage/'protocol.json').read_text())
    assert b.sha(stage/'protocol.json')==fixed['original_protocol_sha256']
    assert all(b.sha(path)==sha for path,sha in protocol['source_hashes'].items())
    assert all(b.sha(path)==sha for path,sha in protocol['binary_hashes'].items())
    assert b.sha(stage/'screen/rows.json')==fixed['completed_prefix_sha256']
    rows=json.loads((stage/'screen/rows.json').read_text())
    for block,order in enumerate(protocol['orders']):
        for arm in order:
            if block==0:continue
            b.space(stage);assert all(b.sha(path)==sha for path,sha in protocol['source_hashes'].items())
            name=f'{block:02d}_{arm}'+('_retry1' if (block,arm)==(1,'extra_nop') else '')
            out=stage/'screen'/name;manifest=out.with_suffix('.json')
            b.save(manifest,dict(protocol['arms'][arm],out=str(out),seed=protocol['seedbase']+block,reverse_pmu=bool(block%2)))
            h.platform(out,['python3',Path(__file__),'trial',manifest])
            value=json.loads((out/'result.json').read_text());assert value['valid']
            row=dict(block=block,arm=arm,valid=True,output=str(out),achieved_rps=value['pool']['achieved_rps'],
                pool_util_pct=value['pool_util_pct'],metrics=dict(mean_ms=value['pool']['mean_ms'],
                p99_ms=value['pool']['p99_ms'],stack_cpu=value['whole_stack_cpu_us_per_request'],
                inverse_rps=1/value['pool']['achieved_rps']))
            rows.append(row);b.save(stage/'screen/rows.json',rows)
            b.save(stage/'screen/summary.json',summarize(rows,protocol['arms']));print(json.dumps(row),flush=True)
    b.save(stage/'screen/complete.json',dict(rows=len(rows)))
    b.save(stage/'complete.json',dict(valid=True,clean_trials=len(rows),aborted_attempts=1,
        quality_amendment_sha256=b.sha(root/'l1_topdown_quality_amendment.json')))
    lead.report(stage)


def confirm(root):
    fixed=json.loads((root/'l1_topdown_quality_amendment.json').read_text())
    assert b.sha(__file__)==fixed['source_sha256']
    original=h.platform
    def wrapped(out,command):
        assert str(command[1])==str(Path(lead.__file__)) and command[2]=='trial'
        return original(out,[command[0],Path(__file__),'trial',command[3]])
    h.platform=wrapped
    confirmation.campaign(root)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['amendment','resume','confirm','trial']);parser.add_argument('root',type=Path)
    args=parser.parse_args()
    def interrupted(sig,frame):raise KeyboardInterrupt(sig)
    signal.signal(signal.SIGTERM,interrupted)
    if args.action=='trial':trial(json.loads(args.root.read_text()))
    else:globals()[args.action](args.root)
