"""Actual context availability, confidence filtering, and miss-weighted selection."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('wake_training',ROOT/'scripts/class_b/train_kernel_wake.py')
training=importlib.util.module_from_spec(spec)
spec.loader.exec_module(training)


def test_future_syscall_does_not_label_earlier_user_run():
    events=[(1.0,7,100),(2.5,45,200),(3.0,1,300)]
    times=[x[0] for x in events]
    assert training.resume_event(events,times,2.0,4.0,2.4) is None
    assert training.resume_event(events,times,2.0,4.0,2.6)==events[1]
    assert training.resume_event(events,times,2.0,2.5,2.6) is None


def test_resume_requires_first_trace_start_unique_syscall_and_real_opcode(tmp_path):
    binary=tmp_path/'libc'
    binary.write_bytes(b'\x90\x90\x0f\x05\x90\x90')
    dso=SimpleNamespace(path='/libc',file=str(binary),segs=[(0,0x1000,6)])
    maps=SimpleNamespace(resolve=lambda ip:(dso,0x1004))
    first=[(1.0,0,0x5004,'tr strt')]
    assert training.resume_context(first,{0x5004:{7}},maps,{})==(7,'/libc',0x1004)
    assert training.resume_context(first,{0x5004:{7,45}},maps,{}) is None
    assert training.resume_context([(1,0x5000,0x5004,'call')],{0x5004:{7}},maps,{}) is None
    assert training.resume_context([(1,0,0x5000,'tr strt'),*first],{0x5004:{7}},maps,{}) is None
    binary.write_bytes(b'\x90'*6)
    assert training.resume_context(first,{0x5004:{7}},maps,{}) is None


def test_confidence_and_sparse_contexts():
    context=(7,'/libc.so',123)
    rows=[dict(context=context,first=[('/app',64),('/app',128)]) for _ in range(20)]
    rows += [dict(context=(45,'/libc.so',200),first=[('/app',192)]) for _ in range(2)]
    profiles=training.fit(rows,1,.8,128)
    assert len(profiles)==1
    assert profiles[0]['targets'][0]['key']==('/app',64)
    assert training.lower_bound(20,20)>.8
    assert training.lower_bound(8,8)<.8


def test_miss_weighting_and_validation_dont_change_training():
    context=(7,'/libc.so',123)
    rows=[dict(context=context,first=[('/app',64),('/app',128)]) for _ in range(20)]
    profiles=training.fit(rows,1,.8,128,{('/app',128):100})
    assert profiles[0]['targets'][0]['key']==('/app',128)
    result=training.evaluate(profiles,[dict(context=context,first=[('/app',64)]),
                                      dict(context=None,first=[('/app',128)])])
    assert result['matched_runs']==1 and result['issued']==1
    assert result['touch_precision']==0
    assert profiles[0]['targets'][0]['key']==('/app',128)
