"""Schedule joining must preserve branch history only for complete runs."""
import importlib.util
from pathlib import Path

PATH = Path(__file__).resolve().parents[1]/'scripts/class_b/wake_miss_timeline.py'
SPEC = importlib.util.spec_from_file_location('wake_temporal_test', PATH)
wake = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wake)


def test_named_event_details_follow_exact_schedule_join():
    lines = [
        'worker 7/7 [032] 10.000001000: 1 sched:sched_switch: idle:0 [120] S ==> worker:7 [120]',
        'worker 7/7 [032] 10.000001500: 257 fe_lat128: 1234 0x1000/0x1200/M/-/-/100/CALL/',
        'worker 7/7 [032] 10.000003000: 1 sched:sched_switch: worker:7 [120] S ==> idle:0 [120]',
        'worker 7/7 [032] 10.000004000: 1 sched:sched_switch: idle:0 [120] S ==> worker:7 [120]',
        'worker 7/7 [032] 10.000004500: 257 fe_lat128: 5678 0x5000/0x5600/P/-/-/200/CALL/',
    ]
    events = wake.parse(lines, 7, sample_events=('fe_lat128',), retain_payload=True)
    seen = []
    result = wake.analyze(events, {7}, 7, sample_detail_callback=lambda *x: seen.append(x))
    assert result['quality']['complete_samples'] == 1
    assert result['quality']['right_censored_samples'] == 1
    assert len(seen) == 1 and seen[0][0] == .5
    assert seen[0][1]['ip'] == 0x1234
    assert '/100/CALL/' in seen[0][1]['payload']
